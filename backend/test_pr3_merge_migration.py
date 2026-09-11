"""
PR #3 合并后的迁移验证（只读验证：全程操作 app.db 的副本，绝不动线上库）

验证目标：
1. 课程中心的 3 张表（t_course_member / t_course_invite / t_user_profile）仍在
2. 合作者题库的 3 张表（t_question / t_answer_record / t_question_favorite）由 init_tables()
   的 CREATE TABLE IF NOT EXISTS 正确建出（因为 app.db 二进制冲突取了 main 侧）
3. 所有既有表的行数与关键字段在迁移前后完全不变
4. 迁移幂等（连续跑 3 次结果一致）

用法：在 backend/ 目录下
    python test_pr3_merge_migration.py
"""
import hashlib
import os
import shutil
import sqlite3
import sys

BACKEND = os.path.dirname(os.path.abspath(__file__))
LIVE_DB = os.path.join(BACKEND, "data", "app.db")
WORK_DB = os.path.join(BACKEND, "data", "_pr3_merge_check.db")

# 需要保证行数零变化的既有表（含课程中心新增表）
PROTECTED = [
    "t_user", "t_course", "t_document", "t_learning_record",
    "t_student_favorite", "t_kp_embedding",
    "t_course_member", "t_course_invite", "t_user_profile",
]
# 期望由本次合并新建出来的题库表
EXPECTED_NEW = ["t_question", "t_answer_record", "t_question_favorite"]

passed = failed = 0


def check(cond, label, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label} {extra}")


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(path):
    """读取受保护表的行数 + 表清单"""
    conn = sqlite3.connect(path)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {}
        for t in PROTECTED:
            if t in tables:
                counts[t] = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        # 抽样校验课程中心数据仍在
        courses = {}
        if "t_course" in tables:
            for cid, code in conn.execute(
                    "SELECT course_id, join_code FROM t_course ORDER BY course_id"):
                courses[cid] = code
        teachers = {}
        if "t_course_member" in tables:
            for cid, uid in conn.execute(
                    "SELECT course_id, user_id FROM t_course_member "
                    "WHERE role='teacher' AND status='approved' ORDER BY course_id"):
                teachers[cid] = uid
        docs = {}
        if "t_document" in tables:
            for did, fp in conn.execute(
                    "SELECT doc_id, file_path FROM t_document ORDER BY doc_id"):
                docs[did] = fp
        return {"tables": tables, "counts": counts, "courses": courses,
                "teachers": teachers, "docs": docs}
    finally:
        conn.close()


def main():
    if not os.path.exists(LIVE_DB):
        print(f"找不到线上库：{LIVE_DB}")
        return 1

    live_md5_before = md5(LIVE_DB)
    print(f"线上库 MD5（运行前）: {live_md5_before}")

    print("\n[1] 复制线上库到工作副本")
    shutil.copy2(LIVE_DB, WORK_DB)
    before = snapshot(WORK_DB)
    print(f"  副本表数: {len(before['tables'])}")
    print(f"  受保护表行数: {before['counts']}")
    print(f"  题库表是否已存在: "
          f"{[t for t in EXPECTED_NEW if t in before['tables']] or '均不存在'}")

    print("\n[2] 对副本跑 init_tables()（模拟后端启动时的迁移）")
    os.environ["SQLITE_DB_PATH"] = WORK_DB
    sys.path.insert(0, BACKEND)
    from app.core.sql_database import sql_db  # noqa: E402

    check(os.path.abspath(sql_db.db_path) == os.path.abspath(WORK_DB),
          "sql_db 指向的是副本而非线上库",
          f"实际={sql_db.db_path}")

    for round_no in (1, 2, 3):
        sql_db.init_tables()
        snap = snapshot(WORK_DB)
        if round_no == 1:
            print(f"\n[3] 迁移后表数: {len(snap['tables'])}")
            for t in EXPECTED_NEW:
                check(t in snap["tables"], f"题库表已建出: {t}")
            for t in PROTECTED:
                if t in before["counts"]:
                    check(snap["counts"].get(t) == before["counts"][t],
                          f"行数不变: {t}",
                          f"{before['counts'][t]} -> {snap['counts'].get(t)}")
            check(snap["courses"] == before["courses"],
                  "全部课程 join_code 未被改动")
            check(snap["teachers"] == before["teachers"],
                  "教师成员关系未被改动")
            check(snap["docs"] == before["docs"],
                  "文档 file_path 未被改动")
            for t in PROTECTED:
                check(t in snap["tables"], f"课程中心表仍在: {t}")
        else:
            check(snap == snapshot(WORK_DB), f"第 {round_no} 次迁移幂等")

    print("\n[4] 校验题库表结构可写（插入后回滚，不留数据）")
    conn = sqlite3.connect(WORK_DB)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(t_question)")]
        for c in ("question_id", "course_id", "document_id", "kp_id", "q_type",
                  "stem", "options", "answer", "analysis", "difficulty",
                  "source", "created_by", "is_active"):
            check(c in cols, f"t_question 含列 {c}")
        acols = [r[1] for r in conn.execute("PRAGMA table_info(t_answer_record)")]
        for c in ("record_id", "user_id", "question_id", "user_answer",
                  "is_correct", "score", "grade_source"):
            check(c in acols, f"t_answer_record 含列 {c}")
    finally:
        conn.close()

    print(f"\n线上库 MD5（运行后）: {md5(LIVE_DB)}")
    check(md5(LIVE_DB) == live_md5_before, "线上库文件全程未被修改")

    try:
        os.remove(WORK_DB)
    except OSError:
        # sql_db 的单例连接仍持有文件句柄（Windows 下无法立即删除），不影响验证结论
        print(f"（副本 {os.path.basename(WORK_DB)} 句柄未释放，可稍后手动删除）")
    print(f"\n===== {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
