"""
教师端题库管理 API

- POST   /api/v1/questions                        新增题目
- GET    /api/v1/questions                        列表（分页 + 课程/文档/知识点/题型/关键词筛选）
- GET    /api/v1/questions/stats                  题库总览
- GET    /api/v1/questions/favorites              题目收藏情况（哪些学生收藏了哪道题）
- GET    /api/v1/questions/{question_id}          题目详情
- PUT    /api/v1/questions/{question_id}          修改题目（未传字段沿用原值）
- DELETE /api/v1/questions/{question_id}          删除题目（已作答过则软删停用）
- PATCH  /api/v1/questions/{question_id}/active   启用/停用

权限：接口层 require_teacher，service 层再做「课程归属校验」（越权 → code 4003）。
⚠ 路由顺序：/stats 与 /favorites 必须声明在 /{question_id} 之前，否则会被当成整数路径参数（422）。
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..core.dependencies import require_teacher
from ..core.response import success, error
from ..services.question_service import QuestionService

router = APIRouter(prefix="/api/v1/questions", tags=["题库管理"])


def _coerce_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _wrap(result: dict):
    """统一包装 service 结果（{ok, code, message, data} → {code,message,data,timestamp}）"""
    return success(result["data"]) if result["ok"] else error(result["code"], result["message"])


class QuestionCreate(BaseModel):
    course_id: str
    document_id: str | None = None
    kp_id: str | None = None
    q_type: str
    stem: str
    options: list = []
    answer: object = None          # 单选/判断为字符串；多选为数组
    analysis: str | None = None
    difficulty: int = 3


class QuestionUpdate(BaseModel):
    document_id: str | None = None
    kp_id: str | None = None
    q_type: str | None = None
    stem: str | None = None
    options: list | None = None
    answer: object = None
    analysis: str | None = None
    difficulty: int | None = None


class QuestionActive(BaseModel):
    is_active: bool = True


@router.post("")
async def create_question(body: QuestionCreate, current_user: dict = Depends(require_teacher)):
    """新增题目（course_id 必传；document_id 留空表示课程通用题）"""
    cid = _coerce_int(body.course_id)
    if cid is None:
        return error(4001, "参数错误：course_id 必须为整数")
    result = QuestionService.create_question(
        current_user["user_id"], cid, body.model_dump(),
    )
    return _wrap(result)


@router.get("")
async def list_questions(
    course_id: str = Query(..., description="课程 ID"),
    document_id: str = Query(None, description="文档 ID（可选，含课程通用题）"),
    kp_id: str = Query(None, description="关联知识点 ID（可选）"),
    q_type: str = Query(None, description="题型：SINGLE/MULTI/JUDGE"),
    keyword: str = Query(None, description="题干关键词"),
    is_active: bool = Query(None, description="启用状态筛选（不传=全部）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: dict = Depends(require_teacher),
):
    """题库列表（教师视角：含答案/解析/作答正确率/收藏数）"""
    cid = _coerce_int(course_id)
    if cid is None:
        return error(4001, "参数错误：course_id 必须为整数")
    result = QuestionService.list_questions(
        current_user["user_id"], cid, document_id=document_id, kp_id=kp_id,
        q_type=q_type, keyword=keyword, is_active=is_active,
        page=page, page_size=page_size,
    )
    return _wrap(result)


@router.get("/stats")
async def question_stats(course_id: str = Query(..., description="课程 ID"),
                         current_user: dict = Depends(require_teacher)):
    """题库总览：题量/启用停用/题型分布/作答总数/平均正确率/收藏总数"""
    cid = _coerce_int(course_id)
    if cid is None:
        return error(4001, "参数错误：course_id 必须为整数")
    return _wrap(QuestionService.stats(current_user["user_id"], cid))


@router.get("/favorites")
async def question_favorites(course_id: str = Query(..., description="课程 ID"),
                             question_id: str = Query(None, description="可选：只看某题"),
                             current_user: dict = Depends(require_teacher)):
    """题目收藏情况：哪些学生收藏了哪道题"""
    cid = _coerce_int(course_id)
    if cid is None:
        return error(4001, "参数错误：course_id 必须为整数")
    qid = _coerce_int(question_id) if question_id not in (None, "") else None
    return _wrap(QuestionService.favorites(current_user["user_id"], cid, qid))


@router.get("/{question_id}")
async def get_question(question_id: int, current_user: dict = Depends(require_teacher)):
    """题目详情（教师视角）"""
    return _wrap(QuestionService.get_question(current_user["user_id"], question_id))


@router.put("/{question_id}")
async def update_question(question_id: int, body: QuestionUpdate,
                          current_user: dict = Depends(require_teacher)):
    """修改题目（exclude_unset：未传字段沿用原值；显式传 document_id=null 改为课程通用题）"""
    payload = body.model_dump(exclude_unset=True)
    return _wrap(QuestionService.update_question(current_user["user_id"], question_id, payload))


@router.delete("/{question_id}")
async def delete_question(question_id: int, current_user: dict = Depends(require_teacher)):
    """删除题目（已被学生作答过的题目只做软删停用，保护答题记录）"""
    return _wrap(QuestionService.delete_question(current_user["user_id"], question_id))


@router.patch("/{question_id}/active")
async def set_question_active(question_id: int, body: QuestionActive,
                              current_user: dict = Depends(require_teacher)):
    """启用/停用题目（停用 = 移出出题池，不影响历史答题记录）"""
    return _wrap(QuestionService.set_active(current_user["user_id"], question_id, body.is_active))
