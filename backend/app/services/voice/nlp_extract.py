"""
Fast regex pre-extraction of structured context from chat messages.

Two extraction paths coexist intentionally:
  1. THIS FILE (regex) -- runs BEFORE the LLM, instant. Its stated_height_cm
     writes to the scan DB (the only place height-from-speech is captured).
     The rest (occasion, formality, etc.) is returned in ChatResponse.extracted_context
     for the frontend but does NOT feed into recommendations.
  2. graph.py's ConversationState (LLM) -- the authoritative extraction that
     drives recommendations via merge_preferences. Extracts occasion, style,
     colors, budget, fit, etc.

The overlap (occasion) is harmless: the regex result goes to the frontend as
quick feedback, the LLM result drives actual behavior.
"""
import re

_OCCASION_KEYWORDS = {
    "wedding": "wedding", "reception": "wedding",
    "party": "party", "birthday": "party", "celebration": "party",
    "date": "date night", "date night": "date night", "dinner": "date night",
    "interview": "interview", "job interview": "interview",
    "office": "office", "work": "office", "meeting": "office", "corporate": "office",
    "gym": "gym", "workout": "gym", "exercise": "gym",
    "beach": "beach", "pool": "beach",
    "brunch": "brunch", "lunch": "casual outing",
    "funeral": "funeral", "memorial": "funeral",
    "graduation": "graduation", "prom": "prom",
    "vacation": "vacation", "travel": "vacation", "trip": "vacation",
    "casual": "casual outing",
}

_FORMALITY_KEYWORDS = {
    "formal": "formal", "black tie": "very formal", "gala": "very formal",
    "smart casual": "smart casual", "business casual": "smart casual",
    "casual": "casual", "relaxed": "casual", "chill": "casual",
    "professional": "formal", "elegant": "formal",
}

_LOCATION_KEYWORDS = {
    "outdoor": "outdoor", "outside": "outdoor", "garden": "outdoor", "park": "outdoor",
    "indoor": "indoor", "inside": "indoor",
    "beach": "beach", "pool": "beach",
    "office": "office", "restaurant": "restaurant",
}

_TIME_KEYWORDS = {
    "morning": "morning", "breakfast": "morning",
    "afternoon": "afternoon", "daytime": "afternoon",
    "evening": "evening", "tonight": "evening", "sunset": "evening",
    "night": "night", "nighttime": "night", "late night": "night",
}

_HEIGHT_PATTERN = re.compile(
    r"""(?:i(?:'m|am)\s+)?(\d)'[\s-]?(\d{1,2})(?:\"|''|in)?"""  # 5'6", 5'6, 5 foot 6
    r"""|(\d)\s*(?:foot|feet|ft)\s*(\d{1,2})?"""                  # 5 foot 6, 5 feet
    r"""|(\d{2,3})\s*cm"""                                         # 170cm, 170 cm
    , re.IGNORECASE
)


def _match_height(text: str):
    m = _HEIGHT_PATTERN.search(text)
    if not m:
        return None
    if m.group(1) and m.group(2):
        return round(int(m.group(1)) * 30.48 + int(m.group(2)) * 2.54, 1)
    if m.group(3):
        inches = int(m.group(4)) if m.group(4) else 0
        return round(int(m.group(3)) * 30.48 + inches * 2.54, 1)
    if m.group(5):
        return float(m.group(5))
    return None


def _match_first(text_lower: str, keywords: dict) -> str | None:
    for kw, val in keywords.items():
        if kw in text_lower:
            return val
    return None


def extract_context(text: str) -> dict:
    lower = text.lower()
    return {
        "occasion": _match_first(lower, _OCCASION_KEYWORDS),
        "formality": _match_first(lower, _FORMALITY_KEYWORDS),
        "location": _match_first(lower, _LOCATION_KEYWORDS),
        "time_of_day": _match_first(lower, _TIME_KEYWORDS),
        "date_reference": None,
        "stated_height_cm": _match_height(text),
        "raw_intent": text,
    }
