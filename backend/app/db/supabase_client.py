"""
Supabase client wrapper.

Handles:
- Application DB (users, sessions, scans, inventory, conversations, feedback)
- Storage (uploaded frames, inventory images)

AI datasets (CSV) are treated separately (see app/utils/dataset_loader.py) since
they're static training/reference data, not live app state.
"""
from functools import lru_cache
from supabase import create_client, Client

from app.config import settings


@lru_cache
def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


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
    sb = get_supabase()
    payload = {"session_id": session_id, **scan}
    res = sb.table("scans").insert(payload).execute()
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


def get_mirror_calibration() -> float | None:
    sb = get_supabase()
    res = sb.table("mirror_calibration").select("px_per_cm").eq("id", 1).execute()
    return res.data[0]["px_per_cm"] if res.data else None


def set_mirror_calibration(px_per_cm: float) -> dict:
    sb = get_supabase()
    res = sb.table("mirror_calibration").upsert({"id": 1, "px_per_cm": px_per_cm}).execute()
    return res.data[0]


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

def get_inventory(category: str | None = None) -> list[dict]:
    sb = get_supabase()
    q = sb.table("inventory").select("*")
    if category:
        q = q.eq("category", category)
    return q.execute().data


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


def get_conversation_history(session_id: str, limit: int = 20) -> list[dict]:
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


# ---------- Storage ----------

def upload_media(path_in_bucket: str, file_bytes: bytes, content_type: str) -> str:
    sb = get_supabase()
    sb.storage.from_(settings.supabase_bucket).upload(
        path_in_bucket,
        file_bytes,
        {"content-type": content_type, "upsert": "true"},
    )
    return sb.storage.from_(settings.supabase_bucket).get_public_url(path_in_bucket)
