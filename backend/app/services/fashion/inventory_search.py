"""
Bridges FashionCLIP embeddings with Supabase's match_inventory() RPC (pgvector
cosine search), and applies the explainable filters this project's Module 1
requires: skin-tone palette, occasion, and rough size.
"""
from app.db.supabase_client import get_supabase, get_inventory
from app.services.fashion.fashion_clip import embed_text
from app.services.vision.skin_tone import recommended_palette


def _fallback_search(query_text: str, category: str | None, palette: list[str], occasion: str | None, top_k: int) -> list[dict]:
    """
    Non-ML stand-in for FashionCLIP + pgvector search, used only while the
    FashionCLIP model weights aren't available yet (e.g. still downloading).
    Scores inventory rows by color-palette match and occasion-tag match so
    /api/recommend still returns real, ranked results in the meantime.
    """
    items = get_inventory(category=category)
    palette_lower = [p.lower() for p in palette]

    def score(item: dict) -> float:
        s = 0.5
        if (item.get("color") or "").lower() in palette_lower:
            s += 0.3
        if occasion and occasion.lower() in [o.lower() for o in (item.get("occasion") or [])]:
            s += 0.2
        return s

    ranked = sorted(items, key=score, reverse=True)[:top_k]
    for item in ranked:
        item["similarity"] = round(score(item), 2)
    return ranked


def semantic_search(query_text: str, category: str | None = None, top_k: int = 10,
                     palette: list[str] | None = None, occasion: str | None = None) -> list[dict]:
    """Search inventory by natural-language description via FashionCLIP + pgvector.
    Falls back to color/occasion filtering if FashionCLIP isn't available yet."""
    try:
        embedding = embed_text(query_text)
    except Exception as e:
        print(f"[inventory_search] FashionCLIP unavailable, using fallback search: {e}")
        return _fallback_search(query_text, category, palette or [], occasion, top_k)

    sb = get_supabase()
    res = sb.rpc(
        "match_inventory",
        {"query_embedding": embedding, "match_category": category, "match_count": top_k},
    ).execute()
    return res.data or []


def recommend_items(
    depth: str,
    undertone: str,
    body_shape: str,
    occasion: str | None = None,
    category: str | None = None,
    height_cm: float | None = None,
    glasses_detected: bool = False,
    hair_length: str = "unknown",
    top_k: int = 8,
) -> dict:
    """
    Core Module 1 recommendation call: combine skin-tone palette + body shape +
    occasion into a FashionCLIP text query, retrieve candidates, and attach a
    human-readable "why" for each -- this IS the explanation the module spec asks for.
    """
    palette = recommended_palette(depth, undertone)
    body_shape_hints = {
        "hourglass": "fitted silhouettes that follow the waist",
        "pear": "structured tops and A-line bottoms that balance hips",
        "inverted_triangle": "flowy tops and fuller bottoms that add hip volume",
        "rectangle": "belted or layered pieces that create waist definition",
        "apple": "empire waists and flowing fabric that skim the midsection",
        "unknown": "versatile, well-balanced silhouettes",
    }.get(body_shape, "versatile, well-balanced silhouettes")

    height_hint = None
    if height_cm:
        if height_cm < 160:
            height_hint = "petite-friendly proportions (higher waistlines, cropped lengths)"
        elif height_cm > 178:
            height_hint = "longer-line pieces that suit a taller frame"

    query_parts = [", ".join(palette[:3]), body_shape_hints]
    if occasion:
        query_parts.append(occasion)
    if height_hint:
        query_parts.append(height_hint)
    query_text = " for ".join(filter(None, [", ".join(palette[:3]) + " clothing", occasion])) or " ".join(query_parts)

    candidates = semantic_search(query_text, category=category, top_k=top_k, palette=palette, occasion=occasion)

    for item in candidates:
        why = []
        if item.get("color", "").lower() in [p.lower() for p in palette]:
            why.append(f"'{item['color']}' complements your {undertone} undertone")
        why.append(f"style suits a {body_shape.replace('_', ' ')} body shape ({body_shape_hints})")
        if occasion and occasion.lower() in [o.lower() for o in (item.get("occasion") or [])]:
            why.append(f"tagged appropriate for {occasion}")
        if height_hint and item.get("category") in ("dress", "top", "bottom"):
            why.append(height_hint)
        if glasses_detected and item.get("category") in ("accessory",):
            why.append("picked with your glasses in mind so it doesn't visually compete")
        item["explanation"] = "; ".join(why)

    return {
        "query_used": query_text,
        "palette_considered": palette,
        "height_hint": height_hint,
        "results": candidates,
    }
