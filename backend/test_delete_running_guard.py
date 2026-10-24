"""删除与后台处理的竞态守卫测试（纯进程内打桩，不读写真实 app.db / Neo4j）。

覆盖三条防线：
1. 文档正在后台处理时，删除入口返回 4009，不进入级联清理；
2. 课程内有文档正在处理时，删除课程返回 4009；
3. 流水线在解析后、入图前、入图后三个节点检查作用域是否仍存在，
   入图期间被删除时清理刚写入的残留图谱。

运行：cd backend && python test_delete_running_guard.py
"""
import asyncio
import sys

from app.services import document_service as ds
from app.services.course_service import CourseService
from app.services.document_service import DocumentService

REAL_FILE = ds.__file__
RUNNING_DOC_ID = 424242


def test_delete_document_guard() -> None:
    ds._running_docs.add(RUNNING_DOC_ID)
    try:
        # 若守卫失效，级联清理会开始访问 Neo4j —— 这里刻意不提供任何真实连接
        result = DocumentService._delete_document_cascade(
            {"doc_id": RUNNING_DOC_ID, "course_id": 1})
    finally:
        ds._running_docs.discard(RUNNING_DOC_ID)
    assert result["ok"] is False and result["code"] == 4009, result


def test_course_running_documents() -> None:
    original = ds.sql_db.list_documents_by_course
    ds.sql_db.list_documents_by_course = lambda cid: [
        {"doc_id": 7}, {"doc_id": RUNNING_DOC_ID}]
    try:
        ds._running_docs.add(RUNNING_DOC_ID)
        assert DocumentService.has_running_documents(1) is True
        ds._running_docs.discard(RUNNING_DOC_ID)
        assert DocumentService.has_running_documents(1) is False
    finally:
        ds._running_docs.discard(RUNNING_DOC_ID)
        ds.sql_db.list_documents_by_course = original


def test_delete_course_guard() -> None:
    orig_get_course = ds.sql_db.get_course
    orig_has_running = DocumentService.has_running_documents
    ds.sql_db.get_course = lambda cid: {"course_id": cid, "teacher_id": 1}
    DocumentService.has_running_documents = staticmethod(lambda cid: True)
    try:
        result = CourseService.delete_course(1, confirm=True)
    finally:
        DocumentService.has_running_documents = staticmethod(orig_has_running)
        ds.sql_db.get_course = orig_get_course
    assert result["ok"] is False and result["code"] == 4009, result


async def test_pipeline_scope_checks() -> None:
    """按作用域存在性的调用顺序，依次验证 4a / 4b / 4c 三个分支。"""
    ds.sql_db.get_document = lambda did: {
        "doc_id": did, "course_id": 1, "file_path": REAL_FILE}
    ds.sql_db.update_document = lambda *args, **kwargs: None
    ds.resolve_document_path = lambda doc: REAL_FILE
    ds._parse_file_sync = lambda path: "some text"

    builds, cleanups, extracts = [], [], []

    class FakeExtractor:
        async def extract(self, text):
            extracts.append(text)
            return {"entities": [{"name": "a"}], "relations": []}

    class FakeKG:
        @staticmethod
        def build_graph(*args):
            builds.append(args)

    ds.KnowledgeExtractor = FakeExtractor
    ds.KnowledgeGraphManager = FakeKG
    DocumentService._cleanup_deleted_scope = staticmethod(
        lambda cid, did: cleanups.append((cid, did)))

    # 4a：解析完成后已删除 → 不再抽取、不入图
    seq = iter([False])
    DocumentService._scope_exists = staticmethod(lambda did, cid: next(seq))
    result = await DocumentService._process_document(1)
    assert result["code"] == 4009 and not builds and not extracts, \
        (result, builds, extracts)

    # 4b：抽取完成后、入图前已删除 → 抽取发生但不再入图
    seq = iter([True, False])
    DocumentService._scope_exists = staticmethod(lambda did, cid: next(seq))
    result = await DocumentService._process_document(1)
    assert result["code"] == 4009 and not builds and len(extracts) == 1, \
        (result, builds, extracts)

    # 4c：入图期间被删除 → 入图完成后清理刚写入的残留
    seq = iter([True, True, False])
    DocumentService._scope_exists = staticmethod(lambda did, cid: next(seq))
    result = await DocumentService._process_document(1)
    assert result["code"] == 4009 and len(builds) == 1 and cleanups == [(1, 1)], \
        (result, builds, cleanups)


def main() -> int:
    tests = [
        ("处理中的文档拒绝删除", test_delete_document_guard),
        ("课程运行中文档检查", test_course_running_documents),
        ("处理中拒绝删除课程", test_delete_course_guard),
        ("流水线作用域检查", lambda: asyncio.run(test_pipeline_scope_checks())),
    ]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  [OK] {name}")
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
    print(f"通过 {passed}/{len(tests)}")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
