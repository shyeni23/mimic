"""
Recommender config registry: A/B testing + rollback (Module 3).

Before this, every tunable in the recommender (Stage B's compatibility
weights, skip-penalty thresholds, etc.) was a hardcoded Python constant --
changing one meant a code edit + redeploy, there was no way to run two
versions side-by-side to compare outcomes, and "roll back" meant finding the
old commit and redeploying again.

This gives named, versioned configs stored in Supabase (see schema.sql's
recommender_configs table):
  - register_config()  -- add a new version (inactive by default)
  - activate_config()  -- make a version live, optionally splitting traffic
                           with other already-active versions of the same name
  - rollback_config()  -- deactivate the current version(s), reactivate the
                           previous one at 100% traffic
  - get_active_config() -- deterministic per-SESSION assignment (same session
                           always gets the same variant for the life of the
                           session -- stable hash, not random-per-call) with
                           a safe built-in default when nothing's registered
                           yet, so the system works with zero configuration
  - list_config_history() -- full version history for one name, for audit

Deliberately NOT wired to require registration -- get_active_config() always
returns something usable (the caller's own default) even if this table has
never been touched, so adopting the registry for a new tunable is opt-in and
additive, never a hard dependency.
"""
import hashlib

from app.db.supabase_client import get_supabase


def _stable_fraction(key: str) -> float:
    """Deterministic pseudo-random float in [0, 1) from a string key -- same
    key always maps to the same fraction, so a given session's variant
    assignment doesn't flicker between calls within the session."""
    digest = hashlib.sha256(key.encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def register_config(name: str, config: dict, notes: str | None = None) -> dict:
    """Adds a new version under `name` (auto-incremented), inactive by
    default -- register first, activate separately (two explicit steps,
    so a new config never goes live by accident)."""
    sb = get_supabase()
    existing = (
        sb.table("recommender_configs")
        .select("version")
        .eq("name", name)
        .order("version", desc=True)
        .limit(1)
        .execute()
        .data
    )
    next_version = (existing[0]["version"] + 1) if existing else 1
    row = {
        "name": name, "version": next_version, "config": config,
        "is_active": False, "traffic_pct": 100, "notes": notes,
    }
    result = sb.table("recommender_configs").insert(row).execute().data[0]
    print(f"[model_registry] registered {name} v{next_version} (inactive)")
    return result


def activate_config(name: str, version: int, traffic_pct: int = 100) -> dict:
    """Makes a version live. traffic_pct=100 (the default) deactivates every
    OTHER active version of this name -- a clean full rollout. A lower
    traffic_pct leaves other active versions in place for a genuine split
    test; the caller is responsible for the split summing to <=100 (a
    mis-summed split just means some sessions fall through to the default
    config below 100% coverage -- degrades safely, never crashes)."""
    sb = get_supabase()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    if traffic_pct >= 100:
        sb.table("recommender_configs").update({
            "is_active": False, "deactivated_at": now,
        }).eq("name", name).eq("is_active", True).execute()

    result = (
        sb.table("recommender_configs")
        .update({"is_active": True, "traffic_pct": traffic_pct, "activated_at": now})
        .eq("name", name).eq("version", version)
        .execute()
        .data
    )
    if not result:
        raise ValueError(f"no config found for name={name!r} version={version}")
    print(f"[model_registry] activated {name} v{version} at {traffic_pct}% traffic")
    return result[0]


def rollback_config(name: str) -> dict:
    """Deactivates whatever's currently active for `name` and reactivates
    the PREVIOUS version (by version number) at 100% traffic. This is the
    literal "roll one back" the gap called out -- no redeploy, no code
    change, just a registry update."""
    sb = get_supabase()
    active = (
        sb.table("recommender_configs")
        .select("version")
        .eq("name", name).eq("is_active", True)
        .order("version", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if not active:
        raise ValueError(f"no active config for name={name!r} to roll back from")
    current_version = active[0]["version"]
    if current_version <= 1:
        raise ValueError(f"{name!r} is already at version 1 -- nothing earlier to roll back to")

    prior = (
        sb.table("recommender_configs")
        .select("version")
        .eq("name", name).lt("version", current_version)
        .order("version", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if not prior:
        raise ValueError(f"no earlier version of {name!r} found to roll back to")

    result = activate_config(name, prior[0]["version"], traffic_pct=100)
    print(f"[model_registry] rolled back {name}: v{current_version} -> v{prior[0]['version']}")
    return result


def get_active_config(name: str, session_id: str, default: dict) -> dict:
    """Deterministic per-session variant assignment. Returns `default`
    untouched if nothing's registered/active for `name` -- callers should
    always pass a real, currently-hardcoded default so this is a strict
    upgrade path, never a new failure mode. Never raises."""
    try:
        sb = get_supabase()
        active = (
            sb.table("recommender_configs")
            .select("version,config,traffic_pct")
            .eq("name", name).eq("is_active", True)
            .order("version")
            .execute()
            .data or []
        )
    except Exception as e:
        print(f"[model_registry] lookup failed for {name!r} (non-fatal, using default): {e}")
        return default

    if not active:
        return default

    # Weighted, deterministic assignment across active variants by
    # cumulative traffic_pct ranges, keyed on (session_id, name) so
    # different config groups don't correlate with each other.
    fraction = _stable_fraction(f"{session_id}:{name}")
    cumulative = 0.0
    for row in active:
        cumulative += row["traffic_pct"] / 100.0
        if fraction < cumulative:
            return row["config"]
    # Traffic doesn't sum to 100% (a partial split) -- sessions landing in
    # the uncovered remainder get the default, not an error.
    return default


def list_config_history(name: str) -> list[dict]:
    """Full version history for one config name, newest first -- for audit/
    debugging ("what was active last Tuesday", "what did we roll back from")."""
    sb = get_supabase()
    return (
        sb.table("recommender_configs")
        .select("*")
        .eq("name", name)
        .order("version", desc=True)
        .execute()
        .data or []
    )


# interactions.context->>'source' values whose ranking honours the session's
# A/B variant (both pass session_id to rerank_by_compatibility).
_AB_SOURCES = ("recommend_clothes", "complete_outfit")


def report_variant_performance(name: str, days_back: int = 30) -> dict:
    """Compares engagement across the currently-active variants of `name`.

    get_active_config() assigns a session to a variant with a pure function
    of (session_id, name) -- no assignment is ever written down anywhere.
    That's fine for serving (recomputing it is cheap and always agrees), but
    it means measuring a test means recomputing the SAME assignment for
    every session seen in the window and bucketing its interactions by it,
    rather than reading a stored label. This only re-derives correctly for
    sessions seen while the CURRENT set of active versions was live -- if
    versions were added/removed/re-split mid-window, older sessions get
    bucketed by today's split, not whatever was active when they occurred.
    For a short-lived test (days, not months) that's an acceptable
    approximation; for anything longer, re-run this soon after each
    registry change instead of spanning across one.

    Only interactions logged with context->>'source' in _AB_SOURCES are
    counted -- the callers that pass session_id into rerank_by_compatibility
    (see compatibility.py), i.e. the only paths where a customer's variant
    assignment could have actually changed what they were shown. Counting
    other sources would dilute both variants with identical noise.
    """
    sb = get_supabase()
    active = (
        sb.table("recommender_configs")
        .select("version,traffic_pct")
        .eq("name", name).eq("is_active", True)
        .order("version")
        .execute()
        .data or []
    )
    if not active:
        return {"error": f"no active config for name={name!r}"}

    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()

    # Paged: PostgREST caps a plain select at 1000 rows, which would
    # silently report on only the first 1000 interactions.
    rows, offset = [], 0
    while True:
        page = (
            sb.table("interactions")
            .select("session_id,event_type")
            .in_("context->>source", list(_AB_SOURCES))
            .gte("created_at", since)
            .order("created_at")
            .range(offset, offset + 999)
            .execute()
            .data or []
        )
        rows.extend(page)
        if len(page) < 1000:
            break
        offset += 1000

    # Bucket every (session, event) pair by which variant that session
    # would be assigned today -- same cumulative-range walk get_active_config
    # itself uses, just without needing a session_id in hand ahead of time.
    def assign(session_id: str) -> int | None:
        fraction = _stable_fraction(f"{session_id}:{name}")
        cumulative = 0.0
        for row in active:
            cumulative += row["traffic_pct"] / 100.0
            if fraction < cumulative:
                return row["version"]
        return None  # falls in an uncovered remainder -- got the default, not a variant

    stats: dict[int, dict] = {row["version"]: {"sessions": set(), "shown": 0, "engaged": 0} for row in active}
    for row in rows:
        version = assign(row["session_id"])
        if version is None or version not in stats:
            continue
        stats[version]["sessions"].add(row["session_id"])
        if row["event_type"] in ("view", "recommend_shown"):
            stats[version]["shown"] += 1
        elif row["event_type"] in ("click", "add_to_cart", "tryon"):
            stats[version]["engaged"] += 1

    result = {}
    for version, s in stats.items():
        shown = s["shown"]
        result[f"v{version}"] = {
            "sessions": len(s["sessions"]),
            "shown": shown,
            "engaged": s["engaged"],
            "engagement_rate": round(s["engaged"] / shown, 3) if shown else None,
        }
    return result
