"""
Outfit completion (Module 3): "here's a top -> want the matching bottom and
shoes?" -- the recommender previously only ever returned a flat list of
individual items scored against a text query. This composes a FULL outfit
around one item the customer has already picked (from cart, tryon, or an
item they just looked at), filling every empty slot (bottom, footwear, bag,
accessory) with a real, compatibility-ranked item.

Reuses the exact same Stage A (Marqo retrieval) + Stage B (compatibility
ranking, see compatibility.py) pipeline recommend_items() already runs --
this just calls it once per missing slot with the primary item as the
anchor, instead of once for a single flat query. No new ML model, no new
embedding space -- same infra, composed differently.
"""
from app.db.supabase_client import get_supabase
from app.services.fashion.inventory_search import semantic_search, _apply_budget_filter, _parse_budget
from app.services.fashion.compatibility import rerank_by_compatibility, compatibility_explanation

# A dress already covers top+bottom -- completing a dress outfit means
# footwear/bag/accessory, not another top or bottom. Anything else gets the
# full slot set minus its own category.
_ALL_SLOTS = ["top", "bottom", "footwear", "bag", "accessory"]
_DRESS_SLOTS = ["footwear", "bag", "accessory"]


def _target_slots(primary_category: str, requested_slots: list[str] | None) -> list[str]:
    if requested_slots:
        return [s for s in requested_slots if s != primary_category]
    if primary_category == "dress":
        return _DRESS_SLOTS
    return [s for s in _ALL_SLOTS if s != primary_category]


def _fetch_primary_item(item_id: str) -> dict | None:
    rows = (
        get_supabase()
        .table("inventory")
        .select("id,name,category,color,style_tags,occasion,embedding,price,image_url")
        .eq("id", item_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def _hydrate_candidates(candidates: list[dict]) -> list[dict]:
    """Same hydration inventory_search.py does for Stage B -- match_inventory's
    RPC doesn't return embedding/style_tags, and compatibility.py needs both."""
    ids = [c["id"] for c in candidates if c.get("id")]
    if not ids:
        return candidates
    try:
        rows = (
            get_supabase()
            .table("inventory")
            .select("id,embedding,style_tags,occasion")
            .in_("id", ids)
            .execute()
            .data or []
        )
        by_id = {r["id"]: r for r in rows}
        for c in candidates:
            extra = by_id.get(c["id"])
            if extra:
                c["embedding"] = extra.get("embedding")
                c["style_tags"] = extra.get("style_tags")
                if not c.get("occasion") and extra.get("occasion"):
                    c["occasion"] = extra["occasion"]
    except Exception as e:
        print(f"[outfit_completion] hydration failed for slot candidates: {e}")
    return candidates


def complete_outfit(
    primary_item_id: str,
    occasion: str | None = None,
    budget: str | float | None = None,
    dismissed_item_ids: list[str] | None = None,
    slots: list[str] | None = None,
) -> dict:
    """Build a full outfit around one item.

    Returns:
        {
            "primary_item": {...},
            "results": [one best-compatibility item per slot, each carrying
                        `slot`, `compatibility_score`, and `explanation`],
            "slots_filled": [...], "slots_missing": [...],
        }
    A slot with no in-stock, budget-fitting candidate is simply left out of
    `results` (and listed in `slots_missing`) rather than forcing a bad
    match -- an empty slot is more honest than a wrong one.
    """
    primary = _fetch_primary_item(primary_item_id)
    if not primary:
        return {"error": f"item {primary_item_id} not found", "results": []}

    occasion = occasion or (primary.get("occasion") or [None])[0]
    budget_value = _parse_budget(budget)
    dismissed_set = set(dismissed_item_ids or [])
    target_slots = _target_slots(primary["category"], slots)

    anchor = [primary]
    results = []
    slots_filled, slots_missing = [], []

    for slot in target_slots:
        query_text = f"{primary.get('color') or ''} {occasion or ''} {slot}".strip() or slot
        candidates = semantic_search(query_text, category=slot, top_k=8, occasion=occasion)
        if dismissed_set:
            candidates = [c for c in candidates if c.get("id") not in dismissed_set]
        if not candidates:
            slots_missing.append(slot)
            continue

        candidates = _hydrate_candidates(candidates)
        ranked = rerank_by_compatibility(candidates, anchor, top_k=3)
        ranked = _apply_budget_filter(ranked, budget_value)
        if not ranked:
            slots_missing.append(slot)
            continue

        best = dict(ranked[0])
        best["slot"] = slot
        comp_line = compatibility_explanation(best, anchor)
        best["explanation"] = comp_line or f"A {slot} that pairs well with the {primary['name']}."
        results.append(best)
        slots_filled.append(slot)

    return {
        "primary_item": {
            "id": primary["id"], "name": primary["name"],
            "category": primary["category"], "color": primary.get("color"),
        },
        "results": results,
        "slots_filled": slots_filled,
        "slots_missing": slots_missing,
    }
