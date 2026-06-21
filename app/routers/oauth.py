"""OAuth2 endpoints.

Mocks:
  POST /token                     — authorization_code and refresh_token grant types
  GET  /o/oauth2/v2/auth          — simulates Google's consent screen (instant redirect)
  GET  /oauth2/v2/userinfo        — returns mock user email + name (called in OAuth callback)
  POST /v4/accounts/{id}/locations/-/reviews:watch  — registers a channel push webhook
"""
import secrets
from typing import Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.state import get_scenario_for_request

router = APIRouter()


@router.post("/token")
async def token_exchange(
    request: Request,
    x_mock_scenario: Optional[str] = Header(None),
):
    state = get_scenario_for_request(x_mock_scenario)
    behavior = state.oauth_behavior
    form = await request.form()
    grant_type = form.get("grant_type", "")

    if behavior == "refresh-revoked" and grant_type == "refresh_token":
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_grant",
                "error_description": "Token has been expired or revoked.",
            },
        )

    if behavior == "zero-quota":
        # Token exchange itself succeeds — zero quota surfaces on resource API calls.
        pass

    if grant_type == "authorization_code":
        return JSONResponse(
            {
                "access_token": f"mock_access_{secrets.token_hex(16)}",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": f"mock_refresh_{secrets.token_hex(16)}",
                "scope": "https://www.googleapis.com/auth/business.manage",
            }
        )

    if grant_type == "refresh_token":
        return JSONResponse(
            {
                "access_token": f"mock_access_{secrets.token_hex(16)}",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/business.manage",
            }
        )

    return JSONResponse(
        status_code=400,
        content={"error": "unsupported_grant_type"},
    )


@router.get("/o/oauth2/v2/auth")
async def oauth_consent(
    redirect_uri: str,
    state: Optional[str] = None,
    client_id: Optional[str] = None,
    response_type: Optional[str] = None,
    scope: Optional[str] = None,
    x_mock_scenario: Optional[str] = Header(None),
):
    """Simulates Google's OAuth consent screen.

    - default / most scenarios: immediately redirects back with a mock code.
    - consent-denied scenario:  redirects back with error=access_denied.

    In a real integration, override the OAuth authorisation base URL to point
    at this mock so the full browser-redirect flow can be tested locally.
    """
    scenario_state = get_scenario_for_request(x_mock_scenario)
    behavior = scenario_state.oauth_behavior

    sep = "&" if "?" in redirect_uri else "?"
    if behavior == "consent-denied":
        url = f"{redirect_uri}{sep}error=access_denied"
        if state:
            url += f"&state={state}"
        return RedirectResponse(url=url)

    code = f"mock_code_{secrets.token_hex(16)}"
    url = f"{redirect_uri}{sep}code={code}"
    if state:
        url += f"&state={state}"
    return RedirectResponse(url=url)


@router.get("/oauth2/v2/userinfo")
async def userinfo(request: Request):
    """Google userinfo endpoint — called after OAuth to get the user's email.

    RepuHub uses this to populate account_email on the GoogleAccountConnection.
    Returns a fixed mock email; safe to override per-fixture if needed.
    """
    return JSONResponse(
        {
            "id": "mock_google_user_001",
            "email": "mock-user@sandbox.example.com",
            "verified_email": True,
            "name": "Mock GBP User",
            "given_name": "Mock",
            "family_name": "User",
            "picture": "https://example.com/photos/mock_user.jpg",
        }
    )


@router.post("/v4/accounts/{account_id}/locations/-/reviews:watch")
async def register_webhook_channel(
    account_id: str,
    request: Request,
    x_mock_scenario: Optional[str] = Header(None),
):
    """Simulates the Google Channel Notifications registration endpoint.

    Real URL: https://mybusiness.googleapis.com/v4/accounts/{id}/locations/-/reviews:watch

    RepuHub sends: { topic, type: "REST", address, id, token }
    Google responds with the created channel resource.

    The mock always succeeds. To exercise the /admin/push endpoint, use the
    channel id and token returned here as the X-Goog-Channel-Id / Token headers.
    """
    from app.auth import require_auth
    if err := require_auth(request, "v4"):
        return err

    body = await request.json()
    channel_id = body.get("id", f"repuhub-mock-{secrets.token_hex(4)}")
    channel_token = body.get("token", secrets.token_hex(16))

    return JSONResponse(
        {
            "kind": "api#channel",
            "id": channel_id,
            "resourceId": f"mock_resource_{secrets.token_hex(8)}",
            "resourceUri": f"https://mybusiness.googleapis.com/v4/accounts/{account_id}/locations/-/reviews",
            "token": channel_token,
            "expiration": "9999999999999",
        }
    )
