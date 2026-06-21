"""Admin / control endpoints (not part of the real Google API).

  POST /admin/reset               — reset state to fixture baseline
  POST /admin/push                — fire a fake Pub/Sub push to a target URL
  POST /admin/scenario/{name}     — switch the global scenario at runtime
  GET  /admin/scenarios           — list all available scenarios
  GET  /admin/state               — inspect current in-memory state (accounts, locations, reviews)
"""
import base64
import json
import secrets
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.state import get_state, list_scenarios, load_scenario

router = APIRouter()


def _now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@router.post("/reset")
def reset_state():
    """Reset the active scenario back to its fixture baseline.

    Clears all persisted replies, patched locations, and request counters.
    """
    get_state().reset()
    return {"ok": True, "scenario": get_state().name}


@router.post("/scenario/{name}")
def switch_scenario(name: str):
    """Switch the global scenario at runtime without restarting the container."""
    available = list_scenarios()
    if name not in available:
        return JSONResponse(
            status_code=404,
            content={
                "error": f"Unknown scenario '{name}'.",
                "available": available,
            },
        )
    load_scenario(name)
    return {"ok": True, "scenario": name}


@router.get("/scenarios")
def get_scenarios():
    """List all available scenarios."""
    state = get_state()
    return {"active": state.name, "available": list_scenarios()}


@router.get("/state")
def get_current_state():
    """Dump the current in-memory state (useful for debugging)."""
    state = get_state()
    return JSONResponse(
        {
            "scenario": state.name,
            "accounts": state.accounts,
            "locations": {
                acc["name"].split("/")[-1]: state.get_locations(
                    acc["name"].split("/")[-1]
                )
                for acc in state.accounts
            },
            "reviews": {
                loc["name"].split("/")[-1]: state.get_reviews(
                    acc["name"].split("/")[-1],
                    loc["name"].split("/")[-1],
                )
                for acc in state.accounts
                for loc in state.get_locations(acc["name"].split("/")[-1])
            },
        }
    )


@router.post("/push")
async def send_push(
    target_url: str = Body(..., description="URL of your app's webhook endpoint — e.g. http://web:8000/api/v1/integrations/google/webhook/push/"),
    channel_id: str = Body(default="repuhub-1-sandbox_tenant", description="Mirrors the channel id your app registered. Format: repuhub-{account_pk}-{schema_name}"),
    channel_token: str = Body(default="", description="Leave empty unless your app checks X-Goog-Channel-Token HMAC. If GOOGLE_WEBHOOK_SECRET is unset in your app, empty is fine."),
    resource_state: str = Body(default="exists", description="X-Goog-Resource-State header value: 'sync' (verification ping), 'exists' (review change), 'not_exists' (deleted)"),
    resource_id: str = Body(default="mock_resource_001", description="X-Goog-Resource-Id header — arbitrary string identifying the watched resource"),
    duplicate: bool = Body(default=False, description="Send the identical request twice — tests at-least-once idempotency in your Celery task"),
):
    """Fire a simulated Google Channel Notification at your app's webhook URL.

    RepuHub uses Google API Channel Notifications (via reviews:watch), NOT
    Cloud Pub/Sub. Google delivers these as an HTTP POST with X-Goog-* headers
    and a minimal body — the real information is in the channel_id header which
    encodes the schema_name your app registered.

    RepuHub's handler (GooglePushNotificationView) parses:
      X-Goog-Channel-Id    → splits as 'repuhub-{pk}-{schema_name}'
      X-Goog-Resource-State → if 'sync', just returns 200 (verification ping)
      X-Goog-Channel-Token  → HMAC check (only if GOOGLE_WEBHOOK_SECRET is set)

    For the duplicate-notification idempotency test, use duplicate=true. This
    sends the exact same request twice with the same headers — your Celery task
    must deduplicate (e.g. via an idempotency key + Redis lock).
    """
    headers = {
        "X-Goog-Channel-Id": channel_id,
        "X-Goog-Resource-State": resource_state,
        "X-Goog-Resource-Id": resource_id,
        "X-Goog-Message-Number": str(int(time.time())),
        "Content-Type": "application/json",
    }
    if channel_token:
        headers["X-Goog-Channel-Token"] = channel_token

    body = json.dumps({"resourceState": resource_state, "resourceId": resource_id})

    results = []
    sends = 2 if duplicate else 1
    async with httpx.AsyncClient(timeout=10.0) as client:
        for i in range(sends):
            try:
                resp = await client.post(target_url, content=body, headers=headers)
                results.append(
                    {"attempt": i + 1, "status": resp.status_code, "body": resp.text[:500]}
                )
            except httpx.RequestError as exc:
                results.append({"attempt": i + 1, "error": str(exc)})

    return {
        "ok": True,
        "channel_id": channel_id,
        "resource_state": resource_state,
        "headers_sent": headers,
        "results": results,
    }


@router.post("/push-pubsub")
async def send_pubsub_push(
    target_url: str = Body(..., description="URL of a Pub/Sub-style webhook endpoint"),
    notification_type: str = Body(default="NEW_REVIEW"),
    location_name: Optional[str] = Body(default=None),
    review_id: Optional[str] = Body(default=None),
    duplicate: bool = Body(default=False),
):
    """Fire a Cloud Pub/Sub-style push envelope (for apps using Pub/Sub delivery).

    RepuHub uses Channel Notifications (POST /admin/push above), not Pub/Sub.
    This endpoint is here for other apps that opted into Pub/Sub delivery via
    the Notifications API (mybusinessnotifications.googleapis.com).

    Pub/Sub envelope wraps the payload in message.data as base64-encoded JSON.
    """
    state = get_state()
    if location_name is None:
        for acc in state.accounts:
            acc_id = acc["name"].split("/")[-1]
            locs = state.get_locations(acc_id)
            if locs:
                location_name = f"accounts/{acc_id}/locations/{locs[0]['name'].split('/')[-1]}"
                break
        location_name = location_name or "accounts/unknown/locations/unknown"

    inner: dict = {"notificationType": notification_type, "locationName": location_name}
    if review_id and notification_type in ("NEW_REVIEW", "UPDATED_REVIEW"):
        inner["reviewId"] = review_id

    data_b64 = base64.b64encode(json.dumps(inner).encode()).decode()
    message_id = f"mock-msg-{secrets.token_hex(8)}"
    envelope = {
        "message": {
            "data": data_b64,
            "messageId": message_id,
            "publishTime": _now_rfc3339(),
            "attributes": {},
        },
        "subscription": "projects/mock-project/subscriptions/gbp-sandbox-sub",
    }

    results = []
    sends = 2 if duplicate else 1
    async with httpx.AsyncClient(timeout=10.0) as client:
        for i in range(sends):
            try:
                resp = await client.post(target_url, json=envelope)
                results.append({"attempt": i + 1, "status": resp.status_code, "body": resp.text[:500]})
            except httpx.RequestError as exc:
                results.append({"attempt": i + 1, "error": str(exc)})

    return {
        "ok": True,
        "message_id": message_id,
        "notification_type": notification_type,
        "envelope_data_decoded": inner,
        "results": results,
    }
