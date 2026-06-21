"""Business Information API v1.

Base URL (real): https://mybusinessbusinessinformation.googleapis.com
Routes exposed here (single-host sandbox):
  GET   /v1/accounts/{account_id}/locations   — locations.list  (account-scoped)
  GET   /v1/locations/{location_id}           — locations.get   (bare path, no account prefix)
  PATCH /v1/locations/{location_id}           — locations.patch

Note the intentional asymmetry: list is account-scoped, get/patch are bare.
This matches the live API (v1 changed get/patch to drop the account prefix
while list remained account-scoped). Don't conflate the two.

readMask is required on all three by the real API. The mock accepts it but
returns all fields regardless — log a warning if it's missing so the caller
knows their code would fail against the real API.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.auth import require_auth
from app.deps import scenario_dep
from app.errors import v1_error
from app.state import ScenarioState

router = APIRouter()

# Maximum locations per page (real API cap is 100).
_LOCATIONS_PAGE_SIZE_MAX = 100
_LOCATIONS_PAGE_SIZE_DEFAULT = 10


def _quota_check(state: ScenarioState) -> Optional[JSONResponse]:
    if state.is_zero_quota:
        return v1_error(
            429,
            "Quota exceeded for quota metric "
            "'mybusinessbusinessinformation.googleapis.com/default'.",
            "RESOURCE_EXHAUSTED",
            details=[
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": "RATE_LIMIT_EXCEEDED",
                    "domain": "googleapis.com",
                    "metadata": {
                        "quota_metric": "mybusinessbusinessinformation.googleapis.com/default",
                        "quota_limit": "300",
                    },
                }
            ],
        )
    if state.is_rate_limited:
        state.track_request("business_info")
        if state.get_request_count("business_info") % 3 == 0:
            return v1_error(429, "Rate limit exceeded.", "RESOURCE_EXHAUSTED")
    return None


@router.get("/v1/accounts/{account_id}/locations")
async def list_locations(
    account_id: str,
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
    page_size: int = Query(default=_LOCATIONS_PAGE_SIZE_DEFAULT, alias="pageSize"),
    page_token: Optional[str] = Query(default=None, alias="pageToken"),
    read_mask: Optional[str] = Query(default=None, alias="readMask"),
):
    if err := require_auth(request, "v1"):
        return err
    if err := _quota_check(state):
        return err

    page_size = min(max(1, page_size), _LOCATIONS_PAGE_SIZE_MAX)
    page, next_token = state.paginate_locations(account_id, page_size, page_token)

    body: dict = {"locations": page}
    if next_token:
        body["nextPageToken"] = next_token
    return JSONResponse(body)


@router.get("/v1/locations/{location_id}")
async def get_location(
    location_id: str,
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
    read_mask: Optional[str] = Query(default=None, alias="readMask"),
):
    if err := require_auth(request, "v1"):
        return err
    if err := _quota_check(state):
        return err

    loc = state.get_location(location_id)
    if loc is None:
        return v1_error(
            404, f"Location 'locations/{location_id}' not found.", "NOT_FOUND"
        )
    return JSONResponse(loc)


@router.patch("/v1/locations/{location_id}")
async def patch_location(
    location_id: str,
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
    update_mask: Optional[str] = Query(default=None, alias="updateMask"),
):
    if err := require_auth(request, "v1"):
        return err
    if err := _quota_check(state):
        return err

    # Rate limit: max 10 edits/min per location (real API constraint).
    key = f"location_edits:{location_id}"
    count = state.track_request(key)
    if state.is_rate_limited and count > 10:
        return v1_error(
            429,
            "Quota exceeded: maximum 10 edits per minute per location.",
            "RESOURCE_EXHAUSTED",
        )

    body = await request.json()
    updated = state.patch_location(location_id, body)
    if updated is None:
        return v1_error(
            404, f"Location 'locations/{location_id}' not found.", "NOT_FOUND"
        )
    return JSONResponse(updated)
