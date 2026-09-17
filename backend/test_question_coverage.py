"""
知识点题目覆盖率与 kp_id 完整性校验（P1）——端到端验证

覆盖范围：
  1. kp_id 完整性校验：图谱可用但查无此点 → 4002（拦住悬空知识点：手输/跨课程复制/图谱重建后失效）
  2. 允许不挂知识点（kp_id 为空）；显式传 null 可清空关联；只改其他字段时不被拦住
  3. 图谱不可用时**放行**并标记 kp_checked=False（图库宕机不应阻塞教师建题）
  4. 覆盖率报表：知识点总数 / 覆盖率 / 无题知识点（只数启用中的题）/ 未挂知识点的题 / 悬空 kp_id
  5. 权限：非本课程教师 → 4003

依赖：目标课程（默认 65）的图谱必须在本机 Neo4j 中（本脚本**只读图谱**，不写图谱）。
运行方式（backend 目录下，需 Neo4j 已启动）：
    python test_question_coverage.py            # 默认课程 65
    python test_question_coverage.py 65
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.database import db
from app.core.sql_database import sql_db
from app.services.question_service import QuestionService

# 目标课程（需本机图谱中存在其知识点）
COURSE_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 65
FAKE_KP = f"kp_{COURSE_ID}_deadbeef"        # 故意不存在的知识点 id


def _payload(document_id, kp_id, stem):
    """覆盖率测试用单选题目"""
    return {
        "document_id": document_id, "kp_id": kp_id, "q_type": "SINGLE", "stem": stem,
        "options": [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
        "answer": "A", "analysis": "覆盖率测试用题（脚本自动清理）", "difficulty": 2,
    }


class _BrokenGraph:
    """模拟「图库不可用」：任何查询都抛异常"""

    @staticmethod
    def query(*args, **kwargs):
        raise RuntimeError("模拟 Neo4j 不可用")


def main():
    checks = []
    created_ids = []
    restored_active = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    try:
        course = sql_db.get_course(COURSE_ID)
        if course is None:
            print(f"✗ 课程不存在：course_id={COURSE_ID}")
            return False
        teacher = course["teacher_id"]
        documents = sql_db.list_documents_by_course(COURSE_ID)
        doc_id = documents[0]["doc_id"] if documents else None
        other_teacher = 2 if teacher != 2 else 1

        kps = db.query(
            "MATCH (n:KnowledgePoint {course_id: $cid}) "
            "RETURN n.kp_id AS kp_id, n.name AS name ORDER BY n.kp_id", {"cid": COURSE_ID})
        if not kps:
            print(f"✗ 本机图谱中没有 course_id={COURSE_ID} 的知识点，无法验证覆盖率"
                  "（请先建图谱或启动 Neo4j）")
            return False
        real_kp = kps[0]["kp_id"]
        print(f"课程 {COURSE_ID}（{course['course_name']}）教师={teacher}，"
              f"图谱知识点 {len(kps)} 个，取用 {real_kp}")

        # ---------- 1. kp_id 完整性校验（新增） ----------
        r_ok = QuestionService.create_question(
            teacher, COURSE_ID, _payload(doc_id, real_kp, "覆盖率-真知识点"))
        check("新增题目：真实 kp_id → 成功", r_ok["ok"], str(r_ok.get("message")))
        check("新增题目：返回 kp_checked=True（确实校验过图谱）",
              r_ok["ok"] and r_ok["data"].get("kp_checked") is True,
              str(r_ok.get("data", {}).get("kp_checked")))
        if r_ok["ok"]:
            created_ids.append(r_ok["data"]["question_id"])

        r_bad = QuestionService.create_question(
            teacher, COURSE_ID, _payload(doc_id, FAKE_KP, "覆盖率-悬空知识点"))
        check("新增题目：不存在的 kp_id → 拒绝（4002）",
              (not r_bad["ok"]) and r_bad["code"] == 4002,
              f"code={r_bad.get('code')} msg={r_bad.get('message')}")
        check("新增题目：被拒绝的题目未落库",
              sql_db._query_one("SELECT count(*) AS c FROM t_question WHERE kp_id = ?",
                                (FAKE_KP,))["c"] == 0)

        r_unlinked = QuestionService.create_question(
            teacher, COURSE_ID, _payload(doc_id, None, "覆盖率-未挂知识点"))
        check("新增题目：kp_id 为空 → 允许（不挂知识点）", r_unlinked["ok"],
              str(r_unlinked.get("message")))
        if r_unlinked["ok"]:
            created_ids.append(r_unlinked["data"]["question_id"])

        # ---------- 2. kp_id 完整性校验（修改） ----------
        q_ok = created_ids[0]
        r_only_analysis = QuestionService.update_question(teacher, q_ok, {"analysis": "只改解析"})
        check("修改题目：只改解析（未传 kp_id）→ 成功", r_only_analysis["ok"],
              str(r_only_analysis.get("message")))
        r_bad_update = QuestionService.update_question(teacher, q_ok, {"kp_id": FAKE_KP})
        check("修改题目：改成不存在的 kp_id → 拒绝（4002）",
              (not r_bad_update["ok"]) and r_bad_update["code"] == 4002,
              f"code={r_bad_update.get('code')}")
        r_clear = QuestionService.update_question(teacher, q_ok, {"kp_id": None})
        check("修改题目：显式传 null → 允许清空关联",
              r_clear["ok"] and not (r_clear["data"]["question"].get("kp_id") or ""),
              str(r_clear.get("data", {}).get("question", {}).get("kp_id")))
        QuestionService.update_question(teacher, q_ok, {"kp_id": real_kp})   # 复原关联

        # ---------- 3. 覆盖率报表 ----------
        cov = QuestionService.coverage(teacher, COURSE_ID)
        check("覆盖率：成功返回", cov["ok"], str(cov.get("message")))
        data = cov["data"]
        check("覆盖率：graph_available=True", data["graph_available"] is True)
        check("覆盖率：知识点总数 = 图谱节点数", data["total_kp"] == len(kps),
              f"{data['total_kp']} vs {len(kps)}")

        grouped, unlinked = sql_db.count_questions_grouped_by_kp(COURSE_ID, only_active=True)
        check("覆盖率：启用中题目数与 DAO 统计一致",
              data["question_count"] == sum(grouped.values()),
              f"{data['question_count']} vs {sum(grouped.values())}")
        check("覆盖率：未挂知识点的题数正确（≥1）",
              data["unlinked_question_count"] == unlinked and unlinked >= 1,
              f"{data['unlinked_question_count']} vs {unlinked}")
        per_kp = {i["kp_id"]: i["question_count"] for i in data["items"]}
        check("覆盖率：各知识点题量与 DAO 分组一致",
              all(per_kp.get(k, 0) == v for k, v in grouped.items()),
              f"items={len(per_kp)} grouped={len(grouped)}")
        check("覆盖率：覆盖率 = 有题知识点 / 知识点总数",
              data["coverage_rate"] == round(data["kp_with_question"] / data["total_kp"] * 100, 1),
              f"{data['coverage_rate']}%")

        # 无题知识点：把该知识点的题全部停用后，它应进入 unmatched（只数启用中的题）
        qs_of_kp = sql_db.list_questions(COURSE_ID, kp_id=real_kp, page=1, page_size=100)[1]
        for q in qs_of_kp:
            sql_db.set_question_active(q["question_id"], False)
            restored_active.append(q["question_id"])
        cov2 = QuestionService.coverage(teacher, COURSE_ID)["data"]
        unmatched_ids = [u["kp_id"] for u in cov2["unmatched"]]
        check("覆盖率：题目全部停用后该知识点进入「无题知识点」",
              real_kp in unmatched_ids, f"unmatched={len(unmatched_ids)}")
        check("覆盖率：无题数 +1", cov2["kp_without_question"] == data["kp_without_question"] + 1,
              f"{cov2['kp_without_question']} vs {data['kp_without_question']}")
        for qid in restored_active:
            sql_db.set_question_active(qid, True)
        restored_active.clear()

        # 悬空 kp_id：绕过服务层直接落库（模拟历史脏数据），覆盖率应把它标出来
        fake_qid = sql_db.create_question(
            course_id=COURSE_ID, document_id=doc_id, kp_id=FAKE_KP, q_type="JUDGE",
            stem="覆盖率-模拟历史悬空知识点", options=[], answer="true",
            analysis="", difficulty=1, created_by=teacher, source="MANUAL")
        created_ids.append(fake_qid)
        cov3 = QuestionService.coverage(teacher, COURSE_ID)["data"]
        check("覆盖率：识别出悬空 kp_id（题目引用的知识点已不在图谱中）",
              cov3["dangling_count"] == 1 and cov3["dangling"][0]["kp_id"] == FAKE_KP,
              f"dangling={cov3['dangling']}")

        # 文档级作用域
        cov_doc = QuestionService.coverage(teacher, COURSE_ID, document_id=doc_id)["data"]
        check("覆盖率：文档级作用域生效（知识点数 ≤ 课程级且 document_id 回显）",
              cov_doc["total_kp"] <= data["total_kp"] and cov_doc["document_id"] == doc_id,
              f"doc={cov_doc['total_kp']} course={data['total_kp']}")

        # ---------- 4. 权限 ----------
        r_perm = QuestionService.coverage(other_teacher, COURSE_ID)
        check("权限：非本课程教师查覆盖率 → 4003",
              (not r_perm["ok"]) and r_perm["code"] == 4003, f"code={r_perm.get('code')}")
        r_perm2 = QuestionService.create_question(
            other_teacher, COURSE_ID, _payload(doc_id, real_kp, "越权建题"))
        check("权限：非本课程教师建题 → 4003",
              (not r_perm2["ok"]) and r_perm2["code"] == 4003, f"code={r_perm2.get('code')}")

        # ---------- 5. 图谱不可用时的降级 ----------
        import app.services.question_service as qs_module
        original_db = qs_module.db
        qs_module.db = _BrokenGraph()
        try:
            r_degraded = QuestionService.create_question(
                teacher, COURSE_ID, _payload(doc_id, real_kp, "覆盖率-图库不可用时建题"))
            check("图库不可用：建题放行（不阻塞教师）且 kp_checked=False",
                  r_degraded["ok"] and r_degraded["data"].get("kp_checked") is False,
                  f"ok={r_degraded.get('ok')} checked={r_degraded.get('data', {}).get('kp_checked')}")
            if r_degraded["ok"]:
                created_ids.append(r_degraded["data"]["question_id"])
            cov_down = QuestionService.coverage(teacher, COURSE_ID)
            check("图库不可用：覆盖率降级返回 graph_available=False（不报错）",
                  cov_down["ok"] and cov_down["data"]["graph_available"] is False
                  and cov_down["data"]["total_kp"] == 0,
                  f"ok={cov_down.get('ok')} avail={cov_down.get('data', {}).get('graph_available')}")
        finally:
            qs_module.db = original_db

        # ---------- 6. 清理：删除本脚本创建的题目（均未被作答 → 物理删除） ----------
        removed = 0
        for qid in created_ids:
            removed += sql_db.delete_question(qid)
        check("清理：本脚本创建的题目已全部删除", removed == len(created_ids),
              f"{removed}/{len(created_ids)}")

        return checks
    finally:
        for qid in restored_active:            # 异常路径也要恢复题目启用状态
            sql_db.set_question_active(qid, True)
        db.close()


if __name__ == "__main__":
    result = main()
    if result is False:
        sys.exit(1)
    print("=" * 68)
    passed = 0
    for name, ok, detail in result:
        print(f"  {'✓' if ok else '✗'} {name}" + (f"  ({detail})" if detail else ""))
        passed += ok
    print(f"\n通过 {passed}/{len(result)}")
    print("=" * 68)
    sys.exit(0 if passed == len(result) else 1)
