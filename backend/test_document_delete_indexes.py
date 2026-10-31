"""文档级删除复合索引回归测试（临时库，不触碰线上 app.db）。

验证三件事：
1. 旧库（t_learning_record / t_student_favorite 没有 document_id 列）经 init_tables
   迁移后能补齐列并建出索引 —— 证明索引放在 _migrate 而不是 _SCHEMA_SQL 的顺序是对的；
2. 三个 DELETE 查询计划都命中新建索引，而不是全表扫描；
3. 索引可重复初始化（幂等）。

运行：cd backend && python test_document_delete_indexes.py
"""
import os
import sqlite3
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core import sql_database as S
from app.core.config import settings

TABLES = {
    "t_learning_record": "idx_lr_course_doc",
    "t_student_favorite": "idx_fav_course_doc",
    "t_answer_record": "idx_ans_course_doc",
}
failures = []


def check(label, ok, detail=""):
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def _plan(conn, sql, params):
    rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return " | ".join(str(r[3]) for r in rows)


def main() -> int:
    fd, path = tempfile.mkstemp(prefix="kg_index_test_", suffix=".db")
    os.close(fd)
    original_path = settings.SQLITE_DB_PATH
    try:
        # 模拟旧库：先建两张「没有 document_id」的历史表
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE t_learning_record ("
            " record_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " user_id INTEGER NOT NULL, course_id INTEGER NOT NULL,"
            " kp_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'MASTERED',"
            " mastery_level INTEGER NOT NULL DEFAULT 100,"
            " source TEXT NOT NULL DEFAULT 'MANUAL', last_learned_at TEXT,"
            " created_at TEXT, updated_at TEXT,"
            " UNIQUE(user_id, course_id, kp_id))"
        )
        conn.execute(
            "CREATE TABLE t_student_favorite ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " user_id INTEGER NOT NULL, course_id INTEGER NOT NULL,"
            " kp_id TEXT NOT NULL, created_at TEXT,"
            " UNIQUE(user_id, course_id, kp_id))"
        )
        conn.commit()
        conn.close()

        settings.SQLITE_DB_PATH = path
        db = S.SQLDatabase()
        db.init_tables()
        db.init_tables()          # 幂等：第二次不应报错
        settings.SQLITE_DB_PATH = original_path

        conn = sqlite3.connect(path)
        try:
            for table, index in TABLES.items():
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
                check(f"{table} 已补齐 document_id", "document_id" in cols)

                indexes = {r[1] for r in conn.execute(f"PRAGMA index_list({table})")}
                check(f"{table} 存在 {index}", index in indexes, str(sorted(indexes)))

                plan = _plan(
                    conn,
                    f"DELETE FROM {table} WHERE course_id = ? AND document_id = ?",
                    (1, 2),
                )
                check(f"{table} 删除命中索引", index in plan, plan)
        finally:
            conn.close()
    finally:
        settings.SQLITE_DB_PATH = original_path
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass

    print(f"通过 {len(TABLES) * 3 - len(failures)}/{len(TABLES) * 3}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
