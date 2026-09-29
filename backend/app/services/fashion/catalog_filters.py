"""
Catalog-level hard filters shared by every recommendation path.

Two things live here because BOTH recommenders (inventory_search.recommend_items
-- the main /api/recommend + Aria `recommend_clothes` path -- and
outfit_recommendation.recommend_outfit) need them and outfit_recommendation
already imports inventory_search, so neither can own them without a cycle:

1. GENDER. The scan (Module 1, DeepFace) produces `gender` = male | female |
   unknown, but until this module existed nothing downstream read it -- a
   male scan was getting saris and tunics (confirmed live). The inventory
   table now has a `gender` column (male | female | unisex | kids, backfilled
   from the source dataset by scripts/backfill_gender.py); for rows that
   haven't been backfilled yet (null), the product name is used instead --
   the Myntra-derived names almost always carry "Men" / "Women" / "Unisex" /
   "Boys" / "Girls" (measured ~92% of a 2,000-row sample), and the rest are
   caught by a few brand-line spellings ("Arrow Woman", "Mens") and garment
   words (sari/saree/kurti are women's wear in this catalog).

2. SAFETY. Underwear/swimwear/sleepwear and kids' items must never surface
   as a styling recommendation. This filter existed in
   outfit_recommendation.py only; the main path didn't apply it and a
   general "style me" set returned a bra (see HANDOFF_MODULE3.md, open
   issue #1). Now applied on every path.
"""
import re

# Same set outfit_recommendation.py used to own -- kept identical so the
# behaviour there doesn't change, just where it's defined.
FORBIDDEN_KEYWORDS = {
    "swimsuit", "swimwear", "bikini", "innerwear", "underwear", "bra", "lingerie",
    "nightwear", "sleepwear", "pyjama", "pajama", "brief", "briefs", "boxer", "boxers",
    "trunks", "camisole", "shapewear", "nightdress", "night suit", "goggles",
}
KIDS_KEYWORDS = {"girl's", "girls", "boy's", "boys", "kid", "kids", "baby", "toddler", "children"}

# Whole-word matching -- "bra" must not match "brand"/"Zebra", "brief" must
# not match "briefcase"-style names (checked: catalog has "Briefs" as a
# standalone word only).
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(FORBIDDEN_KEYWORDS, key=len, reverse=True)) + r")\b")
_KIDS_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(KIDS_KEYWORDS, key=len, reverse=True)) + r")\b")

# Garment/jewellery words that are women's wear in this catalog. Checked
# against the source dataset: earrings 435 Women / 0 Men, kurti 229 / 2,
# clutch 237 / 2. (Bangles deliberately NOT here -- 14 men's kadas exist.)
# A name that matches BOTH lists (e.g. "Men ... Clutch") resolves to
# 'unknown' below, i.e. shown to everyone, so the rare men's clutch is safe.
_FEMALE_RE = re.compile(
    r"\b(women|women's|womens|woman|ladies|lady|female|sari|saree|kurti|kurtis|salwar|lehenga|"
    r"dupatta|earrings?|anklets?|jhumkas?|mangalsutra|clutch)\b"
)
_MALE_RE = re.compile(r"\b(men|men's|mens|man|gents|male)\b")
_UNISEX_RE = re.compile(r"\b(unisex)\b")


def passes_sanity_check(item: dict) -> bool:
    """Reject forbidden (innerwear/swim/sleep) and kids items from ever
    surfacing as a recommendation."""
    name = (item.get("name") or "").lower()
    if _FORBIDDEN_RE.search(name):
        return False
    if _KIDS_RE.search(name):
        return False
    return True


def infer_gender_from_name(name: str | None) -> str:
    """Best-effort gender for a catalog row from its product name only.
    Returns 'male' | 'female' | 'unisex' | 'kids' | 'unknown'. Used both by
    the backfill script (for rows the source dataset can't match) and as the
    live fallback for rows whose `gender` column is still null."""
    n = (name or "").lower()
    if not n:
        return "unknown"
    if _KIDS_RE.search(n):
        return "kids"
    if _UNISEX_RE.search(n):
        return "unisex"
    is_f = bool(_FEMALE_RE.search(n))
    is_m = bool(_MALE_RE.search(n))
    if is_f and not is_m:
        return "female"
    if is_m and not is_f:
        return "male"
    return "unknown"


def normalize_gender(value: str | None) -> str | None:
    """Maps any spelling we might see (scan output, dataset 'Men'/'Women',
    conversation) onto the catalog's own vocabulary. None for unknown/blank
    so callers can use it directly as 'no filter'."""
    v = (value or "").strip().lower()
    if v in ("male", "men", "man", "m", "gents"):
        return "male"
    if v in ("female", "women", "woman", "f", "ladies"):
        return "female"
    if v in ("unisex", "any", "all"):
        return "unisex"
    if v in ("kids", "boys", "girls", "children", "kid"):
        return "kids"
    return None


def item_gender(item: dict) -> str:
    """The row's `gender` column when it's been backfilled, otherwise a
    name-based inference. Never returns None -- 'unknown' when neither works."""
    col = normalize_gender(item.get("gender"))
    if col:
        return col
    return infer_gender_from_name(item.get("name"))


def matches_gender(item: dict, gender: str | None) -> bool:
    """True if this item is appropriate for a customer of `gender`.

    No customer gender (scan said unknown, or no scan) -> everything passes
    except kids' items. With a known gender: that gender's items, unisex
    items, and items we simply can't classify (unknown) all pass -- an
    unclassifiable row is far more likely to be a plain "Lee Navy Slim Fit
    Jeans" than the wrong department, and dropping it would just thin the
    pool. Only the OPPOSITE gender (and kids) is rejected.
    """
    ig = item_gender(item)
    if ig == "kids":
        return False
    want = normalize_gender(gender)
    if want is None or want == "unisex":
        return True
    return ig in (want, "unisex", "unknown")


def apply_catalog_filters(items: list[dict], gender: str | None) -> list[dict]:
    """Sanity + gender filter in one pass, preserving order."""
    return [it for it in items if passes_sanity_check(it) and matches_gender(it, gender)]
