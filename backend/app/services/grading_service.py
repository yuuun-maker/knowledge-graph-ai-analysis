"""
主观题批改服务（Scope B）

设计要点（与需求确认的最终口径一致）：
- 主观题（FILL/ESSAY）提交时**只落库不判分**：t_answer_record 写 grade_status='PENDING'、
  score=0、is_correct=0（占位，不代表答错），学生端返回 pending=True 且不下发参考答案；
- 只有教师批改后才产生分数：**就地更新**同一条记录（grade_status='GRADED'、
  grade_source='TEACHER'、graded_by/graded_at/comment）——既定方案：不留痕、查询简单；
- 批改后 is_correct = (score >= GRADE_PASS_SCORE)：错题本、练习正确率、掌握度都依赖
  这个布尔；部分分则通过 score/100 计入掌握度（见 question_recommender.kp_mastery）。

权限：与题库管理同一口径——仅「该作答所属课程的教师」可批改（越权 4003），
学生无法批改自己（接口层还有 require_teacher 兜底）。
"""

from ..core.sql_database import sql_db
from .question_service import (
    GRADE_PASS_SCORE, MANUAL_TYPES, TYPE_LABELS, _course_for_teacher, _loads, _parse_blanks,
)

# 评语长度上限（避免被塞入超长文本）
MAX_COMMENT_LEN = 500
# 单次批量批改的记录数上限（防误传超大数组）
MAX_BATCH_SIZE = 200


def _normalize_score(score) -> tuple:
    """校验并归一化分数：0~100，保留 1 位小数。返回 (value, error_dict)"""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None, {"ok": False, "code": 4001, "message": "参数错误：score 必须为 0-100 的数字"}
    if not (0 <= value <= 100):
        return None, {"ok": False, "code": 4001, "message": "参数错误：score 应在 0-100 之间"}
    return round(value, 1), None


def _coerce_id(value, field: str) -> tuple:
    """可选过滤参数转 int（空值返回 None 表示不过滤）"""
    if value in (None, "", 0, "0"):
        return None, None
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, {"ok": False, "code": 4001, "message": f"参数错误：{field} 必须为整数"}


def _pending_view(row: dict) -> dict:
    """待批改条目投影（教师视角：题面 + 参考答案 + 学生解答 + 学生信息）。

    学生端绝不可复用本函数——它包含参考答案与解析。
    """
    q_type = row.get("q_type")
    blanks = []
    if q_type == "FILL":
        blanks = _parse_blanks({
            "q_type": q_type,
            "options": row.get("question_options"),
            "answer": row.get("reference_answer"),
        })
    return {
        "record_id": row["record_id"],
        "question_id": row["question_id"],
        "course_id": row["course_id"],
        "document_id": row.get("document_id"),
        "kp_id": row.get("kp_id"),
        "q_type": q_type,
        "q_type_label": TYPE_LABELS.get(q_type, q_type or ""),
        "stem": row.get("stem") or "（题目已删除）",
        "difficulty": row.get("difficulty") or 3,
        "student_id": row["user_id"],
        "student_name": row.get("student_name") or row.get("student_username") or str(row["user_id"]),
        "student_username": row.get("student_username") or "",
        "user_answer": _loads(row.get("user_answer"), row.get("user_answer")),
        "blanks": blanks,                    # 填空题：每空定义 + 参考答案（教师逐空对照）
        "reference_answer": _loads(row.get("reference_answer"), row.get("reference_answer")),
        "analysis": row.get("analysis") or "",
        "grade_status": row.get("grade_status") or "PENDING",
        "answered_at": row.get("answered_at"),
        # 已批改视图（status=GRADED）复查/改判所需：当前分值、评语与批改痕迹
        "score": row.get("score"),
        "comment": row.get("comment") or "",
        "graded_at": row.get("graded_at"),
        "graded_by": row.get("graded_by"),
        "grade_source": row.get("grade_source"),
    }



class GradingService:
    """教师端主观题批改（待批改列表 / 单题批改 / 批量批改 / 进度汇总）"""

    @staticmethod
    def pending_list(user_id: int, course_id: int, document_id=None, kp_id: str = None,
                     student_id=None, page: int = 1, page_size: int = 20,
                     status: str = "PENDING") -> dict:
        """批改台列表（默认待批改，按提交先后：先交先批）

        作用域：course_id 必填（并校验教师归属）；document_id 传入时含课程通用题；
        kp_id / student_id 可选过滤。
        status：PENDING=待批改（默认）/ GRADED=已批改（仅主观题，供复查与改判）/ ALL=全部。
        """
        mode = (status or "PENDING").strip().upper()
        if mode not in ("PENDING", "GRADED", "ALL"):
            return {"ok": False, "code": 4001,
                    "message": f"参数错误：status 只能是 PENDING/GRADED/ALL，收到 {status!r}"}

        _, err = _course_for_teacher(course_id, user_id)
        if err:
            return err

        did, err = _coerce_id(document_id, "document_id")
        if err:
            return err
        sid, err = _coerce_id(student_id, "student_id")
        if err:
            return err

        page = max(1, page)
        page_size = min(max(1, page_size), 100)
        kp = (kp_id or "").strip() or None

        total = sql_db.count_pending_answer_records(
            course_id, document_id=did, kp_id=kp, student_id=sid, status=mode,
        )
        rows = sql_db.list_pending_answer_records(
            course_id, document_id=did, kp_id=kp, student_id=sid,
            limit=page_size, offset=(page - 1) * page_size, status=mode,
        )
        return {"ok": True, "code": 0, "message": "success", "data": {
            "course_id": course_id,
            "document_id": did,
            "status": mode,
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_pending_view(r) for r in rows],
        }}

    @staticmethod
    def grade_one(user_id: int, record_id: int, score, comment: str = None) -> dict:
        """批改单条作答：校验归属与题型 → 就地更新分数/评语 → 返回批改结果"""
        record = sql_db.get_answer_record(record_id)
        if record is None:
            return {"ok": False, "code": 2002,
                    "message": f"作答记录不存在: record_id={record_id}"}

        question = sql_db.get_question(record["question_id"])
        if question is None:
            return {"ok": False, "code": 2002, "message": "题目已被删除，无法批改该作答"}

        _, err = _course_for_teacher(question["course_id"], user_id)
        if err:
            return err

        if question["q_type"] not in MANUAL_TYPES:
            return {"ok": False, "code": 4001,
                    "message": f"{TYPE_LABELS.get(question['q_type'], question['q_type'])}"
                               "由系统自动判分，无需人工批改"}

        value, err = _normalize_score(score)
        if err:
            return err
        text = (comment or "").strip()[:MAX_COMMENT_LEN] or None

        updated = sql_db.grade_answer_record(
            record_id, value, value >= GRADE_PASS_SCORE, user_id, text,
        )
        if not updated:
            return {"ok": False, "code": 2002, "message": "批改失败：记录状态已变化，请刷新后重试"}

        return {"ok": True, "code": 0, "message": "success", "data": {
            "record_id": record_id,
            "question_id": record["question_id"],
            "score": value,
            "is_correct": value >= GRADE_PASS_SCORE,
            "pass_score": GRADE_PASS_SCORE,
            "comment": text,
            "grade_status": "GRADED",
            "grade_source": "TEACHER",
            "graded_by": user_id,
        }}

    @staticmethod
    def grade_batch(user_id: int, record_ids, score, comment: str = None) -> dict:
        """批量批改（同一分数与评语）：跳过非本人课程 / 客观题 / 不存在的记录，逐个报告原因"""
        if not isinstance(record_ids, list) or not record_ids:
            return {"ok": False, "code": 4001, "message": "参数错误：record_ids 不能为空"}
        if len(record_ids) > MAX_BATCH_SIZE:
            return {"ok": False, "code": 4001,
                    "message": f"参数错误：单次批量批改最多 {MAX_BATCH_SIZE} 条"}

        value, err = _normalize_score(score)
        if err:
            return err
        text = (comment or "").strip()[:MAX_COMMENT_LEN] or None

        valid_ids, skipped = [], []
        for rid in record_ids:
            try:
                rid_int = int(rid)
            except (TypeError, ValueError):
                skipped.append({"record_id": rid, "reason": "record_id 非整数"})
                continue
            record = sql_db.get_answer_record(rid_int)
            if record is None:
                skipped.append({"record_id": rid_int, "reason": "记录不存在"})
                continue
            question = sql_db.get_question(record["question_id"])
            if question is None:
                skipped.append({"record_id": rid_int, "reason": "题目已删除"})
                continue
            _, perm_err = _course_for_teacher(question["course_id"], user_id)
            if perm_err:
                skipped.append({"record_id": rid_int, "reason": "无权限（非本课程教师）"})
                continue
            if question["q_type"] not in MANUAL_TYPES:
                skipped.append({"record_id": rid_int, "reason": "客观题无需人工批改"})
                continue
            valid_ids.append(rid_int)

        updated = sql_db.grade_answer_records_batch(
            valid_ids, value, value >= GRADE_PASS_SCORE, user_id, text,
        )
        return {"ok": True, "code": 0, "message": "success", "data": {
            "score": value,
            "is_correct": value >= GRADE_PASS_SCORE,
            "pass_score": GRADE_PASS_SCORE,
            "comment": text,
            "requested": len(record_ids),
            "updated": updated,
            "skipped": skipped,
        }}

    @staticmethod
    def summary(user_id: int, course_id: int) -> dict:
        """批改进度汇总：待批改 / 已批改 / 主观题与客观题作答量 / 已批改平均分

        教师端「批改」入口用它显示角标（pending > 0 即有活要干）。
        """
        _, err = _course_for_teacher(course_id, user_id)
        if err:
            return err
        data = sql_db.answer_grading_summary(course_id)
        return {"ok": True, "code": 0, "message": "success",
                "data": {"course_id": course_id, **data}}
