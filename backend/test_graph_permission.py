"""课程中心改造：图谱相关问题（问答 / 学习路径）作用域收敛测试

运行方式（在 backend 目录下执行）：
    python test_graph_permission.py

本脚本覆盖改造中风险最高的一处重构：path_recommender._node 由 2 元组改为 3 元组
（多返回一个 WHERE 片段），以及 qa_service 的无作用域分支新增课程白名单。

验证两件事：
A. 【不回归】指定了 course_id 时，生成的 Cypher 与参数里不出现 allowed_course_ids，
   即热路径与改造前完全一致；
B. 【不泄漏】未指定 course_id 时，检索结果被限制在 allowed_ids 内，
   空 allowed_ids 直接短路（不再退化成全库扫描）。

对 Neo4j 只读，不做任何写入；只读取线上 data/app.db（不改任何数据）。
"""
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.database import db                       # noqa: E402
from app.services import path_recommender as pr_mod     # noqa: E402
from app.services import qa_service as qa_mod           # noqa: E402
from app.services.path_recommender import PathRecommender   # noqa: E402
from app.services.qa_service import QAService           # noqa: E402

failures = []
passed = 0


def check(label, ok, detail=""):
    global passed
    if ok:
        passed += 1
    else:
        failures.append(f"{label} — {detail}")
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


class CapturingDB:
    """代理真实 db，记录每次 query 的 cypher 与参数后透传"""

    def __init__(self, real):
        self.real = real
        self.calls = []

    def query(self, cypher, params=None):
        self.calls.append((cypher, params or {}))
        return self.real.query(cypher, params or {})

    def __getattr__(self, name):
        return getattr(self.real, name)


def main():
    print("=" * 70)
    print("Step 0: 找一个真实有图谱数据的 (course_id, document_id)")
    print("=" * 70)
    rows = db.query(
        "MATCH (n:KnowledgePoint) WHERE n.document_id IS NOT NULL "
        "RETURN n.course_id AS cid, n.document_id AS did, count(n) AS cnt "
        "ORDER BY cnt DESC LIMIT 5"
    )
    if not rows:
        print("  [SKIP] Neo4j 中没有带 document_id 的节点，无法进行正向验证")
        print("         （权限拒绝路径已在 test_permission_matrix.py 中覆盖）")
        return
    cid = rows[0]["cid"]
    did = rows[0]["did"]
    print(f"  使用 course_id={cid} document_id={did}（{rows[0]['cnt']} 个节点）")

    # 找该课程下的一个真实知识点名，用于 prerequisites
    name_rows = db.query(
        "MATCH (n:KnowledgePoint {course_id: $cid}) RETURN n.name AS name LIMIT 1",
        {"cid": cid},
    )
    kp_name = name_rows[0]["name"] if name_rows else None
    print(f"  取样知识点: {kp_name}")

    print("\n" + "=" * 70)
    print("Step 1: 作用域内（指定 course_id）不引入任何新参数/新 Cypher")
    print("=" * 70)
    cap = CapturingDB(db)
    pr_mod.db = cap
    PathRecommender.recommend_next(["__不存在的知识点__"], cid, did)
    check("指定 course_id 时确实发起了查询", len(cap.calls) > 0, f"{len(cap.calls)} 次")
    leaked = [i for i, (_, p) in enumerate(cap.calls) if "allowed_course_ids" in p]
    check("指定 course_id 时参数中没有 allowed_course_ids", not leaked, f"泄漏的调用序号 {leaked}")
    bad_cypher = [c for c, _ in cap.calls if "allowed_course_ids" in c]
    check("指定 course_id 时 Cypher 中没有 course_id IN $allowed_course_ids",
          not bad_cypher, str(bad_cypher)[:200])
    check("指定 course_id 时 Cypher 仍按属性作用域过滤",
          all("course_id: $course_id" in c for c, _ in cap.calls),
          str([c[:60] for c, _ in cap.calls])[:200])

    # prerequisites 与 learning_path 同样验证
    cap.calls.clear()
    if kp_name:
        PathRecommender.get_prerequisites(kp_name, cid, did)
        PathRecommender.get_learning_path(kp_name, cid, did)
        leaked = [p for _, p in cap.calls if "allowed_course_ids" in p]
        check("get_prerequisites / get_learning_path 作用域内也无新参数", not leaked,
              f"{len(leaked)} 处")
        check("两者都产生了查询", len(cap.calls) >= 2, f"{len(cap.calls)} 次")

    print("\n" + "=" * 70)
    print("Step 2: 语义等价（同一作用域，带/不带 allowed_ids 结果一致）")
    print("=" * 70)
    mastered = [r["name"] for r in db.query(
        "MATCH (n:KnowledgePoint {course_id: $cid}) RETURN n.name AS name LIMIT 3",
        {"cid": cid})]
    a = PathRecommender.recommend_next(mastered, cid, did, allowed_ids=[cid])
    b = PathRecommender.recommend_next(mastered, cid, did)
    check("recommend_next：指定 course_id 时 allowed_ids 不影响结果",
          [x["name"] for x in a] == [x["name"] for x in b],
          f"{[x['name'] for x in a]} vs {[x['name'] for x in b]}")
    a = PathRecommender.recommend_next([], cid, did, allowed_ids=[])
    b = PathRecommender.recommend_next([], cid, did)
    check("recommend_next：指定 course_id 时传空 allowed_ids 也不短路（作用域优先）",
          [x["name"] for x in a] == [x["name"] for x in b], f"{len(a)} vs {len(b)}")

    print("\n" + "=" * 70)
    print("Step 3: 无作用域时收敛到 allowed_ids")
    print("=" * 70)
    other = [r["cid"] for r in db.query(
        "MATCH (n:KnowledgePoint) RETURN DISTINCT n.course_id AS cid")]
    other = [c for c in other if c != cid]
    if not other:
        print("  [SKIP] 只有一个课程有图谱，无法验证跨课程隔离")
    else:
        other_cid = other[0]
        nodes_in_cid = {r["name"] for r in db.query(
            "MATCH (n:KnowledgePoint {course_id: $cid}) RETURN n.name AS name", {"cid": cid})}
        nodes_in_other = {r["name"] for r in db.query(
            "MATCH (n:KnowledgePoint {course_id: $cid}) RETURN n.name AS name", {"cid": other_cid})}
        only_other = nodes_in_other - nodes_in_cid
        check(f"课程 {other_cid} 有课程 {cid} 没有的知识点（可区分）", len(only_other) > 0,
              f"{len(only_other)} 个")
        if mastered and only_other:
            recs = PathRecommender.recommend_next(mastered, None, None, allowed_ids=[cid])
            names = {r["name"] for r in recs}
            check("无 course_id + allowed_ids=[A] → 推荐结果全部来自 A",
                  not (names & only_other), f"越界: {sorted(names & only_other)[:5]}")

        cap.calls.clear()
        res = PathRecommender.recommend_next([], None, None, allowed_ids=[cid])
        cy = " ".join(c for c, _ in cap.calls)
        check("无 course_id 的 Cypher 带上了 course_id IN $allowed_course_ids",
              "allowed_course_ids" in cy, cy[:200])
        check("无 course_id + allowed_ids 时参数里含 allowed_course_ids",
              all("allowed_course_ids" in p for _, p in cap.calls),
              str([list(p.keys()) for _, p in cap.calls])[:200])
        # 逐条断言：无 course_id 时每一次查询都必须同时出现 WHERE 与课程白名单，
        # 即不存在「只有 MATCH 没有任何课程过滤」的裸查询（旧实现正是这种全库扫描）
        unfiltered = [c for c, _ in cap.calls
                      if "allowed_course_ids" not in c or "WHERE" not in c]
        check("无 course_id 时每次查询都带 WHERE + 课程白名单（无裸全库扫描）",
              not unfiltered, str(unfiltered)[:200])

        # 空列表必须短路：一次查询都不发
        cap.calls.clear()
        res_empty = PathRecommender.recommend_next([], None, None, allowed_ids=[])
        check("无 course_id + 空 allowed_ids → 直接返回空", res_empty == [], str(res_empty))
        check("空 allowed_ids 时一次 Neo4j 查询都不发（不会全库扫描）",
              cap.calls == [], f"{len(cap.calls)} 次查询")
        check("空 allowed_ids 时 prerequisites 也短路",
              PathRecommender.get_prerequisites("x", None, None, allowed_ids=[]) == [])
        check("空 allowed_ids 时 learning_path 也短路",
              PathRecommender.get_learning_path("x", None, None, allowed_ids=[])["paths"] == [])

    pr_mod.db = db

    print("\n" + "=" * 70)
    print("Step 4: 问答检索的作用域收敛")
    print("=" * 70)
    qa = QAService()
    cap = CapturingDB(db)
    qa_mod.db = cap

    qa._keyword_search("知识点", cid, did, 5)
    leaked = [p for _, p in cap.calls if "allowed_course_ids" in p]
    check("问答：指定 course_id 时不带 allowed_course_ids（作用域内行为不变）",
          not leaked, f"{len(leaked)} 处")

    cap.calls.clear()
    if other:
        other_cid = other[0]
        res = qa._keyword_search("的", None, None, 20, allowed_ids=[cid])
        cy = " ".join(c for c, _ in cap.calls)
        check("问答：无 course_id 时 Cypher 带课程白名单",
              "allowed_course_ids" in cy, cy[:200])
        check("问答：无 course_id 时参数含 allowed_course_ids",
              all("allowed_course_ids" in p for _, p in cap.calls),
              str([list(p.keys()) for _, p in cap.calls])[:200])
        # 结果不得出现其它课程的知识点
        names_other = {r["name"] for r in db.query(
            "MATCH (n:KnowledgePoint {course_id: $cid}) RETURN n.name AS name", {"cid": other_cid})}
        names_cid = {r["name"] for r in db.query(
            "MATCH (n:KnowledgePoint {course_id: $cid}) RETURN n.name AS name", {"cid": cid})}
        crossed = {n["name"] for n in res} & (names_other - names_cid)
        check("问答：结果全部落在允许课程内", not crossed, f"越界: {sorted(crossed)[:5]}")

    cap.calls.clear()
    res = qa._keyword_search("知识点", None, None, 5, allowed_ids=[])
    check("问答：空 allowed_ids → 直接返回空", res == [], str(res))
    check("问答：空 allowed_ids 时不发查询", cap.calls == [], f"{len(cap.calls)} 次")

    qa_mod.db = db

    print("\n" + "=" * 70)
    if failures:
        print(f"结果: 通过 {passed} 项，失败 {len(failures)} 项")
        for f in failures:
            print("   -", f)
        sys.exit(1)
    print(f"结果: 全部通过（{passed} 项）")
    print("=" * 70)


if __name__ == "__main__":
    main()
