"""
SQLite 关系型数据库访问层（对齐规划文档 4.2 节：t_user / t_course / t_document / t_learning_record）

设计说明：
- 第一阶段用 SQLite（零部署、Python 标准库），第二阶段迁移 MySQL 时仅需替换本模块底层连接实现，
  上层方法签名、表名、字段名全部保持不变，业务代码零改动。
- MySQL -> SQLite 类型映射（SQLite 无 ENUM / UNSIGNED / ON UPDATE 语法，用等价手段保留语义）：
    BIGINT/INT/TINYINT UNSIGNED -> INTEGER
    VARCHAR / CHAR / TEXT / ENUM -> TEXT（ENUM 取值用 CHECK 约束保留）
    DATETIME                     -> TEXT（存 "YYYY-MM-DD HH:MM:SS"，与 MySQL DATETIME 字符串一致）
    AUTO_INCREMENT               -> INTEGER PRIMARY KEY AUTOINCREMENT
    DEFAULT CURRENT_TIMESTAMP    -> DEFAULT (datetime('now','localtime'))
    ON UPDATE CURRENT_TIMESTAMP  -> 应用层在 UPDATE 时显式写入 updated_at（见 _update 相关方法）
"""
import os
import json
import sqlite3
from datetime import datetime

from .config import settings
from .security import hash_password

# 枚举取值（与规划文档表格 8/9/10/11 的 ENUM 定义一致，供应用层校验）
USER_ROLES = ("teacher", "student")
DOC_FILE_TYPES = ("PDF", "TXT", "DOCX", "MD")
DOC_PARSE_STATUS = ("UPLOADED", "PARSING", "PARSED", "FAILED")
DOC_EXTRACT_STATUS = ("PENDING", "EXTRACTING", "COMPLETED", "FAILED")
RECORD_STATUS = ("MASTERED", "LEARNING", "RECOMMENDED")
RECORD_SOURCE = ("MANUAL", "SYSTEM")

# 题库枚举（Scope A：仅三型客观题，全部可自动判分）
QUESTION_TYPES = ("SINGLE", "MULTI", "JUDGE")
QUESTION_SOURCE = ("MANUAL", "AI", "IMPORT")
ANSWER_GRADE_SOURCE = ("AUTO", "LLM", "TEACHER")

# 默认教师账号初始密码（仅用于演示/初始开发；生产环境应删除默认账号或改为环境变量注入）
DEFAULT_TEACHER_PASSWORD = "admin123"


def _now() -> str:
    """返回当前本地时间字符串（MySQL DATETIME 兼容格式）"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# 建表 DDL（含索引、CHECK 约束、外键）。顺序敏感：先建被引用的父表。
_SCHEMA_SQL = [
    # 4.2.1 用户表
    """
    CREATE TABLE IF NOT EXISTS t_user (
        user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role          TEXT NOT NULL DEFAULT 'student' CHECK (role IN ('teacher', 'student')),
        display_name  TEXT,
        email         TEXT,
        is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_role ON t_user(role);",

    # 4.2.2 课程表
    """
    CREATE TABLE IF NOT EXISTS t_course (
        course_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        course_code TEXT UNIQUE,
        course_name TEXT NOT NULL,
        description TEXT,
        teacher_id  INTEGER NOT NULL,
        status      INTEGER NOT NULL DEFAULT 1 CHECK (status IN (0, 1)),
        created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (teacher_id) REFERENCES t_user(user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_teacher_id ON t_course(teacher_id);",

    # 4.2.3 文档表
    """
    CREATE TABLE IF NOT EXISTS t_document (
        doc_id            INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id         INTEGER NOT NULL,
        uploader_id       INTEGER NOT NULL,
        file_name         TEXT NOT NULL,
        file_type         TEXT NOT NULL CHECK (file_type IN ('PDF', 'TXT', 'DOCX', 'MD')),
        file_size         INTEGER NOT NULL,
        file_sha256       TEXT,
        file_path         TEXT,
        parse_status      TEXT NOT NULL DEFAULT 'UPLOADED'
                          CHECK (parse_status IN ('UPLOADED', 'PARSING', 'PARSED', 'FAILED')),
        extract_status    TEXT NOT NULL DEFAULT 'PENDING'
                          CHECK (extract_status IN ('PENDING', 'EXTRACTING', 'COMPLETED', 'FAILED')),
        error_message     TEXT,
        chunk_count       INTEGER NOT NULL DEFAULT 0,
        entity_count      INTEGER NOT NULL DEFAULT 0,
        relation_count    INTEGER NOT NULL DEFAULT 0,
        vector_collection TEXT,
        created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (course_id) REFERENCES t_course(course_id),
        FOREIGN KEY (uploader_id) REFERENCES t_user(user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_course_id ON t_document(course_id);",
    "CREATE INDEX IF NOT EXISTS idx_uploader_id ON t_document(uploader_id);",
    "CREATE INDEX IF NOT EXISTS idx_parse_status ON t_document(parse_status);",
    "CREATE INDEX IF NOT EXISTS idx_extract_status ON t_document(extract_status);",

    # 4.2.4 学习记录表（kp_id 为逻辑外键，关联 Neo4j KnowledgePoint，不建物理外键）
    """
    CREATE TABLE IF NOT EXISTS t_learning_record (
        record_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        course_id       INTEGER NOT NULL,
        document_id     INTEGER,
        kp_id           TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'MASTERED'
                        CHECK (status IN ('MASTERED', 'LEARNING', 'RECOMMENDED')),
        mastery_level   INTEGER NOT NULL DEFAULT 100 CHECK (mastery_level BETWEEN 0 AND 100),
        source          TEXT NOT NULL DEFAULT 'MANUAL' CHECK (source IN ('MANUAL', 'SYSTEM')),
        last_learned_at TEXT,
        created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES t_user(user_id),
        FOREIGN KEY (course_id) REFERENCES t_course(course_id),
        UNIQUE (user_id, course_id, kp_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_user_course ON t_learning_record(user_id, course_id);",
    "CREATE INDEX IF NOT EXISTS idx_course_kp ON t_learning_record(course_id, kp_id);",

    # 4.2.5 知识点向量表（RAG 向量检索；embedding 存 JSON 数组文本）
    """
    CREATE TABLE IF NOT EXISTS t_kp_embedding (
        course_id    INTEGER NOT NULL,
        document_id  INTEGER,
        kp_id        TEXT NOT NULL,
        embedding  TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        PRIMARY KEY (course_id, kp_id)
    )
    """,

    # 4.2.6 学生收藏表（收藏 = 学生个人知识点书签，独立于学习状态；kp_id 为逻辑外键指向 Neo4j）
    """
    CREATE TABLE IF NOT EXISTS t_student_favorite (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        course_id   INTEGER NOT NULL,
        document_id INTEGER,
        kp_id       TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES t_user(user_id),
        FOREIGN KEY (course_id) REFERENCES t_course(course_id),
        UNIQUE (user_id, course_id, kp_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_fav_user_course ON t_student_favorite(user_id, course_id);",

    # 4.2.7 题目表（题库唯一事实来源；kp_id 为逻辑外键 → Neo4j KnowledgePoint）
    # options / answer 用 JSON 文本存储：题型差异大（单选/多选/判断），拆表会产生大量空列；
    # 与 t_kp_embedding.embedding 存 JSON 同一先例，迁 MySQL 时 TEXT/JSON 均可，业务代码零改动。
    """
    CREATE TABLE IF NOT EXISTS t_question (
        question_id  INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id    INTEGER NOT NULL,
        document_id  INTEGER,
        kp_id        TEXT,
        q_type       TEXT NOT NULL CHECK (q_type IN ('SINGLE', 'MULTI', 'JUDGE')),
        stem         TEXT NOT NULL,
        options      TEXT,
        answer       TEXT NOT NULL,
        analysis     TEXT,
        difficulty   INTEGER NOT NULL DEFAULT 3 CHECK (difficulty BETWEEN 1 AND 5),
        source       TEXT NOT NULL DEFAULT 'MANUAL' CHECK (source IN ('MANUAL', 'AI', 'IMPORT')),
        created_by   INTEGER NOT NULL,
        is_active    INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (course_id) REFERENCES t_course(course_id),
        FOREIGN KEY (created_by) REFERENCES t_user(user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_q_course_doc ON t_question(course_id, document_id);",
    "CREATE INDEX IF NOT EXISTS idx_q_kp ON t_question(kp_id);",
    "CREATE INDEX IF NOT EXISTS idx_q_type ON t_question(course_id, q_type);",

    # 4.2.8 学生答题记录（错题本 + 正确率统计的唯一来源）
    # 追加式（不建 UNIQUE）：同一题可多次作答，错题本取「每题最近一次」；
    # 这样既能统计正确率趋势，又不会覆盖历史作答。
    """
    CREATE TABLE IF NOT EXISTS t_answer_record (
        record_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL,
        course_id    INTEGER NOT NULL,
        document_id  INTEGER,
        question_id  INTEGER NOT NULL,
        user_answer  TEXT,
        is_correct   INTEGER NOT NULL DEFAULT 0 CHECK (is_correct IN (0, 1)),
        score        REAL NOT NULL DEFAULT 0,
        grade_source TEXT NOT NULL DEFAULT 'AUTO' CHECK (grade_source IN ('AUTO', 'LLM', 'TEACHER')),
        answered_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (user_id) REFERENCES t_user(user_id),
        FOREIGN KEY (course_id) REFERENCES t_course(course_id),
        FOREIGN KEY (question_id) REFERENCES t_question(question_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ans_user_q ON t_answer_record(user_id, question_id);",
    "CREATE INDEX IF NOT EXISTS idx_ans_user_c ON t_answer_record(user_id, course_id, document_id);",

    # 4.2.9 学生题目收藏（独立于 t_student_favorite 的知识点收藏：
    # 后者 kp_id NOT NULL 且语义为「知识点书签」，混用会污染两侧统计口径）
    """
    CREATE TABLE IF NOT EXISTS t_question_favorite (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        course_id   INTEGER NOT NULL,
        question_id INTEGER NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        UNIQUE (user_id, question_id),
        FOREIGN KEY (user_id) REFERENCES t_user(user_id),
        FOREIGN KEY (course_id) REFERENCES t_course(course_id),
        FOREIGN KEY (question_id) REFERENCES t_question(question_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_qfav_user_course ON t_question_favorite(user_id, course_id);",
]


class SQLDatabase:
    """SQLite 数据库管理类（第一阶段；第二阶段由 MySQL 实现替换底层连接）"""

    def __init__(self):
        self.db_path = settings.SQLITE_DB_PATH
        # 确保数据库文件所在目录存在
        parent = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(parent, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """新建连接：开启外键约束 + 行字典工厂"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_tables(self):
        """初始化表结构（幂等，可重复调用）"""
        with self._connect() as conn:
            for stmt in _SCHEMA_SQL:
                conn.execute(stmt)
            conn.commit()
        self._migrate()

    def _migrate(self):
        """幂等迁移：为旧库补齐 document_id 列并回填（文档作用域改造）。

        第一阶段历史数据「一个课程 == 一个文档」，故每个 course_id 至多映射一个 doc_id，
        可安全回填；仅回填 document_id IS NULL 的行，重复执行无副作用。
        新库由 _SCHEMA_SQL 直接建出含 document_id 的表，本方法对空表无影响。

        说明：document_id 列故意不设 NOT NULL，以保证「改列阶段」旧写入路径
        （尚未传 document_id）不报错；Phase 5/8 后所有写入都会显式提供 document_id。
        """
        doc_scoped_tables = (
            ("t_learning_record", "course_id"),
            ("t_student_favorite", "course_id"),
            ("t_kp_embedding", "course_id"),
        )
        with self._connect() as conn:
            for table, fk in doc_scoped_tables:
                columns = {row["name"] for row in
                           conn.execute(f"PRAGMA table_info({table})").fetchall()}
                if "document_id" not in columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN document_id INTEGER")
                conn.execute(
                    f"UPDATE {table} SET document_id = ("
                    f"SELECT d.doc_id FROM t_document d WHERE d.course_id = {table}.{fk} LIMIT 1"
                    f") WHERE document_id IS NULL"
                )
            conn.commit()

    def _execute(self, sql: str, params: tuple = ()) -> int:
        """执行写操作，返回 lastrowid（INSERT 时的自增主键）"""
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.lastrowid

    def _query(self, sql: str, params: tuple = ()) -> list:
        """执行查询，返回字典列表"""
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def _query_one(self, sql: str, params: tuple = ()) -> dict:
        """执行查询，返回单行字典；无结果返回 None"""
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    # ---------- 用户 ----------

    def create_user(self, username: str, password_hash: str, role: str = "student",
                    display_name: str = None, email: str = None) -> int:
        return self._execute(
            "INSERT INTO t_user (username, password_hash, role, display_name, email) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, password_hash, role, display_name, email),
        )

    def get_user_by_username(self, username: str) -> dict:
        return self._query_one("SELECT * FROM t_user WHERE username = ?", (username,))

    def get_user_by_id(self, user_id: int) -> dict:
        return self._query_one("SELECT * FROM t_user WHERE user_id = ?", (user_id,))

    def list_users(self) -> list:
        return self._query("SELECT * FROM t_user ORDER BY user_id")

    def ensure_default_teacher(self) -> int:
        """确保存在默认教师账号 admin（初始密码 admin123，仅用于演示），返回其 user_id"""
        existing = self.get_user_by_username("admin")
        if existing:
            # 迁移：旧版占位密码 "<not-implemented>" 无法通过校验，替换为真实哈希
            if existing["password_hash"] == "<not-implemented>":
                self._execute(
                    "UPDATE t_user SET password_hash = ? WHERE user_id = ?",
                    (hash_password(DEFAULT_TEACHER_PASSWORD), existing["user_id"]),
                )
                existing = self.get_user_by_username("admin")
            return existing["user_id"]
        return self.create_user(
            username="admin", password_hash=hash_password(DEFAULT_TEACHER_PASSWORD),
            role="teacher", display_name="默认教师",
        )

    # ---------- 课程 ----------

    def create_course(self, course_name: str, teacher_id: int,
                      course_code: str = None, description: str = None) -> int:
        return self._execute(
            "INSERT INTO t_course (course_name, teacher_id, course_code, description) "
            "VALUES (?, ?, ?, ?)",
            (course_name, teacher_id, course_code, description),
        )

    def get_course(self, course_id: int) -> dict:
        return self._query_one("SELECT * FROM t_course WHERE course_id = ?", (course_id,))

    def list_courses(self) -> list:
        return self._query("SELECT * FROM t_course ORDER BY course_id")

    def get_course_by_name(self, course_name: str) -> dict:
        return self._query_one("SELECT * FROM t_course WHERE course_name = ?", (course_name,))

    def get_course_by_code(self, course_code: str) -> dict:
        return self._query_one("SELECT * FROM t_course WHERE course_code = ?", (course_code,))

    def list_courses_page(self, page: int = 1, page_size: int = 10,
                          teacher_id: int = None, keyword: str = None):
        """分页查询课程（LEFT JOIN 教师表取教师名），返回 (total, rows)"""
        where, params = [], []
        if teacher_id is not None:
            where.append("c.teacher_id = ?")
            params.append(teacher_id)
        if keyword:
            where.append("c.course_name LIKE ?")
            params.append(f"%{keyword}%")
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        total = self._query_one(
            f"SELECT count(*) AS cnt FROM t_course c {where_sql}", tuple(params)
        )["cnt"]

        rows = self._query(
            f"""
            SELECT c.*, COALESCE(u.display_name, u.username, '') AS teacher_name
            FROM t_course c LEFT JOIN t_user u ON c.teacher_id = u.user_id
            {where_sql}
            ORDER BY c.course_id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [page_size, (page - 1) * page_size]),
        )
        return total, rows

    def update_course(self, course_id: int, **fields) -> None:
        """更新课程字段（白名单，None 跳过表示不修改），自动刷新 updated_at"""
        allowed = {"course_name", "course_code", "description", "status"}
        sets, params = [], []
        for key, val in fields.items():
            if key not in allowed or val is None:
                continue
            sets.append(f"{key} = ?")
            params.append(val)
        if not sets:
            return
        sets.append("updated_at = ?")
        params.append(_now())
        params.append(course_id)
        self._execute(f"UPDATE t_course SET {', '.join(sets)} WHERE course_id = ?", tuple(params))

    def delete_course(self, course_id: int) -> int:
        """删除课程及其文档、学习记录、收藏、向量、题库（按子表->父表顺序满足外键），返回删除的文档数。

        Phase 9（技术债修复）：补充清理 t_kp_embedding——该表无外键、不参与级联，
        历史实现整课删除会残留孤儿向量，故在此显式删除。
        题库（题目/答题记录/题目收藏）同样无级联，必须在删 t_course 前显式清理，
        否则会留下指向已删课程的孤儿题目。
        """
        doc_count = self.count_documents_by_course(course_id)
        with self._connect() as conn:
            conn.execute("DELETE FROM t_kp_embedding WHERE course_id = ?", (course_id,))
            conn.execute("DELETE FROM t_student_favorite WHERE course_id = ?", (course_id,))
            conn.execute("DELETE FROM t_learning_record WHERE course_id = ?", (course_id,))
            # 题库：先删题目收藏与答题记录（引用 t_question），再删题目本身
            conn.execute(
                "DELETE FROM t_question_favorite WHERE question_id IN "
                "(SELECT question_id FROM t_question WHERE course_id = ?)", (course_id,),
            )
            conn.execute(
                "DELETE FROM t_answer_record WHERE question_id IN "
                "(SELECT question_id FROM t_question WHERE course_id = ?)", (course_id,),
            )
            conn.execute("DELETE FROM t_question WHERE course_id = ?", (course_id,))
            conn.execute("DELETE FROM t_document WHERE course_id = ?", (course_id,))
            conn.execute("DELETE FROM t_course WHERE course_id = ?", (course_id,))
            conn.commit()
        return doc_count

    # ---------- 文档 ----------

    def create_document(self, course_id: int, uploader_id: int, file_name: str,
                        file_type: str, file_size: int,
                        file_sha256: str = None, file_path: str = None) -> int:
        return self._execute(
            "INSERT INTO t_document "
            "(course_id, uploader_id, file_name, file_type, file_size, file_sha256, file_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (course_id, uploader_id, file_name, file_type, file_size, file_sha256, file_path),
        )

    def update_document(self, doc_id: int, **fields) -> None:
        """
        更新文档表字段（字段白名单防注入），自动刷新 updated_at。
        示例：update_document(doc_id, parse_status='PARSED', entity_count=12)
        """
        allowed = {"parse_status", "extract_status", "error_message", "chunk_count",
                   "entity_count", "relation_count", "vector_collection", "file_path"}
        sets, params = [], []
        for key, val in fields.items():
            if key not in allowed:
                continue
            sets.append(f"{key} = ?")
            params.append(val)
        if not sets:
            return
        sets.append("updated_at = ?")
        params.append(_now())
        params.append(doc_id)
        self._execute(f"UPDATE t_document SET {', '.join(sets)} WHERE doc_id = ?", tuple(params))

    def get_document(self, doc_id: int) -> dict:
        return self._query_one("SELECT * FROM t_document WHERE doc_id = ?", (doc_id,))

    def list_documents_by_course(self, course_id: int) -> list:
        return self._query(
            "SELECT * FROM t_document WHERE course_id = ? ORDER BY doc_id", (course_id,),
        )

    def count_documents_by_course(self, course_id: int) -> int:
        return self._query_one(
            "SELECT count(*) AS cnt FROM t_document WHERE course_id = ?", (course_id,),
        )["cnt"]

    def count_documents_grouped(self) -> dict:
        """按课程统计文档数，返回 {course_id: count}"""
        rows = self._query("SELECT course_id, count(*) AS cnt FROM t_document GROUP BY course_id")
        return {r["course_id"]: r["cnt"] for r in rows}

    def delete_document(self, doc_id: int) -> int:
        """删除单个文档记录（仅删除 t_document 行；图谱/向量/学习/收藏清理由上层 Phase 8/9 完成）"""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM t_document WHERE doc_id = ?", (doc_id,))
            conn.commit()
            return cur.rowcount

    # ---------- 学习记录 ----------

    def upsert_learning_record(self, user_id: int, course_id: int, document_id, kp_id: str,
                               status: str = "MASTERED", mastery_level: int = 100,
                               source: str = "MANUAL", last_learned_at: str = None) -> int:
        """
        写入学习记录；依赖 UNIQUE(user_id, course_id, kp_id) 冲突时更新，
        保证同一学生、同一课程、同一知识点仅一条记录。

        Phase 8B：document_id 作为业务作用域字段写入（kp_id 全局唯一，UNIQUE 无需改为四列；
        具体见规划文档「数据库约束」）。注：ON CONFLICT DO UPDATE 为 SQLite 语法，
        迁 MySQL 时改为 ON DUPLICATE KEY UPDATE。
        """
        now = _now()
        sql = """
        INSERT INTO t_learning_record
            (user_id, course_id, document_id, kp_id, status, mastery_level, source, last_learned_at,
             created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, course_id, kp_id) DO UPDATE SET
            document_id = excluded.document_id,
            status = excluded.status,
            mastery_level = excluded.mastery_level,
            source = excluded.source,
            last_learned_at = excluded.last_learned_at,
            updated_at = excluded.updated_at
        """
        return self._execute(sql, (user_id, course_id, document_id, kp_id, status, mastery_level,
                                   source, last_learned_at, now, now))

    def list_records_by_user_course(self, user_id: int, course_id: int, document_id=None) -> list:
        """查询某用户某文档的学习记录；document_id 为 None 时退化为课程级（教师监测汇总）"""
        if document_id is not None:
            return self._query(
                "SELECT * FROM t_learning_record WHERE user_id = ? AND course_id = ? "
                "AND document_id = ? ORDER BY record_id",
                (user_id, course_id, document_id),
            )
        return self._query(
            "SELECT * FROM t_learning_record WHERE user_id = ? AND course_id = ? "
            "ORDER BY record_id",
            (user_id, course_id),
        )

    def list_records_by_user(self, user_id: int) -> list:
        return self._query(
            "SELECT * FROM t_learning_record WHERE user_id = ? ORDER BY course_id, record_id",
            (user_id,),
        )

    def list_records_by_course(self, course_id: int) -> list:
        """查询某课程下全部学习记录（教师查看班级学习情况）"""
        return self._query(
            "SELECT * FROM t_learning_record WHERE course_id = ? ORDER BY user_id, record_id",
            (course_id,),
        )

    def delete_learning_record(self, user_id: int, course_id: int, document_id, kp_id: str) -> int:
        """删除某用户某文档某知识点的学习记录（用于取消掌握标记）"""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM t_learning_record "
                "WHERE user_id = ? AND course_id = ? AND document_id = ? AND kp_id = ?",
                (user_id, course_id, document_id, kp_id),
            )
            conn.commit()
            return cur.rowcount

    # ---------- 学生收藏（收藏 = 个人知识点书签，独立于学习状态） ----------

    def add_favorite(self, user_id: int, course_id: int, document_id, kp_id: str) -> bool:
        """新增收藏（INSERT OR IGNORE 幂等）；返回是否新插入（True=新增，False=已存在未重复）。

        Phase 8B：document_id 作为业务作用域字段写入（kp_id 全局唯一，UNIQUE 无需改为四列）。
        """
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO t_student_favorite (user_id, course_id, document_id, kp_id) "
                "VALUES (?, ?, ?, ?)",
                (user_id, course_id, document_id, kp_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def remove_favorite(self, user_id: int, course_id: int, document_id, kp_id: str) -> int:
        """取消收藏，返回删除条数"""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM t_student_favorite "
                "WHERE user_id = ? AND course_id = ? AND document_id = ? AND kp_id = ?",
                (user_id, course_id, document_id, kp_id),
            )
            conn.commit()
            return cur.rowcount

    def list_favorites_by_user_course(self, user_id: int, course_id: int, document_id=None) -> list:
        """查询某用户某文档的收藏（按收藏时间倒序）；document_id 为 None 时退化为课程级"""
        if document_id is not None:
            return self._query(
                "SELECT kp_id, course_id, document_id, created_at FROM t_student_favorite "
                "WHERE user_id = ? AND course_id = ? AND document_id = ? ORDER BY id DESC",
                (user_id, course_id, document_id),
            )
        return self._query(
            "SELECT kp_id, course_id, created_at FROM t_student_favorite "
            "WHERE user_id = ? AND course_id = ? ORDER BY id DESC",
            (user_id, course_id),
        )

    def list_favorites_by_user(self, user_id: int) -> list:
        """查询某用户全部课程的收藏（按课程 + 收藏时间倒序）"""
        return self._query(
            "SELECT kp_id, course_id, created_at FROM t_student_favorite "
            "WHERE user_id = ? ORDER BY course_id, id DESC",
            (user_id,),
        )

    def count_favorites_by_course(self, course_id: int) -> dict:
        """按用户统计某课程的收藏数，返回 {user_id: count}（教师查看学生收藏情况）"""
        rows = self._query(
            "SELECT user_id, count(*) AS cnt FROM t_student_favorite "
            "WHERE course_id = ? GROUP BY user_id",
            (course_id,),
        )
        return {r["user_id"]: r["cnt"] for r in rows}

    # ---------- 知识点向量（RAG 向量检索） ----------

    def upsert_kp_embedding(self, course_id: int, document_id, kp_id: str, embedding: list) -> int:
        """写入/更新知识点向量（embedding 序列化为 JSON 文本；Phase 8C 保存 document_id）"""
        return self._execute(
            "INSERT INTO t_kp_embedding (course_id, document_id, kp_id, embedding, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(course_id, kp_id) DO UPDATE SET "
            "document_id = excluded.document_id, "
            "embedding = excluded.embedding, updated_at = excluded.updated_at",
            (course_id, document_id, kp_id, json.dumps(embedding), _now()),
        )

    def get_embeddings_by_document(self, course_id: int, document_id) -> list:
        """返回文档全部知识点向量，[{kp_id, embedding(list[float])}]"""
        rows = self._query(
            "SELECT kp_id, embedding FROM t_kp_embedding WHERE course_id = ? AND document_id = ?",
            (course_id, document_id),
        )
        result = []
        for r in rows:
            try:
                vec = json.loads(r["embedding"])
            except (ValueError, TypeError):
                continue
            result.append({"kp_id": r["kp_id"], "embedding": vec})
        return result

    def delete_embeddings_by_document(self, course_id: int, document_id) -> int:
        """删除文档全部知识点向量，返回删除条数"""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM t_kp_embedding WHERE course_id = ? AND document_id = ?",
                (course_id, document_id),
            )
            conn.commit()
            return cur.rowcount

    def count_embeddings_by_course(self, course_id: int) -> int:
        """某课程全部知识点向量数量（供整课删除前统计与报告）"""
        return self._query_one(
            "SELECT count(*) AS cnt FROM t_kp_embedding WHERE course_id = ?", (course_id,),
        )["cnt"]

    def delete_learning_records_by_document(self, course_id: int, document_id) -> int:
        """删除文档全部学习记录，返回删除条数（Phase 8C 删除文档级清理）"""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM t_learning_record WHERE course_id = ? AND document_id = ?",
                (course_id, document_id),
            )
            conn.commit()
            return cur.rowcount

    def delete_favorites_by_document(self, course_id: int, document_id) -> int:
        """删除文档全部收藏，返回删除条数（Phase 8C 删除文档级清理）"""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM t_student_favorite WHERE course_id = ? AND document_id = ?",
                (course_id, document_id),
            )
            conn.commit()
            return cur.rowcount

    # ---------- 题库：题目（题库唯一事实来源） ----------

    @staticmethod
    def _json_text(value):
        """把 options/answer 一律序列化为 JSON 文本（None 原样返回）。

        为什么「一律 dumps」而不是「字符串原样返回」：
        - 单选答案 "A" 这类字符串不是合法 JSON，原样存库后回读 json.loads 会失败；
        - 判断题答案 "true" 恰好是合法 JSON，原样存库后回读会变成布尔 True；
        两种题型行为不一致（单选永远判错）。统一 json.dumps 后 _loads 可无损还原：
        "A" -> '"A"' -> "A"，"true" -> '"true"' -> "true"。
        """
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def create_question(self, course_id: int, document_id, kp_id, q_type: str,
                        stem: str, options, answer, analysis: str = None,
                        difficulty: int = 3, created_by: int = None,
                        source: str = "MANUAL") -> int:
        """新增题目，返回 question_id（options/answer 自动序列化为 JSON 文本）"""
        return self._execute(
            "INSERT INTO t_question "
            "(course_id, document_id, kp_id, q_type, stem, options, answer, analysis, "
            " difficulty, source, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (course_id, document_id, kp_id, q_type, stem,
             self._json_text(options), self._json_text(answer),
             analysis, difficulty, source, created_by),
        )

    def get_question(self, question_id: int) -> dict:
        return self._query_one("SELECT * FROM t_question WHERE question_id = ?", (question_id,))

    def update_question(self, question_id: int, **fields) -> None:
        """更新题目字段（白名单，None 跳过表示不修改；options/answer 自动序列化），刷新 updated_at"""
        allowed = {"document_id", "kp_id", "q_type", "stem", "options", "answer",
                   "analysis", "difficulty", "source", "is_active"}
        sets, params = [], []
        for key, val in fields.items():
            if key not in allowed or val is None:
                continue
            if key in ("options", "answer"):
                val = self._json_text(val)
            sets.append(f"{key} = ?")
            params.append(val)
        if not sets:
            return
        sets.append("updated_at = ?")
        params.append(_now())
        params.append(question_id)
        self._execute(f"UPDATE t_question SET {', '.join(sets)} WHERE question_id = ?", tuple(params))

    def set_question_document(self, question_id: int, document_id) -> int:
        """把题目挂到指定文档（document_id=None 表示改为「课程通用题」）。

        单独提供该方法是必要的：update_question 对 None 的语义是「不修改」，
        无法表达「清空 document_id」，而「改为课程通用题」是教师端的真实编辑动作。
        """
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE t_question SET document_id = ?, updated_at = ? WHERE question_id = ?",
                (document_id, _now(), question_id),
            )
            conn.commit()
            return cur.rowcount

    def set_question_active(self, question_id: int, is_active: bool) -> int:
        """启用/停用题目（软删：保留学生答题记录，仅从出题池移除），返回受影响行数"""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE t_question SET is_active = ?, updated_at = ? WHERE question_id = ?",
                (1 if is_active else 0, _now(), question_id),
            )
            conn.commit()
            return cur.rowcount

    def delete_question(self, question_id: int) -> int:
        """物理删除题目及其全部收藏/答题记录（先删子表再删主表，满足外键顺序）"""
        with self._connect() as conn:
            conn.execute("DELETE FROM t_question_favorite WHERE question_id = ?", (question_id,))
            conn.execute("DELETE FROM t_answer_record WHERE question_id = ?", (question_id,))
            cur = conn.execute("DELETE FROM t_question WHERE question_id = ?", (question_id,))
            conn.commit()
            return cur.rowcount

    # ---------- 题库：题目查询（管理列表 / 出题池） ----------

    def list_questions(self, course_id: int, document_id=None, kp_id: str = None,
                       q_type: str = None, keyword: str = None, is_active=None,
                       page: int = 1, page_size: int = 10,
                       include_course_level: bool = True):
        """分页查询题目（LEFT JOIN 取创建人姓名），返回 (total, rows)。

        作用域规则：传入 document_id 时默认同时包含「该文档题目」与「课程通用题
        （document_id IS NULL，即题目挂课程不挂具体文档）」；include_course_level=False
        时退化为精确匹配该文档（用于文档级清理/统计）。
        """
        where, params = ["course_id = ?"], [course_id]
        if document_id is not None:
            if include_course_level:
                where.append("(document_id = ? OR document_id IS NULL)")
            else:
                where.append("document_id = ?")
            params.append(document_id)
        if kp_id:
            where.append("kp_id = ?")
            params.append(kp_id)
        if q_type:
            where.append("q_type = ?")
            params.append(q_type)
        if keyword:
            where.append("stem LIKE ?")
            params.append(f"%{keyword}%")
        if is_active is not None:
            where.append("is_active = ?")
            params.append(1 if is_active else 0)
        where_sql = "WHERE " + " AND ".join(where)

        total = self._query_one(
            f"SELECT count(*) AS cnt FROM t_question {where_sql}", tuple(params),
        )["cnt"]
        rows = self._query(
            f"""
            SELECT q.*, COALESCE(u.display_name, u.username, '') AS creator_name
            FROM t_question q LEFT JOIN t_user u ON q.created_by = u.user_id
            {where_sql}
            ORDER BY q.question_id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [page_size, (page - 1) * page_size]),
        )
        return total, rows

    def list_practice_questions(self, course_id: int, document_id=None, kp_id: str = None,
                                q_type: str = None, limit: int = 10,
                                exclude_ids=None) -> list:
        """出题查询：仅取启用题目，随机排序；document_id 传入时含「该文档题 + 课程通用题」。"""
        where, params = ["course_id = ?", "is_active = 1"], [course_id]
        if document_id is not None:
            where.append("(document_id = ? OR document_id IS NULL)")
            params.append(document_id)
        if kp_id:
            where.append("kp_id = ?")
            params.append(kp_id)
        if q_type:
            where.append("q_type = ?")
            params.append(q_type)
        if exclude_ids:
            placeholders = ",".join("?" for _ in exclude_ids)
            where.append(f"question_id NOT IN ({placeholders})")
            params.extend(list(exclude_ids))
        params.append(limit)
        return self._query(
            f"SELECT * FROM t_question WHERE {' AND '.join(where)} "
            f"ORDER BY RANDOM() LIMIT ?",
            tuple(params),
        )

    def count_questions_by_course(self, course_id: int) -> int:
        return self._query_one(
            "SELECT count(*) AS cnt FROM t_question WHERE course_id = ?", (course_id,),
        )["cnt"]

    def count_questions_by_document(self, course_id: int, document_id) -> int:
        """该文档精确挂载的题目数（不含课程通用题），供文档删除报告使用"""
        return self._query_one(
            "SELECT count(*) AS cnt FROM t_question WHERE course_id = ? AND document_id = ?",
            (course_id, document_id),
        )["cnt"]

    def question_answer_stats(self, course_id: int) -> dict:
        """按题统计作答人次与正确数，返回 {question_id: {"attempts": n, "correct": n}}"""
        rows = self._query(
            "SELECT question_id, count(*) AS attempts, sum(is_correct) AS correct "
            "FROM t_answer_record WHERE course_id = ? GROUP BY question_id",
            (course_id,),
        )
        return {
            r["question_id"]: {"attempts": r["attempts"], "correct": r["correct"] or 0}
            for r in rows
        }

    # ---------- 题库：学生答题记录 ----------

    def add_answer_record(self, user_id: int, course_id: int, document_id, question_id: int,
                          user_answer, is_correct: bool, score: float = 0,
                          grade_source: str = "AUTO") -> int:
        """追加一条答题记录（不覆盖历史，同一题可多次作答）"""
        return self._execute(
            "INSERT INTO t_answer_record "
            "(user_id, course_id, document_id, question_id, user_answer, is_correct, "
            " score, grade_source, answered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, course_id, document_id, question_id, self._json_text(user_answer),
             1 if is_correct else 0, score, grade_source, _now()),
        )

    def list_answer_records(self, user_id: int, course_id: int = None, document_id=None,
                            only_wrong: bool = False) -> list:
        """查询答题记录（时间倒序）；only_wrong=True 仅返回答错的记录（错题本原始数据）"""
        where, params = ["user_id = ?"], [user_id]
        if course_id is not None:
            where.append("course_id = ?")
            params.append(course_id)
        if document_id is not None:
            where.append("document_id = ?")
            params.append(document_id)
        if only_wrong:
            where.append("is_correct = 0")
        return self._query(
            f"SELECT * FROM t_answer_record WHERE {' AND '.join(where)} ORDER BY record_id DESC",
            tuple(params),
        )

    def list_answer_records_by_course(self, course_id: int) -> list:
        """某课程全部答题记录（教师端统计学生练习情况）"""
        return self._query(
            "SELECT * FROM t_answer_record WHERE course_id = ? ORDER BY user_id, record_id",
            (course_id,),
        )

    def count_answers_by_course(self, course_id: int) -> int:
        return self._query_one(
            "SELECT count(*) AS cnt FROM t_answer_record WHERE course_id = ?", (course_id,),
        )["cnt"]

    def count_answers_by_question(self, question_id: int) -> int:
        """某题被作答次数（题目是否可物理删除的判据：已作答过则只允许软删）"""
        return self._query_one(
            "SELECT count(*) AS cnt FROM t_answer_record WHERE question_id = ?", (question_id,),
        )["cnt"]

    def count_answers_grouped_by_course(self) -> dict:
        """按课程统计答题总数，返回 {course_id: count}"""
        rows = self._query(
            "SELECT course_id, count(*) AS cnt FROM t_answer_record GROUP BY course_id",
        )
        return {r["course_id"]: r["cnt"] for r in rows}

    # ---------- 题库：学生题目收藏（独立于知识点收藏 t_student_favorite） ----------

    def add_question_favorite(self, user_id: int, course_id: int, question_id: int) -> bool:
        """新增题目收藏（INSERT OR IGNORE 幂等）；返回是否新插入（True=新增，False=已存在）"""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO t_question_favorite (user_id, course_id, question_id) "
                "VALUES (?, ?, ?)",
                (user_id, course_id, question_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def remove_question_favorite(self, user_id: int, course_id: int, question_id: int) -> int:
        """取消题目收藏，返回删除条数"""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM t_question_favorite "
                "WHERE user_id = ? AND course_id = ? AND question_id = ?",
                (user_id, course_id, question_id),
            )
            conn.commit()
            return cur.rowcount

    def list_question_favorites(self, user_id: int, course_id: int) -> list:
        """查询某用户某课程的题目收藏（按收藏时间倒序）"""
        return self._query(
            "SELECT question_id, course_id, created_at FROM t_question_favorite "
            "WHERE user_id = ? AND course_id = ? ORDER BY id DESC",
            (user_id, course_id),
        )

    def list_question_favorite_ids(self, user_id: int, course_id: int) -> set:
        """某用户某课程已收藏的 question_id 集合（出题时回填 is_favorited 标记）"""
        rows = self._query(
            "SELECT question_id FROM t_question_favorite WHERE user_id = ? AND course_id = ?",
            (user_id, course_id),
        )
        return {r["question_id"] for r in rows}

    def count_question_favorites_grouped(self, course_id: int) -> dict:
        """按题统计某课程的收藏数，返回 {question_id: count}（教师端「题目收藏情况」）"""
        rows = self._query(
            "SELECT question_id, count(*) AS cnt FROM t_question_favorite "
            "WHERE course_id = ? GROUP BY question_id",
            (course_id,),
        )
        return {r["question_id"]: r["cnt"] for r in rows}

    def list_question_favorite_users(self, course_id: int, question_id: int = None) -> list:
        """某课程（或某题）的收藏明细：谁收藏了哪道题，[{user_id, question_id, created_at}]"""
        if question_id is not None:
            return self._query(
                "SELECT user_id, question_id, created_at FROM t_question_favorite "
                "WHERE course_id = ? AND question_id = ? ORDER BY id DESC",
                (course_id, question_id),
            )
        return self._query(
            "SELECT user_id, question_id, created_at FROM t_question_favorite "
            "WHERE course_id = ? ORDER BY id DESC",
            (course_id,),
        )

    # ---------- 题库：级联清理（防孤儿数据，顺序敏感：子表 -> 主表） ----------

    def delete_questions_by_course(self, course_id: int) -> int:
        """删除课程全部题目及其收藏/答题记录，返回删除的题目数（整课删除时调用）"""
        with self._connect() as conn:
            count = conn.execute(
                "SELECT count(*) AS cnt FROM t_question WHERE course_id = ?", (course_id,),
            ).fetchone()["cnt"]
            conn.execute(
                "DELETE FROM t_question_favorite WHERE question_id IN "
                "(SELECT question_id FROM t_question WHERE course_id = ?)", (course_id,),
            )
            conn.execute(
                "DELETE FROM t_answer_record WHERE question_id IN "
                "(SELECT question_id FROM t_question WHERE course_id = ?)", (course_id,),
            )
            conn.execute("DELETE FROM t_question WHERE course_id = ?", (course_id,))
            conn.commit()
            return count

    def delete_questions_by_document(self, course_id: int, document_id) -> int:
        """删除某文档精确挂载的题目（课程通用题 document_id IS NULL 刻意保留），返回题目数。

        防御性处理：若题目在「已被作答之后」才被改挂到别的文档，其答题记录的 document_id
        可能与题目当前 document_id 不一致，故这里先按 question_id 子查询清子表，再删题目，
        避免触发 t_answer_record / t_question_favorite 的外键约束。
        """
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM t_question_favorite WHERE question_id IN "
                "(SELECT question_id FROM t_question WHERE course_id = ? AND document_id = ?)",
                (course_id, document_id),
            )
            conn.execute(
                "DELETE FROM t_answer_record WHERE question_id IN "
                "(SELECT question_id FROM t_question WHERE course_id = ? AND document_id = ?)",
                (course_id, document_id),
            )
            cur = conn.execute(
                "DELETE FROM t_question WHERE course_id = ? AND document_id = ?",
                (course_id, document_id),
            )
            conn.commit()
            return cur.rowcount

    def delete_question_favorites_by_document(self, course_id: int, document_id) -> int:
        """删除某文档题目的收藏记录（须先于题目删除调用），返回条数"""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM t_question_favorite WHERE question_id IN "
                "(SELECT question_id FROM t_question WHERE course_id = ? AND document_id = ?)",
                (course_id, document_id),
            )
            conn.commit()
            return cur.rowcount

    def delete_answers_by_document(self, course_id: int, document_id) -> int:
        """删除某文档的答题记录，返回条数"""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM t_answer_record WHERE course_id = ? AND document_id = ?",
                (course_id, document_id),
            )
            conn.commit()
            return cur.rowcount

    # ---------- 统计（数据总览） ----------

    def count_courses(self) -> int:
        """课程总数"""
        return self._query_one("SELECT count(*) AS cnt FROM t_course")["cnt"]

    def count_users_by_role(self, role: str) -> int:
        """按角色统计用户数（teacher / student）"""
        return self._query_one(
            "SELECT count(*) AS cnt FROM t_user WHERE role = ?", (role,),
        )["cnt"]

    def count_documents(self) -> int:
        """文档总数"""
        return self._query_one("SELECT count(*) AS cnt FROM t_document")["cnt"]


# 全局关系型数据库实例
sql_db = SQLDatabase()
