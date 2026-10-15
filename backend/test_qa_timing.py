"""
性能测试：智能问答单次响应时间（赛题指标：≤15 秒）

用法（backend 目录下，需真实 LLM + Embedding API，且 Neo4j 与后端数据可用）：

    # 先探明图谱现状（不调 API）
    python test_qa_timing.py --dry-run

    # 正式计时：对问答测试集的全部题目各测一次并落盘
    python test_qa_timing.py --output eval_data/qa_timing.json

    # 指定课程 / 文档（默认 course_id=5，文档取该课程节点最多的那本）
    python test_qa_timing.py --course-id 5 --document-id 4

## 计时口径

赛题口径是「用户提交问题到收到回答」的端到端时间，因此计时覆盖完整链路：

    问题 → EmbeddingClient.embed(问题)   ← 外部 API
         → KnowledgeEmbedder.ensure_index  ← 索引新鲜度检查（首问可能触发重建）
         → 余弦排序 top_k → 回查 Neo4j → DeepSeek 生成

**必须区分两种场景**（`ensure_index` 是懒构建 + 懒重建，首次提问含全量索引构建）：

- `首问` —— 进程内第 1 次提问，含索引新鲜度检查（若索引缺失/失效则含全量重建）
- `热路径` —— 索引已就绪时的稳定响应时间，这才是用户日常体验的值

报告同时给出两者，不把首问的数字混进均值。

安全边界：本脚本只读图谱、只调 LLM/Embedding 接口，不写库、不写图。
"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.database import db
from app.core.sql_database import sql_db
from app.services.qa_service import QAService, _coerce_document_id

THRESHOLD_SECONDS = 15.0
DEFAULT_QUESTIONS = "test_qa_testset.json"


def pick_scope(course_id):
    """在指定课程下挑节点数最多的文档（问答测试集的原文档可能已不在库中）。"""
    with db.driver.session() as s:
        rows = s.run(
            "MATCH (n:KnowledgePoint) WHERE n.course_id = $cid "
            "RETURN n.document_id AS did, count(n) AS c ORDER BY c DESC",
            cid=course_id,
        ).data()
    return [(r["did"], r["c"]) for r in rows if r["did"] is not None]


def index_state(course_id, document_id):
    """返回该作用域已存的向量条数与图谱中的知识点数，判断首问是否会触发重建。

    注意：Neo4j 里 `document_id` 存的是**整数**属性，SQLite 的向量表按**字符串**存。
    这里必须复用服务层的 `_coerce_document_id()`（其注释即「对齐 Neo4j 存储类型」），
    否则用字符串去 Neo4j 查会恒返回 0 个知识点，把「图谱明明有货」误报成「向量与
    知识点数不一致」。
    """
    did_doc = _coerce_document_id(document_id)
    try:
        with db.driver.session() as s:
            n_kp = s.run(
                "MATCH (n:KnowledgePoint) WHERE n.course_id = $cid AND n.document_id = $did "
                "RETURN count(n) AS c", cid=course_id, did=did_doc,
            ).single()["c"]
    except Exception as e:
        n_kp = f"查询失败: {e}"
    try:
        rows = sql_db.get_embeddings_by_document(course_id, str(document_id)) or []
        n_vec = len(rows)
    except Exception:
        n_vec = "查询失败"
    return n_kp, n_vec


def load_questions(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("questions", [])
    out = []
    for i, q in enumerate(data, 1):
        if isinstance(q, str):
            out.append({"id": i, "type": "", "question": q})
        else:
            out.append({
                "id": q.get("id", i),
                "type": q.get("type", ""),
                "question": q.get("question", ""),
            })
    return out


async def run(args):
    if args.questions and not os.path.isfile(args.questions):
        print(f"✗ 题目文件不存在：{args.questions}")
        return 1

    print(f"=== 图谱作用域（course_id={args.course_id}）===")
    try:
        scopes = pick_scope(args.course_id)
    except Exception as e:
        print(f"✗ 无法连接 Neo4j：{type(e).__name__}: {str(e)[:160]}")
        print("  问答链路依赖 Neo4j（检索回查节点），请先启动 Neo4j 再运行本脚本。")
        return 2
    if not scopes:
        print("✗ 该课程在 Neo4j 中没有 KnowledgePoint 节点，无法计时。")
        return 2
    for did, c in scopes:
        print(f"  document_id={did}：{c} 个知识点")

    doc_id = args.document_id if args.document_id is not None else scopes[0][0]
    n_kp, n_vec = index_state(args.course_id, doc_id)
    print(f"\n选定 document_id={doc_id}：图谱 {n_kp} 个知识点 / 已存向量 {n_vec} 条")
    if n_vec != n_kp:
        print("  ⚠ 向量条数与知识点数不一致 → 首问将触发索引重建（这正是需要单独计时的场景）")

    questions = load_questions(args.questions)
    print(f"题目：{len(questions)} 道（{args.questions}）")

    if args.dry_run:
        print("\n--dry-run：仅探明作用域，不调用 API、不计时。")
        return 0

    qa = QAService()
    print(f"\n=== 逐题计时（阈值 {THRESHOLD_SECONDS}s）===")
    print(f"{'#':>3}  {'耗时(s)':>8}  {'来源数':>6}  {'答案字数':>8}  场景   问题")
    records = []
    for i, q in enumerate(questions):
        scene = "首问" if i == 0 else "热路径"
        t0 = time.perf_counter()
        try:
            res = await qa.ask_with_sources(q["question"], args.course_id, doc_id)
            err = None
        except Exception as e:
            res, err = {"answer": "", "sources": []}, f"{type(e).__name__}: {e}"
        el = time.perf_counter() - t0

        srcs = res.get("sources") or []
        rec = {
            "id": q["id"], "type": q["type"], "question": q["question"],
            "elapsed_s": round(el, 3), "scene": scene,
            "sources_count": len(srcs), "answer_chars": len(res.get("answer") or ""),
            "error": err,
        }
        records.append(rec)
        print(f"{str(q['id']):>3}  {el:8.2f}  {len(srcs):>6}  {rec['answer_chars']:>8}  "
              f"{scene:<6} {q['question'][:34]}")
        if err:
            print(f"      ✗ {err}")

    warm = [r["elapsed_s"] for r in records[1:] if not r["error"]]
    allok = [r["elapsed_s"] for r in records if not r["error"]]
    summary = {
        "threshold_seconds": THRESHOLD_SECONDS,
        "questions_total": len(records),
        "errors": sum(1 for r in records if r["error"]),
        "cold_start_s": records[0]["elapsed_s"] if records else None,
        "warm_mean_s": round(sum(warm) / len(warm), 3) if warm else None,
        "warm_max_s": max(warm) if warm else None,
        "warm_min_s": min(warm) if warm else None,
        "all_mean_s": round(sum(allok) / len(allok), 3) if allok else None,
        "pass": bool(warm) and max(warm) <= THRESHOLD_SECONDS,
    }

    out = {
        "kind": "qa_response_time",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scope": {"course_id": args.course_id, "document_id": doc_id},
        "index_before": {"kp_nodes": n_kp, "stored_vectors": n_vec},
        "summary": summary,
        "records": records,
    }
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("\n=== 汇总 ===")
    print(f"  首问（含索引新鲜度检查）: {summary['cold_start_s']}s")
    if warm:
        print(f"  热路径均值: {summary['warm_mean_s']}s（{summary['warm_min_s']}~{summary['warm_max_s']}s，"
              f"n={len(warm)}）")
        print(f"  判定（以热路径最大值为准，阈值 {THRESHOLD_SECONDS}s）: "
              f"{'✓ 达标' if summary['pass'] else '✗ 未达标'}")
    if summary["errors"]:
        print(f"  ⚠ {summary['errors']} 题调用失败，已计入错误但不参与均值")
    print(f"\n结果已写入 {args.output}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="智能问答单次响应时间测试（赛题指标 ≤15s）")
    ap.add_argument("--course-id", type=int, default=5)
    ap.add_argument("--document-id", default=None,
                    help="默认取该课程在 Neo4j 中节点最多的文档")
    ap.add_argument("--questions", default=DEFAULT_QUESTIONS, help="题目 JSON（默认问答测试集）")
    ap.add_argument("--output", default="eval_data/qa_timing.json", help="结果落盘路径")
    ap.add_argument("--dry-run", action="store_true", help="只探明图谱作用域，不调用 API")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
