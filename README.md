# GBP Sandbox

A local mock server for the **Google Business Profile (GBP) APIs** — because Google doesn't provide one.

Google's only official testing option is a `validateOnly` flag on some write calls, and even that requires their manual API-access approval (which takes weeks). This sandbox fills the gap: run it locally, point your app at it, and develop your full GBP integration the same day.

---

## What you'll be able to test

- The full **OAuth 2.0 flow** (consent screen → code exchange → tokens)
- Listing **accounts and locations**
- Fetching, **paginating**, and replying to **reviews**
- Reading and writing **notification settings**
- Edge cases: rate limits, revoked tokens, unverified accounts, closed locations, service-area businesses, duplicate webhook delivery, and more

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/yasir-alobaidi/gbp-sandbox.git
cd gbp-sandbox

# 2. Start
docker compose up

# 3. Confirm it's running
curl http://localhost:8090/health
# → {"status":"ok","scenario":"default"}
```

Browse the interactive API docs at **http://localhost:8090/docs**

---

## Credentials to use

> The sandbox skips all real authentication. Use the values below everywhere your app asks for Google credentials.

### Google OAuth config (in your app's `.env`)

| Setting | Value to use |
|---|---|
| Client ID | `sandbox-client-id` _(any string works)_ |
| Client Secret | `sandbox-client-secret` _(any string works)_ |
| Auth URL | `http://localhost:8090/o/oauth2/v2/auth` |
| Token URL | `http://localhost:8090/token` |

### What happens when OAuth runs

When your app redirects to the Google consent screen, the sandbox **instantly auto-completes** it — no browser interaction needed. Your callback will receive a `mock_code_…` authorization code. Exchange it normally and you'll get back:

```json
{
  "access_token": "mock_access_a3f8c2d1...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "mock_refresh_b7e9a4c0...",
  "scope": "https://www.googleapis.com/auth/business.manage"
}
```

### Logged-in user identity

After OAuth your app may call the userinfo endpoint. It returns:

```json
{
  "email": "mock-user@sandbox.example.com",
  "name": "Mock GBP User",
  "verified_email": true
}
```

Use **`mock-user@sandbox.example.com`** as the connected Google account email anywhere your UI or database stores it.

### API calls (after OAuth)

Pass any Bearer token in your `Authorization` header — the value doesn't matter, presence does:

```bash
Authorization: Bearer mock_access_a3f8c2d1...
# or just:
Authorization: Bearer dev
```

Missing the header → `401`. Any value → accepted.

---

## Account and location IDs

Each scenario ships with fixed IDs. Here are the defaults:

| What | ID | Full resource name |
|---|---|---|
| Account | `100000001` | `accounts/100000001` |
| Location (primary) | `200000001` | `accounts/100000001/locations/200000001` |
| Location (secondary) | `200000002` | `accounts/100000001/locations/200000002` |
| Review | `rev001` | `accounts/100000001/locations/200000001/reviews/rev001` |

The `multi-account` scenario has three accounts:

| Account name | ID |
|---|---|
| Personal (no locations) | `100000001` |
| Meridian Retail Group | `100000002` |
| Crema Coffee Collective | `100000003` |

> **Tip:** Call `GET /v1/accounts` first in your integration flow — it returns the IDs from the active fixture so you never have to hard-code them.

---

## Wiring your app to the sandbox

Replace each hardcoded Google base URL in your app with an env-controlled setting, then point those settings here in dev:

```bash
# .env (dev only)
GOOGLE_OAUTH_TOKEN_URL=http://localhost:8090/token
GOOGLE_OAUTH_AUTH_URL=http://localhost:8090/o/oauth2/v2/auth
GOOGLE_ACCOUNT_MGMT_BASE_URL=http://localhost:8090
GOOGLE_BUSINESS_INFO_BASE_URL=http://localhost:8090
GOOGLE_MYBUSINESS_BASE_URL=http://localhost:8090
GOOGLE_NOTIFICATIONS_BASE_URL=http://localhost:8090
```

Add a guard so these URLs can never reach staging or production:

```python
# Django example
if ENVIRONMENT != "development":
    for key in GOOGLE_BASE_URLS:
        if "localhost" in getattr(settings, key, ""):
            raise ImproperlyConfigured(f"{key} points at localhost in non-dev!")
```

If your app runs inside Docker Compose, add the sandbox as a service:

```yaml
# docker-compose.dev.yml
services:
  gbp-mock:
    build: ./gbp-sandbox   # or image: gbp-sandbox
    ports:
      - "8090:8090"
    environment:
      SCENARIO: default
```

Then set `GOOGLE_*_BASE_URL=http://gbp-mock:8090` in your app's service env.

---

## Scenarios

Switch scenarios at startup with the `SCENARIO` env var, or per-request with the `X-Mock-Scenario` header (doesn't affect global state):

```bash
# Change startup scenario
SCENARIO=multi-location docker compose up

# Override for a single request only
curl -H "X-Mock-Scenario: zero-quota" \
     -H "Authorization: Bearer dev" \
     http://localhost:8090/v1/accounts
```

Switch globally at runtime (no restart needed):
```bash
curl -X POST http://localhost:8090/admin/scenario/unverified-account
```

---

### Scenario reference

#### 🏪 Business structure

| Scenario | Business | What it tests |
|---|---|---|
| `default` | Sakura Japanese Restaurant — 1 location, 20 reviews | Happy path: OWNER, VERIFIED, full hours, replies |
| `multi-location` | Harbor Fresh Seafood — 3 SF locations, 27 reviews | Plan limit enforcement, location selection cap |
| `multi-account` | 3 accounts (personal + 2 business groups), 14 reviews | Account-picker logic, cross-account review fetching |
| `empty-account` | Flour & Stone Bakery — 0 locations | "No locations to import" branch in onboarding |
| `many-locations` | VitaBlend Juice Bar — 12 Chicago branches, 30 reviews | `locations.list` pagination (default pageSize=10) |
| `manager-role` | Bright Smile Dental — MANAGER role, 2 locations, 15 reviews | Role-gating — not all users are PRIMARY_OWNER |
| `closed-location` | Pacific Grounds Coffee — OPEN + CLOSED_TEMPORARILY + CLOSED_PERMANENTLY | All 3 location statuses in one fixture |
| `service-area-business` | ProTrades (plumbing/HVAC/landscaping) — no `storefrontAddress` | Parser must not assume address fields exist |
| `already-claimed-location` | UrbanEdge Barbershop — 10 reviews | `select_for_update` concurrency guard on double-import |

#### ⭐ Reviews

| Scenario | Business | What it tests |
|---|---|---|
| `many-reviews` | Pinnacle Fitness — **150 auto-generated reviews** | Forces 3 pagination round-trips at `pageSize=50` |
| `rating-only-reviews` | NW Auto Detailing — 15 reviews, 7 with no `comment` | Parser must handle missing `comment` without crashing |
| `pre-existing-replies` | Grand Palms Hotel — 15 reviews, some already replied | Sync must not clobber existing owner replies |
| `rate-limited` | Nightfall Rooftop — 2 locations, 15 reviews | Every 3rd request returns 429; tests retry/backoff across pagination too |

#### 🔐 OAuth & token lifecycle

| Scenario | What it tests |
|---|---|
| `consent-denied` | `/auth` redirects with `error=access_denied` — OAuth callback must not crash |
| `refresh-revoked` | `POST /token` returns `invalid_grant` — must trigger re-auth, not silent retry |
| `zero-quota` | Every resource call returns `429 RESOURCE_EXHAUSTED` — mimics 0-QPM GCP project |

#### 📨 Webhook / Pub/Sub delivery

| Scenario | Trigger | What it tests |
|---|---|---|
| `duplicate-notification` | `POST /admin/push?duplicate=true` | At-least-once delivery — handler must be idempotent |
| `google-update-notification` | `POST /admin/push` with `notification_type=GOOGLE_UPDATE` | Handler must route on type, not assume every push is `NEW_REVIEW` |

---

## Sample API calls

All calls after OAuth use `Authorization: Bearer <any_value>`.

**List accounts**
```bash
curl -H "Authorization: Bearer dev" http://localhost:8090/v1/accounts
```

**List locations for an account**
```bash
curl -H "Authorization: Bearer dev" \
  http://localhost:8090/v1/accounts/100000001/locations
```

**List reviews (with pagination)**
```bash
curl -H "Authorization: Bearer dev" \
  "http://localhost:8090/v4/accounts/100000001/locations/200000001/reviews?pageSize=10"
```

**Reply to a review**
```bash
curl -X PUT \
  -H "Authorization: Bearer dev" \
  -H "Content-Type: application/json" \
  -d '{"comment": "Thank you for your feedback!"}' \
  http://localhost:8090/v4/accounts/100000001/locations/200000001/reviews/rev001/reply
```

**Delete a reply**
```bash
curl -X DELETE \
  -H "Authorization: Bearer dev" \
  http://localhost:8090/v4/accounts/100000001/locations/200000001/reviews/rev001/reply
```

**Get notification settings**
```bash
curl -H "Authorization: Bearer dev" \
  http://localhost:8090/v1/accounts/100000001/notificationSetting
```

**Fire a test webhook**
```bash
curl -X POST http://localhost:8090/admin/push \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "http://your-app:8000/api/v1/webhooks/gbp/",
    "notification_type": "NEW_REVIEW",
    "location_name": "accounts/100000001/locations/200000001",
    "review_id": "rev001"
  }'
```

**Fire it twice (idempotency test)**
```bash
curl -X POST http://localhost:8090/admin/push \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "http://your-app:8000/api/v1/webhooks/gbp/",
    "notification_type": "NEW_REVIEW",
    "location_name": "accounts/100000001/locations/200000001",
    "duplicate": true
  }'
```

---

## Admin endpoints

These only exist in the sandbox — not part of the real Google API.

| Endpoint | What it does |
|---|---|
| `GET /admin/scenarios` | List all available scenarios + show the active one |
| `POST /admin/scenario/{name}` | Switch the global scenario (no restart needed) |
| `GET /admin/state` | Dump current in-memory state (accounts, locations, reviews, replies) |
| `POST /admin/reset` | Reset to fixture baseline — clears replies, patches, request counters |
| `POST /admin/push` | Fire a simulated Pub/Sub push notification at your webhook URL |

---

## Things that will catch you out

These are the subtle GBP API behaviours the sandbox enforces — the real API does too.

**`starRating` is a string, not a number.**
The Reviews API returns `"ONE"`, `"TWO"`, `"THREE"`, `"FOUR"`, `"FIVE"` — not `1`–`5`. A parser that reads it as an integer will silently break.

**`locations.list` and `locations.get` have different path shapes.**
- List: `GET /v1/accounts/{accountId}/locations` ← scoped under an account
- Get: `GET /v1/locations/{locationId}` ← no account prefix

This is intentional in the v1 Business Information API and a common source of confusion.

**Error envelopes differ between v1 and v4 surfaces.**
- v1 (Accounts, Locations, Notifications): `{ "error": { "code", "message", "status" } }`
- v4 (Reviews): `{ "error": { "errors": [{ "domain", "reason", "message" }], "code", "message" } }`

**Reviews require a VERIFIED account.** The `unverified-account` scenario returns 403 on both `reviews.list` and `reviews.reply`.

**`pageSize` ceilings are enforced.**
- Locations: max 100, default 10
- Reviews: max **50**, default 20

**Pub/Sub is at-least-once delivery** — your webhook handler must be idempotent. Use the `duplicate-notification` scenario to test this.

---

## Adding your own fixture

1. Create `app/fixtures/{name}.json` following the shape of `default.json`
2. Switch to it: `curl -X POST http://localhost:8090/admin/scenario/{name}`

No restart needed if you're using the Docker volume mount.

To auto-generate a large number of reviews without writing them by hand:
```json
{
  "_auto_generate_reviews": {
    "account_id": "100000001",
    "location_id": "200000001",
    "count": 75
  }
}
```

---

## Endpoints mocked

| Real Google URL | Sandbox path |
|---|---|
| `oauth2.googleapis.com/token` | `POST /token` |
| `accounts.google.com/o/oauth2/v2/auth` | `GET /o/oauth2/v2/auth` |
| `googleapis.com/oauth2/v2/userinfo` | `GET /oauth2/v2/userinfo` |
| `mybusinessaccountmanagement…/v1/accounts` | `GET /v1/accounts` |
| `mybusinessaccountmanagement…/v1/accounts/{id}` | `GET /v1/accounts/{id}` |
| `mybusinessbusinessinformation…/v1/accounts/{id}/locations` | `GET /v1/accounts/{id}/locations` |
| `mybusinessbusinessinformation…/v1/locations/{id}` | `GET /v1/locations/{id}` · `PATCH /v1/locations/{id}` |
| `mybusiness…/v4/…/reviews` | `GET /v4/…/reviews` |
| `mybusiness…/v4/…/reviews/{r}` | `GET` · `PUT …/reply` · `DELETE …/reply` |
| `mybusinessnotifications…/v1/…/notificationSetting` | `GET` · `PATCH` |
| `mybusiness…/v4/…/reviews:watch` | `POST` (webhook channel registration) |

---

## Project layout

```
app/
  main.py               Entry point
  state.py              In-memory state + pagination helpers
  errors.py             v1 and v4 error envelope factories
  auth.py               Authorization header check
  deps.py               FastAPI dependency for scenario injection
  config.py             SCENARIO env var
  routers/
    oauth.py            /token · /o/oauth2/v2/auth · /oauth2/v2/userinfo
    accounts.py         /v1/accounts[/{id}]
    business_info.py    /v1/locations · /v1/accounts/{id}/locations
    reviews.py          /v4/…/reviews[/{id}[/reply]]
    notifications.py    /v1/accounts/{id}/notificationSetting
    admin.py            /admin/* controls
  fixtures/             One JSON file per scenario
```

---

## License

MIT
