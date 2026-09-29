"""
Weather-aware styling nudges (Module 4 -- was a pure stub: get_weather()
returned a "not built yet" note and nothing ever consumed it).

Two pieces:
  1. get_current_weather() -- real OpenWeatherMap call (free tier), with a
     short in-process cache since weather doesn't change turn-to-turn and
     this shouldn't burn API quota or add latency to every recommendation.
  2. weather_style_hints() -- deterministic weather -> clothing-signal
     mapping (rain avoids open footwear, heat avoids heavy layers, cold
     prefers layers) reused by recommend_clothes to bias results, and by
     the agent's reply to explain WHY a nudge makes sense ("it's raining
     today, so...").

Gracefully degrades to "unavailable" everywhere OPENWEATHER_API_KEY isn't
set -- matches this project's own established pattern (FashionCLIP/DeepFace
missing-weights paths) rather than raising and breaking a recommendation.
"""
import time

import httpx

from app.config import settings

_CACHE_TTL_SECONDS = 1800  # 30 min -- weather-appropriate clothing doesn't need fresher data than this
_cache: dict = {"data": None, "fetched_at": 0.0}


def get_current_weather(location: str | None = None) -> dict | None:
    """Returns {"condition": "Rain", "description": "...", "temp_c": 18.5,
    "is_raining": bool, "is_hot": bool, "is_cold": bool} or None if the
    integration isn't configured / the API call fails. Never raises."""
    if not settings.openweather_api_key:
        return None

    now = time.time()
    if _cache["data"] is not None and (now - _cache["fetched_at"]) < _CACHE_TTL_SECONDS:
        return _cache["data"]

    try:
        resp = httpx.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "q": location or settings.mirror_location,
                "appid": settings.openweather_api_key,
                "units": "metric",
            },
            timeout=5.0,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        print(f"[weather] fetch failed (non-fatal, recommendations proceed without weather bias): {e}")
        return None

    condition = (raw.get("weather") or [{}])[0].get("main", "")  # "Rain", "Clear", "Snow", etc.
    description = (raw.get("weather") or [{}])[0].get("description", "")
    temp_c = raw.get("main", {}).get("temp")

    result = {
        "condition": condition,
        "description": description,
        "temp_c": temp_c,
        "is_raining": condition in ("Rain", "Drizzle", "Thunderstorm"),
        "is_snowing": condition == "Snow",
        "is_hot": temp_c is not None and temp_c >= 30,
        "is_cold": temp_c is not None and temp_c <= 12,
    }
    _cache["data"] = result
    _cache["fetched_at"] = now
    return result


def weather_style_hints(weather: dict | None) -> dict:
    """Deterministic weather -> clothing-signal mapping. Returns:
        {
            "avoid_terms": [...],    # fed into recommend_items()'s existing
                                      # `constraints` param -- text-matched
                                      # against item name/style_tags, same
                                      # mechanism "not too flashy" already uses
            "prefer_terms": [...],   # folded into the Marqo query text as a
                                      # hint, same mechanism style/size/height
                                      # hints already use
            "note": "..." | None,    # human-readable reason, for the agent's reply
        }
    All-empty/None when weather is unavailable or conditions are unremarkable
    (mild, dry, comfortable temp) -- a weather nudge should only ever fire
    when it's genuinely relevant, not every single recommendation.
    """
    if not weather:
        return {"avoid_terms": [], "prefer_terms": [], "note": None}

    avoid, prefer, notes = [], [], []

    if weather.get("is_raining"):
        avoid.append("sandal")
        prefer.append("waterproof")
        notes.append(f"it's rainy today ({weather.get('description', 'rain')})")
    if weather.get("is_snowing"):
        avoid.append("sandal")
        prefer.append("boots")
        notes.append("it's snowing today")
    if weather.get("is_hot"):
        prefer.append("breathable")
        prefer.append("lightweight")
        notes.append(f"it's quite warm out ({round(weather['temp_c'])}°C)")
    if weather.get("is_cold"):
        prefer.append("layered")
        prefer.append("warm")
        notes.append(f"it's cold out ({round(weather['temp_c'])}°C)")

    note = "; ".join(notes) if notes else None
    return {"avoid_terms": avoid, "prefer_terms": prefer, "note": note}
