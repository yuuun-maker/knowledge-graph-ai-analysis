"""
题库服务（教师端题目管理 + 学生端做题练习）

分层约定（与 CourseService / DocumentService 完全一致）：
- 静态方法统一返回 {"ok": bool, "code": int, "message": str, "data": dict}
- 接口层（api/questions.py、api/practice.py）只做参数解析与响应包装

作用域与安全口径（本项目两条硬纪律）：
1. 教师端每个方法都做「课程归属校验」：course.teacher_id != user_id → 4003，
   不能只依赖 require_teacher（否则任何教师都能改别人的题库）。
2. 学生端出题走 _public_view() 白名单投影，**绝不下发 answer / analysis**（防泄题）；
   正确答案与解析只在该题提交后随判分结果返回。

题目作用域：course_id 必填；document_id 可空（空 = 课程通用题，任何文档出题都可见）；
kp_id 可空（逻辑外键指向 Neo4j KnowledgePoint，用于「推荐知识点 → 直接练题」闭环）。
"""
import json

from ..core.database import db
from ..core.sql_database import sql_db

# 题型（Scope A：仅三型客观题，全部可自动判分）
VALID_TYPES = ("SINGLE", "MULTI", "JUDGE")
TYPE_LABELS = {"SINGLE": "单选题", "MULTI": "多选题", "JUDGE": "判断题"}

MAX_STEM_LEN = 1000
MAX_ANALYSIS_LEN = 1000

# 判断题答案同义归一（"对/正确/是/T/Y/1" 一律视为 true）
_JUDGE_TRUE = {"true", "t", "y", "yes", "1", "对", "正确", "是"}
_JUDGE_FALSE = {"false", "f", "n", "no", "0", "错", "错误", "否"}

_HALF_WIDTH = {ord(c): ord(c) - 0xFEE0
               for c in "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
                        "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
                        "０１２３４５６７８９"}


def _loads(value, default):
    """把库内 JSON 文本解析回对象；已是对象则原样返回；解析失败返回 default"""
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _normalize_text(value) -> str:
    """答案/选项键归一化：去首尾空白 → 全角转半角 → 小写（仅用于比较，不改变存储值）"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().translate(_HALF_WIDTH).lower()


def _normalize_judge(value) -> str:
    """判断题答案归一化为 "true"/"false"；无法识别时返回归一化文本本身"""
    text = _normalize_text(value)
    if text in _JUDGE_TRUE:
        return "true"
    if text in _JUDGE_FALSE:
        return "false"
    return text


def _answer_keys(answer) -> set:
    """把答案（标量或数组）展开为归一化后的键集合"""
    if answer is None:
        return set()
    raw = answer if isinstance(answer, list) else [answer]
    keys = {_normalize_text(x) for x in raw}
    keys.discard("")
    return keys


def _parse_options(question: dict) -> list:
    """解析 options 字段为 [{"key","text"}]；兼容 ["A. xxx"] 这类纯字符串写法"""
    raw = _loads(question.get("options"), [])
    options = []
    if isinstance(raw, dict):
        raw = [{"key": k, "text": v} for k, v in raw.items()]
    if not isinstance(raw, list):
        return options
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            key = str(item.get("key") or chr(65 + i)).strip()
            options.append({"key": key, "text": str(item.get("text") or "").strip()})
        else:
            options.append({"key": chr(65 + i), "text": str(item).strip()})
    return options


def _public_view(question: dict, favorited: bool = False) -> dict:
    """学生视角投影：**白名单**，刻意不包含 answer / analysis（防泄题的关键实现）"""
    return {
        "question_id": question["question_id"],
        "course_id": question["course_id"],
        "document_id": question.get("document_id"),
        "kp_id": question.get("kp_id"),
        "q_type": question["q_type"],
        "q_type_label": TYPE_LABELS.get(question["q_type"], question["q_type"]),
        "stem": question["stem"],
        "options": _parse_options(question),
        "difficulty": question.get("difficulty", 3),
        "is_favorited": bool(favorited),
    }


def grade(question: dict, user_answer) -> dict:
    """自动判分（Scope A 三型客观题），返回 {is_correct, score, correct_answer, analysis}。

    - SINGLE：归一化后严格相等
    - MULTI ：归一化后的键集合严格相等（顺序无关；少选/多选任一情况判错）
    - JUDGE ：布尔归一化后相等（对/正确/true/T/1 等价）
    """
    q_type = question["q_type"]
    correct = _loads(question.get("answer"), None)

    if q_type == "JUDGE":
        expected = _normalize_judge(correct)
        got = _normalize_judge(user_answer)
    elif q_type == "MULTI":
        expected = _answer_keys(correct)
        got = _answer_keys(user_answer)
    else:  # SINGLE
        expected = _normalize_text(correct)
        got = _normalize_text(user_answer)

    is_correct = bool(expected) and expected == got

    return {
        "is_correct": is_correct,
        "score": 100.0 if is_correct else 0.0,
        "correct_answer": correct,
        "analysis": question.get("analysis") or "",
    }


def validate_question_payload(payload: dict) -> tuple:
    """校验题目字段（新增/修改共用），返回 (ok, message, normalized)。

    normalized 仅含通过校验的字段，供 DAO 直接落库；题型 / 答案规则：
    - SINGLE/MULTI：≥2 个选项且编号唯一非空；答案键必须落在选项内；SINGLE 恰好 1 个答案
    - JUDGE：答案归一化为 true/false
    """
    normalized = {}

    q_type = (payload.get("q_type") or "").strip().upper()
    if q_type not in VALID_TYPES:
        return False, f"题型不合法，仅支持 {list(VALID_TYPES)}", None

    stem = (payload.get("stem") or "").strip()
    if not stem:
        return False, "题干不能为空", None
    if len(stem) > MAX_STEM_LEN:
        return False, f"题干过长（最大 {MAX_STEM_LEN} 字符）", None

    analysis = payload.get("analysis")
    analysis = analysis.strip() if isinstance(analysis, str) else analysis
    if analysis and len(analysis) > MAX_ANALYSIS_LEN:
        return False, f"解析过长（最大 {MAX_ANALYSIS_LEN} 字符）", None

    difficulty = payload.get("difficulty", 3)
    try:
        difficulty = int(difficulty)
    except (TypeError, ValueError):
        return False, "难度必须为 1-5 的整数", None
    if not (1 <= difficulty <= 5):
        return False, "难度应在 1-5 之间", None

    options = payload.get("options") or []
    answer = payload.get("answer")

    if q_type in ("SINGLE", "MULTI"):
        if not isinstance(options, list) or len(options) < 2:
            return False, "选择题至少需要 2 个选项", None
        parsed = _parse_options({"options": options})
        keys = [o["key"] for o in parsed]
        if any(not k for k in keys):
            return False, "选项编号不能为空", None
        if len({_normalize_text(k) for k in keys}) != len(keys):
            return False, "选项编号不能重复", None
        if any(not o["text"] for o in parsed):
            return False, "选项内容不能为空", None
        answer_keys = _answer_keys(answer)
        if not answer_keys:
            return False, "请设置正确答案", None
        invalid = answer_keys - {_normalize_text(k) for k in keys}
        if invalid:
            return False, f"正确答案不在选项范围内: {sorted(invalid)}", None
        if q_type == "SINGLE" and len(answer_keys) != 1:
            return False, "单选题正确答案必须且只能有 1 个", None
        normalized["options"] = parsed
        if q_type == "MULTI":
            # 多选答案统一存为「归一化后的键数组」，保证与判分口径一致
            normalized["answer"] = sorted(answer_keys)
        else:
            normalized["answer"] = answer[0] if isinstance(answer, list) else answer
    else:  # JUDGE
        judge = _normalize_judge(answer)
        if judge not in ("true", "false"):
            return False, "判断题答案必须为 true/false（或 对/错）", None
        normalized["options"] = []
        normalized["answer"] = judge

    normalized["q_type"] = q_type
    normalized["stem"] = stem
    normalized["analysis"] = analysis
    normalized["difficulty"] = difficulty
    normalized["kp_id"] = (payload.get("kp_id") or "").strip() or None
    if "document_id" in payload:
        normalized["document_id"] = payload.get("document_id")
    return True, "success", normalized


def _course_for_teacher(course_id: int, user_id: int) -> tuple:
    """课程归属校验：返回 (course, error_dict)；通过时 error_dict 为 None"""
    course = sql_db.get_course(course_id)
    if course is None:
        return None, {"ok": False, "code": 2001, "message": f"课程不存在: course_id={course_id}"}
    if course["teacher_id"] != user_id:
        return None, {"ok": False, "code": 4003,
                      "message": "无权限：仅该课程所属教师可管理其题库"}
    return course, None


def _question_for_teacher(question_id: int, user_id: int) -> tuple:
    """题目归属校验（经 question → course），返回 (question, error_dict)"""
    question = sql_db.get_question(question_id)
    if question is None:
        return None, {"ok": False, "code": 2002, "message": f"题目不存在: question_id={question_id}"}
    _, err = _course_for_teacher(question["course_id"], user_id)
    if err:
        return None, {"ok": False, "code": 4003,
                      "message": "无权限：仅该题目所属课程的教师可操作"}
    return question, None


def _check_document(course_id: int, document_id):
    """document_id 可空（空 = 课程通用题）；非空时校验文档存在且属于该课程。

    返回 (did, error_dict)：did 为 None 表示课程通用题。
    """
    if document_id in (None, "", 0, "0"):
        return None, None
    try:
        did = int(document_id)
    except (TypeError, ValueError):
        return None, {"ok": False, "code": 4001, "message": "参数错误：document_id 必须为整数"}
    doc = sql_db.get_document(did)
    if doc is None:
        return None, {"ok": False, "code": 2002, "message": f"文档不存在: document_id={did}"}
    if doc["course_id"] != course_id:
        return None, {"ok": False, "code": 4003, "message": "无权限：该文档不属于此课程"}
    return did, None


def _teacher_view(question: dict, stats: dict = None, favorite_count: int = 0) -> dict:
    """教师视角：在库行基础上补充解析后的 options/answer 与作答统计（学生接口绝不复用本函数）"""
    data = dict(question)
    data["options"] = _parse_options(question)
    data["answer"] = _loads(question.get("answer"), question.get("answer"))
    if question["q_type"] == "JUDGE":
        # 兼容历史行：旧数据里判断题答案可能被存成裸 JSON（回读为布尔 True），
        # 这里统一归一化为 "true"/"false" 字符串，保证教师端展示口径一致。
        data["answer"] = _normalize_judge(data["answer"])
    data["q_type_label"] = TYPE_LABELS.get(question["q_type"], question["q_type"])
    st = stats or {}
    attempts = st.get("attempts", 0)
    correct = st.get("correct", 0)
    data["attempts"] = attempts
    data["correct_count"] = correct
    data["correct_rate"] = round(correct / attempts * 100, 1) if attempts else 0.0
    data["favorite_count"] = favorite_count
    return data


class QuestionService:
    """教师端题库管理（每个方法都做课程归属校验，越权返回 4003）"""

    @staticmethod
    def create_question(user_id: int, course_id: int, payload: dict) -> dict:
        """新增题目（course_id 必传；document_id 可空 = 课程通用题）"""
        _, err = _course_for_teacher(course_id, user_id)
        if err:
            return err

        ok, message, normalized = validate_question_payload(payload)
        if not ok:
            return {"ok": False, "code": 1001, "message": message}

        did, err = _check_document(course_id, payload.get("document_id"))
        if err:
            return err

        question_id = sql_db.create_question(
            course_id=course_id, document_id=did, kp_id=normalized["kp_id"],
            q_type=normalized["q_type"], stem=normalized["stem"],
            options=normalized["options"], answer=normalized["answer"],
            analysis=normalized["analysis"], difficulty=normalized["difficulty"],
            created_by=user_id, source="MANUAL",
        )
        return {"ok": True, "code": 0, "message": "success", "data": {
            "question_id": question_id,
            "course_id": course_id,
            "document_id": did,
            "created": True,
            "question": _teacher_view(sql_db.get_question(question_id)),
        }}

    @staticmethod
    def update_question(user_id: int, question_id: int, payload: dict) -> dict:
        """修改题目：未传的字段沿用原值（支持只改解析、只改难度等局部编辑）"""
        question, err = _question_for_teacher(question_id, user_id)
        if err:
            return err

        merged = {
            "q_type": payload.get("q_type") if payload.get("q_type") is not None else question["q_type"],
            "stem": payload.get("stem") if payload.get("stem") is not None else question["stem"],
            "options": payload.get("options") if payload.get("options") is not None
                       else _parse_options(question),
            "answer": payload.get("answer") if payload.get("answer") is not None
                      else _loads(question.get("answer"), question.get("answer")),
            "analysis": payload.get("analysis") if payload.get("analysis") is not None
                        else question.get("analysis"),
            "difficulty": payload.get("difficulty") if payload.get("difficulty") is not None
                          else question.get("difficulty", 3),
            "kp_id": payload.get("kp_id") if payload.get("kp_id") is not None
                     else question.get("kp_id"),
        }
        if "document_id" in payload:
            merged["document_id"] = payload.get("document_id")

        ok, message, normalized = validate_question_payload(merged)
        if not ok:
            return {"ok": False, "code": 1001, "message": message}

        did = question.get("document_id")
        if "document_id" in payload:
            did, err = _check_document(question["course_id"], payload.get("document_id"))
            if err:
                return err
            # document_id 的「清空」语义用独立方法表达（update_question 对 None = 不修改）
            sql_db.set_question_document(question_id, did)

        sql_db.update_question(
            question_id,
            q_type=normalized["q_type"],
            stem=normalized["stem"],
            options=normalized["options"],
            answer=normalized["answer"],
            analysis=normalized["analysis"] or "",
            difficulty=normalized["difficulty"],
            kp_id=normalized["kp_id"] or "",
        )
        return {"ok": True, "code": 0, "message": "success", "data": {
            "question_id": question_id,
            "updated": True,
            "question": _teacher_view(sql_db.get_question(question_id)),
        }}

    @staticmethod
    def set_active(user_id: int, question_id: int, is_active: bool) -> dict:
        """启用/停用题目（停用 = 软删：从出题池移除但保留历史答题记录）"""
        _, err = _question_for_teacher(question_id, user_id)
        if err:
            return err
        sql_db.set_question_active(question_id, is_active)
        return {"ok": True, "code": 0, "message": "success", "data": {
            "question_id": question_id,
            "is_active": bool(is_active),
        }}

    @staticmethod
    def delete_question(user_id: int, question_id: int) -> dict:
        """删除题目：已被作答过的题目只做软删（保护学生答题记录），否则物理删除"""
        _, err = _question_for_teacher(question_id, user_id)
        if err:
            return err

        answered = sql_db.count_answers_by_question(question_id)
        if answered > 0:
            sql_db.set_question_active(question_id, False)
            return {"ok": True, "code": 0, "message": "success", "data": {
                "question_id": question_id,
                "deleted": False,
                "soft_deleted": True,
                "answered_count": answered,
                "hint": f"该题已有 {answered} 条学生作答记录，已停用（移出出题池）而未物理删除",
            }}

        removed = sql_db.delete_question(question_id)
        return {"ok": True, "code": 0, "message": "success", "data": {
            "question_id": question_id,
            "deleted": removed > 0,
            "soft_deleted": False,
            "answered_count": 0,
        }}

    @staticmethod
    def list_questions(user_id: int, course_id: int, document_id=None, kp_id: str = None,
                       q_type: str = None, keyword: str = None, is_active=None,
                       page: int = 1, page_size: int = 10) -> dict:
        """题库列表（教师视角，含答案/解析/作答统计/收藏数），分页 + 多条件筛选"""
        _, err = _course_for_teacher(course_id, user_id)
        if err:
            return err

        did = None
        if document_id not in (None, "", 0, "0"):
            did, err = _check_document(course_id, document_id)
            if err:
                return err

        page = max(1, page)
        page_size = min(max(1, page_size), 100)
        total, rows = sql_db.list_questions(
            course_id, document_id=did, kp_id=(kp_id or "").strip() or None,
            q_type=(q_type or "").strip().upper() or None,
            keyword=(keyword or "").strip() or None, is_active=is_active,
            page=page, page_size=page_size,
        )
        stats = sql_db.question_answer_stats(course_id)
        fav_counts = sql_db.count_question_favorites_grouped(course_id)
        items = [
            _teacher_view(r, stats.get(r["question_id"]), fav_counts.get(r["question_id"], 0))
            for r in rows
        ]
        return {"ok": True, "code": 0, "message": "success", "data": {
            "course_id": course_id,
            "document_id": did,
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }}

    @staticmethod
    def get_question(user_id: int, question_id: int) -> dict:
        """题目详情（教师视角）"""
        question, err = _question_for_teacher(question_id, user_id)
        if err:
            return err
        stats = sql_db.question_answer_stats(question["course_id"]).get(question_id)
        fav = sql_db.count_question_favorites_grouped(question["course_id"]).get(question_id, 0)
        return {"ok": True, "code": 0, "message": "success",
                "data": _teacher_view(question, stats, fav)}

    @staticmethod
    def stats(user_id: int, course_id: int) -> dict:
        """题库总览：题量 / 启用停用 / 题型分布 / 作答总数 / 平均正确率 / 收藏总数"""
        _, err = _course_for_teacher(course_id, user_id)
        if err:
            return err

        _, rows = sql_db.list_questions(course_id, page=1, page_size=10000)
        by_type = {t: 0 for t in VALID_TYPES}
        active = 0
        for r in rows:
            by_type[r["q_type"]] = by_type.get(r["q_type"], 0) + 1
            if r["is_active"]:
                active += 1

        answers = sql_db.list_answer_records_by_course(course_id)
        correct = sum(1 for a in answers if a["is_correct"])
        fav_total = sum(sql_db.count_question_favorites_grouped(course_id).values())

        return {"ok": True, "code": 0, "message": "success", "data": {
            "course_id": course_id,
            "total": len(rows),
            "active_count": active,
            "inactive_count": len(rows) - active,
            "by_type": by_type,
            "answer_count": len(answers),
            "correct_rate": round(correct / len(answers) * 100, 1) if answers else 0.0,
            "student_count": len({a["user_id"] for a in answers}),
            "favorite_total": fav_total,
        }}

    @staticmethod
    def favorites(user_id: int, course_id: int, question_id: int = None) -> dict:
        """题目收藏情况：哪些学生收藏了哪道题（教师端「查看题目收藏情况」）"""
        _, err = _course_for_teacher(course_id, user_id)
        if err:
            return err

        rows = sql_db.list_question_favorite_users(course_id, question_id)
        items = []
        for r in rows:
            q = sql_db.get_question(r["question_id"]) or {}
            u = sql_db.get_user_by_id(r["user_id"]) or {}
            items.append({
                "question_id": r["question_id"],
                "stem": q.get("stem", ""),
                "q_type": q.get("q_type"),
                "q_type_label": TYPE_LABELS.get(q.get("q_type"), q.get("q_type", "")),
                "student_id": r["user_id"],
                "student_name": u.get("display_name") or u.get("username") or str(r["user_id"]),
                "username": u.get("username", ""),
                "created_at": r["created_at"],
            })
        return {"ok": True, "code": 0, "message": "success", "data": {
            "course_id": course_id,
            "total": len(items),
            "items": items,
        }}


class PracticeService:
    """学生端做题练习（出题 / 判分 / 错题本 / 题目收藏）。

    可见性口径：与「文档、图谱」保持一致——学生可见课程内全部启用题目
    （系统当前无选课关系表，故不做「仅已选课程」限制；若要收紧，只需改本类）。
    """

    @staticmethod
    def get_questions(user_id: int, course_id: int, document_id=None, kp_id: str = None,
                      q_type: str = None, count: int = 10) -> dict:
        """出题：随机取启用题目；**返回体不含 answer/analysis**（提交后才下发）"""
        course = sql_db.get_course(course_id)
        if course is None:
            return {"ok": False, "code": 2001, "message": f"课程不存在: course_id={course_id}"}

        did = None
        if document_id not in (None, "", 0, "0"):
            try:
                did = int(document_id)
            except (TypeError, ValueError):
                return {"ok": False, "code": 4001, "message": "参数错误：document_id 必须为整数"}

        try:
            count = int(count or 10)
        except (TypeError, ValueError):
            count = 10
        count = min(max(1, count), 50)

        rows = sql_db.list_practice_questions(
            course_id, document_id=did, kp_id=(kp_id or "").strip() or None,
            q_type=(q_type or "").strip().upper() or None, limit=count,
        )
        fav_ids = sql_db.list_question_favorite_ids(user_id, course_id)
        items = [_public_view(r, r["question_id"] in fav_ids) for r in rows]
        return {"ok": True, "code": 0, "message": "success", "data": {
            "course_id": course_id,
            "document_id": did,
            "count": len(items),
            "total_in_bank": sql_db.count_questions_by_course(course_id),
            "items": items,
        }}

    @staticmethod
    def submit(user_id: int, question_id: int, user_answer) -> dict:
        """提交作答：服务端判分 → 落答题记录 → 返回正确答案与解析（答案解析仅此路径下发）"""
        question = sql_db.get_question(question_id)
        if question is None:
            return {"ok": False, "code": 2002, "message": f"题目不存在: question_id={question_id}"}
        if not question["is_active"]:
            return {"ok": False, "code": 2004, "message": "该题已停用，无法作答"}

        result = grade(question, user_answer)
        record_id = sql_db.add_answer_record(
            user_id=user_id, course_id=question["course_id"],
            document_id=question.get("document_id"), question_id=question_id,
            user_answer=user_answer, is_correct=result["is_correct"],
            score=result["score"], grade_source="AUTO",
        )
        return {"ok": True, "code": 0, "message": "success", "data": {
            "record_id": record_id,
            "question_id": question_id,
            "course_id": question["course_id"],
            "document_id": question.get("document_id"),
            "kp_id": question.get("kp_id"),
            "user_answer": user_answer,
            "is_correct": result["is_correct"],
            "score": result["score"],
            "correct_answer": result["correct_answer"],
            "analysis": result["analysis"],
        }}

    @staticmethod
    def records(user_id: int, course_id: int = None, document_id=None,
                only_wrong: bool = False, limit: int = 100) -> dict:
        """我的答题记录（时间倒序，含题干与正确答案——本人已作答过，可回看）"""
        did = None
        if document_id not in (None, "", 0, "0"):
            try:
                did = int(document_id)
            except (TypeError, ValueError):
                return {"ok": False, "code": 4001, "message": "参数错误：document_id 必须为整数"}

        rows = sql_db.list_answer_records(user_id, course_id=course_id, document_id=did,
                                          only_wrong=only_wrong)
        items = []
        for r in rows[:max(1, limit)]:
            q = sql_db.get_question(r["question_id"])
            items.append({
                "record_id": r["record_id"],
                "question_id": r["question_id"],
                "course_id": r["course_id"],
                "document_id": r.get("document_id"),
                "stem": (q or {}).get("stem", "（题目已删除）"),
                "q_type": (q or {}).get("q_type"),
                "q_type_label": TYPE_LABELS.get((q or {}).get("q_type"), ""),
                "user_answer": _loads(r.get("user_answer"), r.get("user_answer")),
                "is_correct": bool(r["is_correct"]),
                "score": r["score"],
                "answered_at": r["answered_at"],
                "correct_answer": _loads((q or {}).get("answer"), None),
                "analysis": (q or {}).get("analysis") or "",
            })
        correct = sum(1 for r in rows if r["is_correct"])
        return {"ok": True, "code": 0, "message": "success", "data": {
            "total": len(rows),
            "correct_count": correct,
            "correct_rate": round(correct / len(rows) * 100, 1) if rows else 0.0,
            "items": items,
        }}

    @staticmethod
    def wrong_book(user_id: int, course_id: int, document_id=None) -> dict:
        """错题本：按题取「最近一次答错」的记录，并回填知识点名称（供「回图谱重学」）"""
        did = None
        if document_id not in (None, "", 0, "0"):
            try:
                did = int(document_id)
            except (TypeError, ValueError):
                return {"ok": False, "code": 4001, "message": "参数错误：document_id 必须为整数"}

        rows = sql_db.list_answer_records(user_id, course_id=course_id,
                                          document_id=did, only_wrong=True)
        wrong_counts = {}
        for r in rows:
            wrong_counts[r["question_id"]] = wrong_counts.get(r["question_id"], 0) + 1

        # rows 已按 record_id DESC（时间倒序），首次出现的即该题最近一次错误
        seen, items = set(), []
        for r in rows:
            qid = r["question_id"]
            if qid in seen:
                continue
            seen.add(qid)
            q = sql_db.get_question(qid)
            if q is None or not q["is_active"]:
                continue
            view = _public_view(q)
            view.update({
                "wrong_count": wrong_counts[qid],
                "last_wrong_at": r["answered_at"],
                "last_user_answer": _loads(r.get("user_answer"), r.get("user_answer")),
                "correct_answer": _loads(q.get("answer"), None),
                "analysis": q.get("analysis") or "",
                "kp_name": None,
            })
            items.append(view)

        # 知识点名称（Neo4j 不可用时降级为 None，不影响错题本可用性）
        kp_ids = [it["kp_id"] for it in items if it.get("kp_id")]
        if kp_ids:
            try:
                recs = db.query(
                    "MATCH (n:KnowledgePoint {course_id: $cid}) WHERE n.kp_id IN $ids "
                    "RETURN n.kp_id AS kp_id, n.name AS name",
                    {"cid": course_id, "ids": kp_ids},
                )
                kp_names = {r["kp_id"]: r["name"] for r in recs}
                for it in items:
                    it["kp_name"] = kp_names.get(it.get("kp_id"))
            except Exception:
                pass

        return {"ok": True, "code": 0, "message": "success", "data": {
            "course_id": course_id,
            "document_id": did,
            "total": len(items),
            "items": items,
        }}

    @staticmethod
    def stats(user_id: int, course_id: int, document_id=None) -> dict:
        """我的练习统计：累计作答 / 正确率 / 错题数 / 收藏数（学生总览 KPI 用）"""
        did = None
        if document_id not in (None, "", 0, "0"):
            try:
                did = int(document_id)
            except (TypeError, ValueError):
                return {"ok": False, "code": 4001, "message": "参数错误：document_id 必须为整数"}

        rows = sql_db.list_answer_records(user_id, course_id=course_id, document_id=did)
        correct = sum(1 for r in rows if r["is_correct"])
        wrong_questions = {r["question_id"] for r in rows if not r["is_correct"]}
        return {"ok": True, "code": 0, "message": "success", "data": {
            "course_id": course_id,
            "document_id": did,
            "answer_count": len(rows),
            "correct_count": correct,
            "correct_rate": round(correct / len(rows) * 100, 1) if rows else 0.0,
            "wrong_question_count": len(wrong_questions),
            "favorite_count": len(sql_db.list_question_favorites(user_id, course_id)),
        }}

    @staticmethod
    def list_favorites(user_id: int, course_id: int) -> dict:
        """我的题目收藏（含题面，便于直接重做）"""
        if sql_db.get_course(course_id) is None:
            return {"ok": False, "code": 2001, "message": f"课程不存在: course_id={course_id}"}

        items = []
        for r in sql_db.list_question_favorites(user_id, course_id):
            q = sql_db.get_question(r["question_id"])
            if q is None:
                continue
            view = _public_view(q, favorited=True)
            view["favorited_at"] = r["created_at"]
            items.append(view)
        return {"ok": True, "code": 0, "message": "success", "data": {
            "course_id": course_id,
            "total": len(items),
            "items": items,
        }}

    @staticmethod
    def favorite(user_id: int, course_id: int, question_id: int) -> dict:
        """收藏题目（幂等：重复收藏不产生重复记录）"""
        question = sql_db.get_question(question_id)
        if question is None:
            return {"ok": False, "code": 2002, "message": f"题目不存在: question_id={question_id}"}
        if question["course_id"] != course_id:
            return {"ok": False, "code": 4003, "message": "无权限：该题目不属于此课程"}

        created = sql_db.add_question_favorite(user_id, course_id, question_id)
        return {"ok": True, "code": 0, "message": "success", "data": {
            "course_id": course_id,
            "question_id": question_id,
            "created": created,
        }}

    @staticmethod
    def unfavorite(user_id: int, course_id: int, question_id: int) -> dict:
        """取消题目收藏"""
        deleted = sql_db.remove_question_favorite(user_id, course_id, question_id)
        return {"ok": True, "code": 0, "message": "success", "data": {
            "course_id": course_id,
            "question_id": question_id,
            "deleted": deleted,
        }}