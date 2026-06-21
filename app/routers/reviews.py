"""Reviews API — both v1 (mybusinessreviews.googleapis.com) and v4 legacy.

RepuHub uses the newer v1 path:
  Base URL: https://mybusinessreviews.googleapis.com
  GET    /v1/accounts/{account_id}/locations/{location_id}/reviews
  GET    /v1/accounts/{account_id}/locations/{location_id}/reviews/{review_id}
  PUT    /v1/accounts/{account_id}/locations/{location_id}/reviews/{review_id}/reply
  DELETE /v1/accounts/{account_id}/locations/{location_id}/reviews/{review_id}/reply

v4 routes are also kept for apps that haven't migrated yet:
  Base URL: https://mybusiness.googleapis.com
  GET/PUT/DELETE /v4/accounts/{account_id}/locations/{location_id}/reviews[/{id}[/reply]]

Key notes:
- starRating is a STRING enum ("ONE".."FIVE"), not an int.
- pageSize max is exactly 50 (enforced by the real API).
- reviews.list and reply both require a VERIFIED account (returns 403 otherwise).
- v1 uses the modern error envelope; v4 uses the legacy errors[] envelope.
- Reply writes persist in-memory; a subsequent GET reflects them.

Path collision note: /v1/accounts/{a}/locations/{l}/reviews does NOT conflict
with /v1/accounts/{a}/locations (Business Information list) because FastAPI
matches the more specific path first. Verified with the running server.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.auth import require_auth
from app.deps import scenario_dep
from app.errors import v1_error, v4_error
from app.state import ScenarioState

router = APIRouter()

_REVIEWS_PAGE_SIZE_MAX = 50
_REVIEWS_PAGE_SIZE_DEFAULT = 20


# ── Shared helpers ────────────────────────────────────────────────────────────

def _quota_check_v1(state: ScenarioState) -> Optional[JSONResponse]:
    if state.is_zero_quota:
        return v1_error(
            429,
            "Quota exceeded for quota metric 'mybusinessreviews.googleapis.com/default'.",
            "RESOURCE_EXHAUSTED",
            details=[{
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": "RATE_LIMIT_EXCEEDED",
                "domain": "googleapis.com",
                "metadata": {"quota_metric": "mybusinessreviews.googleapis.com/default"},
            }],
        )
    if state.is_rate_limited:
        state.track_request("reviews_v1")
        if state.get_request_count("reviews_v1") % 3 == 0:
            return v1_error(429, "Rate limit exceeded.", "RESOURCE_EXHAUSTED")
    return None


def _quota_check_v4(state: ScenarioState) -> Optional[JSONResponse]:
    if state.is_zero_quota:
        return v4_error(
            429,
            "Quota exceeded for quota metric 'mybusiness.googleapis.com/default'.",
            "quotaExceeded",
        )
    if state.is_rate_limited:
        state.track_request("reviews_v4")
        if state.get_request_count("reviews_v4") % 3 == 0:
            return v4_error(429, "Rate limit exceeded.", "rateLimitExceeded")
    return None


def _verify_check_v1(state: ScenarioState, account_id: str) -> Optional[JSONResponse]:
    if not state.account_is_verified(account_id):
        return v1_error(
            403,
            "This location is not verified. Reviews are only available for verified locations.",
            "PERMISSION_DENIED",
        )
    return None


def _verify_check_v4(state: ScenarioState, account_id: str) -> Optional[JSONResponse]:
    if not state.account_is_verified(account_id):
        return v4_error(
            403,
            "This location is not verified. Reviews are only available for verified locations.",
            "notVerified",
        )
    return None


def _reviews_response(state, account_id, location_id, page_size, page_token):
    page_size = min(max(1, page_size), _REVIEWS_PAGE_SIZE_MAX)
    page, avg, total, next_token = state.paginate_reviews(
        account_id, location_id, page_size, page_token
    )
    body: dict = {"reviews": page, "averageRating": avg, "totalReviewCount": total}
    if next_token:
        body["nextPageToken"] = next_token
    return JSONResponse(body)


# ── Reviews API v1 (mybusinessreviews.googleapis.com) — what RepuHub calls ───

@router.get("/v1/accounts/{account_id}/locations/{location_id}/reviews")
async def list_reviews_v1(
    account_id: str,
    location_id: str,
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
    page_size: int = Query(default=_REVIEWS_PAGE_SIZE_DEFAULT, alias="pageSize"),
    page_token: Optional[str] = Query(default=None, alias="pageToken"),
    order_by: Optional[str] = Query(default=None, alias="orderBy"),
):
    if err := require_auth(request, "v1"):
        return err
    if err := _quota_check_v1(state):
        return err
    if err := _verify_check_v1(state, account_id):
        return err
    return _reviews_response(state, account_id, location_id, page_size, page_token)


@router.get("/v1/accounts/{account_id}/locations/{location_id}/reviews/{review_id}")
async def get_review_v1(
    account_id: str,
    location_id: str,
    review_id: str,
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
):
    if err := require_auth(request, "v1"):
        return err
    if err := _quota_check_v1(state):
        return err
    if err := _verify_check_v1(state, account_id):
        return err
    review = state.get_review(account_id, location_id, review_id)
    if review is None:
        return v1_error(404, f"Review '{review_id}' not found.", "NOT_FOUND")
    return JSONResponse(review)


@router.put("/v1/accounts/{account_id}/locations/{location_id}/reviews/{review_id}/reply")
async def update_reply_v1(
    account_id: str,
    location_id: str,
    review_id: str,
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
):
    if err := require_auth(request, "v1"):
        return err
    if err := _quota_check_v1(state):
        return err
    if not state.account_is_verified(account_id):
        return v1_error(403, "Replies can only be posted for verified locations.", "PERMISSION_DENIED")

    review = state.get_review(account_id, location_id, review_id)
    if review is None:
        return v1_error(404, f"Review '{review_id}' not found.", "NOT_FOUND")

    body = await request.json()
    comment = body.get("comment", "")
    if not comment:
        return v1_error(400, "reply.comment is required.", "INVALID_ARGUMENT")

    reply = state.put_reply(review_id, comment)
    return JSONResponse(reply)


@router.delete("/v1/accounts/{account_id}/locations/{location_id}/reviews/{review_id}/reply")
async def delete_reply_v1(
    account_id: str,
    location_id: str,
    review_id: str,
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
):
    if err := require_auth(request, "v1"):
        return err
    if err := _quota_check_v1(state):
        return err
    if not state.account_is_verified(account_id):
        return v1_error(403, "Operation not permitted for unverified location.", "PERMISSION_DENIED")

    deleted = state.delete_reply(review_id)
    if not deleted:
        return v1_error(404, f"Reply for review '{review_id}' not found.", "NOT_FOUND")
    return JSONResponse({})


# ── Reviews API v4 (mybusiness.googleapis.com) — kept for legacy callers ─────

@router.get("/v4/accounts/{account_id}/locations/{location_id}/reviews")
async def list_reviews_v4(
    account_id: str,
    location_id: str,
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
    page_size: int = Query(default=_REVIEWS_PAGE_SIZE_DEFAULT, alias="pageSize"),
    page_token: Optional[str] = Query(default=None, alias="pageToken"),
    order_by: Optional[str] = Query(default=None, alias="orderBy"),
):
    if err := require_auth(request, "v4"):
        return err
    if err := _quota_check_v4(state):
        return err
    if err := _verify_check_v4(state, account_id):
        return err
    return _reviews_response(state, account_id, location_id, page_size, page_token)


@router.get("/v4/accounts/{account_id}/locations/{location_id}/reviews/{review_id}")
async def get_review_v4(
    account_id: str,
    location_id: str,
    review_id: str,
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
):
    if err := require_auth(request, "v4"):
        return err
    if err := _quota_check_v4(state):
        return err
    if err := _verify_check_v4(state, account_id):
        return err
    review = state.get_review(account_id, location_id, review_id)
    if review is None:
        return v4_error(404, f"Review '{review_id}' not found.", "notFound")
    return JSONResponse(review)


@router.put("/v4/accounts/{account_id}/locations/{location_id}/reviews/{review_id}/reply")
async def update_reply_v4(
    account_id: str,
    location_id: str,
    review_id: str,
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
):
    if err := require_auth(request, "v4"):
        return err
    if err := _quota_check_v4(state):
        return err
    if not state.account_is_verified(account_id):
        return v4_error(403, "Replies can only be posted for verified locations.", "notVerified")

    review = state.get_review(account_id, location_id, review_id)
    if review is None:
        return v4_error(404, f"Review '{review_id}' not found.", "notFound")

    body = await request.json()
    comment = body.get("comment", "")
    if not comment:
        return v4_error(400, "reply.comment is required.", "required")

    reply = state.put_reply(review_id, comment)
    return JSONResponse(reply)


@router.delete("/v4/accounts/{account_id}/locations/{location_id}/reviews/{review_id}/reply")
async def delete_reply_v4(
    account_id: str,
    location_id: str,
    review_id: str,
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
):
    if err := require_auth(request, "v4"):
        return err
    if err := _quota_check_v4(state):
        return err
    if not state.account_is_verified(account_id):
        return v4_error(403, "Operation not permitted for unverified location.", "notVerified")

    deleted = state.delete_reply(review_id)
    if not deleted:
        return v4_error(404, f"Reply for review '{review_id}' not found.", "notFound")
    return JSONResponse({})
