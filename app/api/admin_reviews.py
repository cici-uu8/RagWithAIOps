"""Admin API for Enterprise 2.0 F6 human reviews."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.enterprise.admin.models import success_payload
from app.enterprise.admin.routes import require_admin_user
from app.enterprise.auth.models import UserProfile
from app.enterprise.context import RequestContext, get_current_request_context
from app.enterprise.reviews.models import HumanReviewDecision
from app.enterprise.reviews.service import HumanReviewError, human_review_service

router = APIRouter(prefix="/admin/reviews", tags=["企业人工审批"])


AdminUser = Annotated[UserProfile, Depends(require_admin_user)]


def _require_context() -> RequestContext:
    context = get_current_request_context()
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="RequestContext is missing",
        )
    return context


def _not_found(exc: HumanReviewError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/pending")
async def list_pending_reviews(_admin: AdminUser):
    reviews = [review.model_dump(mode="json") for review in human_review_service.list_pending()]
    return success_payload({"reviews": reviews})


@router.post("/{review_id}/approve")
async def approve_review(
    review_id: str,
    request: HumanReviewDecision,
    _admin: AdminUser,
):
    context = _require_context()
    try:
        review = human_review_service.approve(
            context,
            review_id=review_id,
            reason=request.reason,
        )
    except HumanReviewError as exc:
        raise _not_found(exc) from exc
    return success_payload({"review": review.model_dump(mode="json")})


@router.post("/{review_id}/reject")
async def reject_review(
    review_id: str,
    request: HumanReviewDecision,
    _admin: AdminUser,
):
    context = _require_context()
    try:
        review = human_review_service.reject(
            context,
            review_id=review_id,
            reason=request.reason,
        )
    except HumanReviewError as exc:
        raise _not_found(exc) from exc
    return success_payload({"review": review.model_dump(mode="json")})
