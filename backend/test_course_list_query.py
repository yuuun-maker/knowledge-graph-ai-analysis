"""课程列表查询优化回归测试（纯打桩，不连 Neo4j / 不读写 app.db）。

守住三条约束：
1. 节点/关系统计只查询当前页课程（Cypher 带 `course_id IN $cids`），页面无数据时不发查询；
2. 文档分组统计同样只统计当前页课程；
3. 「我的课程」「发现课程」只查一次成员关系，不再在 list_courses 内部重复查询。

运行：cd backend && python test_course_list_query.py
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.services import course_service as CS
from app.services.course_service import CourseService

failures = []


def check(label, ok, detail=""):
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def _row(cid, teacher_id=1):
    return {
        "course_id": cid, "course_name": f"课程{cid}", "course_code": f"C{cid}",
        "description": "", "teacher_id": teacher_id, "teacher_name": "教师",
        "status": 1, "governance_status": "normal", "created_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-01 00:00:00", "category": "计算机", "organization": "",
        "cover": "", "join_mode": "auto", "is_public": 1, "join_code": f"JOIN{cid}",
    }


class Patcher:
    """集中替换 sql_db / db 的方法，退出时无条件还原。"""

    def __init__(self):
        self.saved = []

    def set(self, obj, name, value):
        self.saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        for obj, name, value in reversed(self.saved):
            setattr(obj, name, value)
        return False


def test_list_courses_filters_graph_queries() -> None:
    calls = {"membership": 0, "queries": [], "doc_ids": None}
    rows = [_row(1, teacher_id=1), _row(2, teacher_id=2)]

    def fake_page(*args, **kwargs):
        return 2, rows

    def fake_memberships(uid):
        calls["membership"] += 1
        return [{"course_id": 2, "role": "teacher", "status": "approved"}]

    def fake_doc_counts(cids=None):
        calls["doc_ids"] = list(cids or [])
        return {1: 2, 2: 1}

    def fake_query(cypher, params=None):
        calls["queries"].append((cypher, params or {}))
        if "count(rel)" in cypher:
            return [{"cid": 1, "cnt": 5}]
        return [{"cid": 1, "cnt": 3}, {"cid": 2, "cnt": 4}]

    with Patcher() as p:
        p.set(CS.sql_db, "list_courses_page", fake_page)
        p.set(CS.sql_db, "list_memberships_by_user", fake_memberships)
        p.set(CS.sql_db, "count_documents_grouped", fake_doc_counts)
        p.set(CS.sql_db, "member_counts_by_course", lambda cids: {})
        p.set(CS.db, "query", fake_query)
        result = CourseService.list_courses(
            page=1, page_size=12, viewer={"user_id": 99, "role": "teacher"})

    items = result["data"]["items"]
    check("返回两门课程", len(items) == 2)
    check("成员关系只查一次", calls["membership"] == 1, str(calls["membership"]))
    check("文档统计只传当前页课程", calls["doc_ids"] == [1, 2], str(calls["doc_ids"]))
    check("Neo4j 只发两条聚合查询", len(calls["queries"]) == 2, str(len(calls["queries"])))
    check("节点查询按课程 ID 过滤",
          all("IN $cids" in c and params == {"cids": [1, 2]}
              for c, params in calls["queries"]),
          str(calls["queries"]))
    check("节点/关系统计回填正确",
          items[0]["node_count"] == 3 and items[0]["edge_count"] == 5
          and items[1]["node_count"] == 4 and items[1]["edge_count"] == 0,
          str([(i["node_count"], i["edge_count"]) for i in items]))


def test_empty_page_skips_graph() -> None:
    calls = {"queries": 0, "membership": 0}

    def fake_memberships(uid):
        calls["membership"] += 1
        return []

    def fake_query(cypher, params=None):
        calls["queries"] += 1
        return []

    with Patcher() as p:
        p.set(CS.sql_db, "list_courses_page", lambda *a, **k: (0, []))
        p.set(CS.sql_db, "list_memberships_by_user", fake_memberships)
        p.set(CS.sql_db, "count_documents_grouped", lambda cids=None: {})
        p.set(CS.sql_db, "member_counts_by_course", lambda cids: {})
        p.set(CS.db, "query", fake_query)
        result = CourseService.list_courses(
            page=2, page_size=12, viewer={"user_id": 99, "role": "teacher"})

    check("空页返回空列表", result["data"]["items"] == [])
    check("空页不查询 Neo4j", calls["queries"] == 0, str(calls["queries"]))


def test_my_courses_reuses_membership_query() -> None:
    calls = {"membership": 0}

    def fake_memberships(uid):
        calls["membership"] += 1
        return [{"course_id": 1, "role": "teacher", "status": "approved"}]

    with Patcher() as p:
        p.set(CS.sql_db, "list_memberships_by_user", fake_memberships)
        p.set(CS.sql_db, "list_accessible_course_ids", lambda uid, role: [1])
        p.set(CS.sql_db, "list_courses_page", lambda *a, **k: (1, [_row(1)]))
        p.set(CS.sql_db, "count_documents_grouped", lambda cids=None: {1: 1})
        p.set(CS.sql_db, "member_counts_by_course", lambda cids: {})
        p.set(CS.db, "query", lambda cypher, params=None: [])
        result = CourseService.list_my_courses({"user_id": 99, "role": "teacher"})

    check("我的课程：成员关系只查一次", calls["membership"] == 1, str(calls["membership"]))
    check("我的课程：返回课程", len(result["data"]["items"]) == 1)
    check("我的课程：my_role 仍正确",
          result["data"]["items"][0]["my_role"] == "teacher",
          str(result["data"]["items"][0].get("my_role")))


def test_discover_reuses_membership_query() -> None:
    calls = {"membership": 0, "exclude": None}
    orig_list_courses = CourseService.list_courses

    def fake_memberships(uid):
        calls["membership"] += 1
        return [{"course_id": 7, "role": "student", "status": "approved"}]

    def fake_list_courses(*args, **kwargs):
        calls["exclude"] = kwargs.get("exclude_course_ids")
        return {"ok": True, "code": 0, "message": "success", "data": {
            "total": 1, "page": 1, "page_size": 12,
            "items": [{**_row(8), "governance_status": "normal", "status": 1}],
        }}

    CourseService.list_courses = staticmethod(fake_list_courses)
    try:
        with Patcher() as p:
            p.set(CS.sql_db, "list_memberships_by_user", fake_memberships)
            result = CourseService.list_discover({"user_id": 99, "role": "student"})
    finally:
        CourseService.list_courses = staticmethod(orig_list_courses)

    check("发现课程：成员关系只查一次", calls["membership"] == 1, str(calls["membership"]))
    check("发现课程：排除已加入课程", calls["exclude"] == [7], str(calls["exclude"]))
    check("发现课程：标记 my_relation",
          result["data"]["items"][0]["my_relation"] == "NONE",
          str(result["data"]["items"][0]))


def main() -> int:
    tests = [
        ("课程列表聚合过滤", test_list_courses_filters_graph_queries),
        ("空页跳过图查询", test_empty_page_skips_graph),
        ("我的课程复用成员查询", test_my_courses_reuses_membership_query),
        ("发现课程复用成员查询", test_discover_reuses_membership_query),
    ]
    passed = 0
    for name, fn in tests:
        before = len(failures)
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - 测试脚本：把异常转成失败项继续跑
            print(f"  [FAIL] {name}: {type(e).__name__}: {e}")
            failures.append(name)
        if len(failures) == before:
            passed += 1
    print(f"通过 {passed}/{len(tests)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
