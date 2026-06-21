"""Account Management API v1.

Base URL (real): https://mybusinessaccountmanagement.googleapis.com
Routes exposed here (single-host sandbox):
  GET  /v1/accounts             — accounts.list
  GET  /v1/accounts/{account_id} — accounts.get
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
            "'mybusinessaccountmanagement.googleapis.com/default'.",
            "RESOURCE_EXHAUSTED",
            details=[
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": "RATE_LIMIT_EXCEEDED",
                    "domain": "googleapis.com",
                    "metadata": {
                        "quota_metric": "mybusinessaccountmanagement.googleapis.com/default"
                    },
                }
            ],
        )
    if state.is_rate_limited:
        state.track_request("accounts")
        if state.get_request_count("accounts") % 3 == 0:
            return v1_error(429, "Rate limit exceeded.", "RESOURCE_EXHAUSTED")
    return None


@router.get("/v1/accounts")
async def list_accounts(
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
):
    if err := require_auth(request, "v1"):
        return err
    if err := _quota_check(state):
        return err
    return JSONResponse({"accounts": state.accounts})


@router.get("/v1/accounts/{account_id}")
async def get_account(
    account_id: str,
    request: Request,
    state: ScenarioState = Depends(scenario_dep),
):
    if err := require_auth(request, "v1"):
        return err
    if err := _quota_check(state):
        return err
    account = state.get_account(account_id)
    if account is None:
        return v1_error(
            404, f"Account 'accounts/{account_id}' not found.", "NOT_FOUND"
        )
    return JSONResponse(account)
