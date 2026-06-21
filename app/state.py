"""In-memory state management for GBP Sandbox.

The global ScenarioState is loaded from a JSON fixture at startup and stays
alive for the container lifetime. Mutations (review replies, notification
settings) are stored in-memory and survive until POST /admin/reset.

Per-request scenario overrides (X-Mock-Scenario header) get a fresh,
ephemeral ScenarioState that is discarded after the response — mutations
on per-request overrides are not persisted.
"""
import base64
import copy
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_lock = threading.Lock()
_current: Optional["ScenarioState"] = None

_STAR_RATINGS = ["ONE", "TWO", "THREE", "FOUR", "FIVE"]
_NAMES = [
    "Alex Johnson", "Maria Garcia", "James Wilson", "Emily Chen",
    "Michael Brown", "Sarah Davis", "Robert Taylor", "Jennifer Anderson",
    "William Martinez", "Elizabeth Thomas", "David Jackson", "Susan White",
    "Richard Harris", "Jessica Lewis", "Joseph Robinson", "Karen Walker",
    "Charles Hall", "Nancy Young", "Thomas Allen", "Sandra King",
    "Christopher Lee", "Patricia Harris", "Daniel Clark", "Lisa Robinson",
    "Paul Wright", "Barbara Scott", "Mark Green", "Dorothy Adams",
]
_COMMENTS = [
    "Great service!",
    "Very professional staff.",
    "Would recommend to everyone.",
    "Average experience, nothing special.",
    "Loved the atmosphere.",
    "Prices are reasonable for the quality.",
    "Fast and efficient service.",
    "Will definitely come back.",
    "Disappointed with the wait time.",
    "Staff was very helpful and friendly.",
    "Good value for money.",
    "The location is very convenient.",
    "Clean and well-maintained facility.",
    "Exceeded my expectations!",
    "Decent but there's room for improvement.",
    "Outstanding quality and presentation.",
    "Friendly team, would visit again.",
    "Not bad, but I've seen better.",
    "Highly recommend this place.",
    "Mixed feelings about the experience.",
]


def _generate_reviews(account_id: str, location_id: str, count: int) -> List[Dict]:
    reviews = []
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(count):
        rid = f"auto_{i + 1:04d}"
        create_time = base_time + timedelta(days=i, hours=i % 24)
        ts = create_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        reviews.append(
            {
                "name": f"accounts/{account_id}/locations/{location_id}/reviews/{rid}",
                "reviewId": rid,
                "reviewer": {
                    "displayName": _NAMES[i % len(_NAMES)],
                    "profilePhotoUrl": f"https://example.com/photos/{i % len(_NAMES)}.jpg",
                    "isAnonymous": False,
                },
                "starRating": _STAR_RATINGS[i % 5],
                "comment": _COMMENTS[i % len(_COMMENTS)],
                "createTime": ts,
                "updateTime": ts,
            }
        )
    return reviews


def _load_fixture(name: str) -> Dict:
    path = FIXTURES_DIR / f"{name}.json"
    if not path.exists():
        raise ValueError(
            f"Unknown scenario: '{name}'. No fixture found at {path}. "
            f"Available: {list_scenarios()}"
        )
    with open(path) as f:
        data = json.load(f)

    if "_auto_generate_reviews" in data:
        gen = data.pop("_auto_generate_reviews")
        data["reviews"] = {
            gen["location_id"]: _generate_reviews(
                gen["account_id"], gen["location_id"], gen["count"]
            )
        }
    return data


def _now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def encode_page_token(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def decode_page_token(token: str) -> int:
    try:
        return int(base64.urlsafe_b64decode(token.encode()).decode())
    except Exception:
        return 0


class ScenarioState:
    def __init__(self, name: str, data: Optional[Dict] = None):
        self.name = name
        raw = data if data is not None else _load_fixture(name)
        self._baseline = raw
        self._state: Dict = copy.deepcopy(raw)
        self._replies: Dict[str, Dict] = {}
        self._req_counts: Dict[str, int] = {}

    def reset(self) -> None:
        self._state = copy.deepcopy(self._baseline)
        self._replies.clear()
        self._req_counts.clear()

    # ── Accounts ─────────────────────────────────────────────────────────────

    @property
    def accounts(self) -> List[Dict]:
        return self._state.get("accounts", [])

    def get_account(self, account_id: str) -> Optional[Dict]:
        for a in self.accounts:
            if a["name"] == f"accounts/{account_id}":
                return a
        return None

    def account_is_verified(self, account_id: str) -> bool:
        a = self.get_account(account_id)
        if a is None:
            return False
        return a.get("verificationState", "VERIFIED") == "VERIFIED"

    # ── Locations ─────────────────────────────────────────────────────────────

    def get_locations(self, account_id: str) -> List[Dict]:
        return self._state.get("locations", {}).get(account_id, [])

    def get_location(self, location_id: str) -> Optional[Dict]:
        for locs in self._state.get("locations", {}).values():
            for loc in locs:
                if loc["name"] == f"locations/{location_id}":
                    return copy.deepcopy(loc)
        return None

    def patch_location(self, location_id: str, patch: Dict) -> Optional[Dict]:
        for locs in self._state.get("locations", {}).values():
            for i, loc in enumerate(locs):
                if loc["name"] == f"locations/{location_id}":
                    locs[i] = {**loc, **patch, "name": loc["name"]}
                    return copy.deepcopy(locs[i])
        return None

    # ── Reviews ───────────────────────────────────────────────────────────────

    def get_reviews(self, account_id: str, location_id: str) -> List[Dict]:
        reviews = copy.deepcopy(
            self._state.get("reviews", {}).get(location_id, [])
        )
        for r in reviews:
            r["name"] = (
                f"accounts/{account_id}/locations/{location_id}"
                f"/reviews/{r['reviewId']}"
            )
            rid = r["reviewId"]
            if rid in self._replies:
                r["reviewReply"] = copy.deepcopy(self._replies[rid])
        return reviews

    def get_review(
        self, account_id: str, location_id: str, review_id: str
    ) -> Optional[Dict]:
        for r in self.get_reviews(account_id, location_id):
            if r["reviewId"] == review_id:
                return r
        return None

    def put_reply(self, review_id: str, comment: str) -> Dict:
        reply = {"comment": comment, "updateTime": _now_rfc3339()}
        self._replies[review_id] = reply
        return reply

    def delete_reply(self, review_id: str) -> bool:
        if review_id in self._replies:
            del self._replies[review_id]
            return True
        for locs_reviews in self._state.get("reviews", {}).values():
            for r in locs_reviews:
                if r["reviewId"] == review_id and "reviewReply" in r:
                    del r["reviewReply"]
                    return True
        return False

    # ── Notification settings ─────────────────────────────────────────────────

    def get_notification_setting(self, account_id: str) -> Optional[Dict]:
        return self._state.get("notification_settings", {}).get(account_id)

    def put_notification_setting(self, account_id: str, data: Dict) -> Dict:
        self._state.setdefault("notification_settings", {})[account_id] = data
        return data

    # ── Scenario-level behaviour flags ───────────────────────────────────────

    @property
    def oauth_behavior(self) -> str:
        return self._state.get("oauth", {}).get("behavior", "success")

    @property
    def is_rate_limited(self) -> bool:
        return bool(self._state.get("error_injection", {}).get("rate_limit", False))

    @property
    def is_zero_quota(self) -> bool:
        return bool(self._state.get("error_injection", {}).get("zero_quota", False))

    # ── Request counting (for rate-limit scenario) ────────────────────────────

    def track_request(self, key: str) -> int:
        count = self._req_counts.get(key, 0) + 1
        self._req_counts[key] = count
        return count

    def get_request_count(self, key: str) -> int:
        return self._req_counts.get(key, 0)

    # ── Pagination helpers ────────────────────────────────────────────────────

    def paginate_reviews(
        self,
        account_id: str,
        location_id: str,
        page_size: int,
        page_token: Optional[str],
    ) -> Tuple[List[Dict], float, int, Optional[str]]:
        all_reviews = self.get_reviews(account_id, location_id)
        total = len(all_reviews)
        offset = decode_page_token(page_token) if page_token else 0
        page = all_reviews[offset: offset + page_size]
        next_token = (
            encode_page_token(offset + page_size)
            if offset + page_size < total
            else None
        )
        ratings = {
            "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5
        }
        avg = (
            sum(ratings.get(r["starRating"], 0) for r in all_reviews) / total
            if total
            else 0.0
        )
        return page, round(avg, 1), total, next_token

    def paginate_locations(
        self,
        account_id: str,
        page_size: int,
        page_token: Optional[str],
    ) -> Tuple[List[Dict], Optional[str]]:
        all_locs = self.get_locations(account_id)
        offset = decode_page_token(page_token) if page_token else 0
        page = all_locs[offset: offset + page_size]
        next_token = (
            encode_page_token(offset + page_size)
            if offset + page_size < len(all_locs)
            else None
        )
        return page, next_token


# ── Module-level helpers ──────────────────────────────────────────────────────

def load_scenario(name: str) -> None:
    global _current
    with _lock:
        _current = ScenarioState(name)


def get_state() -> ScenarioState:
    if _current is None:
        raise RuntimeError("No scenario loaded. Call load_scenario() first.")
    return _current


def get_scenario_for_request(override: Optional[str]) -> ScenarioState:
    state = get_state()
    if override and override != state.name:
        try:
            return ScenarioState(override)
        except ValueError:
            return state
    return state


def list_scenarios() -> List[str]:
    return sorted(p.stem for p in FIXTURES_DIR.glob("*.json"))
