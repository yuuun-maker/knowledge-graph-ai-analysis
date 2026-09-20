"""
主观题（填空/解答）与教师批改 端到端验证（Scope B）

覆盖范围：
  1. 建题校验：填空题空位/参考答案/编号/分值，解答题参考答案必填
  2. 防泄题：学生视角不含每空答案、不含参考答案与解析（批改前批改后分别断言）
  3. 提交不判分：主观题落库为 PENDING（is_correct/score 返回 null）
  4. 统计口径：未批改不进正确率、不进错题本、不进掌握度
  5. 自动组卷不硬插入：默认候选池与组卷结果都不含主观题；显式指定题型时才取
  6. 教师批改：单题 / 批量 / 重批 / 阈值判对错 / 部分分计入掌握度
  7. 权限：客观题不可人工批改、非本课程教师 4003、参数校验

运行方式（backend 目录下；**不依赖 Neo4j**——只用 SQLite 与纯函数）：
    python test_subjective_grading.py
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.security import hash_password
from app.core.sql_database import sql_db
from app.services.grading_service import GradingService
from app.services.question_recommender import kp_mastery
from app.services.question_service import (
    GRADE_PASS_SCORE, PracticeService, QuestionService,
)

TEST_COURSE_MARK = "__subjective_grading_test__"


def _ensure_user(username: str, role: str, display_name: str) -> int:
    """复用或创建测试用户（t_user 无删除接口，故幂等复用）"""
    existing = sql_db.get_user_by_username(username)
    if existing:
        return existing["user_id"]
    return sql_db.create_user(
        username, hash_password("subj-pass-123"), role=role, display_name=display_name,
    )


def _cleanup_existing_test_course():
    """清理残留测试课程（幂等；delete_course 为纯 SQLite 清理，不触碰 Neo4j）"""
    for c in sql_db.list_courses():
        if c["course_name"] == TEST_COURSE_MARK:
            sql_db.delete_course(c["course_id"])


def _fill_payload(document_id, with_answers=True):
    blanks = [
        {"key": 1, "label": "第1空", "hint": "单位：kg", "score": 50, "answer": "浮点数"},
        {"key": 2, "label": "第2空", "hint": "", "score": 50, "answer": "0.5"},
    ]
    if not with_answers:
        blanks = [dict(b, answer="") for b in blanks]
    return {
        "document_id": document_id, "kp_id": None, "q_type": "FILL",
        "stem": "计算机中实数的表示方式是 ____ ，十进制 1/2 的小数形式是 ____。",
        "options": blanks, "answer": None,
        "analysis": "第1空：浮点数；第2空：0.5。", "difficulty": 3,
    }


def _essay_payload(document_id):
    return {
        "document_id": document_id, "kp_id": None, "q_type": "ESSAY",
        "stem": "简述线性表顺序存储与链式存储的差异，并说明各自适用场景。",
        "options": [], "answer": "顺序存储用连续空间，随机访问 O(1) 但插入删除 O(n)；"
                                  "链式存储用指针链接，插入删除 O(1) 但随机访问 O(n)。",
        "analysis": "从存储连续性、访问与插入删除复杂度、适用场景三方面作答。",
        "difficulty": 4,
    }


def _single_payload(document_id):
    return {
        "document_id": document_id, "kp_id": None, "q_type": "SINGLE",
        "stem": "线性表是有限序列吗？",
        "options": [{"key": "A", "text": "是"}, {"key": "B", "text": "不是"}],
        "answer": "A", "analysis": "线性表是由 n 个数据元素组成的有限序列。", "difficulty": 1,
    }



def main():
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    _cleanup_existing_test_course()

    teacher = sql_db.ensure_default_teacher()
    other_teacher = _ensure_user("subj_other_teacher", "teacher", "别的老师")
    student = _ensure_user("subj_student", "student", "测试学生")

    course_id = sql_db.create_course(TEST_COURSE_MARK, teacher)
    doc_id = sql_db.create_document(course_id, teacher, "主观题测试文档.txt", "TXT", 10)

    # ---------- 1. 建题与校验 ----------
    r_fill = QuestionService.create_question(teacher, course_id, _fill_payload(doc_id))
    check("新增填空题成功", r_fill["ok"] and r_fill["data"]["question_id"] > 0,
          str(r_fill.get("message")))
    q_fill = r_fill["data"]["question_id"]
    teacher_view = r_fill["data"]["question"]
    check("填空题教师视角保留每空参考答案",
          [b["answer"] for b in teacher_view["options"]] == ["浮点数", "0.5"],
          str(teacher_view["options"]))
    check("填空题 answer 存参考答案数组（与多选同构）",
          teacher_view["answer"] == ["浮点数", "0.5"], str(teacher_view["answer"]))
    check("填空题 auto_graded=False（需教师批改）", teacher_view["auto_graded"] is False)

    bad = _fill_payload(doc_id, with_answers=False)
    check("填空题缺参考答案被拒",
          QuestionService.create_question(teacher, course_id, bad)["code"] == 1001)
    bad = _fill_payload(doc_id); bad["options"] = []
    check("填空题无空位被拒", QuestionService.create_question(teacher, course_id, bad)["code"] == 1001)
    bad = _fill_payload(doc_id)
    bad["options"] = [dict(bad["options"][0]), dict(bad["options"][1], key=1)]
    check("填空题空位编号重复被拒",
          QuestionService.create_question(teacher, course_id, bad)["code"] == 1001)
    bad = _fill_payload(doc_id); bad["options"][0]["score"] = 120
    check("填空题分值越界被拒", QuestionService.create_question(teacher, course_id, bad)["code"] == 1001)

    r_essay = QuestionService.create_question(teacher, course_id, _essay_payload(doc_id))
    check("新增解答题成功", r_essay["ok"], str(r_essay.get("message")))
    q_essay = r_essay["data"]["question_id"]
    bad = _essay_payload(doc_id); bad["answer"] = "   "
    check("解答题缺参考答案被拒",
          QuestionService.create_question(teacher, course_id, bad)["code"] == 1001)

    r_single = QuestionService.create_question(teacher, course_id, _single_payload(doc_id))
    q_single = r_single["data"]["question_id"]
    check("同课程客观题仍可正常创建（回归）", r_single["ok"])

    # ---------- 2. 防泄题：学生视角 ----------
    public = {it["question_id"]: it for it in PracticeService.get_questions(
        student, course_id, document_id=doc_id, q_type="FILL", count=10)["data"]["items"]}
    check("显式指定 q_type=FILL 可取到填空题", q_fill in public, str(sorted(public)))
    fill_view = public.get(q_fill) or {}
    check("填空题学生视角无每空答案",
          fill_view.get("options") and all("answer" not in b for b in fill_view["options"]),
          str(fill_view.get("options")))
    check("填空题学生视角含空位编号与提示",
          [b["key"] for b in fill_view.get("options", [])] == [1, 2]
          and fill_view["options"][0]["hint"] == "单位：kg")
    check("学生视角无 answer / analysis 字段",
          "answer" not in fill_view and "analysis" not in fill_view)

    # ---------- 3. 默认出题池不含主观题 ----------
    default_items = PracticeService.get_questions(
        student, course_id, document_id=doc_id, count=10)["data"]["items"]
    types = {it["q_type"] for it in default_items}
    check("默认随机出题不含主观题（不硬插入）", types and not (types & {"FILL", "ESSAY"}),
          str(types))

    # ---------- 4. 提交主观题：只落库不判分 ----------
    s_fill = PracticeService.submit(student, q_fill, {"1": "浮点数", "2": "0.5"})
    check("填空题提交成功且返回 pending=True",
          s_fill["ok"] and s_fill["data"]["pending"] is True, str(s_fill.get("message")))
    check("未批改不给分、不判对错（null）",
          s_fill["data"]["is_correct"] is None and s_fill["data"]["score"] is None)
    check("未批改不下发参考答案与解析",
          s_fill["data"]["correct_answer"] is None and not s_fill["data"]["analysis"])
    check("落库状态为 PENDING",
          sql_db.get_answer_record(s_fill["data"]["record_id"])["grade_status"] == "PENDING")

    s_essay = PracticeService.submit(student, q_essay, "顺序存储连续、链式存储用指针……")
    check("解答题提交成功且 pending", s_essay["ok"] and s_essay["data"]["pending"] is True)

    s_obj = PracticeService.submit(student, q_single, "A")
    check("客观题仍即时判分（回归）",
          s_obj["data"]["pending"] is False and s_obj["data"]["is_correct"] is True
          and s_obj["data"]["score"] == 100.0)
    check("客观题提交仍下发答案与解析",
          s_obj["data"]["correct_answer"] == "A" and bool(s_obj["data"]["analysis"]))

    # ---------- 5. 统计口径：未批改不影响正确率 / 错题本 / 掌握度 ----------
    rec = PracticeService.records(student, course_id=course_id)["data"]
    check("练习记录区分 pending / graded",
          rec["pending_count"] == 2 and rec["graded_count"] == 1, str(rec))
    check("未批改记录不下发参考答案与解析",
          all(it["correct_answer"] is None and it["analysis"] == ""
              for it in rec["items"] if it["pending"]))
    check("正确率只按已批改记录计算（1/1 = 100%）",
          rec["correct_rate"] == 100.0 and rec["correct_count"] == 1, str(rec))

    stats = PracticeService.stats(student, course_id)["data"]
    check("练习统计区分 graded / pending",
          stats["graded_count"] == 1 and stats["pending_count"] == 2
          and stats["correct_rate"] == 100.0, str(stats))

    wrong = PracticeService.wrong_book(student, course_id)["data"]
    check("未批改不进错题本", wrong["total"] == 0, str(wrong["total"]))

    legacy = kp_mastery([{"kp_id": "kp_demo", "is_correct": True,
                          "answered_at": "2026-09-19 10:00:00"}], [])
    check("掌握度兼容旧调用方（无 score 时退回 is_correct）",
          legacy["kp_demo"]["mastery"] == 100.0, str(legacy))

    # ---------- 6. 自动组卷不硬插入主观题 ----------
    mixed = PracticeService.recommend_questions(student, course_id, document_id=doc_id,
                                                count=5, mode="mixed")
    check("智能组卷返回成功", mixed["ok"], str(mixed.get("message")))
    mixed_types = {it["q_type"] for it in mixed["data"]["items"]}
    check("mixed 组卷结果不含主观题", not (mixed_types & {"FILL", "ESSAY"}), str(mixed_types))
    check("mixed 组卷 meta 标注 subjectivity_policy=excluded",
          mixed["data"]["meta"]["subjectivity_policy"] == "excluded",
          str(mixed["data"]["meta"].get("subjectivity_policy")))

    subj_rec = PracticeService.recommend_questions(student, course_id, document_id=doc_id,
                                                  q_type="FILL", count=5, mode="mixed")
    subj_types = {it["q_type"] for it in subj_rec["data"]["items"]}
    check("显式 q_type=FILL 时组卷可取到主观题", subj_types == {"FILL"}, str(subj_types))
    check("显式请求时 meta 标注 subjectivity_policy=requested",
          subj_rec["data"]["meta"]["subjectivity_policy"] == "requested")
    # ---------- 7. 教师批改 ----------
    pending = GradingService.pending_list(teacher, course_id)["data"]
    check("待批改列表含 2 条（填空题 + 解答题）", pending["total"] == 2, str(pending["total"]))
    check("待批改列表带出参考答案（教师侧）",
          all(it["reference_answer"] for it in pending["items"]))
    fill_item = next(it for it in pending["items"] if it["question_id"] == q_fill)
    check("填空题待批改条目带出每空定义与参考答案",
          len(fill_item["blanks"]) == 2 and fill_item["blanks"][0]["answer"] == "浮点数",
          str(fill_item["blanks"]))
    check("待批改条目带出学生解答",
          fill_item["user_answer"] == {"1": "浮点数", "2": "0.5"},
          str(fill_item["user_answer"]))

    g1 = GradingService.grade_one(teacher, s_fill["data"]["record_id"], 80, "两空都对，表述规范")
    check("单题批改成功且 >=60 判为答对",
          g1["ok"] and g1["data"]["is_correct"] is True and g1["data"]["score"] == 80.0,
          str(g1.get("message")))
    row = sql_db.get_answer_record(s_fill["data"]["record_id"])
    check("批改就地更新 grade_status/grade_source/graded_by/comment",
          row["grade_status"] == "GRADED" and row["grade_source"] == "TEACHER"
          and row["graded_by"] == teacher and row["comment"] == "两空都对，表述规范",
          str(dict(row)))

    g2 = GradingService.grade_one(teacher, s_essay["data"]["record_id"], 40, "要点不全")
    check("解答题批改 40 分判为答错（低于阈值 60）",
          g2["ok"] and g2["data"]["is_correct"] is False and g2["data"]["score"] < GRADE_PASS_SCORE)

    wrong2 = PracticeService.wrong_book(student, course_id)["data"]
    check("批改答错后进入错题本",
          wrong2["total"] == 1 and wrong2["items"][0]["question_id"] == q_essay,
          str(wrong2["total"]))
    rec2 = PracticeService.records(student, course_id=course_id)["data"]
    check("批改后记录显示得分与评语",
          any(it["question_id"] == q_fill and it["score"] == 80.0
              and it["comment"] == "两空都对，表述规范" for it in rec2["items"]),
          str([(it["question_id"], it["score"], it["comment"]) for it in rec2["items"]]))
    check("已批改记录重新下发参考答案与解析",
          all(it["correct_answer"] is not None for it in rec2["items"] if not it["pending"]))
    check("批改后正确率按 2/3 计算（66.7%）",
          rec2["graded_count"] == 3 and rec2["correct_count"] == 2
          and rec2["correct_rate"] == 66.7, str(rec2))

    mastery2 = kp_mastery(
        [{"kp_id": "kp_demo", "is_correct": False, "score": 40,
          "answered_at": "2026-09-19 10:00:00"}], [])
    check("掌握度使用部分分（40 分 → 40 而非 0）",
          mastery2["kp_demo"]["mastery"] == 40.0, str(mastery2))

    g3 = GradingService.grade_one(teacher, s_essay["data"]["record_id"], 90, "复评后给分")
    row2 = sql_db.get_answer_record(s_essay["data"]["record_id"])
    check("重批覆盖旧分与旧评语",
          g3["ok"] and row2["score"] == 90.0 and row2["is_correct"] == 1
          and row2["comment"] == "复评后给分", str(dict(row2)))

    gb = GradingService.grade_batch(
        teacher, [s_fill["data"]["record_id"], s_obj["data"]["record_id"]], 100, "批量给满分")
    check("批量批改更新主观题、跳过客观题",
          gb["ok"] and gb["data"]["updated"] == 1 and len(gb["data"]["skipped"]) == 1
          and "客观题" in gb["data"]["skipped"][0]["reason"], str(gb["data"]))
    check("批量批改后分数生效",
          sql_db.get_answer_record(s_fill["data"]["record_id"])["score"] == 100.0)

    summary = GradingService.summary(teacher, course_id)["data"]
    check("批改进度汇总：待批改归零、已批改 3 条、主观题 2 条",
          summary["pending"] == 0 and summary["graded"] == 3 and summary["manual_total"] == 2,
          str(summary))

    # ---------- 8. 权限与参数校验 ----------
    check("非本课程教师批改被拒（4003）",
          GradingService.grade_one(other_teacher, s_essay["data"]["record_id"], 90)["code"] == 4003)
    check("非本课程教师查看待批改被拒（4003）",
          GradingService.pending_list(other_teacher, course_id)["code"] == 4003)
    check("批改客观题被拒（4001）",
          GradingService.grade_one(teacher, s_obj["data"]["record_id"], 90)["code"] == 4001)
    check("不存在的记录被拒（2002）",
          GradingService.grade_one(teacher, 99999999, 60)["code"] == 2002)
    check("分数越界被拒（4001）",
          GradingService.grade_one(teacher, s_fill["data"]["record_id"], 120)["code"] == 4001)
    check("分数非数字被拒（4001）",
          GradingService.grade_one(teacher, s_fill["data"]["record_id"], "优秀")["code"] == 4001)
    check("批量批改空列表被拒（4001）",
          GradingService.grade_batch(teacher, [], 60)["code"] == 4001)

    # ---------- 9. 清理（纯 SQLite，不触碰 Neo4j） ----------
    sql_db.delete_course(course_id)
    check("清理测试课程后无残留题目与作答",
          sql_db.count_questions_by_course(course_id) == 0
          and sql_db.count_answers_by_course(course_id) == 0)

    print("=" * 68)
    passed = 0
    for name, ok, detail in checks:
        print(f"  {'✓' if ok else '✗'} {name}" + (f"  ({detail})" if not ok and detail else ""))
        passed += ok
    print(f"\n通过 {passed}/{len(checks)}")
    print("=" * 68)
    return passed == len(checks)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
