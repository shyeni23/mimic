"""
Section 7 -- Combined User Context tests.

All tests are deterministic. No Gemini API, no Supabase, no CV computation.
They validate that build_user_context and extract_visual_profile correctly
combine visual profile data (from scans) with conversation preferences
(from the agent) without inventing, losing, or mixing data.
"""
import pytest

from app.services.user_context import build_user_context, extract_visual_profile


# A realistic scan row as it comes back from get_latest_scan / the scans table.
SAMPLE_SCAN = {
    "id": "scan-001",
    "session_id": "session-a",
    "body_shape": "pear",
    "face_shape": "oval",
    "skin_tone_hex": "#d4a574",
    "skin_tone_category": "medium",
    "skin_tone_undertone": "warm",
    "body_size_estimate": "M",
    "height_cm": 165.0,
    "height_source": "camera",
    "glasses_detected": False,
    "hair_length": "medium",
    "landmarks": {"face": [], "pose": []},
    "frame_url": "https://example.com/frame.jpg",
    "created_at": "2026-08-20T10:00:00Z",
}

SAMPLE_PREFERENCES = {
    "occasion": "engagement",
    "style": "traditional",
    "color_preferences": ["pastel"],
    "constraints": ["lightweight"],
}


class TestUserContext:

    def test_1_visual_profile_only(self):
        """TEST 1: visual profile preserved exactly, no conversation data."""
        ctx = build_user_context("session-a", SAMPLE_SCAN, None)

        assert ctx["session_id"] == "session-a"
        vp = ctx["visual_profile"]
        assert vp["body_shape"] == "pear"
        assert vp["skin_tone_category"] == "medium"
        assert vp["skin_tone_undertone"] == "warm"
        assert vp["face_shape"] == "oval"
        assert vp["body_size_estimate"] == "M"
        assert vp["height_cm"] == 165.0
        assert vp["glasses_detected"] is False
        assert vp["hair_length"] == "medium"
        assert ctx["fashion_preferences"] == {}

    def test_2_conversation_preferences_only(self):
        """TEST 2: conversation preferences preserved exactly, no scan data."""
        ctx = build_user_context("session-b", None, SAMPLE_PREFERENCES)

        assert ctx["session_id"] == "session-b"
        fp = ctx["fashion_preferences"]
        assert fp["occasion"] == "engagement"
        assert fp["style"] == "traditional"
        assert fp["color_preferences"] == ["pastel"]
        assert fp["constraints"] == ["lightweight"]
        vp = ctx["visual_profile"]
        for field in vp:
            assert vp[field] is None, f"visual {field} should be None without scan"

    def test_3_combined_context(self):
        """TEST 3: both profiles present, associated with the same session."""
        ctx = build_user_context("session-c", SAMPLE_SCAN, SAMPLE_PREFERENCES)

        assert ctx["session_id"] == "session-c"
        assert ctx["visual_profile"]["body_shape"] == "pear"
        assert ctx["visual_profile"]["skin_tone_undertone"] == "warm"
        assert ctx["visual_profile"]["face_shape"] == "oval"
        assert ctx["visual_profile"]["body_size_estimate"] == "M"
        assert ctx["fashion_preferences"]["occasion"] == "engagement"
        assert ctx["fashion_preferences"]["style"] == "traditional"
        assert ctx["fashion_preferences"]["color_preferences"] == ["pastel"]

    def test_4_missing_cv_value_stays_null(self):
        """TEST 4: a scan with skin_tone fields as None must NOT invent values."""
        partial_scan = {
            "body_shape": "rectangle",
            "face_shape": "round",
            "skin_tone_hex": None,
            "skin_tone_category": None,
            "skin_tone_undertone": None,
            "body_size_estimate": "L",
            "height_cm": None,
            "height_source": None,
            "glasses_detected": True,
            "hair_length": "short",
        }
        ctx = build_user_context("session-d", partial_scan, None)
        vp = ctx["visual_profile"]
        assert vp["skin_tone_hex"] is None
        assert vp["skin_tone_category"] is None
        assert vp["skin_tone_undertone"] is None
        assert vp["height_cm"] is None
        assert vp["body_shape"] == "rectangle"
        assert vp["glasses_detected"] is True

    def test_5_missing_conversation_value_stays_null(self):
        """TEST 5: preferences with occasion=None must NOT invent an occasion."""
        empty_prefs = {"style": "modern"}
        ctx = build_user_context("session-e", SAMPLE_SCAN, empty_prefs)
        fp = ctx["fashion_preferences"]
        assert fp.get("occasion") is None
        assert fp["style"] == "modern"

    def test_6_session_isolation(self):
        """TEST 6: two sessions get independent contexts with no data leakage."""
        ctx_a = build_user_context("session-A", SAMPLE_SCAN, {"occasion": "wedding"})
        ctx_b = build_user_context("session-B", None, {"occasion": "party"})

        assert ctx_a["session_id"] == "session-A"
        assert ctx_b["session_id"] == "session-B"

        assert ctx_a["visual_profile"]["body_shape"] == "pear"
        for field in ctx_b["visual_profile"]:
            assert ctx_b["visual_profile"][field] is None

        assert ctx_a["fashion_preferences"]["occasion"] == "wedding"
        assert ctx_b["fashion_preferences"]["occasion"] == "party"

    def test_7_extract_visual_profile_strips_non_profile_fields(self):
        """TEST 7: extract_visual_profile returns only profile fields, not
        raw scan internals like landmarks, frame_url, or created_at."""
        vp = extract_visual_profile(SAMPLE_SCAN)
        assert "landmarks" not in vp
        assert "frame_url" not in vp
        assert "created_at" not in vp
        assert "id" not in vp
        assert "session_id" not in vp
        assert vp["body_shape"] == "pear"
        assert vp["face_shape"] == "oval"

    def test_both_empty(self):
        """Edge case: no scan, no preferences -- still produces a valid context."""
        ctx = build_user_context("session-empty", None, None)
        assert ctx["session_id"] == "session-empty"
        assert ctx["fashion_preferences"] == {}
        for field in ctx["visual_profile"]:
            assert ctx["visual_profile"][field] is None
