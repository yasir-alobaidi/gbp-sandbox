from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import SCENARIO
from app.state import load_scenario, get_state
from app.routers import oauth, accounts, business_info, reviews, notifications, admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_scenario(SCENARIO)
    yield


app = FastAPI(
    title="GBP Sandbox",
    description=(
        "Local mock server for Google Business Profile APIs.\n\n"
        "Covers OAuth2, Account Management API v1, Business Information API v1, "
        "Reviews API v4, and Notifications API v1 — with scenario-based testing, "
        "stateful reply persistence, error injection, and an on-demand Pub/Sub "
        "push trigger.\n\n"
        "Control the active scenario via the `SCENARIO` env var at startup, "
        "or override per-request with the `X-Mock-Scenario` header.\n\n"
        "Admin endpoints live under `/admin`."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(oauth.router, tags=["OAuth2"])
app.include_router(accounts.router, tags=["Account Management API v1"])
app.include_router(business_info.router, tags=["Business Information API v1"])
app.include_router(reviews.router, tags=["Reviews API v4"])
app.include_router(notifications.router, tags=["Notifications API v1"])
app.include_router(admin.router, prefix="/admin", tags=["Admin / Control"])


@app.get("/health", tags=["Health"])
def health():
    state = get_state()
    return {"status": "ok", "scenario": state.name}
