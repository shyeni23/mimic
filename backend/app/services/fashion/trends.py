"""
Trend / seasonal awareness (Module 3): inventory rows had no way to say
"this just arrived" or "this is trending" -- recommend/search results were
otherwise identical whether an item landed yesterday or a year ago, and
whether the whole store is currently adding it to cart or ignoring it.

Two signals, deliberately kept independent (an item can be trending without
being new, or new without being trending yet):

  - NEW ARRIVAL: inventory.created_at within a recency window. No new data
    needed -- created_at already exists on every row.
  - TRENDING: cross-session engagement via trending_items() (see
    cold_start.py / schema.sql) -- reused here, not reimplemented, so the
    "what counts as trending" definition can't drift between the cold-start
    path and the normal recommend/search path.

Also exposes `season`/`year` (see schema.sql's migration -- the source
dataset always had this, it just was never captured) so recommendations can
filter or mention "this season's" pieces without invented data.
"""
from datetime import datetime, timedelta, timezone

from app.db.supabase_client import get_supabase

NEW_ARRIVAL_WINDOW_DAYS = 14


def is_new_arrival(created_at) -> bool:
    """created_at may already be a datetime (from some Supabase client
    paths) or an ISO string (the common case) -- handle both rather than
    assuming one."""
    if not created_at:
        return False
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created_at) <= timedelta(days=NEW_ARRIVAL_WINDOW_DAYS)


def get_trending_ids(category: str | None = None, occasion: str | None = None, top_k: int = 50) -> set[str]:
    """Best-effort set of currently-trending item ids for annotation
    purposes -- wider top_k than a normal recommendation call (50, not 8)
    since this is used to TAG candidates already retrieved by Marqo, not to
    source the candidates itself. Returns an empty set (never raises) if the
    RPC isn't deployed yet or there's not enough engagement volume --
    trend-tagging is a nice-to-have annotation, never a hard dependency."""
    try:
        rows = (
            get_supabase()
            .rpc("trending_items", {
                "match_category": category, "match_occasion": occasion,
                "days_back": 30, "match_count": top_k,
            })
            .execute()
            .data or []
        )
        return {r["id"] for r in rows if r.get("id")}
    except Exception as e:
        print(f"[trends] trending lookup failed (non-fatal, no tags applied): {e}")
        return set()


def annotate_trend_signals(items: list[dict], category: str | None = None, occasion: str | None = None) -> list[dict]:
    """Mutates and returns the SAME list, adding `is_new_arrival` (bool,
    free from created_at) and `is_trending` (bool, from cross-session
    engagement) to every item. Call this right before building each item's
    `explanation` string so the trend note can be appended naturally.
    """
    if not items:
        return items
    trending_ids = get_trending_ids(category=category, occasion=occasion) if items else set()
    for item in items:
        item["is_new_arrival"] = is_new_arrival(item.get("created_at"))
        item["is_trending"] = item.get("id") in trending_ids
    return items


def trend_explanation_fragment(item: dict) -> str | None:
    """One short phrase to fold into an item's explanation string, or None
    if neither signal applies. Both signals present is rare but handled
    (new AND trending is a strong signal, worth saying both)."""
    parts = []
    if item.get("is_new_arrival"):
        parts.append("just arrived")
    if item.get("is_trending"):
        parts.append("trending right now")
    if not parts:
        return None
    return " and ".join(parts)
