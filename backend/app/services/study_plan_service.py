from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.common.response import PageResponse
from app.config import STUDY_PLAN_MAX_LENGTH
from app.models.study_plan import StudyPlan
from app.models.user import User
from app.schemas.study_plan import StudyPlanCreateRequest, StudyPlanResponse


def list_page_plans(
    db: Session, current_user: User, page: int = 1, page_size: int = 10
) -> PageResponse:
    """查询学习计划分页列表"""
    query = db.query(StudyPlan).filter(StudyPlan.user_id == current_user.id)
    total = query.count()
    rows = (
        query.order_by(StudyPlan.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PageResponse(
        list=[StudyPlanResponse.model_validate(row) for row in rows], total=total
    )


def create_study_plan(
    db: Session, current_user: User, data: StudyPlanCreateRequest
) -> StudyPlanResponse:
    """创建学习计划"""
    if not data.content:
        raise BusinessException(message="计划内容不能为空")
    if len(data.content) > STUDY_PLAN_MAX_LENGTH:
        raise BusinessException(message=f"计划内容不能超过{STUDY_PLAN_MAX_LENGTH}字")
    row = StudyPlan(user_id=current_user.id, content=data.content)
    db.add(row)
    db.commit()
    db.refresh(row)
    return StudyPlanResponse.model_validate(row)


def delete_study_plan(db: Session, current_user: User, plan_id: int) -> None:
    """删除本人的学习计划"""
    row = (
        db.query(StudyPlan)
        .filter(StudyPlan.id == plan_id, StudyPlan.user_id == current_user.id)
        .first()
    )
    if not row:
        raise BusinessException(message="学习计划不存在")
    db.delete(row)
    db.commit()
