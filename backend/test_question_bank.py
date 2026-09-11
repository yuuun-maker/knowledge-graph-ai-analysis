"""
题库功能端到端验证（Scope A：单选 / 多选 / 判断 + 全自动判分）

覆盖范围：
  1. 教师端题目 CRUD + 参数校验（题干/题型/选项/答案）
  2. 课程归属校验（非本课程教师 → 4003）
  3. 题库列表 / 总览统计（题量、题型分布、作答正确率、收藏数）
  4. 学生出题**不泄答案**（硬断言响应中无 answer / analysis）
  5. 判分正确性：单选、多选（顺序无关）、判断（同义归一：对=true）、未作答判错
  6. 答题记录追加、错题本（每题取最近一次错误 + 正确答案/解析/知识点）
  7. 题目收藏幂等 + 教师端收藏情况
  8. 停用语义（停用后不出题、不可提交）
  9. 删除语义：已作答 → 软删；未作答 → 物理删
 10. 文档级清理：只清该文档题目与答题记录，课程通用题（document_id IS NULL）保留
 11. 课程级联清理：题目/答题记录/题目收藏全部清空，无孤儿数据

运行方式（backend 目录下，需 Neo4j 已启动）：
    python test_question_bank.py
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.database import db
from app.core.security import hash_password
from app.core.sql_database import sql_db
from app.services.course_service import CourseService
from app.services.document_service import DocumentService
from app.services.question_service import QuestionService, PracticeService

TEST_COURSE_MARK = "__question_bank_test__"


def _ensure_user(username: str, role: str, display_name: str) -> int:
    """复用或创建测试用户（t_user 无删除接口，故幂等复用，避免重复注册报错）"""
    existing = sql_db.get_user_by_username(username)
    if existing:
        return existing["user_id"]
    return sql_db.create_user(
        username, hash_password("qb-pass-123"), role=role, display_name=display_name,
    )


def _cleanup_existing_test_course():
    """清理残留测试课程（幂等：先删图/子表/文档，再删课程；题库随课程一并清理）"""
    for c in sql_db.list_courses():
        if c["course_name"] == TEST_COURSE_MARK:
            cid = c["course_id"]
            db.delete_course_graph(cid)
            for d in sql_db.list_documents_by_course(cid):
                sql_db.delete_learning_records_by_document(cid, d["doc_id"])
                sql_db.delete_favorites_by_document(cid, d["doc_id"])
                sql_db.delete_embeddings_by_document(cid, d["doc_id"])
                sql_db.delete_document(d["doc_id"])
            sql_db.delete_course(cid)


def _single_payload(document_id, stem="下列关于线性表的说法正确的是？"):
    return {
        "document_id": document_id, "kp_id": None, "q_type": "SINGLE", "stem": stem,
        "options": [{"key": "A", "text": "线性表是有限序列"},
                    {"key": "B", "text": "线性表是无限序列"},
                    {"key": "C", "text": "线性表只能顺序存储"},
                    {"key": "D", "text": "线性表不能插入元素"}],
        "answer": "A", "analysis": "线性表是由 n 个数据元素组成的有限序列。", "difficulty": 2,
    }


def _multi_payload(document_id):
    return {
        "document_id": document_id, "kp_id": None, "q_type": "MULTI",
        "stem": "线性表的存储结构包括哪些？",
        "options": [{"key": "A", "text": "顺序存储"}, {"key": "B", "text": "散列存储"},
                    {"key": "C", "text": "链式存储"}, {"key": "D", "text": "索引存储"}],
        "answer": ["A", "C"], "analysis": "线性表有顺序存储与链式存储两种结构。", "difficulty": 3,
    }


def _judge_payload(document_id=None):
    return {
        "document_id": document_id, "kp_id": None, "q_type": "JUDGE",
        "stem": "栈是一种操作受限的线性表。",
        "options": [], "answer": "对",
        "analysis": "栈只允许在栈顶插入和删除。", "difficulty": 1,
    }


def main():
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    db.init_schema()
    _cleanup_existing_test_course()

    teacher = sql_db.ensure_default_teacher()
    other_teacher = _ensure_user("qb_other_teacher", "teacher", "别的老师")
    student = _ensure_user("qb_student", "student", "测试学生")

    course_id = sql_db.create_course(TEST_COURSE_MARK, teacher)
    doc1 = sql_db.create_document(course_id, teacher, "题库测试文档A.txt", "TXT", 10)
    doc2 = sql_db.create_document(course_id, teacher, "题库测试文档B.txt", "TXT", 10)

    # ---------- 1. 教师端新增：三型题目 ----------
    r_single = QuestionService.create_question(teacher, course_id, _single_payload(doc1))
    r_multi = QuestionService.create_question(teacher, course_id, _multi_payload(doc1))
    r_judge = QuestionService.create_question(teacher, course_id, _judge_payload(None))
    check("新增单选题成功", r_single["ok"] and r_single["data"]["question_id"] > 0,
          str(r_single.get("message")))
    check("新增多选题成功", r_multi["ok"], str(r_multi.get("message")))
    check("新增判断题成功且 answer=对 归一化为 true",
          r_judge["ok"] and r_judge["data"]["question"]["answer"] == "true",
          str(r_judge["data"]["question"].get("answer")) if r_judge["ok"] else r_judge["message"])
    check("判断题挂课程级（document_id 为空）",
          r_judge["ok"] and r_judge["data"]["document_id"] is None)
    check("选择题选项被解析为 [{key,text}]",
          r_single["ok"] and r_single["data"]["question"]["options"][0] ==
          {"key": "A", "text": "线性表是有限序列"})

    q_single = r_single["data"]["question_id"]
    q_multi = r_multi["data"]["question_id"]
    q_judge = r_judge["data"]["question_id"]

    # ---------- 2. 参数校验 ----------
    bad = _single_payload(doc1); bad["stem"] = "   "
    check("空题干被拒", QuestionService.create_question(teacher, course_id, bad)["code"] == 1001)
    bad = _single_payload(doc1); bad["q_type"] = "SHORT"
    check("非法题型被拒（Scope A 不含简答题）",
          QuestionService.create_question(teacher, course_id, bad)["code"] == 1001)
    bad = _single_payload(doc1); bad["answer"] = "Z"
    check("答案不在选项内被拒", QuestionService.create_question(teacher, course_id, bad)["code"] == 1001)
    bad = _single_payload(doc1); bad["answer"] = ["A", "B"]
    check("单选题多答案被拒", QuestionService.create_question(teacher, course_id, bad)["code"] == 1001)
    bad = _single_payload(doc1); bad["options"] = [{"key": "A", "text": "只有一个选项"}]
    check("选项少于 2 个被拒", QuestionService.create_question(teacher, course_id, bad)["code"] == 1001)
    bad = _judge_payload(doc1); bad["answer"] = "也许"
    check("判断题非布尔答案被拒", QuestionService.create_question(teacher, course_id, bad)["code"] == 1001)

    # ---------- 3. 课程归属校验（防越权改他人题库） ----------
    check("非本课程教师查看题库被拒（4003）",
          QuestionService.list_questions(other_teacher, course_id)["code"] == 4003)
    check("非本课程教师改题被拒（4003）",
          QuestionService.update_question(other_teacher, q_single, {"analysis": "越权"})["code"] == 4003)
    check("非本课程教师删题被拒（4003）",
          QuestionService.delete_question(other_teacher, q_single)["code"] == 4003)

    # ---------- 4. 列表与统计 ----------
    listed = QuestionService.list_questions(teacher, course_id, document_id=doc1)
    check("按文档列出题库含「该文档题 + 课程通用题」（3 条）",
          listed["ok"] and listed["data"]["total"] == 3,
          str(listed["data"]["total"]) if listed["ok"] else listed["message"])
    exact_total, _ = sql_db.list_questions(course_id, document_id=doc1, include_course_level=False)
    check("DAO 精确过滤（仅该文档题，不含课程通用题）为 2 条", exact_total == 2, str(exact_total))
    stats = QuestionService.stats(teacher, course_id)["data"]
    check("题库统计：题型分布 1/1/1",
          stats["by_type"] == {"SINGLE": 1, "MULTI": 1, "JUDGE": 1}, str(stats["by_type"]))
    check("题库统计：启用 3 题、作答 0 次", stats["active_count"] == 3 and stats["answer_count"] == 0)

    # ---------- 5. 学生出题：防泄题硬断言 ----------
    got = PracticeService.get_questions(student, course_id, document_id=doc1, count=10)
    items = got["data"]["items"] if got["ok"] else []
    check("学生出题返回 3 题（含课程通用题）", got["ok"] and len(items) == 3, str(len(items)))
    check("学生出题不含 answer 字段", all("answer" not in it for it in items))
    check("学生出题不含 analysis 字段", all("analysis" not in it for it in items))
    check("学生出题含题面/选项/题型/收藏标记",
          all(it.get("stem") and "options" in it and it.get("q_type")
              and "is_favorited" in it for it in items))
    check("出题题目集合与题库一致",
          {it["question_id"] for it in items} == {q_single, q_multi, q_judge},
          str(sorted(it["question_id"] for it in items)))

    # ---------- 6. 判分正确性 ----------
    def submit(question_id, answer):
        return PracticeService.submit(student, question_id, answer)

    s1 = submit(q_single, "A")
    check("单选答对：判正确 + 100 分 + 下发答案与解析",
          s1["ok"] and s1["data"]["is_correct"] is True and s1["data"]["score"] == 100.0
          and s1["data"]["correct_answer"] == "A" and bool(s1["data"]["analysis"]),
          str(s1.get("message")))
    s2 = submit(q_single, "B")
    check("单选答错：判错误 + 0 分", s2["data"]["is_correct"] is False and s2["data"]["score"] == 0.0)
    s3 = submit(q_multi, ["C", "A"])
    check("多选答案顺序无关：判正确", s3["data"]["is_correct"] is True)
    s4 = submit(q_multi, ["A"])
    check("多选少选：判错误", s4["data"]["is_correct"] is False)
    s5 = submit(q_judge, "对")
    check("判断题「对」同义归一：判正确", s5["data"]["is_correct"] is True)
    s6 = submit(q_judge, None)
    check("未作答：判错误", s6["data"]["is_correct"] is False)
    check("每次提交都返回正确答案与解析（提交后才下发）",
          all("correct_answer" in r["data"] and "analysis" in r["data"] for r in (s1, s2, s3, s4, s5, s6)))

    # ---------- 7. 答题记录与错题本 ----------
    rec = PracticeService.records(student, course_id=course_id)
    check("答题记录追加（6 次提交 → 6 条）", rec["data"]["total"] == 6, str(rec["data"]["total"]))
    check("答题记录正确率 3/6 = 50%",
          rec["data"]["correct_count"] == 3 and rec["data"]["correct_rate"] == 50.0)
    check("答题记录含题干与正确答案（本人已作答，可回看）",
          all(r.get("stem") and "correct_answer" in r for r in rec["data"]["items"]))

    wrong = PracticeService.wrong_book(student, course_id)
    check("错题本按题去重（3 题曾答错）", wrong["ok"] and wrong["data"]["total"] == 3,
          str(wrong["data"]["total"]) if wrong["ok"] else wrong["message"])
    w_multi = next((it for it in wrong["data"]["items"] if it["question_id"] == q_multi), None)
    check("错题本取每题最近一次错误作答",
          w_multi is not None and w_multi["last_user_answer"] == ["A"],
          str(w_multi and w_multi["last_user_answer"]))
    check("错题本含错答次数/正确答案/解析/知识点字段",
          all(k in wrong["data"]["items"][0] for k in
              ("wrong_count", "correct_answer", "analysis", "kp_name")))

    # ---------- 8. 题目收藏 ----------
    f1 = PracticeService.favorite(student, course_id, q_single)
    f2 = PracticeService.favorite(student, course_id, q_single)
    check("收藏幂等：首次 created=True，重复 created=False",
          f1["data"]["created"] is True and f2["data"]["created"] is False)
    mine = PracticeService.list_favorites(student, course_id)
    check("我的题目收藏 1 条且 is_favorited=True",
          mine["data"]["total"] == 1 and mine["data"]["items"][0]["is_favorited"] is True)
    tf = QuestionService.favorites(teacher, course_id)
    check("教师端可见题目收藏情况（含学生与题面）",
          tf["ok"] and tf["data"]["total"] == 1
          and tf["data"]["items"][0]["student_id"] == student
          and bool(tf["data"]["items"][0]["stem"]), str(tf.get("message")))
    check("收藏非本课程题目被拒（4003）",
          PracticeService.favorite(student, course_id + 999, q_single)["code"] == 4003)
    PracticeService.unfavorite(student, course_id, q_single)
    check("取消收藏后为 0 条",
          PracticeService.list_favorites(student, course_id)["data"]["total"] == 0)

    # ---------- 9. 停用 / 删除语义 ----------
    check("停用题目成功", QuestionService.set_active(teacher, q_single, False)["ok"])
    ids = {it["question_id"] for it in PracticeService.get_questions(
        student, course_id, document_id=doc1, count=10)["data"]["items"]}
    check("停用后不再出现在出题池", q_single not in ids, str(sorted(ids)))
    check("停用后提交被拒（2004）", PracticeService.submit(student, q_single, "A")["code"] == 2004)
    QuestionService.set_active(teacher, q_single, True)
    ids2 = {it["question_id"] for it in PracticeService.get_questions(
        student, course_id, document_id=doc1, count=10)["data"]["items"]}
    check("重新启用后恢复出题", q_single in ids2)

    dele = QuestionService.delete_question(teacher, q_single)
    check("删除已作答题目 → 软删（答题记录得以保留）",
          dele["ok"] and dele["data"]["soft_deleted"] is True
          and sql_db.get_question(q_single) is not None
          and sql_db.get_question(q_single)["is_active"] == 0, str(dele.get("message")))

    r_tmp = QuestionService.create_question(
        teacher, course_id, _single_payload(doc1, stem="临时题目：用于验证物理删除"))
    q_tmp = r_tmp["data"]["question_id"]
    dele2 = QuestionService.delete_question(teacher, q_tmp)
    check("删除未被作答的题目 → 物理删除",
          dele2["ok"] and dele2["data"]["deleted"] is True and sql_db.get_question(q_tmp) is None)

    upd = QuestionService.update_question(teacher, q_multi, {"analysis": "补充：顺序存储与链式存储。"})
    check("局部修改题目（仅改解析）成功且题干不变",
          upd["ok"] and upd["data"]["question"]["analysis"].startswith("补充")
          and upd["data"]["question"]["stem"] == "线性表的存储结构包括哪些？", str(upd.get("message")))

    # ---------- 10. 文档级清理（课程通用题保留） ----------
    PracticeService.favorite(student, course_id, q_multi)
    doc_result = DocumentService.delete_document(doc1, teacher)
    check("删除文档返回题库清理计数（2 题 / 4 答题 / 1 收藏）",
          doc_result["ok"] and doc_result["data"]["removed_questions"] == 2
          and doc_result["data"]["removed_answers"] == 4
          and doc_result["data"]["removed_question_favorites"] == 1,
          str(doc_result.get("data") if doc_result["ok"] else doc_result.get("message")))
    check("删除文档后该文档题目清空",
          sql_db.count_questions_by_document(course_id, doc1) == 0)
    check("课程通用题不受文档删除影响（仍存在）",
          sql_db.get_question(q_judge) is not None)
    check("同课程其他文档题目不受影响",
          sql_db.count_questions_by_document(course_id, doc2) == 0)
    check("答题记录按文档清理（课程级题的 2 条保留）",
          sql_db.count_answers_by_course(course_id) == 2,
          str(sql_db.count_answers_by_course(course_id)))

    # ---------- 11. 课程级联清理（无孤儿数据） ----------
    course_result = CourseService.delete_course(course_id, confirm=True)
    check("删除课程返回题库清理计数（1 题 / 2 答）",
          course_result["ok"] and course_result["data"]["removed_questions"] == 1
          and course_result["data"]["removed_answers"] == 2,
          str(course_result.get("data") if course_result["ok"] else course_result.get("message")))
    check("课程删除后题目清空", sql_db.count_questions_by_course(course_id) == 0)
    check("课程删除后答题记录清空", sql_db.count_answers_by_course(course_id) == 0)
    check("课程删除后题目收藏清空",
          sql_db.list_question_favorite_users(course_id) == [])
    check("课程删除后无孤儿题目（按 question_id 复查）",
          sql_db.get_question(q_judge) is None and sql_db.get_question(q_multi) is None)

    db.close()

    print("=" * 68)
    passed = 0
    for name, ok, detail in checks:
        print(f"  {'✓' if ok else '✗'} {name}" + (f"  ({detail})" if detail else ""))
        passed += ok
    print(f"\n通过 {passed}/{len(checks)}")
    print("=" * 68)
    return passed == len(checks)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
