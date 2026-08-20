"""
Combined user context -- merges the visual profile (from CV/scans table)
with conversation preferences (from conversations.meta) into one dict
keyed to a session_id.

This is the bridge between Module 1 (CV) and Module 2 (conversation).
It does NOT duplicate any CV computation or create new DB tables -- it
reads from the existing `scans` and `conversations` tables and combines
their data in application logic.

The recommendation engine (Section 8) will consume this combined context.
For now (Section 7) it's just assembled and exposed for verification.
"""


_VISUAL_PROFILE_FIELDS = (
    "body_shape",
    "face_shape",
    "skin_tone_hex",
    "skin_tone_category",
    "skin_tone_undertone",
    "body_size_estimate",
    "height_cm",
    "height_source",
    "glasses_detected",
    "hair_length",
)


def extract_visual_profile(scan: dict | None) -> dict:
    """Extracts only the visual-profile fields from a raw scan row.
    Unknown/missing values stay None -- never invented."""
    if not scan:
        return {field: None for field in _VISUAL_PROFILE_FIELDS}
    return {field: scan.get(field) for field in _VISUAL_PROFILE_FIELDS}


def build_user_context(
    session_id: str,
    scan: dict | None,
    preferences: dict | None,
) -> dict:
    """Builds the combined user context from a scan row and conversation
    preferences. Both sides are optional -- the context is valid with only
    visual data, only conversation data, or both.

    Returns:
        {
            "session_id": str,
            "visual_profile": { body_shape, face_shape, skin_tone_*, ... },
            "fashion_preferences": { occasion, style, color_preferences, ... },
        }
    """
    return {
        "session_id": session_id,
        "visual_profile": extract_visual_profile(scan),
        "fashion_preferences": dict(preferences or {}),
    }


def get_user_context(session_id: str) -> dict:
    """Convenience function that reads both sources from the DB and returns
    the combined context. Tolerates DB failures gracefully -- if scans or
    conversations are unreachable, that side comes back empty rather than
    crashing -- but logs the failure so an outage is diagnosable instead of
    silently producing an empty profile."""
    from app.db.supabase_client import get_latest_scan, get_conversation_history
    from app.services.agent.preferences import extract_prior_preferences

    scan = None
    try:
        scan = get_latest_scan(session_id)
    except Exception as e:
        print(f"[user_context] scan lookup failed for session {session_id}: {e}")

    preferences = {}
    try:
        history = get_conversation_history(session_id)
        preferences = extract_prior_preferences(history)
    except Exception as e:
        print(f"[user_context] conversation history lookup failed for session {session_id}: {e}")

    return build_user_context(session_id, scan, preferences)
