"""
"Show me ONLY what I asked for" -- when the customer names an item type
("saree", "kurti", "heels", "a clutch"), the recommendations contain only
products of that type, still ranked for her scan (skin tone, body shape,
size) and occasion.

Category alone isn't enough: sarees, dresses and gowns all live in the
`dress` category, kurtas and shirts in `top`. So each requested word is
retrieved within its category (when it maps to one) and then filtered on
the product NAME. Words that ARE a whole category ("shoes", "bag",
"jewellery", "clothes") filter by category only.
"""
import re

from app.services.fashion.inventory_search import recommend_items, normalize_category

_CATALOG_CATEGORIES = {"top", "bottom", "dress", "footwear", "bag", "watch", "jewelry", "accessory"}
# Whole-category words: category filter only, no name filter.
_CATEGORY_ONLY = {
    "shoes", "footwear", "bag", "bags", "watch", "watches", "jewellery", "jewelry",
    "accessory", "accessories", "clothes", "clothing", "outfit", "outfits", "attire",
}
# Words with no category at all (whole outfit) -> nothing to narrow.
_NO_FILTER = {"clothes", "clothing", "outfit", "outfits", "attire"}
_SYNONYMS = {
    "saree": r"sar(?:ee|i)s?", "sari": r"sar(?:ee|i)s?",
    "tshirt": r"t-?shirts?|tees?", "t-shirt": r"t-?shirts?|tees?",
    "lehnga": r"lehe?n?gas?", "lehenga": r"lehe?n?gas?",
    "kurti": r"kurti?s?|kurtas?", "kurta": r"kurti?s?|kurtas?",
}
# Garment words normalize_category doesn't know -> their catalog category.
_WORD_CATEGORY = {
    **dict.fromkeys(["heel", "sandal", "flat", "sneaker", "boot", "loafer", "slipper", "jutti",
                     "flip flop", "wedge", "pump"], "footwear"),
    **dict.fromkeys(["kurti", "kurta", "tunic", "blouse", "shirt", "top", "sweater", "hoodie",
                     "jacket", "blazer"], "top"),
    **dict.fromkeys(["saree", "sari", "gown", "jumpsuit", "dress"], "dress"),
    **dict.fromkeys(["skirt", "palazzo", "leggings", "jeans", "trousers", "pants", "shorts",
                     "lehenga", "lehnga"], "bottom"),
    **dict.fromkeys(["clutch", "handbag", "purse", "wallet", "tote", "backpack"], "bag"),
    **dict.fromkeys(["earring", "necklace", "bangle", "bracelet", "ring", "pendant"], "jewelry"),
    **dict.fromkeys(["belt", "sunglasses", "scarf", "stole", "tie", "cap"], "accessory"),
}
_KEEP_PLURAL = {"jeans", "pants", "shorts", "trousers", "leggings", "sunglasses", "palazzos"}
_LABELS = {"saree": "Sarees", "sari": "Sarees", "tshirt": "T-shirts", "t-shirt": "T-shirts"}


def _stem(word: str) -> str:
    w = word.lower()
    if w in _KEEP_PLURAL:
        return w
    if w.endswith(("ches", "shes", "sses")):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _plan(word: str) -> tuple[str | None, re.Pattern | None, str]:
    """(catalog category or None, name pattern or None, section label)."""
    w = word.lower()
    stem = _stem(w)
    category = normalize_category(stem)
    if category not in _CATALOG_CATEGORIES:
        category = _WORD_CATEGORY.get(stem)
    plural = "" if stem in _KEEP_PLURAL else ("es" if stem.endswith(("ch", "sh", "ss", "x")) else "s")
    label = _LABELS.get(stem) or (stem.capitalize() + plural)
    if w in _CATEGORY_ONLY or stem in _CATEGORY_ONLY:
        return category, None, label
    pattern = _SYNONYMS.get(stem) or (re.escape(stem) + r"(?:e?s)?")
    return category, re.compile(r"\b(?:" + pattern + r")\b", re.IGNORECASE), label


def specific_items(requested: list[str] | None) -> list[str]:
    """The requested words that actually narrow the results."""
    return [w for w in (requested or []) if w.lower() not in _NO_FILTER]


def recommend_requested(requested: list[str], per_item: int = 9, **scan_kwargs) -> dict | None:
    """One section per requested item type, containing only that type.
    None when nothing was requested or nothing matched (caller falls back
    to its normal look rather than showing an empty page)."""
    sections, flat = [], []
    for word in specific_items(requested)[:3]:
        category, pattern, label = _plan(word)
        items = []
        for cat in ([category, None] if category else [None]):
            found = recommend_items(category=cat, extra_query_terms=[word], top_k=150, **scan_kwargs)["results"]
            items = [i for i in found if pattern is None or pattern.search(i.get("name") or "")]
            if len(items) >= 2:
                break
        items = items[:per_item]
        if not items:
            continue
        sections.append({"category": category or word, "label": label,
                         "groups": [{"label": label, "items": items}], "items": items})
        flat.extend(items)
    if not sections:
        return None
    return {"mode": "requested_items", "requested_items": requested, "sections": sections, "results": flat}
