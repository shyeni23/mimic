"""
Supabase client wrapper.

Handles:
- Application DB (users, sessions, scans, inventory, conversations, feedback)
- Storage (uploaded frames, inventory images)

AI datasets (CSV) are treated separately (see app/utils/dataset_loader.py) since
they're static training/reference data, not live app state.
"""
import re
import threading
from supabase import create_client, Client
from postgrest.exceptions import APIError

from app.config import settings


# One client PER THREAD, not one per process. The supabase-py client's
# underlying httpx connection pool is not safe to share across threads:
# once recommend_complete_look() started running its per-category searches
# concurrently, the shared singleton produced "Server disconnected" and
# "deque mutated during iteration" errors mid-request. Each worker thread
# (and uvicorn's request thread) now owns its own pooled client -- still
# created once per thread and reused, so no per-call connection cost.
_thread_local = threading.local()


def get_supabase() -> Client:
    client = getattr(_thread_local, "client", None)
    if client is None:
        client = create_client(settings.supabase_url, settings.supabase_key)
        _thread_local.client = client
    return client


_MISSING_COLUMN_RE = re.compile(r"Could not find the '(\w+)' column of '(\w+)'")


def _insert_tolerant(table: str, payload: dict):
    """
    Insert, but never let a column that exists in application code and not yet
    in the live schema (e.g. a migration the operator hasn't run in the
    Supabase SQL editor yet -- schema.sql's CREATE TABLE IF NOT EXISTS is a
    no-op against an already-existing table, so new columns need a manual
    ALTER TABLE there) take down the whole request. Drops the offending
    key(s) and retries once; the rest of the scan is still real and useful
    even if one field silently didn't persist.
    """
    sb = get_supabase()
    remaining = dict(payload)
    for _ in range(len(payload) + 1):
        try:
            return sb.table(table).insert(remaining).execute()
        except APIError as e:
            match = _MISSING_COLUMN_RE.search(e.message or "")
            if not match or match.group(2) != table or match.group(1) not in remaining:
                raise
            missing_col = match.group(1)
            print(
                f"[supabase] '{table}.{missing_col}' doesn't exist in the live schema yet "
                f"(run the pending migration in schema.sql) -- dropping it from this insert "
                f"and retrying rather than failing the whole request."
            )
            remaining.pop(missing_col)
    raise RuntimeError(f"_insert_tolerant exhausted retries for table '{table}'")


# ---------- Users / Sessions ----------

def upsert_user(user_id: str, data: dict) -> dict:
    sb = get_supabase()
    payload = {"id": user_id, **data}
    res = sb.table("users").upsert(payload).execute()
    return res.data[0] if res.data else {}


def create_session(user_id: str | None = None) -> dict:
    sb = get_supabase()
    res = sb.table("sessions").insert({"user_id": user_id}).execute()
    return res.data[0]


# ---------- Body / Face scan results (Module 1) ----------

def save_scan_result(session_id: str, scan: dict) -> dict:
    payload = {"session_id": session_id, **scan}
    res = _insert_tolerant("scans", payload)
    return res.data[0]


def update_scan_height(session_id: str, height_cm: float, source: str) -> dict | None:
    """Called when the user SPEAKS their height during chat -- overrides the camera guess
    on the most recent scan for this session."""
    sb = get_supabase()
    latest = get_latest_scan(session_id)
    if not latest:
        return None
    res = (
        sb.table("scans")
        .update({"height_cm": height_cm, "height_source": source})
        .eq("id", latest["id"])
        .execute()
    )
    return res.data[0] if res.data else None


_calibration_cache = {"value": None, "loaded": False}


def get_mirror_calibration() -> float | None:
    if _calibration_cache["loaded"]:
        return _calibration_cache["value"]
    sb = get_supabase()
    res = sb.table("mirror_calibration").select("px_per_cm").eq("id", 1).execute()
    val = res.data[0]["px_per_cm"] if res.data else None
    _calibration_cache["value"] = val
    _calibration_cache["loaded"] = True
    return val


def set_mirror_calibration(px_per_cm: float) -> dict:
    sb = get_supabase()
    res = sb.table("mirror_calibration").upsert({"id": 1, "px_per_cm": px_per_cm}).execute()
    _calibration_cache["value"] = px_per_cm
    _calibration_cache["loaded"] = True
    return res.data[0]


def update_scan_gender(session_id: str, gender: str) -> dict | None:
    """Customer-confirmed department override (Recommendations page "Range"
    chip). Overwrites the ensemble's estimate on the most recent scan so
    /api/recommend, Aria's recommend_clothes and everything else that reads
    get_latest_scan() agree from then on -- the customer's own answer always
    beats a classifier."""
    sb = get_supabase()
    latest = get_latest_scan(session_id)
    if not latest:
        return None
    res = sb.table("scans").update({"gender": gender}).eq("id", latest["id"]).execute()
    return res.data[0] if res.data else None


def update_scan_frame_url(session_id: str, frame_url: str) -> dict | None:
    """Called from a background task after /api/vision/scan already responded,
    so Storage upload latency never blocks the sub-1-second scan response."""
    sb = get_supabase()
    latest = get_latest_scan(session_id)
    if not latest:
        return None
    res = sb.table("scans").update({"frame_url": frame_url}).eq("id", latest["id"]).execute()
    return res.data[0] if res.data else None


def get_latest_scan(session_id: str) -> dict | None:
    sb = get_supabase()
    res = (
        sb.table("scans")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


# ---------- Inventory (Module 1/3) ----------

def get_inventory(category: str | None = None, in_stock_only: bool = True,
                   include_embedding: bool = True) -> list[dict]:
    """in_stock_only defaults to True -- the agent must never recommend or
    show an item that isn't actually purchasable. Callers that genuinely need
    the full catalog (e.g. admin stock management) can pass False.

    include_embedding=False skips the 512-float `embedding` column for
    callers that only do rule-based scoring/display (outfit_recommendation.py's
    recommend_outfit(), the /api/inventory/browse route) -- confirmed live
    that pulling embeddings for a whole unfiltered category is slow enough to
    hit Supabase's statement timeout (error 57014) under load, and even when
    it succeeds it was pure wasted transfer for callers that never touch the
    column. Callers that DO need it (Stage B compatibility reranking) keep
    the default."""
    sb = get_supabase()
    slim = (
        "id,name,category,color,occasion,style_tags,image_url,price,stock,"
        "created_at,embedding_source,season,year"
    )

    def _run(columns: str):
        q = sb.table("inventory").select(columns)
        if category:
            q = q.eq("category", category)
        if in_stock_only:
            q = q.gt("stock", 0)
        return q.execute().data

    if include_embedding:
        return _run("*")
    try:
        return _run(slim + ",gender")
    except Exception as e:
        # `gender` column not migrated yet (module3_missing_migrations.sql
        # section 6) -- degrade to the pre-gender column list instead of
        # taking /api/inventory/browse down. catalog_filters falls back to
        # name-based gender inference when the key is absent.
        if "gender" not in str(e):
            raise
        return _run(slim)


def insert_inventory_item(item: dict) -> dict:
    sb = get_supabase()
    res = sb.table("inventory").insert(item).execute()
    return res.data[0]


# ---------- Conversations (Module 2) ----------

def append_conversation_turn(session_id: str, role: str, content: str, meta: dict | None = None) -> dict:
    sb = get_supabase()
    payload = {"session_id": session_id, "role": role, "content": content, "meta": meta or {}}
    res = sb.table("conversations").insert(payload).execute()
    return res.data[0]


def get_conversation_history(session_id: str, limit: int = 50) -> list[dict]:
    sb = get_supabase()
    res = (
        sb.table("conversations")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return res.data


# ---------- Staff escalation (human-in-the-loop) ----------

def create_staff_request(session_id: str, reason: str, message: str = "") -> dict:
    sb = get_supabase()
    payload = {"session_id": session_id, "reason": reason, "message": message}
    res = _insert_tolerant("staff_requests", payload)
    return res.data[0]


def get_pending_staff_requests() -> list[dict]:
    sb = get_supabase()
    res = (
        sb.table("staff_requests")
        .select("*")
        .eq("status", "pending")
        .order("created_at", desc=False)
        .execute()
    )
    return res.data


def get_recent_staff_requests(limit: int = 50) -> list[dict]:
    """All statuses, newest first -- for a dashboard view that also shows
    recently acknowledged/resolved requests, not just pending ones."""
    sb = get_supabase()
    res = (
        sb.table("staff_requests")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data


def update_staff_request_status(request_id: str, status: str) -> dict | None:
    """status: pending | acknowledged | resolved (matches schema.sql's check)."""
    sb = get_supabase()
    res = sb.table("staff_requests").update({"status": status}).eq("id", request_id).execute()
    return res.data[0] if res.data else None


# ---------- Interaction-event feedback (Module 3, agent situational awareness) ----------

def get_session_interaction_signals(session_id: str) -> dict:
    """
    Reads this session's own interaction log and returns what the recommender
    and agent brain should know about what the customer has already reacted to:

        {
            "dismissed_item_ids": [...],   # skip / dismiss events -- do NOT re-recommend
            "shown_item_ids":     [...],   # view / recommend_shown -- already seen
            "engaged_item_ids":   [...],   # click / add_to_cart / tryon -- POSITIVE signal
        }

    Enables the "she noticed you kept skipping the fitted ones" behavior:
    recommend_items() removes dismissed ones from candidates, and the LLM can
    reference engagement in its reply. Falls back to empty lists on any error
    -- interaction data missing shouldn't ever break a scan or chat response.
    """
    signals = {"dismissed_item_ids": [], "shown_item_ids": [], "engaged_item_ids": []}
    try:
        sb = get_supabase()
        # Only this session's own events -- cross-session personalization is a
        # separate feature that needs user_id (see cross-session-memory plan).
        rows = (
            sb.table("interactions")
            .select("item_id,event_type")
            .eq("session_id", session_id)
            .execute()
            .data
        )
    except Exception as e:
        print(f"[interaction-signals] read failed (non-fatal, empty signals): {e}")
        return signals

    dismissed: set = set()
    shown: set = set()
    engaged: set = set()
    for r in rows:
        item_id = r.get("item_id")
        if not item_id:
            continue
        et = r.get("event_type")
        if et in ("skip", "dismiss"):
            dismissed.add(item_id)
        elif et in ("view", "recommend_shown"):
            shown.add(item_id)
        elif et in ("click", "add_to_cart", "tryon"):
            engaged.add(item_id)

    signals["dismissed_item_ids"] = list(dismissed - engaged)  # engaged wins over later skip
    signals["shown_item_ids"] = list(shown)
    signals["engaged_item_ids"] = list(engaged)
    return signals


def log_shown_items(session_id: str, item_ids: list[str], source: str) -> None:
    """Server-side interaction log for items an agent tool just returned to
    the customer (search_inventory, recommend_clothes, complete_outfit) --
    independent of whether the FRONTEND ever renders/navigates to a screen
    that shows them.

    Why this exists: the frontend's own `view`/`recommend_shown` event
    logger (see src/hooks/useEventLogger.js) only fires when a page actually
    renders product cards -- which only happens after a queue_action like
    "show_recommendations" navigates there. search_inventory is a pure read
    tool with no queue_action at all (it just informs Aria's spoken reply),
    so its results were NEVER logged, silently breaking cross-turn recall
    ("add the one from earlier") for exactly the tool customers hit most
    before a body scan exists. Logging server-side here removes that
    dependency entirely -- works identically for voice-only customers with
    no screen interaction too.

    Fire-and-forget: a failure here must never break the tool's real
    response to the customer, so every error is swallowed after logging.
    """
    if not item_ids:
        return
    try:
        sb = get_supabase()
        rows = [
            {"session_id": session_id, "item_id": iid, "event_type": "view",
             "context": {"source": source}}
            for iid in item_ids
        ]
        sb.table("interactions").insert(rows).execute()
    except Exception as e:
        print(f"[shown-items-log] failed for source={source} (non-fatal): {e}")


# ---------- Storage ----------

def upload_media(path_in_bucket: str, file_bytes: bytes, content_type: str) -> str:
    sb = get_supabase()
    sb.storage.from_(settings.supabase_bucket).upload(
        path_in_bucket,
        file_bytes,
        {"content-type": content_type, "upsert": "true"},
    )
    return sb.storage.from_(settings.supabase_bucket).get_public_url(path_in_bucket)
