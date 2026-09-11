"""
数据总览 API
"""
from fastapi import APIRouter, Depends

from ..core.dependencies import get_current_user
from ..core.permissions import Permissions
from ..core.response import success
from ..services.dashboard_service import DashboardService

router = APIRouter(prefix="/api/v1/dashboard", tags=["数据总览"])


@router.get("/stats")
async def get_stats(current_user: dict = Depends(get_current_user)):
    """数据总览统计（课程/用户/文档/知识点/关系，缺数据返回 0）。

    课程中心改造：课程与文档相关统计收敛到「当前用户可访问的课程」，
    避免教师的课程分布图里出现其他教师的课程；用户数等平台级指标保持全局。
    """
    allowed_ids = Permissions.allowed_course_ids(current_user)
    return success(DashboardService.get_stats(allowed_ids))
