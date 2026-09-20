"""上传文件路径解析（t_document.file_path 的只读场景共用）。

背景：file_path 是上传时写入的绝对路径。app.db 与 data/uploads/ 都曾在 git 跟踪下
随仓库在多台机器间流转（app.db 已移出跟踪，见 .gitignore；uploads 的历史文件仍在），
历史行里因此存在三种形态：

  1. 本机绝对路径（上传时正常写入的形态）
  2. 相对 backend/ 的路径（如 ./data/uploads/5/x.pdf）
  3. 其他机器的绝对路径（如 F:\\com\\knowledge-graph-ai-analysis\\uploads\\5\\x.pdf）

形态 3 在本机必然不存在，会表现为「文档打不开」。故在按原样找不到文件时，再按上传时
的命名约定回退定位，使随仓库拉取下来的历史文档同样可读（只读解析，不写回数据库）。
"""
import glob
import os

from .config import BASE_DIR, settings


def _exists(path) -> bool:
    return bool(path) and os.path.exists(path)


def resolve_document_path(doc: dict) -> str | None:
    """把一行 t_document 解析为本机可用的绝对路径。

    依次尝试：原样 -> 相对 backend/ -> 上传约定 {UPLOAD_DIR}/{course_id}/{doc_id}_{文件名}
    -> 在上传目录内按「文档号_」前缀查找。全部落空时返回原值，由调用方决定如何报错。
    """
    raw = doc.get("file_path")
    if not raw:
        return None

    # 形态 2：相对路径一律相对 backend/ 起算，不依赖启动目录
    # （若反过来先按原样判断，「从 backend/ 启动」时会得到相对路径，换个启动目录就失效）
    if os.path.isabs(raw):
        if _exists(raw):
            return raw
    else:
        candidate = os.path.normpath(os.path.join(str(BASE_DIR), raw))
        if _exists(candidate):
            return candidate
        if _exists(raw):
            return raw

    doc_id = doc.get("doc_id")
    if doc_id is None:
        return raw

    # 上传约定：document_service 保存文件时用的就是 {UPLOAD_DIR}/{course_id}/{doc_id}_{文件名}
    course_id, file_name = doc.get("course_id"), doc.get("file_name")
    if course_id is not None and file_name:
        candidate = os.path.normpath(os.path.join(
            str(settings.UPLOAD_DIR), str(course_id), f"{doc_id}_{file_name}"))
        if _exists(candidate):
            return candidate

    # 课程目录名与记录里的 course_id 不一致时（如课程改号后目录未同步迁移），
    # 退回按文档号查找：文件名以「{doc_id}_」开头，可唯一定位该文档的文件
    try:
        hits = glob.glob(os.path.join(str(settings.UPLOAD_DIR), "*", f"{doc_id}_*"))
    except OSError:
        hits = []
    if hits:
        return sorted(hits)[0]

    return raw
