# -*- coding: utf-8 -*-
"""知识融合：**删课程**时级联清理验证（回归测试）

背景（对应 docs/数据库设计.md §2.22 记录的那个缺口）：
    融合的 5 张表（t_kp_fusion_*）最初只挂在**文档级**删除路径上
    （document_service.delete_document → delete_fusion_by_document），
    `SQLDatabase.delete_course()` 完全没引用它们，且全仓不存在
    `delete_fusion_by_course()`。这 5 张表都没设物理外键，所以漏清
    **不会报错**，只会静默堆积指向已删课程的孤儿行。

覆盖修复后应有的行为：
    课程 A 建 2 个文档、课程 B 建 1 个文档，各自写入 5 张融合表的行；
    删除课程 A 后验证：A 的融合行全清，**B 的一行不少**（对照，防误删越界）。

运行方式（backend 目录下，需 Neo4j 已启动 —— CourseService.delete_course 会清图）：
    python test_fusion_course_delete.py
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.database import db
from app.core.sql_database import sql_db
from app.services.course_service import CourseService

FUSION_TABLES = ("t_kp_fusion_run", "t_kp_fusion_candidate", "t_kp_fusion_map",
                 "t_kp_fusion_conflict", "t_kp_fusion_scope")

TEST_COURSE_MARK = "__fusion_course_delete_test__"
CONTROL_COURSE_MARK = "__fusion_course_delete_control__"


def _fusion_rows(cid):
    """该课程在 5 张融合表上的行数（逐表）"""
    return {
        t: sql_db._query_one(
            f"SELECT count(*) AS c FROM {t} WHERE course_id = ?", (cid,)
        )["c"]
        for t in FUSION_TABLES
    }


def _seed_fusion(cid, doc_id, tag):
    """给 (course, document) 写入 5 张表各一行"""
    run_id = f"run_{tag}"
    sql_db.insert_fusion_run(run_id, cid, doc_id, "APPLY")
    sql_db.upsert_fusion_candidates(cid, doc_id, [{
        "source_kp_id": f"kp_{tag}_a", "target_kp_id": f"kp_{tag}_b",
        "source_name": "A", "target_name": "B",
        "source_category": "概念", "target_category": "概念",
        "score": 0.9, "decision": "SAME", "decision_source": "RULE",
    }], run_id=run_id)
    sql_db.insert_fusion_map(cid, doc_id, f"kp_{tag}_a", f"kp_{tag}_b", "A", "B")
    sql_db.insert_fusion_conflict(cid, doc_id, "CYCLE", f"kp_{tag}_a", f"kp_{tag}_b")
    sql_db.fusion_scope_bump_epoch(cid, doc_id)


def _cleanup_existing():
    """清掉上一次失败运行可能遗留的测试课程（删课现在会一并清融合表）"""
    for c in sql_db.list_courses():
        if c["course_name"] in (TEST_COURSE_MARK, CONTROL_COURSE_MARK):
            db.delete_course_graph(c["course_id"])
            sql_db.delete_course(c["course_id"])


def main():
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    db.init_schema()
    _cleanup_existing()
    teacher = sql_db.ensure_default_teacher()

    # 课程 A（被测）+ 课程 B（对照）
    cid_a = sql_db.create_course(TEST_COURSE_MARK, teacher)
    doc_a1 = sql_db.create_document(cid_a, teacher, "融合删除测试A1.txt", "TXT", 10)
    doc_a2 = sql_db.create_document(cid_a, teacher, "融合删除测试A2.txt", "TXT", 10)

    cid_b = sql_db.create_course(CONTROL_COURSE_MARK, teacher)
    doc_b1 = sql_db.create_document(cid_b, teacher, "融合对照B1.txt", "TXT", 10)

    _seed_fusion(cid_a, doc_a1, "a1")
    _seed_fusion(cid_a, doc_a2, "a2")
    _seed_fusion(cid_b, doc_b1, "b1")

    before_a = _fusion_rows(cid_a)
    before_b = _fusion_rows(cid_b)
    check("前置：A 的 5 张融合表各有 2 行", all(v == 2 for v in before_a.values()), str(before_a))
    check("前置：B 的 5 张融合表各有 1 行", all(v == 1 for v in before_b.values()), str(before_b))

    # 计数 helper 与实际行数一致（删除报告依赖它）
    check("count_fusion_by_course 与实际一致（A）",
          sql_db.count_fusion_by_course(cid_a) == before_a, str(sql_db.count_fusion_by_course(cid_a)))

    # ---- 删除课程 A ----
    result = CourseService.delete_course(cid_a, confirm=True)
    check("delete_course 返回成功", result.get("ok") is True, str(result.get("message")))

    after_a = _fusion_rows(cid_a)
    after_b = _fusion_rows(cid_b)

    for t in FUSION_TABLES:
        check(f"{t} 已清空（A）", after_a[t] == 0, f"残留 {after_a[t]} 行")
    for t in FUSION_TABLES:
        check(f"{t} 未受影响（B 对照）", after_b[t] == before_b[t],
              f"{before_b[t]} -> {after_b[t]}")

    # 删除报告应带上分表计数（此前课程级路径没有这个字段）
    removed_fusion = (result.get("data") or {}).get("removed_fusion")
    check("删除报告含 removed_fusion 字段", isinstance(removed_fusion, dict),
          str(removed_fusion))
    check("removed_fusion 计数正确（2 文档 × 5 表 = 10 行）",
          isinstance(removed_fusion, dict) and sum(removed_fusion.values()) == 10,
          str(removed_fusion))

    # 直接调用 DAO 的返回也应带分表计数（供其他删除路径复用）
    direct = sql_db.delete_fusion_by_course(cid_b)
    check("delete_fusion_by_course 返回分表计数（B）",
          sum(direct.values()) == sum(before_b.values()), str(direct))
    after_b2 = _fusion_rows(cid_b)
    check("直接调用后 B 也已清空", all(v == 0 for v in after_b2.values()), str(after_b2))

    # ---- 收尾 ----
    db.delete_course_graph(cid_b)
    sql_db.delete_course(cid_b)
    db.close()

    print("=" * 60)
    passed = 0
    for name, ok, detail in checks:
        print(f"  {'✓' if ok else '✗'} {name}" + (f"  ({detail})" if detail else ""))
        passed += ok
    print(f"\n通过 {passed}/{len(checks)}")
    print("=" * 60)
    return passed == len(checks)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
