"""
学生端做题练习 API

- GET    /api/v1/practice/questions              出题（**不含答案**，提交后才下发）
- POST   /api/v1/practice/submit                 提交作答（服务端判分 + 落答题记录）
- GET    /api/v1/practice/records                我的答题记录（only_wrong=true 即错题原始记录）
- GET    /api/v1/practice/wrong-book             错题本（每题最近一次错误 + 关联知识点）
- GET    /api/v1/practice/stats                  我的练习统计
- GET    /api/v1/practice/favorites              我的题目收藏
- POST   /api/v1/practice/favorites              收藏题目
- DELETE /api/v1/practice/favorites/{question_id} 取消收藏

防泄题：出题与收藏列表均走 service 的 _public_view 白名单投影，响应中不含 answer/analysis。
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..core.dependencies import get_current_user
from ..core.response import success, error
from ..services.question_service import PracticeService

router = APIRouter(prefix="/api/v1/practice", tags=["做题练习"])


def _coerce_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _wrap(result: dict):
    return success(result["data"]) if result["ok"] else error(result["code"], result["message"])


class SubmitRequest(BaseModel):
    question_id: int
    user_answer: object = None     # 单选/判断：字符串；多选：数组；未作答可传 null


class QuestionFavoriteRequest(BaseModel):
    course_id: str
    question_id: int


@router.get("/questions")
async def practice_questions(
    course_id: str = Query(..., description="课程 ID"),
    document_id: str = Query(None, description="文档 ID（可选；含课程通用题）"),
    kp_id: str = Query(None, description="指定知识点出题（可选，配合学习路径推荐）"),
    q_type: str = Query(None, description="题型：SINGLE/MULTI/JUDGE"),
    count: int = Query(10, ge=1, le=50, description="出题数量"),
    current_user: dict = Depends(get_current_user),
):
    """出题：随机取启用题目，返回题面与选项（不含答案与解析）"""
    cid = _coerce_int(course_id)
    if cid is None:
        return error(4001, "参数错误：course_id 必须为整数")
    return _wrap(PracticeService.get_questions(
        current_user["user_id"], cid, document_id=document_id,
        kp_id=kp_id, q_type=q_type, count=count,
    ))


@router.post("/submit")
async def submit_answer(body: SubmitRequest, current_user: dict = Depends(get_current_user)):
    """提交作答：自动判分并落库，返回正确答案与解析"""
    return _wrap(PracticeService.submit(
        current_user["user_id"], body.question_id, body.user_answer,
    ))


@router.get("/records")
async def answer_records(
    course_id: str = Query(None, description="课程 ID（可选）"),
    document_id: str = Query(None, description="文档 ID（可选）"),
    only_wrong: bool = Query(False, description="仅返回答错的记录"),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """我的答题记录（时间倒序）"""
    cid = _coerce_int(course_id) if course_id not in (None, "") else None
    if course_id not in (None, "") and cid is None:
        return error(4001, "参数错误：course_id 必须为整数")
    return _wrap(PracticeService.records(
        current_user["user_id"], course_id=cid, document_id=document_id,
        only_wrong=only_wrong, limit=limit,
    ))


@router.get("/wrong-book")
async def wrong_book(course_id: str = Query(..., description="课程 ID"),
                     document_id: str = Query(None, description="文档 ID（可选）"),
                     current_user: dict = Depends(get_current_user)):
    """错题本：按题取最近一次答错，附关联知识点名称"""
    cid = _coerce_int(course_id)
    if cid is None:
        return error(4001, "参数错误：course_id 必须为整数")
    return _wrap(PracticeService.wrong_book(
        current_user["user_id"], cid, document_id=document_id,
    ))


@router.get("/stats")
async def practice_stats(course_id: str = Query(..., description="课程 ID"),
                         document_id: str = Query(None, description="文档 ID（可选）"),
                         current_user: dict = Depends(get_current_user)):
    """我的练习统计：累计作答/正确率/错题数/收藏数"""
    cid = _coerce_int(course_id)
    if cid is None:
        return error(4001, "参数错误：course_id 必须为整数")
    return _wrap(PracticeService.stats(
        current_user["user_id"], cid, document_id=document_id,
    ))


@router.get("/favorites")
async def list_favorites(course_id: str = Query(..., description="课程 ID"),
                         current_user: dict = Depends(get_current_user)):
    """我的题目收藏"""
    cid = _coerce_int(course_id)
    if cid is None:
        return error(4001, "参数错误：course_id 必须为整数")
    return _wrap(PracticeService.list_favorites(current_user["user_id"], cid))


@router.post("/favorites")
async def add_favorite(body: QuestionFavoriteRequest,
                       current_user: dict = Depends(get_current_user)):
    """收藏题目（幂等）"""
    cid = _coerce_int(body.course_id)
    if cid is None:
        return error(4001, "参数错误：course_id 必须为整数")
    return _wrap(PracticeService.favorite(
        current_user["user_id"], cid, body.question_id,
    ))


@router.delete("/favorites/{question_id}")
async def remove_favorite(question_id: int,
                          course_id: str = Query(..., description="课程 ID"),
                          current_user: dict = Depends(get_current_user)):
    """取消题目收藏"""
    cid = _coerce_int(course_id)
    if cid is None:
        return error(4001, "参数错误：course_id 必须为整数")
    return _wrap(PracticeService.unfavorite(current_user["user_id"], cid, question_id))
