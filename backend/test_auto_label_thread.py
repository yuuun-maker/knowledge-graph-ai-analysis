"""自动标注接口线程池化回归测试（不调用真实 embedding / 数据库）。

`/api/v1/questions/auto-label` 原先在 async 端点里同步执行整个标注流程，
批量题时会让事件循环停摆。本测试确认：
1. service 方法确实在事件循环线程之外执行；
2. 参数（course_id/document_id/only_missing/apply/top_k/阈值）原样透传；
3. 返回值仍按统一包装返回。

运行：cd backend && python test_auto_label_thread.py
"""
import asyncio
import sys
import threading
from types import SimpleNamespace

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.api import questions as api_questions
from app.services.question_service import QuestionService

failures = []


def check(label, ok, detail=""):
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    seen = {}
    original = QuestionService.auto_label
    loop_thread = threading.get_ident()

    def fake_auto_label(user_id, course_id, **kwargs):
        seen["thread"] = threading.get_ident()
        seen["user_id"] = user_id
        seen["course_id"] = course_id
        seen["kwargs"] = kwargs
        return {"ok": True, "code": 0, "message": "success",
                "data": {"applied": 0, "labeled": 1}}

    QuestionService.auto_label = staticmethod(fake_auto_label)
    try:
        body = SimpleNamespace(
            course_id="42", document_id="7", question_ids=[1, 2],
            only_missing=False, apply=True, top_k=5, apply_threshold=0.75,
        )
        user = {"user_id": 9, "username": "t", "role": "teacher"}
        result = asyncio.run(api_questions.auto_label_questions(body, user))
    finally:
        QuestionService.auto_label = staticmethod(original)

    check("service 在独立线程执行", seen.get("thread") != loop_thread,
          f"loop={loop_thread}, service={seen.get('thread')}")
    check("course_id 已转为整数", seen.get("course_id") == 42, str(seen.get("course_id")))
    check("document_id 原样透传", seen.get("kwargs", {}).get("document_id") == "7")
    check("标注参数原样透传",
          seen.get("kwargs") == {
              "document_id": "7", "question_ids": [1, 2],
              "only_missing": False, "apply": True,
              "top_k": 5, "apply_threshold": 0.75,
          },
          str(seen.get("kwargs")))
    check("统一响应包装仍生效",
          result.get("code") == 0 and result.get("data", {}).get("labeled") == 1,
          str(result))

    print(f"通过 {5 - len(failures)}/5")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
