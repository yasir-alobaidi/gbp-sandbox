# GBP Sandbox

A self-contained local mock server for the **Google Business Profile (GBP) APIs**.

Google does not offer a sandbox for Business Profile APIs — only a `validateOnly`
flag on some write calls, which still requires approved API access. This project
fills that gap so you can develop and test the full GBP integration locally,
without waiting for Google's manual API-access approval.

---

## What it mocks

| Real Google endpoint | Mocked at |
|---|---|
| `https://oauth2.googleapis.com/token` | `POST /token` |
| `https://accounts.google.com/o/oauth2/v2/auth` | `GET /o/oauth2/v2/auth` |
| `https://mybusinessaccountmanagement.googleapis.com/v1/accounts` | `GET /v1/accounts` |
| `https://mybusinessaccountmanagement.googleapis.com/v1/accounts/{id}` | `GET /v1/accounts/{id}` |
| `https://mybusinessbusinessinformation.googleapis.com/v1/accounts/{id}/locations` | `GET /v1/accounts/{id}/locations` |
| `https://mybusinessbusinessinformation.googleapis.com/v1/locations/{id}` | `GET /v1/locations/{id}` · `PATCH /v1/locations/{id}` |
| `https://mybusiness.googleapis.com/v4/accounts/{a}/locations/{l}/reviews` | `GET /v4/accounts/{a}/locations/{l}/reviews` |
| `https://mybusiness.googleapis.com/v4/.../reviews/{r}` | `GET`, `PUT .../reply`, `DELETE .../reply` |
| `https://mybusinessnotifications.googleapis.com/v1/accounts/{id}/notificationSetting` | `GET`, `PATCH` |

All responses match the real API field-for-field (v1 vs v4 error envelopes,
`starRating` as a string enum `"ONE"–"FIVE"`, pagination tokens, etc.).

An extra `/admin` namespace provides test controls not present in the real API.

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/your-org/gbp-sandbox.git
cd gbp-sandbox

# 2. Copy env (optional — defaults work out of the box)
cp .env.example .env

# 3. Start
docker compose up

# 4. Verify
curl http://localhost:8090/health
# {"status":"ok","scenario":"default"}
```

The mock is now reachable at `http://localhost:8090`.

Interactive API docs: `http://localhost:8090/docs`

---

## Wiring your app to use the sandbox

Replace each hardcoded Google base URL in your app with an env-controlled setting,
then point those settings at the sandbox in your dev environment:

```bash
# .env (dev only)
GOOGLE_OAUTH_TOKEN_URL=http://localhost:8090/token
GOOGLE_OAUTH_AUTH_URL=http://localhost:8090/o/oauth2/v2/auth
GOOGLE_ACCOUNT_MGMT_BASE_URL=http://localhost:8090
GOOGLE_BUSINESS_INFO_BASE_URL=http://localhost:8090
GOOGLE_MYBUSINESS_BASE_URL=http://localhost:8090
GOOGLE_NOTIFICATIONS_BASE_URL=http://localhost:8090
```

Add a startup guard in your app so these overrides are structurally impossible to
reach staging or production:

```python
# Django example
if ENVIRONMENT != "development":
    for key in GOOGLE_BASE_URLS:
        if "localhost" in getattr(settings, key, ""):
            raise ImproperlyConfigured(f"{key} points at localhost in non-dev environment")
```

If your app runs inside Docker Compose, add the sandbox as a service and use the
service name as the host:

```yaml
# your docker-compose.dev.yml
services:
  gbp-mock:
    image: gbp-sandbox        # or build: ./path/to/gbp-sandbox
    ports:
      - "8090:8090"
    environment:
      SCENARIO: default
```

Then set `GOOGLE_*_BASE_URL=http://gbp-mock:8090` in your app's env.

---

## Scenarios

Switch the active scenario via the `SCENARIO` env var at startup, or switch
any single request by adding the `X-Mock-Scenario: <name>` header.

```bash
# Startup scenario
SCENARIO=multi-location docker compose up

# Per-request override (doesn't affect global state)
curl -H "X-Mock-Scenario: zero-quota" -H "Authorization: Bearer t" \
  http://localhost:8090/v1/accounts
```

### Account / location shape

| Scenario | What it tests |
|---|---|
| `default` | 1 location, OWNER, VERIFIED — the happy path |
| `multi-location` | 3 locations — plan limit enforcement and Google-import bypass |
| `multi-account` | 2 accounts (PERSONAL + LOCATION_GROUP) — account-picker logic |
| `empty-account` | 0 locations — "no locations to import" branch |
| `many-locations` | 12 locations — forces `locations.list` pagination (default pageSize=10) |
| `manager-role` | Account `role: MANAGER` — role-gating in the consuming app |
| `unverified-account` | `verificationState: UNVERIFIED` — `reviews.list` and `reply` both 403 |
| `closed-location` | One `OPEN` + one `CLOSED_PERMANENTLY` — import/sync status handling |
| `service-area-business` | No `storefrontAddress`, only `regionCode` — parser mustn't assume address |
| `already-claimed-location` | Same location available for two concurrent imports — exercises `select_for_update` |

### Reviews

| Scenario | What it tests |
|---|---|
| `many-reviews` | 55 auto-generated reviews — requires two pages at `pageSize=50` |
| `rating-only-reviews` | Reviews with `starRating` but no `comment` — parser must not assume comment |
| `pre-existing-replies` | Some reviews already have a `reviewReply` — sync must not clobber them |
| `rate-limited` | Every 3rd request returns 429 — retry / backoff logic |

### OAuth / token lifecycle

| Scenario | What it tests |
|---|---|
| `consent-denied` | `GET /o/oauth2/v2/auth` redirects with `error=access_denied` — OAuth callback must not crash |
| `refresh-revoked` | `POST /token` with `grant_type=refresh_token` returns `invalid_grant` — must trigger re-auth, not silent retry |
| `zero-quota` | Every resource API call returns `429 RESOURCE_EXHAUSTED` — mimics a GCP project with 0-QPM quota (not yet approved) |

### Pub/Sub delivery

| Scenario | Trigger via |
|---|---|
| `duplicate-notification` | `POST /admin/push?duplicate=true` — tests at-least-once idempotency |
| `google-update-notification` | `POST /admin/push` with `notification_type=GOOGLE_UPDATE` — handler must not assume every push is `NEW_REVIEW` |

---

## Admin endpoints

All live under `/admin` and are **only** present in this sandbox — not part of the real Google API.

### `POST /admin/reset`
Resets the active scenario to its fixture baseline. Clears persisted replies,
patched locations, and request counters.

```bash
curl -X POST http://localhost:8090/admin/reset
```

### `POST /admin/scenario/{name}`
Switches the global scenario at runtime without restarting the container.

```bash
curl -X POST http://localhost:8090/admin/scenario/unverified-account
```

### `GET /admin/scenarios`
Lists all available scenarios and shows the currently active one.

### `GET /admin/state`
Dumps the current in-memory state — accounts, locations, reviews.

### `POST /admin/push`
Fires a simulated Cloud Pub/Sub push notification at a target URL.

Google does **not** POST a plain JSON body — it wraps the notification in a
Pub/Sub envelope where `message.data` is **base64-encoded**. This endpoint
constructs that exact envelope so your handler's unwrapping logic is exercised,
not bypassed.

```bash
curl -X POST http://localhost:8090/admin/push \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "http://your-app:8000/api/v1/integrations/google/webhook/push/",
    "notification_type": "NEW_REVIEW",
    "location_name": "accounts/100000001/locations/200000001",
    "review_id": "rev001"
  }'
```

Add `"duplicate": true` to send the same `messageId` twice — tests that your
Celery task doesn't double-process:

```bash
curl -X POST http://localhost:8090/admin/push \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "http://your-app:8000/api/v1/integrations/google/webhook/push/",
    "notification_type": "NEW_REVIEW",
    "location_name": "accounts/100000001/locations/200000001",
    "duplicate": true
  }'
```

The Pub/Sub envelope format (for reference):

```json
{
  "message": {
    "data": "<base64-encoded JSON>",
    "messageId": "mock-msg-abc123",
    "publishTime": "2026-06-21T10:00:00Z",
    "attributes": {}
  },
  "subscription": "projects/mock-project/subscriptions/gbp-sandbox-sub"
}
```

The base64-decoded `data` contains:
```json
{
  "notificationType": "NEW_REVIEW",
  "locationName": "accounts/100000001/locations/200000001",
  "reviewId": "rev001"
}
```

---

## Stateful behaviour

Review replies are **persisted in-memory** across requests:

```bash
# PUT a reply
curl -X PUT http://localhost:8090/v4/accounts/100000001/locations/200000001/reviews/rev001/reply \
  -H "Authorization: Bearer any_token" \
  -H "Content-Type: application/json" \
  -d '{"comment": "Thank you for your review!"}'

# GET the same review — reply is reflected
curl -H "Authorization: Bearer any_token" \
  http://localhost:8090/v4/accounts/100000001/locations/200000001/reviews/rev001
```

Reset to fixture baseline:
```bash
curl -X POST http://localhost:8090/admin/reset
```

---

## API shape notes

These are the subtle details that catch integration bugs. The sandbox enforces all of them.

**`starRating` is a string enum, not an int.** The Reviews v4 API returns
`"ONE"`, `"TWO"`, `"THREE"`, `"FOUR"`, `"FIVE"` — not `1`–`5`. A parser
that reads it as a number will silently break.

**`locations.list` and `locations.get` have different path shapes.**
- List: `GET /v1/accounts/{accountId}/locations` (account-scoped)
- Get: `GET /v1/locations/{locationId}` (bare — no account prefix)

This is intentional in the v1 Business Information API and a common source of
confusion when migrating from the old v4 monolith.

**Error envelopes differ by API surface.**
- v1 surfaces (Account Management, Business Information, Notifications): `{ "error": { "code", "message", "status", "details?" } }`
- v4 surface (Reviews): `{ "error": { "errors": [{ "domain", "reason", "message" }], "code", "message" } }`

**`reviews.list` and `reviews.reply` both require a VERIFIED account.**
The `unverified-account` scenario returns 403 on both, matching the documented
constraint (real-world enforcement may be more lenient — flag and verify when
you get real API access).

**`pageSize` ceilings are enforced.**
- Locations: max 100, default 10
- Reviews: max **50** (exact, per the REST reference), default 20

**Cloud Pub/Sub is at-least-once delivery.** The `duplicate-notification`
scenario exists specifically to catch handlers that aren't idempotent.

---

## Adding a fixture

Create `app/fixtures/{name}.json` following the shape of `default.json`.
The fixture is available immediately — no restart needed when using
`docker compose up` with the volume mount. Switch to it with:

```bash
curl -X POST http://localhost:8090/admin/scenario/{name}
```

For auto-generated reviews (to force pagination without writing 50+ JSON objects),
add `_auto_generate_reviews` to the fixture:

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

## Authentication

The sandbox accepts any `Authorization: Bearer <token>` header. No token
validation is done — just presence. Absence of the header returns 401.

The `POST /token` endpoint issues real-looking (but fake) access and refresh
tokens. The `refresh-revoked` scenario makes it return `invalid_grant` on
`grant_type=refresh_token`.

---

## Project layout

```
app/
  main.py               FastAPI app entry point
  state.py              In-memory state management + pagination helpers
  errors.py             v1 and v4 error envelope factories
  auth.py               Authorization header check
  deps.py               FastAPI dependency for scenario injection
  config.py             SCENARIO env var
  routers/
    oauth.py            POST /token · GET /o/oauth2/v2/auth
    accounts.py         GET /v1/accounts[/{id}]
    business_info.py    GET/PATCH /v1/locations · GET /v1/accounts/{id}/locations
    reviews.py          GET/PUT/DELETE /v4/…/reviews[/{id}[/reply]]
    notifications.py    GET/PATCH /v1/accounts/{id}/notificationSetting
    admin.py            POST /admin/reset · push · scenario · GET state · scenarios
  fixtures/             One JSON file per scenario
```

---

## License

MIT
