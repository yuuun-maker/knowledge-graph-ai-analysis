"""
重建 Neo4j 中缺失的文档级知识图谱（一键修复 SQLite 与图数据库不同步）

背景：Neo4j 是每台机器上的本地实例、不进仓库，而 app.db 在很长一段时间里被 git 跟踪、
随仓库在多台机器间流转（现已移出跟踪，见 .gitignore，但此前拉取下来的旧库仍在各机器上）。
换机器 / 重新拉取后，SQLite 里「文档已抽取完成」的记录还在，但对应的知识点节点留在了
原来那台机器的 Neo4j 里，于是：

    图谱页面空白 → RAG 检索不到任何知识点 → 智能问答回答「知识库中没有相关内容」

本脚本自动找出这类「记录说抽取完成、图里却没有节点」的文档，用本机已有的源文件
重新解析 → 抽取 → 入图 → 重建向量索引，恢复 AI 问答与图谱展示。

特性：
- 自动发现待修复文档，无需手工维护清单
- 按 (course_id, document_id, name) MERGE，重复执行幂等，不会产生重复节点
- 先清理该文档的过期向量再重建，避免旧向量指向已不存在的知识点
- --dry-run 只列出待修复项；--yes 跳过交互确认（供自动化调用）

用法（backend 目录下）：
    python scripts/rebuild_missing_graphs.py --dry-run   # 先看要修哪些
    python scripts/rebuild_missing_graphs.py             # 修复（逐篇确认）
    python scripts/rebuild_missing_graphs.py --yes       # 修复（不再逐篇确认）
"""
import argparse
import asyncio
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.database import db  # noqa: E402
from app.core.sql_database import sql_db  # noqa: E402
from app.core.storage import resolve_document_path  # noqa: E402
from app.services.document_parser import DocumentParser  # noqa: E402
from app.services.embedding import KnowledgeEmbedder  # noqa: E402
from app.services.knowledge_extractor import KnowledgeExtractor  # noqa: E402
from app.services.kg_manager import KnowledgeGraphManager  # noqa: E402


def node_count(course_id, document_id) -> int:
    """该文档当前在 Neo4j 里的知识点数量"""
    return db.query(
        "MATCH (n:KnowledgePoint {course_id: $cid, document_id: $did}) RETURN count(n) AS c",
        {"cid": course_id, "did": document_id},
    )[0]["c"]


def find_broken_documents() -> list:
    """找出「抽取状态为 COMPLETED，但 Neo4j 里一个节点都没有」的文档"""
    broken = []
    for doc in sql_db.list_all_documents():
        if (doc.get("extract_status") or "").upper() != "COMPLETED":
            continue
        if node_count(doc["course_id"], doc["doc_id"]) == 0:
            broken.append(doc)
    return broken


async def rebuild_one(doc: dict) -> dict:
    """重建单篇文档的图谱，返回 {ok, message, nodes, edges}"""
    doc_id, course_id = doc["doc_id"], doc["course_id"]

    path = resolve_document_path(doc)
    if not path or not os.path.exists(path):
        return {"ok": False, "message": f"源文件找不到（file_path={doc.get('file_path')}）"}

    try:
        text = await DocumentParser.parse(path)
    except Exception as e:
        return {"ok": False, "message": f"解析失败: {e}"}
    if not text or not text.strip():
        return {"ok": False, "message": "解析结果为空（可能是扫描版 PDF 无文本层）"}

    try:
        result = await KnowledgeExtractor().extract(text)
    except Exception as e:
        return {"ok": False, "message": f"抽取失败: {e}"}
    if result.get("error"):
        return {"ok": False, "message": f"抽取失败: {result['error']}"}

    entities = result.get("entities", [])
    relations = result.get("relations", [])

    # 先清掉该文档的过期向量：旧向量按已消失的 kp_id 索引，留着会让向量检索持续返回空
    dropped_vectors = sql_db.delete_embeddings_by_document(course_id, doc_id)

    stats = KnowledgeGraphManager.build_graph(course_id, doc_id, entities, relations)

    # 重建向量索引（embedding 不可用时静默跳过，此时问答会退回关键词检索）
    indexed = KnowledgeEmbedder().build_index(course_id, doc_id)

    sql_db.update_document(
        doc_id,
        extract_status="COMPLETED",
        entity_count=len(entities),
        relation_count=len(relations),
    )
    return {
        "ok": True,
        "message": f"入图 {stats['node_count']} 节点 / {stats['relation_count']} 关系，"
                   f"清理过期向量 {dropped_vectors} 条，重建向量 {indexed} 条",
        "nodes": stats["node_count"],
        "edges": stats["relation_count"],
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="重建 Neo4j 中缺失的文档级知识图谱")
    parser.add_argument("--dry-run", action="store_true", help="只列出待修复文档，不做任何写入")
    parser.add_argument("--yes", action="store_true", help="不逐篇确认，直接修复")
    args = parser.parse_args()

    print("扫描中…（读取 SQLite 记录并核对 Neo4j 节点数）")
    broken = find_broken_documents()

    if not broken:
        print("\n✓ 没有发现缺失图谱的文档，SQLite 与 Neo4j 一致。")
        return 0

    print(f"\n发现 {len(broken)} 篇文档「记录为抽取完成、图里却没有节点」：\n")
    for d in broken:
        print("  course=%-4s doc=%-5s %-34s DB记实体=%s"
              % (d["course_id"], d["doc_id"], str(d.get("file_name"))[:34],
                 d.get("entity_count")))

    if args.dry_run:
        print("\n（--dry-run 模式，未做任何写入）")
        return 0

    if not args.yes:
        print("\n接下来会调用 LLM 重新抽取这些文档（每篇约 10-60 秒），并写入 Neo4j 与 SQLite。")
        if input("继续？输入 yes 确认: ").strip().lower() not in ("y", "yes"):
            print("已取消，未做任何修改。")
            return 0

    ok_cnt = fail_cnt = 0
    for i, doc in enumerate(broken, 1):
        label = "course=%s doc=%s %s" % (doc["course_id"], doc["doc_id"],
                                         str(doc.get("file_name"))[:28])
        print(f"\n[{i}/{len(broken)}] {label}")
        try:
            r = await rebuild_one(doc)
        except Exception as e:
            r = {"ok": False, "message": f"意外异常: {e}"}

        if r["ok"]:
            ok_cnt += 1
            print(f"    ✓ {r['message']}")
            left = node_count(doc["course_id"], doc["doc_id"])
            print(f"    校验：Neo4j 现有 {left} 个节点"
                  + ("" if left == r["nodes"] else "  ✗ 与入图数不一致，请检查"))
        else:
            fail_cnt += 1
            print(f"    ✗ {r['message']}")

    print(f"\n完成：成功 {ok_cnt} 篇，失败 {fail_cnt} 篇。")
    if fail_cnt:
        print("失败项可按上面的原因单独处理；修复后重跑本脚本即可（幂等）。")
    db.close()
    return 0 if fail_cnt == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
