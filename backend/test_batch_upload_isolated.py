"""
批量上传 / 独立建图 / 失败隔离 / 重试 / 权限 —— 隔离验证脚本

⚠️ 与仓库里多数 test_*.py 不同，本脚本**不触碰任何线上数据**：
    - SQLITE_DB_PATH / UPLOAD_DIR 在导入 app 之前指向临时目录，用完即删；
    - Neo4j 被替换为内存记录器（KnowledgeGraphManager.build_graph / db 删除接口），
      因此不需要启动 Neo4j，也不会对真实图谱执行任何 DELETE；
    - LLM 抽取被替换为确定性桩（不发外部请求）。

运行方式（在 backend 目录下）：
    python test_batch_upload_isolated.py
"""
import asyncio
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 必须在导入 app.* 之前设置，config.Settings 在模块导入时读取
_TMP_DIR = tempfile.mkdtemp(prefix="kg_batch_test_")
os.environ["SQLITE_DB_PATH"] = os.path.join(_TMP_DIR, "test_app.db")
os.environ["UPLOAD_DIR"] = os.path.join(_TMP_DIR, "uploads")

import time

from fastapi.testclient import TestClient                      # noqa: E402

from app.core.sql_database import sql_db                      # noqa: E402
from app.core.dependencies import get_current_user            # noqa: E402
from app.main import app                                      # noqa: E402
from app.services import document_service                     # noqa: E402
from app.services.document_service import DocumentService     # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [通过] {name}")
    else:
        FAIL += 1
        print(f"  [失败] {name} {detail}")


class FakeUpload:
    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._content = content

    async def read(self) -> bytes:
        return self._content


class FakeExtractor:
    """确定性抽取桩：首行作为知识点名；FAIL_EXTRACT 触发抽取失败。"""
    state = {"fail_extract": True}

    def __init__(self, *args, **kwargs):
        pass

    async def extract(self, text: str) -> dict:
        if FakeExtractor.state["fail_extract"] and "FAIL_EXTRACT" in text:
            return {"error": "模拟抽取失败"}
        marker = (text.strip().splitlines() or ["未知知识点"])[0].strip()
        return {
            "entities": [{"name": marker, "category": "概念", "description": marker}],
            "relations": [],
        }


class FakeKG:
    """内存图谱写入桩：按 document_id 隔离记录，FAIL_GRAPH 触发构建失败。"""
    build_calls = []
    graphs = {}
    state = {"fail_graph": True}

    @staticmethod
    def build_graph(course_id, document_id, entities, relations):
        names = [e.get("name", "") for e in entities]
        FakeKG.build_calls.append((course_id, document_id, names))
        if FakeKG.state["fail_graph"] and any("FAIL_GRAPH" in n for n in names):
            raise RuntimeError("模拟图谱写入失败")
        FakeKG.graphs.setdefault(document_id, set()).update(names)
        return {"course_id": course_id, "document_id": document_id,
                "node_count": len(names), "relation_count": len(relations)}


class FakeNeo4j:
    deleted = []

    @staticmethod
    def delete_document_graph(course_id, document_id):
        FakeNeo4j.deleted.append((course_id, document_id))
        return (0, 0)


async def wait_idle(timeout: float = 10.0):
    """等待后台批处理任务全部结束（桩处理，通常几十毫秒）。"""
    start = asyncio.get_event_loop().time()
    while document_service._running_docs or document_service._background_tasks:
        if asyncio.get_event_loop().time() - start > timeout:
            raise TimeoutError("后台处理超时未结束")
        await asyncio.sleep(0.02)


def doc_of(doc_id: int) -> dict:
    return sql_db.get_document(doc_id)


async def main():
    print("=" * 66)
    print("Step 0: 初始化临时数据库 / 打桩（不接触线上 SQLite 与 Neo4j）")
    print("=" * 66)
    sql_db.init_tables()
    sql_db.init_tables()  # 幂等：重复迁移不应报错
    check("临时库初始化且迁移幂等", True)

    # 打桩必须替换 document_service 模块里导入的名字（它持有独立引用）
    document_service.KnowledgeExtractor = FakeExtractor
    document_service.KnowledgeGraphManager = FakeKG
    document_service.db = FakeNeo4j

    teacher_id = sql_db.create_user("bt_teacher", "x", role="teacher")
    outsider_id = sql_db.create_user("bt_outsider", "x", role="teacher")
    course_id = sql_db.create_course("批量上传隔离测试课程", teacher_id)
    other_course_id = sql_db.create_course("另一门课", outsider_id)
    check("测试账号与课程已创建", bool(teacher_id and outsider_id and course_id))

    print("\n" + "=" * 66)
    print("Step 1: 一次批量上传 3 个文件（其中一个抽取失败）")
    print("=" * 66)
    files = [
        FakeUpload("one.txt", "KP_ONE\n第一篇文档的内容。".encode("utf-8")),
        FakeUpload("two.txt", "KP_TWO\n第二篇文档的内容。".encode("utf-8")),
        FakeUpload("three.txt", "FAIL_EXTRACT\n第三篇会抽取失败。".encode("utf-8")),
    ]
    result = await DocumentService.process_batch(files, course_id, teacher_id)
    check("批量接口返回成功", result["ok"], str(result))
    items = result["data"]["items"]
    check("每个文件都有独立返回项", len(items) == 3, str(items))
    check("3 个文件都进入处理队列", result["data"]["accepted"] == 3, str(result["data"]))
    doc_ids = [it["document_id"] for it in items]
    check("3 个文件拿到互不相同的 document_id", len(set(doc_ids)) == 3, str(doc_ids))

    await wait_idle()

    d1, d2, d3 = (doc_of(i) for i in doc_ids)
    check("文档1 图谱构建完成", d1["graph_status"] == "COMPLETED", str(d1))
    check("文档2 图谱构建完成", d2["graph_status"] == "COMPLETED", str(d2))
    check("文档3 抽取失败且原因落库",
          d3["extract_status"] == "FAILED" and "模拟抽取失败" in (d3["error_message"] or ""),
          str(d3))
    check("失败文件不影响同批其他文件", d2["graph_status"] == "COMPLETED")

    print("\n" + "=" * 66)
    print("Step 2: 图谱按文档隔离（不同 doc_id 只拿到自己的知识点）")
    print("=" * 66)
    g1 = FakeKG.graphs.get(doc_ids[0], set())
    g2 = FakeKG.graphs.get(doc_ids[1], set())
    check("文档1 图谱只含 KP_ONE", g1 == {"KP_ONE"}, str(g1))
    check("文档2 图谱只含 KP_TWO", g2 == {"KP_TWO"}, str(g2))
    check("图谱写入均携带各自 document_id",
          {(c, d) for c, d, _ in FakeKG.build_calls} >=
          {(course_id, doc_ids[0]), (course_id, doc_ids[1])},
          str(FakeKG.build_calls))

    print("\n" + "=" * 66)
    print("Step 3: 重复提交同一文件（同课程内容哈希去重）")
    print("=" * 66)
    before = sql_db.count_documents_by_course(course_id)
    dup = await DocumentService.process_batch(
        [FakeUpload("one_again.txt", "KP_ONE\n第一篇文档的内容。".encode("utf-8"))],
        course_id, teacher_id)
    await wait_idle()
    check("重复文件被识别为 duplicate", dup["data"]["items"][0].get("duplicate") is True, str(dup))
    check("重复文件复用原 document_id",
          dup["data"]["items"][0]["document_id"] == doc_ids[0], str(dup))
    check("重复提交没有新建文档行",
          sql_db.count_documents_by_course(course_id) == before, str(before))

    print("\n" + "=" * 66)
    print("Step 4: 单文件失败重试（只重试失败文档，已成功文档拒绝重试）")
    print("=" * 66)
    FakeExtractor.state["fail_extract"] = False
    retry = await DocumentService.retry_document(doc_ids[2], teacher_id)
    check("失败文档重试进入队列", retry["ok"], str(retry))
    await wait_idle()
    d3 = doc_of(doc_ids[2])
    check("重试后图谱构建完成", d3["graph_status"] == "COMPLETED", str(d3))
    check("重试后旧错误信息被清除", not d3["error_message"], str(d3.get("error_message")))
    check("重试前只清理该文档图谱",
          (course_id, doc_ids[2]) in FakeNeo4j.deleted, str(FakeNeo4j.deleted))

    again = await DocumentService.retry_document(doc_ids[0], teacher_id)
    check("已成功文档拒绝重试", not again["ok"] and again["code"] == 4000, str(again))

    print("\n" + "=" * 66)
    print("Step 5: 图谱构建失败隔离 + 修复后重试")
    print("=" * 66)
    FakeKG.state["fail_graph"] = True
    mix = await DocumentService.process_batch([
        FakeUpload("graph_fail.txt", "FAIL_GRAPH\n会写图失败。".encode("utf-8")),
        FakeUpload("graph_ok.txt", "KP_OK\n会写图成功。".encode("utf-8")),
    ], course_id, teacher_id)
    mix_ids = [it["document_id"] for it in mix["data"]["items"]]
    await wait_idle()
    check("同批中一篇图谱失败",
          doc_of(mix_ids[0])["graph_status"] == "FAILED", str(doc_of(mix_ids[0])))
    check("同批中另一篇仍成功",
          doc_of(mix_ids[1])["graph_status"] == "COMPLETED", str(doc_of(mix_ids[1])))

    FakeKG.state["fail_graph"] = False
    retry2 = await DocumentService.retry_document(mix_ids[0], teacher_id)
    await wait_idle()
    check("图谱失败文档可重试成功",
          retry2["ok"] and doc_of(mix_ids[0])["graph_status"] == "COMPLETED",
          str(doc_of(mix_ids[0])))

    print("\n" + "=" * 66)
    print("Step 6: 非法文件 / 超大文件与正常文件同批（逐文件独立结果）")
    print("=" * 66)
    weird = await DocumentService.process_batch([
        FakeUpload("bad.exe", b"not a document"),
        FakeUpload("empty.txt", b""),
        FakeUpload("still_ok.txt", "KP_STILL_OK\n正常文件。".encode("utf-8")),
    ], course_id, teacher_id)
    weird_items = weird["data"]["items"]
    check("非法扩展名单独失败", weird_items[0]["ok"] is False and weird_items[0]["code"] == 1001,
          str(weird_items[0]))
    check("空文件单独失败", weird_items[1]["ok"] is False and weird_items[1]["code"] == 1003,
          str(weird_items[1]))
    check("同批正常文件仍被接收", weird_items[2]["ok"] is True, str(weird_items[2]))
    await wait_idle()

    old_limit = document_service.settings.MAX_UPLOAD_SIZE
    document_service.settings.MAX_UPLOAD_SIZE = 4
    try:
        big = await DocumentService.process_batch(
            [FakeUpload("big.txt", b"12345")], course_id, teacher_id)
        check("超大文件被拒绝", big["data"]["items"][0]["code"] == 1002, str(big))
    finally:
        document_service.settings.MAX_UPLOAD_SIZE = old_limit

    print("\n" + "=" * 66)
    print("Step 7: 权限校验（非课程教师不能上传/重试）")
    print("=" * 66)
    denied = await DocumentService.process_batch(
        [FakeUpload("x.txt", "KP_X\n越权。".encode("utf-8"))], course_id, outsider_id)
    check("无权限教师不能向该课程上传",
          not denied["ok"] and denied["code"] == 4003, str(denied))
    denied_retry = await DocumentService.retry_document(doc_ids[2], outsider_id)
    check("无权限教师不能重试该课程文档",
          not denied_retry["ok"] and denied_retry["code"] == 4003, str(denied_retry))
    other = await DocumentService.process_batch(
        [FakeUpload("x.txt", "KP_X\n跨课程。".encode("utf-8"))], other_course_id, outsider_id)
    check("教师可上传到自己拥有的另一门课", other["ok"], str(other))
    await wait_idle()

    print("\n" + "=" * 66)
    print("Step 8: 文档列表返回图谱状态与失败原因")
    print("=" * 66)
    listed = DocumentService.list_documents(course_id, teacher_id)
    check("文档列表可读", listed["ok"], str(listed))
    sample = listed["data"][0]
    check("列表包含 graph_status", "graph_status" in sample, str(sample))
    check("列表包含 error_message", "error_message" in sample, str(sample))
    failed_doc = next((d for d in listed["data"]
                       if d["doc_id"] == mix_ids[0]), None)
    check("重试成功后错误信息为空",
          failed_doc is not None and not failed_doc.get("error_message"), str(failed_doc))

    print("\n" + "=" * 66)
    print(f"结果：通过 {PASS}/{PASS + FAIL}")
    print("=" * 66)


def api_smoke():
    """HTTP 层冒烟：确认 multipart 批量端点与重试端点真实可用。"""
    print("\n" + "=" * 66)
    print("Step 9: HTTP 接口冒烟（multipart 多文件 / 状态查询 / 重试端点）")
    print("=" * 66)

    teacher_id = sql_db.get_user_by_username("bt_teacher")["user_id"]
    outsider_id = sql_db.get_user_by_username("bt_outsider")["user_id"]
    current = {"user": {"user_id": teacher_id, "username": "bt_teacher", "role": "teacher"}}
    app.dependency_overrides[get_current_user] = lambda: current["user"]

    try:
        with TestClient(app) as client:
            course = sql_db.create_course("HTTP 冒烟课程", teacher_id)
            files = [
                ("files", ("http_a.txt", "HTTP_A\n接口测试一。".encode("utf-8"), "text/plain")),
                ("files", ("http_b.txt", "HTTP_B\n接口测试二。".encode("utf-8"), "text/plain")),
            ]
            resp = client.post("/api/v1/documents/batch-upload",
                               data={"course_id": str(course)}, files=files)
            body = resp.json()
            check("批量上传端点返回 code=0", resp.status_code == 200 and body.get("code") == 0,
                  str(body))
            ids = [it.get("document_id") for it in body.get("data", {}).get("items", [])]
            check("HTTP 批量返回两个独立 document_id",
                  len(ids) == 2 and len(set(ids)) == 2, str(ids))

            # 轮询文档列表，等后台任务把状态推到终态
            deadline = time.time() + 10
            docs = []
            while time.time() < deadline:
                listing = client.get("/api/v1/documents", params={"course_id": course}).json()
                docs = listing.get("data", [])
                if docs and all(d.get("graph_status") in ("COMPLETED", "FAILED") for d in docs):
                    break
                time.sleep(0.1)
            check("文档列表反映真实图谱完成状态",
                  len(docs) == 2 and all(d["graph_status"] == "COMPLETED" for d in docs),
                  str(docs))

            detail = client.get(f"/api/v1/documents/{ids[0]}").json()
            check("文档详情含 graph_status / error_message",
                  detail.get("code") == 0 and "graph_status" in detail.get("data", {}),
                  str(detail))

            # 原有单文件上传端点保持可用（同步返回时图谱已完成）
            single = client.post(
                "/api/v1/documents/upload", data={"course_id": str(course)},
                files={"file": ("single.txt", "SINGLE\n单文件。".encode("utf-8"), "text/plain")},
            ).json()
            check("原有单文件上传端点仍可用",
                  single.get("code") == 0
                  and single.get("data", {}).get("graph_status") == "COMPLETED",
                  str(single))

            # 已成功文档重试应被拒绝（4000）
            retry = client.post(f"/api/v1/documents/{ids[0]}/retry").json()
            check("HTTP 重试端点拒绝已完成文档",
                  retry.get("code") == 4000, str(retry))

            # 越权：换成另一门课的教师
            current["user"] = {"user_id": outsider_id, "username": "bt_outsider", "role": "teacher"}
            denied = client.post("/api/v1/documents/batch-upload",
                                 data={"course_id": str(course)},
                                 files=[("files", ("no.txt", "NO\n越权".encode("utf-8"), "text/plain"))]).json()
            check("HTTP 无权限上传返回 4003", denied.get("code") == 4003, str(denied))
    finally:
        app.dependency_overrides.pop(get_current_user, None)


if __name__ == "__main__":
    try:
        asyncio.run(main())
        api_smoke()
        print("\n" + "=" * 66)
        print(f"最终结果：通过 {PASS}/{PASS + FAIL}")
        print("=" * 66)
    finally:
        shutil.rmtree(_TMP_DIR, ignore_errors=True)
