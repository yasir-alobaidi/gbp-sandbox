"""Notifications API v1.

Base URL (real): https://mybusinessnotifications.googleapis.com
Routes exposed here (single-host sandbox):
  GET   /v1/accounts/{account_id}/notificationSetting
  PATCH /v1/accounts/{account_id}/notificationSetting

Note: delivery is via Cloud Pub/Sub, not a direct webhook. The sandbox's
/admin/push endpoint simulates the Pub/Sub push envelope that Google would
deliver to your configured push endpoint.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.auth import require_auth
from app.deps import scenario_dep
from app.errors import v1_error
from app.state import ScenarioState

router = APIRouter()


def _quota_check(state: ScenarioState) -> Optional[JSONResponse]:
    if state.is_zero_quota:
        return v1_error(
            429,
            "Quota exceeded for quota metric "
            "'mybusinessnotifications.googleapis.com/default'.",
            "RESOURCE_EXHAUSTED",
        )
    return None


@router.get("/v1/accounts/{account_id}/notificationSetting")
async def get_notification_setting(
    account_id: str,
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
):
    if err := require_auth(request, "v1"):
        return err
    if err := _quota_check(state):
        return err

    setting = state.get_notification_setting(account_id)
    if setting is None:
        # If no setting is configured, return a default empty setting.
        return JSONResponse(
            {
                "name": f"accounts/{account_id}/notificationSetting",
                "pubsubTopic": "",
                "notificationTypes": [],
            }
        )
    return JSONResponse(setting)


@router.patch("/v1/accounts/{account_id}/notificationSetting")
async def patch_notification_setting(
    account_id: str,
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
):
    if err := require_auth(request, "v1"):
        return err
    if err := _quota_check(state):
        return err

    body = await request.json()
    existing = state.get_notification_setting(account_id) or {
        "name": f"accounts/{account_id}/notificationSetting",
        "pubsubTopic": "",
        "notificationTypes": [],
    }
    merged = {**existing, **body, "name": f"accounts/{account_id}/notificationSetting"}
    updated = state.put_notification_setting(account_id, merged)
    return JSONResponse(updated)
