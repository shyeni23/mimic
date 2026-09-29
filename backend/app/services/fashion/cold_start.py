"""
Cold-start personalization (Module 3): a brand-new customer has no body
scan and no conversation history -- recommend_clothes' only prior option
was to trigger a scan and return NOTHING until it completes, leaving the
customer staring at an empty screen for the ~10-20s a scan takes. This
gives her something real and relevant immediately.

Two tiers, in order:
  1. TRENDING -- cross-session engagement (click/add_to_cart/tryon) via the
     trending_items() RPC (see schema.sql). This is real store-wide
     popularity, not personalization of a specific returning customer --
     no user_id/cross-session identity involved.
  2. CURATED VARIETY -- fallback for when there isn't enough interaction
     volume yet to trust tier 1 (true today: this is a fresh catalog with
     thin interaction history). Pulls a spread across categories so the
     customer sees a real cross-section of the store instead of an
     accidentally narrow slice, sorted by stock (favor what's actually
     available) rather than any relevance signal we don't have yet.

Both tiers respect occasion/category filters when the customer has already
said something conversationally, so cold-start still narrows toward
relevance instead of being purely generic.
"""
from app.db.supabase_client import get_supabase

_VARIETY_CATEGORIES = ["top", "bottom", "dress", "footwear", "bag", "accessory", "watch", "jewelry"]


def _curated_variety(category: str | None, occasion: str | None, top_k: int) -> list[dict]:
    """Tier 2 fallback -- spread across categories (or just the one
    requested), sorted by stock so what's shown is genuinely available."""
    sb = get_supabase()
    categories = [category] if category else _VARIETY_CATEGORIES
    per_category = max(1, top_k // len(categories))
    results = []
    for cat in categories:
        q = sb.table("inventory").select("id,name,category,color,occasion,image_url,price,stock,created_at,season,year").eq("category", cat).gt("stock", 0)
        if occasion:
            q = q.contains("occasion", [occasion])
        rows = q.order("stock", desc=True).limit(per_category).execute().data or []
        results.extend(rows)
    return results[:top_k]


def get_cold_start_recommendations(
    category: str | None = None,
    occasion: str | None = None,
    top_k: int = 8,
) -> dict:
    """Returns {"results": [...], "source": "trending"|"curated_variety"}.
    `results` items are shaped like recommend_items()'s output (id, name,
    category, color, price, image_url) so the SAME frontend rendering path
    (show_recommendations action) and the SAME explanation-building
    convention work unchanged -- this is a different SOURCE of candidates,
    not a different consumer-facing shape.
    """
    sb = get_supabase()
    try:
        trending = sb.rpc("trending_items", {
            "match_category": category, "match_occasion": occasion,
            "days_back": 30, "match_count": top_k,
        }).execute().data or []
    except Exception as e:
        print(f"[cold_start] trending_items RPC failed, falling back to curated variety: {e}")
        trending = []

    from app.services.fashion.trends import annotate_trend_signals, trend_explanation_fragment

    # Tier 1 only trusted once there's enough real signal -- a single
    # engaged item isn't "trending," it's noise. Require at least half the
    # requested count before using it as the sole source.
    if len(trending) >= max(3, top_k // 2):
        annotate_trend_signals(trending, category=category, occasion=occasion)
        for r in trending:
            r["explanation"] = "Popular pick right now while we get to know your style."
            new_note = trend_explanation_fragment(r)
            if new_note and "trending" not in new_note:  # avoid saying "trending" twice
                r["explanation"] += f" ({new_note})"
        return {"results": trending, "source": "trending"}

    variety = _curated_variety(category, occasion, top_k)
    annotate_trend_signals(variety, category=category, occasion=occasion)
    for r in variety:
        r["explanation"] = "A great option to start with while we learn your style."
        trend_note = trend_explanation_fragment(r)
        if trend_note:
            r["explanation"] += f" ({trend_note})"
    return {"results": variety, "source": "curated_variety"}
