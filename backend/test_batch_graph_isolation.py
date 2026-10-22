"""
Neo4j 侧文档级图谱隔离验证（批量上传后的核心约束）

只使用固定的测试 course_id / document_id，并在开始前确认这些 ID 不与真实数据重叠：
  - 若 SQLite 中已存在 TEST_COURSE_ID，直接中止；
  - 若 Neo4j 中该 course_id 已有任何节点，直接中止（不清空未知数据）；
  - 结束后只删除本次测试 course_id 下的节点（按 course_id 限定）。

运行方式（在 backend 目录下）：
    python test_batch_graph_isolation.py
"""
import asyncio
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.database import db
from app.core.sql_database import sql_db
from app.services.kg_manager import KnowledgeGraphManager

TEST_COURSE_ID = 990199
DOC_A = 990001
DOC_B = 990002

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [通过] {name}")
    else:
        FAIL += 1
        print(f"  [失败] {name} {detail}")


def _cleanup():
    # 只按固定的测试 course_id 删除，绝不出现无 course_id 的全局删除
    db.delete_document_graph(TEST_COURSE_ID, DOC_A)
    db.delete_document_graph(TEST_COURSE_ID, DOC_B)


async def main():
    print("=" * 60)
    print("Neo4j 文档级图谱隔离验证")
    print("=" * 60)

    if sql_db.get_course(TEST_COURSE_ID) is not None:
        print(f"[中止] SQLite 中已存在 course_id={TEST_COURSE_ID}，为避免误伤真实数据不执行")
        return
    existing = db.query(
        "MATCH (n:KnowledgePoint {course_id: $cid}) RETURN count(n) AS cnt",
        {"cid": TEST_COURSE_ID},
    )[0]["cnt"]
    if existing:
        print(f"[中止] Neo4j 中 course_id={TEST_COURSE_ID} 已有 {existing} 个节点，不执行")
        return

    try:
        # 两个文档各建两个知识点 + 一条关系，模拟批量上传后的独立建图
        a_entities = [
            {"name": "TEST_A1", "category": "概念", "description": "A1"},
            {"name": "TEST_A2", "category": "方法", "description": "A2"},
        ]
        b_entities = [
            {"name": "TEST_B1", "category": "概念", "description": "B1"},
            {"name": "TEST_B2", "category": "定理", "description": "B2"},
        ]
        await asyncio.to_thread(
            KnowledgeGraphManager.build_graph, TEST_COURSE_ID, DOC_A, a_entities,
            [{"source": "TEST_A1", "target": "TEST_A2", "type": "PRECEDES", "confidence": 0.9}])
        await asyncio.to_thread(
            KnowledgeGraphManager.build_graph, TEST_COURSE_ID, DOC_B, b_entities,
            [{"source": "TEST_B1", "target": "TEST_B2", "type": "CONTAINS", "confidence": 0.9}])

        graph_a = await asyncio.to_thread(
            KnowledgeGraphManager.get_graph_v1, TEST_COURSE_ID, DOC_A)
        graph_b = await asyncio.to_thread(
            KnowledgeGraphManager.get_graph_v1, TEST_COURSE_ID, DOC_B)

        labels_a = {n["label"] for n in graph_a["nodes"]}
        labels_b = {n["label"] for n in graph_b["nodes"]}
        check("文档 A 只包含自己的知识点", labels_a == {"TEST_A1", "TEST_A2"}, str(labels_a))
        check("文档 B 只包含自己的知识点", labels_b == {"TEST_B1", "TEST_B2"}, str(labels_b))
        ids_a = {n["id"] for n in graph_a["nodes"]}
        ids_b = {n["id"] for n in graph_b["nodes"]}
        check("文档 A 的关系两端都在自己的节点集合内",
              len(graph_a["edges"]) == 1
              and graph_a["edges"][0]["source"] in ids_a
              and graph_a["edges"][0]["target"] in ids_a,
              str(graph_a["edges"]))
        check("文档 B 的关系两端都在自己的节点集合内",
              len(graph_b["edges"]) == 1
              and graph_b["edges"][0]["source"] in ids_b
              and graph_b["edges"][0]["target"] in ids_b,
              str(graph_b["edges"]))
        check("两文档节点 ID 不重叠",
              not ({n["id"] for n in graph_a["nodes"]} & {n["id"] for n in graph_b["nodes"]}))

        count_a = db.query(
            "MATCH (n:KnowledgePoint {course_id: $cid, document_id: $did}) RETURN count(n) AS cnt",
            {"cid": TEST_COURSE_ID, "did": DOC_A})[0]["cnt"]
        count_b = db.query(
            "MATCH (n:KnowledgePoint {course_id: $cid, document_id: $did}) RETURN count(n) AS cnt",
            {"cid": TEST_COURSE_ID, "did": DOC_B})[0]["cnt"]
        check("Neo4j 按 document_id 隔离存储", count_a == 2 and count_b == 2,
              f"A={count_a}, B={count_b}")
    finally:
        _cleanup()
        left = db.query(
            "MATCH (n:KnowledgePoint {course_id: $cid}) RETURN count(n) AS cnt",
            {"cid": TEST_COURSE_ID})[0]["cnt"]
        check("测试数据已按课程范围清理", left == 0, f"剩余 {left}")
        db.close()

    print(f"结果：通过 {PASS}/{PASS + FAIL}")


if __name__ == "__main__":
    asyncio.run(main())
