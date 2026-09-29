"""
Bridges FashionCLIP embeddings with Supabase's match_inventory() RPC (pgvector
cosine search), and applies the explainable filters this project's Module 1
requires: skin-tone palette, occasion, style, size, and user constraints.

style/constraints/size support added after an audit against the project's
reference doc found recommend_items() was silently ignoring three of the
five scoring factors the doc calls for ("body-shape suitability, color
compatibility, occasion, style and user constraints") -- style and
constraints weren't parameters at all, and body_size_estimate was captured
by the CV scan but never read downstream. No external repo covers this
(searched and confirmed empty -- see the project's own record of that
search); this is built in-house per the reference doc's own "Implementation
Principle" section.

budget support added the same way, after auditing the conversational agent's
own extraction schema (app/services/agent/graph.py's ConversationState) found
it captures `budget` from the customer every turn but nothing downstream ever
read it -- recommend_items() had no budget parameter at all, so a customer
saying "around Rs.5000" had zero effect on what got recommended. Also closes a
related gap: neither this module nor get_inventory() filtered on stock, so an
out-of-stock item could be recommended -- see get_inventory()'s in_stock_only
default and match_inventory's own `stock > 0` filter (schema.sql).
"""
import re

from app.db.supabase_client import get_supabase, get_inventory
from app.services.fashion.catalog_filters import apply_catalog_filters, normalize_gender
from app.services.fashion.fashion_clip import embed_text
from app.services.vision.skin_tone import recommended_palette

# Flipped to False the first time match_inventory rejects `match_gender` --
# i.e. the DB hasn't had module3_missing_migrations.sql section 2d applied
# yet. Retrieval then runs unfiltered and gender is enforced in Python only
# (apply_catalog_filters), which still gives correct results, just from a
# pool that had to be fetched wider. Logged once so it's not silent.
_RPC_SUPPORTS_GENDER = True


def _matches_constraint(item: dict, constraint: str) -> bool:
    """True if an item's name/style_tags mention a thing the customer said
    to avoid (e.g. 'heavy embroidery', 'flashy')."""
    constraint_lower = constraint.lower()
    name = (item.get("name") or "").lower()
    tags = " ".join(str(t) for t in (item.get("style_tags") or [])).lower()
    return constraint_lower in name or constraint_lower in tags


def _matches_style(item: dict, style: str) -> bool:
    style_lower = style.lower()
    name = (item.get("name") or "").lower()
    tags = [str(t).lower() for t in (item.get("style_tags") or [])]
    return style_lower in name or style_lower in tags


def _size_hint_text(size: str | None) -> str | None:
    """Turns a body_size_estimate (XS/S/M/L/XL/XXL) into a query-text hint.
    Unknown/missing size returns None -- never guessed."""
    if not size or size == "unknown":
        return None
    return {
        "XS": "extra small fit", "S": "small fit", "M": "medium fit",
        "L": "large fit", "XL": "extra large fit", "XXL": "plus size fit",
    }.get(size)


def _fallback_search(
    query_text: str, category: str | None, palette: list[str], occasion: str | None,
    style: str | None, constraints: list[str] | None, top_k: int,
    gender: str | None = None,
) -> list[dict]:
    """
    Non-ML stand-in for FashionCLIP + pgvector search, used only while the
    FashionCLIP model weights aren't available yet (e.g. still downloading).
    Scores inventory rows by color-palette, occasion-tag, style-tag match and
    constraint-avoidance so /api/recommend still returns real, ranked results
    in the meantime -- and now actually reflects style/constraints too.
    get_inventory() defaults to in_stock_only=True, so this never surfaces an
    item that isn't actually purchasable.
    """
    items = apply_catalog_filters(get_inventory(category=category, include_embedding=False), gender)
    palette_lower = [p.lower() for p in palette]
    constraints = constraints or []

    def score(item: dict) -> float:
        s = 0.5
        if (item.get("color") or "").lower() in palette_lower:
            s += 0.3
        if occasion and occasion.lower() in [o.lower() for o in (item.get("occasion") or [])]:
            s += 0.2
        if style and _matches_style(item, style):
            s += 0.15
        for c in constraints:
            if c and _matches_constraint(item, c):
                s -= 0.25
        return s

    ranked = sorted(items, key=score, reverse=True)[:top_k]
    for item in ranked:
        item["similarity"] = round(score(item), 2)
    return ranked


def semantic_search(query_text: str, category: str | None = None, top_k: int = 10,
                     palette: list[str] | None = None, occasion: str | None = None,
                     style: str | None = None, constraints: list[str] | None = None,
                     gender: str | None = None) -> list[dict]:
    """Search inventory by natural-language description via FashionCLIP + pgvector.
    Falls back to color/occasion/style/constraint filtering if FashionCLIP isn't
    available yet -- the fallback is the only path that can apply style/constraints
    directly (pgvector search encodes them into query_text instead; see recommend_items).
    Both paths only ever return in-stock items: the fallback via get_inventory()'s
    in_stock_only default, the pgvector RPC via match_inventory's own `stock > 0`
    filter (see schema.sql) -- neither can surface something that isn't purchasable.

    gender ('male' | 'female', from the body scan) is pushed down into the RPC
    so the similarity ranking happens over the right department -- filtering
    afterwards in Python would mean a top-8 that was mostly the wrong gender
    gets cut to 1-2 items. Rows with a null gender column (not yet backfilled)
    and unisex rows always pass at the SQL level; apply_catalog_filters then
    does the name-based check on those in Python."""
    global _RPC_SUPPORTS_GENDER
    gender = normalize_gender(gender)
    if gender == "unisex":
        gender = None
    try:
        embedding = embed_text(query_text)
    except Exception as e:
        print(f"[inventory_search] FashionCLIP unavailable, using fallback search: {e}")
        return _fallback_search(query_text, category, palette or [], occasion, style, constraints, top_k, gender=gender)

    sb = get_supabase()
    params = {"query_embedding": embedding, "match_category": category, "match_count": top_k}
    if gender and _RPC_SUPPORTS_GENDER:
        try:
            res = sb.rpc("match_inventory", {**params, "match_gender": gender}).execute()
            return res.data or []
        except Exception as e:
            # PostgREST 404 "function match_inventory(...) does not exist" /
            # PGRST202 = migration 2d not applied. Anything else is a real
            # error and should surface normally on the retry below.
            msg = str(e)
            if "match_gender" in msg or "PGRST202" in msg or "does not exist" in msg:
                _RPC_SUPPORTS_GENDER = False
                print(
                    "[inventory_search] match_inventory has no match_gender parameter -- run "
                    "module3_missing_migrations.sql section 6. Falling back to Python-side gender filtering."
                )
            else:
                raise
    res = sb.rpc("match_inventory", params).execute()
    return res.data or []


def _parse_budget(budget: str | float | None) -> float | None:
    """Pulls a numeric ceiling out of whatever the conversation extracted
    (e.g. '5000', '₹5,000', 'around 5000', 'under 3k'). Returns None if
    nothing numeric is present -- an unparseable budget is never guessed at,
    just dropped as a filter."""
    if budget is None:
        return None
    if isinstance(budget, (int, float)):
        return float(budget)
    match = re.search(r"[\d,]+(\.\d+)?", str(budget))
    if not match:
        return None
    raw = match.group(0).replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    if "k" in str(budget).lower():
        value *= 1000
    return value


def _apply_budget_filter(candidates: list[dict], budget: float | None) -> list[dict]:
    """Hard-prefers in-budget items, but never silently returns an empty
    result just because everything found is slightly over -- the agent needs
    something real to talk about ("closest option is a bit over budget")
    rather than a dead end. Every item gets `within_budget` so the caller/LLM
    can be honest about which case it's in."""
    if budget is None:
        for item in candidates:
            item["within_budget"] = None
        return candidates

    for item in candidates:
        price = item.get("price")
        item["within_budget"] = (price is not None and price <= budget)

    in_budget = [c for c in candidates if c["within_budget"]]
    if in_budget:
        return in_budget

    # Nothing fits -- surface the closest-priced items instead of nothing,
    # so the agent can honestly say "a bit over your budget" rather than
    # inventing an in-budget item that doesn't exist.
    priced = [c for c in candidates if c.get("price") is not None]
    return sorted(priced, key=lambda c: c["price"])[:3]


# Categories that finish a look rather than being the main garment.
_ACCESSORY_CATEGORIES = ("footwear", "bag", "jewelry", "watch", "accessory")
_GARMENT_CATEGORIES = ("top", "bottom", "dress")

# inventory.category is a fixed vocabulary (see schema.sql / seed script);
# callers -- the Recommendations page's filter chips ("Tops", "Shoes"), Aria's
# tool args ("handbag", "sneakers") -- use natural words. Confirmed live that
# the page's "Tops" chip sent category="tops" and got zero rows back.
_CATEGORY_ALIASES = {
    "top": "top", "tops": "top", "shirt": "top", "shirts": "top", "tshirt": "top", "t-shirt": "top",
    "t-shirts": "top", "tee": "top", "tees": "top", "kurta": "top", "kurtas": "top", "jacket": "top",
    "jackets": "top", "blazer": "top", "sweater": "top", "sweaters": "top",
    "bottom": "bottom", "bottoms": "bottom", "pants": "bottom", "trousers": "bottom", "jeans": "bottom",
    "skirt": "bottom", "skirts": "bottom", "shorts": "bottom", "leggings": "bottom",
    "dress": "dress", "dresses": "dress", "saree": "dress", "sarees": "dress", "sari": "dress",
    "footwear": "footwear", "shoes": "footwear", "shoe": "footwear", "sneakers": "footwear",
    "sandals": "footwear", "heels": "footwear", "boots": "footwear", "flats": "footwear",
    "bag": "bag", "bags": "bag", "handbag": "bag", "handbags": "bag", "backpack": "bag", "wallet": "bag",
    "wallets": "bag", "clutch": "bag",
    "watch": "watch", "watches": "watch",
    "jewelry": "jewelry", "jewellery": "jewelry", "earrings": "jewelry", "necklace": "jewelry",
    "bracelet": "jewelry", "ring": "jewelry",
    "accessory": "accessory", "accessories": "accessory", "belt": "accessory", "belts": "accessory",
    "sunglasses": "accessory", "scarf": "accessory", "scarves": "accessory", "cap": "accessory",
    "hat": "accessory", "tie": "accessory", "socks": "accessory",
}
CATEGORY_LABELS = {
    "top": "Tops", "bottom": "Bottoms", "dress": "Dresses", "footwear": "Footwear",
    "bag": "Bags", "watch": "Watches", "jewelry": "Jewellery", "accessory": "Accessories",
}
# What CLIP is asked for per category -- "watches" ranks watches by the
# palette far better than "clothing" does with a category filter bolted on.
_CATEGORY_NOUN = {
    "top": "tops and shirts", "bottom": "trousers, jeans and bottoms", "dress": "dresses",
    "footwear": "shoes", "bag": "bags", "watch": "watches", "jewelry": "jewellery",
    "accessory": "accessories such as belts, sunglasses and scarves",
}
# The sections a post-scan "complete look" is built from, per department.
# Men's jewellery is ~1% of the catalog and almost entirely unclassifiable
# by name, so it's left out of the men's plan rather than risk earrings.
_LOOK_PLAN = {
    "female": ["top", "bottom", "dress", "footwear", "bag", "watch", "jewelry", "accessory"],
    "male": ["top", "bottom", "footwear", "bag", "watch", "accessory"],
    None: ["top", "bottom", "dress", "footwear", "bag", "watch", "jewelry", "accessory"],
}


# Persistent worker pool for recommend_complete_look. Long-lived threads
# matter here: get_supabase() is thread-local, so a fresh pool per call
# meant a fresh client (and TCP/TLS setup) per section per call -- reusing
# the threads reuses their pooled connections.
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
_LOOK_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="look")


CLOTHES_CATEGORIES = ("top", "bottom", "dress")
ALL_ITEM_CATEGORIES = ("top", "bottom", "dress", "footwear", "bag", "watch", "jewelry", "accessory")

# Free-text item words -> the categories they ask for. Used when the customer
# answers "what should I include?" ("suggest heels also", "a dress, bag and
# heels", "only clothes") -- see parse_requested_items.
_ITEM_PHRASES = {
    "clothes": CLOTHES_CATEGORIES, "clothing": CLOTHES_CATEGORIES, "clothe": CLOTHES_CATEGORIES,
    "outfit": CLOTHES_CATEGORIES, "outfits": CLOTHES_CATEGORIES, "garments": CLOTHES_CATEGORIES,
    "dress": ("dress",), "dresses": ("dress",), "saree": ("dress",), "sari": ("dress",),
    "gown": ("dress",), "lehenga": ("dress",),
    "top": ("top",), "tops": ("top",), "shirt": ("top",), "shirts": ("top",), "kurta": ("top",),
    "kurti": ("top",), "tshirt": ("top",), "t-shirt": ("top",), "tee": ("top",), "blouse": ("top",),
    "jacket": ("top",), "blazer": ("top",), "sweater": ("top",),
    "bottom": ("bottom",), "bottoms": ("bottom",), "jeans": ("bottom",), "trouser": ("bottom",),
    "trousers": ("bottom",), "pant": ("bottom",), "pants": ("bottom",), "skirt": ("bottom",),
    "skirts": ("bottom",), "leggings": ("bottom",), "shorts": ("bottom",), "capri": ("bottom",),
    "footwear": ("footwear",), "shoe": ("footwear",), "shoes": ("footwear",), "heel": ("footwear",),
    "heels": ("footwear",), "sandal": ("footwear",), "sandals": ("footwear",), "flats": ("footwear",),
    "sneakers": ("footwear",), "boots": ("footwear",), "wedges": ("footwear",), "pumps": ("footwear",),
    "bag": ("bag",), "bags": ("bag",), "handbag": ("bag",), "handbags": ("bag",), "purse": ("bag",),
    "clutch": ("bag",), "tote": ("bag",), "backpack": ("bag",), "wallet": ("bag",), "sling": ("bag",),
    "watch": ("watch",), "watches": ("watch",),
    "jewellery": ("jewelry",), "jewelry": ("jewelry",), "earring": ("jewelry",),
    "earrings": ("jewelry",), "necklace": ("jewelry",), "bangle": ("jewelry",),
    "bangles": ("jewelry",), "bracelet": ("jewelry",), "ring": ("jewelry",), "rings": ("jewelry",),
    # "accessories" in a customer's mouth means the finishing pieces, which in
    # this catalog live in BOTH the accessory (belts/sunglasses/scarves) and
    # jewelry categories.
    "accessory": ("accessory", "jewelry"), "accessories": ("accessory", "jewelry"),
    "belt": ("accessory",), "belts": ("accessory",), "sunglasses": ("accessory",),
    "shades": ("accessory",), "scarf": ("accessory",), "scarves": ("accessory",),
    "cap": ("accessory",), "hat": ("accessory",), "tie": ("accessory",), "socks": ("accessory",),
}
_EVERYTHING_WORDS = ("everything", "all of it", "all items", "the whole look", "full look",
                     "complete look", "anything", "whatever", "all", "surprise me")
_NOTHING_ELSE_WORDS = ("only clothes", "just clothes", "clothes only", "nothing else",
                       "no accessories", "just the clothes", "only the clothes", "only outfit")


def parse_requested_items(text: str | None) -> list[str] | None:
    """Which item categories the customer asked to be shown.

    Returns a canonical-ordered list of inventory categories, or None for
    "no preference stated" (caller decides its own default). Examples:
        "suggest heels also"            -> [top, bottom, dress, footwear]
        "a dress, bag and heels"        -> [dress, footwear, bag]
        "only clothes"                  -> [top, bottom, dress]
        "everything"                    -> all eight categories
    "also"/"too" means ADD to the clothes (see the customer's own example:
    "Suggest heels also" -> clothes AND heels), whereas naming garments
    explicitly ("a dress, bag and heels") means exactly those.
    """
    if not text:
        return None
    t = " " + re.sub(r"[^a-z0-9\s-]", " ", text.lower()) + " "
    if any(w in t for w in _NOTHING_ELSE_WORDS):
        return list(CLOTHES_CATEGORIES)
    if any(f" {w} " in t or t.strip() == w for w in _EVERYTHING_WORDS):
        return list(ALL_ITEM_CATEGORIES)

    found: set[str] = set()
    named_garment = False
    for word, cats in _ITEM_PHRASES.items():
        if re.search(rf"\b{re.escape(word)}\b", t):
            found.update(cats)
            if set(cats) & set(CLOTHES_CATEGORIES):
                named_garment = True
    if not found:
        return None
    # "...also" / "...too" / "with" = in ADDITION to the clothes.
    if not named_garment and re.search(r"\b(also|too|as well|with|plus|along)\b", t):
        found.update(CLOTHES_CATEGORIES)
    return [c for c in ALL_ITEM_CATEGORIES if c in found]


def body_shape_hint(body_shape: str | None, gender: str | None) -> str:
    """Stylist wording for a body shape, per department -- also used by
    styled_look.py. The women's wording ("belted", "A-line") is real advice
    but retrieves belts when fed to CLIP for a men's search."""
    if gender == "male":
        return {
            "hourglass": "tailored, fitted cuts that follow the torso",
            "pear": "structured jackets and straight-leg trousers that balance the hips",
            "inverted_triangle": "straight-cut shirts and fuller-fit trousers that balance broad shoulders",
            "rectangle": "layered pieces and structured shoulders that add shape",
            "apple": "vertical lines and straight-fit shirts worn untucked",
        }.get(body_shape or "", "versatile, well-balanced cuts")
    return {
        "hourglass": "fitted silhouettes that follow the waist",
        "pear": "structured tops and A-line bottoms that balance hips",
        "inverted_triangle": "flowy tops and fuller bottoms that add hip volume",
        "rectangle": "belted or layered pieces that create waist definition",
        "apple": "empire waists and flowing fabric that skim the midsection",
    }.get(body_shape or "", "versatile, well-balanced silhouettes")


def normalize_category(category: str | None) -> str | None:
    """Maps any caller spelling onto inventory.category. Unknown words pass
    through unchanged (an explicit but unrecognised category should return
    nothing rather than silently everything)."""
    if not category:
        return None
    key = category.strip().lower()
    return _CATEGORY_ALIASES.get(key, key)


# Customer words -> the real occasion tags in inventory (casual, ethnic,
# formal, office, party, smart casual, sports, travel, wedding). Order
# matters: first match wins, so specific events come before generic words.
_OCCASION_WORDS = [
    ("wedding", r"wedding|marriage|shaadi|shadi|engagement|reception|sangeet|mehendi|mehndi|haldi|bridal"),
    ("ethnic", r"ethnic|traditional|festival|festive|diwali|puja|pooja|eid|navratri|garba|holi|temple"),
    ("party", r"party|club|clubbing|birthday|cocktail|night\s*out|date|dinner|celebration"),
    ("office", r"office|work|meeting|interview|presentation|corporate"),
    ("smart casual", r"smart[\s-]*casual|brunch|semi[\s-]*formal"),
    ("formal", r"formal|business|conference|gala"),
    ("sports", r"sports?|gym|workout|running|yoga|training|athletic"),
    ("travel", r"travel|trip|vacation|holiday|beach|tour|airport"),
    ("casual", r"casual|everyday|daily|college|hangout|weekend|shopping|movie"),
]


def normalize_occasion(occasion: str | list | None) -> str | None:
    """Maps whatever the customer said ("my sister's wedding", "Party",
    ["engagement"]) onto one real inventory occasion tag, or None when it
    names nothing we stock -- an unrecognised occasion must not become a
    strict filter that empties the page."""
    if isinstance(occasion, list):
        occasion = " ".join(str(o) for o in occasion if o)
    if not occasion or not str(occasion).strip():
        return None
    text = str(occasion).lower()
    for tag, pattern in _OCCASION_WORDS:
        if re.search(rf"\b(?:{pattern})\b", text):
            return tag
    return None


def recommend_look_for_occasion(strict_occasion: bool = False, **kwargs) -> dict:
    """recommend_complete_look, but a strict occasion filter that leaves the
    page EMPTY falls back to occasion-as-preference -- showing nothing is
    worse than showing the closest matches."""
    result = recommend_complete_look(strict_occasion=strict_occasion, **kwargs)
    if strict_occasion and not result.get("results"):
        print(f"[occasion] strict '{kwargs.get('occasion')}' returned nothing -- relaxing")
        result = recommend_complete_look(strict_occasion=False, **kwargs)
        result["occasion_relaxed"] = True
    return result


# Share of an unfiltered "style me" set that should be accessories -- enough
# that the set reads as a complete look, not so many that clothes get
# crowded out. 0.35 of 8 -> 3 accessories, 5 garments.
_ACCESSORY_SHARE = 0.35


def _dedupe_by_name(candidates: list[dict]) -> list[dict]:
    """Keep only the best-ranked item per product name.

    The catalog contains genuinely distinct rows that share one product name
    (~12% of it -- same duplication scripts/backfill_season_year.py had to
    handle), so one similarity search can return "Royal Diadem Rust
    Earrings" two or three times over. Different ids, but to a customer it
    just looks like the recommender repeated itself. Confirmed live.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for c in candidates:
        key = (c.get("name") or "").strip().lower()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(c)
    return out


def _merge_accessory_coverage(
    candidates: list[dict], accessory_query: str, palette: list[str],
    occasion: str | None, style: str | None, constraints: list[str] | None,
    top_k: int, gender: str | None = None,
) -> list[dict]:
    """Ensure an uncategorized recommendation set spans garments AND
    accessories (see the call site for why a single search doesn't).

    Interleaves rather than appends: recommend_items slices to top_k further
    down, so accessories tacked onto the end would all be cut back off.
    Anything beyond top_k is still kept on the end as headroom for the
    skip-penalty and budget filters that run after this.
    """
    target = max(1, round(top_k * _ACCESSORY_SHARE))
    garments = [c for c in candidates if c.get("category") not in _ACCESSORY_CATEGORIES]
    # One accessory per category from the MAIN search; the rest go to an
    # overflow list used only if the accessory-worded search below can't
    # fill the slots. Without this, a "belted pieces" body-shape hint
    # (rectangle) returned four belts in one men's set and the top-up
    # search never ran because len(accessories) was already >= target.
    accessories: list[dict] = []
    overflow: list[dict] = []
    for c in candidates:
        if c.get("category") not in _ACCESSORY_CATEGORIES:
            continue
        if c.get("category") in {a.get("category") for a in accessories}:
            overflow.append(c)
        else:
            accessories.append(c)

    if len(accessories) < target:
        # accessory_query is the same palette/occasion/style context worded
        # for accessories and WITHOUT the body-shape hint -- CLIP ranks on
        # what the text says, and "straight-cut shirts and fuller-fit
        # trousers" in the query returned 48 shirts and zero accessories.
        try:
            extra = apply_catalog_filters(semantic_search(
                accessory_query, category=None, top_k=top_k * 6, palette=palette,
                occasion=occasion, style=style, constraints=constraints, gender=gender,
            ), gender)
        except Exception as e:
            print(f"[recommend_items] accessory coverage search failed (non-fatal): {e}")
            extra = []
        seen_ids = {c.get("id") for c in candidates}
        seen_names = {(c.get("name") or "").strip().lower() for c in candidates}
        # Spread the accessory slots ACROSS accessory types rather than
        # filling them all from whichever type the palette happens to match
        # best -- unconstrained, a rust/gold palette returned three
        # earrings and no shoes or bag, which doesn't read as a finished
        # look. One pass capped at 1 per category, then a second pass to
        # top up if some categories had nothing.
        used_categories = {c.get("category") for c in accessories}
        for cap in (1, None):
            for c in extra:
                if len(accessories) >= target:
                    break
                cat = c.get("category")
                if cat not in _ACCESSORY_CATEGORIES:
                    continue
                name = (c.get("name") or "").strip().lower()
                if c.get("id") in seen_ids or (name and name in seen_names):
                    continue
                if cap is not None and cat in used_categories:
                    continue
                accessories.append(c)
                seen_ids.add(c.get("id"))
                if name:
                    seen_names.add(name)
                used_categories.add(cat)
            if len(accessories) >= target:
                break

    # Still short (thin catalog for this palette)? Fall back to the
    # same-category extras rather than leaving slots empty.
    if len(accessories) < target:
        accessories.extend(overflow[: target - len(accessories)])

    if not accessories:
        return candidates

    stride = max(2, round(1 / _ACCESSORY_SHARE))  # every ~3rd slot
    merged: list[dict] = []
    gi = ai = 0
    for slot in range(top_k):
        if (slot + 1) % stride == 0 and ai < min(len(accessories), target):
            merged.append(accessories[ai]); ai += 1
        elif gi < len(garments):
            merged.append(garments[gi]); gi += 1
        elif ai < len(accessories):
            merged.append(accessories[ai]); ai += 1
    merged.extend(garments[gi:])
    merged.extend(accessories[ai:])
    print(
        f"[recommend_items] category coverage: {len(accessories)} accessory candidates "
        f"merged with {len(garments)} garments (target {target} of top {top_k})"
    )
    return merged


def recommend_items(
    depth: str,
    undertone: str,
    body_shape: str,
    occasion: str | None = None,
    category: str | None = None,
    height_cm: float | None = None,
    glasses_detected: bool = False,
    hair_length: str = "unknown",
    style: str | None = None,
    constraints: list[str] | None = None,
    size: str | None = None,
    budget: str | float | None = None,
    top_k: int = 8,
    dismissed_item_ids: list[str] | None = None,
    anchor_items: list[dict] | None = None,
    extra_query_terms: list[str] | None = None,
    session_id: str | None = None,
    gender: str | None = None,
) -> dict:
    """
    Core Module 1 recommendation call: combine skin-tone palette + body shape +
    occasion + style + constraints + size into a FashionCLIP text query, retrieve
    candidates, and attach a human-readable "why" for each -- this IS the
    explanation the module spec asks for.

    style/constraints/size were added after an audit found the reference doc's
    five stated scoring factors ("body-shape suitability, color compatibility,
    occasion, style and user constraints") weren't all actually wired in --
    style and constraints weren't parameters at all, and size (captured by the
    CV scan as body_size_estimate) was never read downstream. No usable
    external repo exists for body-shape/style/constraint scoring on structured
    metadata (searched and confirmed empty), so this is built in-house.

    budget: whatever free-form string the conversation extracted (e.g. '5000',
    '₹5,000') -- parsed via _parse_budget and applied as a post-filter (see
    _apply_budget_filter) after candidates come back, since neither the
    pgvector RPC nor the fallback scorer has a native price constraint. Every
    returned item carries `within_budget` (None if no budget was given) so the
    agent/LLM can speak accurately about which case it's in rather than
    guessing.

    gender: the scan's DeepFace label ('male' | 'female' | 'unknown'). This is
    the single biggest "based on the scan" signal and was never wired in --
    without it a male customer's set was saris and tunics (confirmed live).
    'unknown' (low-confidence detection) means no gender filtering at all,
    never a guess. See catalog_filters.py for how items are classified.
    """
    gender = normalize_gender(gender)
    if gender not in ("male", "female"):
        gender = None
    category = normalize_category(category)
    # Body-shape / size / height advice is about garments. For a watch or a
    # bag search it only pollutes the CLIP query and produces nonsense
    # explanations ("this watch suits a pear body shape").
    is_garment_search = category is None or category in _GARMENT_CATEGORIES
    palette = recommended_palette(depth, undertone)
    # Body-shape advice is phrased per department: the women's wording
    # ("belted", "A-line", "empire waist") is real stylist language, but fed
    # to CLIP for a men's search it just retrieves belts (observed: a men's
    # rectangle set came back as 4 belts + 4 tees).
    body_shape_hints = body_shape_hint(body_shape, gender)

    height_hint = None
    if height_cm:
        if height_cm < 160:
            height_hint = "petite-friendly proportions (higher waistlines, cropped lengths)"
        elif height_cm > 178:
            height_hint = "longer-line pieces that suit a taller frame"

    size_hint = _size_hint_text(size)
    constraints = constraints or []

    # NOTE: this used to build a `query_parts` list containing style/size/height
    # hints, then do `" for ".join(filter(None, [palette_text, occasion])) or
    # " ".join(query_parts)` -- the left side was ALWAYS truthy (palette text is
    # never empty), so that `or` fallback could never actually trigger.
    # style/constraints/size were being computed but silently never reaching
    # the real search query. Fixed: build one query string that genuinely
    # includes every part that's present, each added exactly once.
    # Department word goes first -- CLIP ranks on what the text says, and
    # "men's" / "women's" is the strongest single token for keeping the
    # similarity ordering itself (not just the post-filter) on the right side
    # of the catalog.
    department = {"male": "men's ", "female": "women's "}.get(gender, "")
    noun = _CATEGORY_NOUN.get(category, "clothing")
    query_text = department + ", ".join(palette[:3]) + f" {noun}"
    accessory_query = department + ", ".join(palette[:3]) + " accessories, shoes and bags"
    if occasion:
        query_text += f" for {occasion}"
        accessory_query += f" for {occasion}"
    if is_garment_search:
        query_text += f", {body_shape_hints}"
    if style:
        query_text += f", {style} style"
        accessory_query += f", {style} style"
    if size_hint and is_garment_search:
        query_text += f", {size_hint}"
    if height_hint and is_garment_search:
        query_text += f", {height_hint}"
    for term in (extra_query_terms or []):
        if term:
            query_text += f", {term}"
    for c in constraints:
        if c:
            query_text += f", not {c}"

    budget_value = _parse_budget(budget)
    # Fetch a wider pool when a budget is set so filtering down to in-budget
    # items still leaves enough to rank -- top_k alone (ranked by similarity,
    # not price) could easily be all over-budget even when cheaper matches exist.
    fetch_k = top_k * 3 if budget_value is not None else top_k

    dismissed_set = set(dismissed_item_ids or [])
    from app.services.fashion.feedback_signals import MIN_SKIPS_FOR_SIGNAL
    skip_signal_active = len(dismissed_set) >= MIN_SKIPS_FOR_SIGNAL
    # Fetch more when we'll be filtering exact dismissed ids AND/OR
    # penalty-filtering near-duplicates of the skip pattern -- the latter
    # can remove more than just the exact matches, so needs extra headroom.
    # Also widen when there are hard constraints to post-filter (see below).
    if dismissed_set:
        fetch_k = max(fetch_k, top_k * (4 if skip_signal_active else 3))
    if constraints:
        fetch_k = max(fetch_k, top_k * 3)
    # The sanity filter (no innerwear/kids) and the Python-side gender check
    # both drop rows AFTER retrieval, so always fetch some headroom -- and a
    # lot more when the RPC can't pre-filter by gender itself.
    fetch_k = max(fetch_k, top_k * 2)
    if gender and not _RPC_SUPPORTS_GENDER:
        fetch_k = max(fetch_k, top_k * 6)

    candidates = semantic_search(
        query_text, category=category, top_k=fetch_k, palette=palette,
        occasion=occasion, style=style, constraints=constraints, gender=gender,
    )
    # HARD SAFETY + GENDER FILTER, before anything else looks at the pool:
    # no bras/briefs/swimwear/kids' items on any path (this was only ever
    # applied in outfit_recommendation.py -- a "style me" set returned
    # "Biara Women Orange Blush Bra" live), and nothing from the opposite
    # department to what the scan saw.
    candidates = apply_catalog_filters(candidates, gender)
    # Applies on every path, not just the uncategorized one -- "show me
    # tops" can return the same duplicate-named row twice just as easily.
    candidates = _dedupe_by_name(candidates)

    # RECALL SAFETY NET for a single-category search: pgvector's HNSW scan
    # applies the category/gender WHERE clause AFTER collecting its
    # ef_search nearest rows, so a small slice of the catalog (men's
    # bottoms ~3%) can come back with 0-2 rows no matter what match_count
    # says -- a complete look lost its whole Bottoms section live.
    # migrations section 7 fixes the RPC itself; this keeps the section
    # populated regardless, by topping up from an exact palette/occasion
    # scan of that category (same scorer the no-FashionCLIP fallback uses).
    if category and len(candidates) < top_k:
        try:
            have = {c.get("id") for c in candidates}
            extra = [
                c for c in _fallback_search(
                    query_text, category, palette, occasion, style, constraints,
                    top_k * 3, gender=gender,
                )
                if c.get("id") not in have
            ]
            if extra:
                print(
                    f"[recommend_items] {category}: vector search returned {len(candidates)} "
                    f"of {top_k} -- topped up {min(len(extra), top_k - len(candidates))} from palette scan "
                    f"(run module3_missing_migrations.sql section 7 to fix retrieval recall)"
                )
                candidates = _dedupe_by_name(candidates + extra)
        except Exception as e:
            print(f"[recommend_items] palette top-up failed (non-fatal): {e}")

    # CATEGORY COVERAGE: when no specific category was asked for, one
    # similarity search over the whole catalog comes back dominated by
    # garments -- confirmed live, 7 of 8 results were dresses/tops, 1 jewelry
    # item, zero footwear or bags. "Style me" means a LOOK (clothes plus the
    # accessories that finish it), not eight variations of the same dress.
    # The query text is part of the cause (it literally ends in "clothing"),
    # so pull accessory candidates with their own accessory-worded search and
    # interleave them, keeping garments the majority.
    if category is None:
        candidates = _merge_accessory_coverage(
            candidates, accessory_query, palette, occasion, style, constraints, top_k, gender=gender,
        )

    # FEEDBACK LOOP, layer 1: drop items the customer already skipped this
    # session verbatim -- re-recommending the SAME item is the baseline bug.
    if dismissed_set:
        candidates = [c for c in candidates if c.get("id") not in dismissed_set]

    # HARD CONSTRAINT FILTER: "not X" is already baked into query_text above,
    # but CLIP-family embedding models are well-documented as unreliable at
    # respecting negation in a text prompt -- "not sandal" can still rank a
    # sandal #1 (observed live: the weather nudge's "avoid sandal" term did
    # exactly this before this filter existed). _matches_constraint already
    # existed for the non-Marqo fallback path only; applying it here as a
    # real post-filter makes EVERY constraint (weather-driven or customer-
    # stated, e.g. "nothing too flashy") actually enforced regardless of
    # which retrieval path served the candidates, not just a soft embedding
    # nudge that CLIP may or may not honor.
    if constraints:
        hard_filtered = [
            c for c in candidates
            if not any(_matches_constraint(c, con) for con in constraints if con)
        ]
        # Never let an over-eager constraint empty the result entirely --
        # showing an imperfect match beats showing nothing.
        if hard_filtered:
            candidates = hard_filtered

    # Hydrate embedding/style_tags whenever we'll need them -- Stage B
    # compatibility ranking (anchor_items) or Stage B' skip-pattern penalty
    # (skip_signal_active) both need fields match_inventory's RPC doesn't
    # return. One bulk query covers both consumers.
    need_hydration = bool(anchor_items) or skip_signal_active
    if need_hydration and candidates:
        candidate_ids = [c["id"] for c in candidates if c.get("id")]
        if candidate_ids:
            try:
                hydration = (
                    get_supabase()
                    .table("inventory")
                    .select("id,embedding,style_tags,occasion")
                    .in_("id", candidate_ids)
                    .execute()
                    .data or []
                )
                by_id = {r["id"]: r for r in hydration}
                for c in candidates:
                    extra = by_id.get(c["id"])
                    if extra:
                        c["embedding"] = extra.get("embedding")
                        c["style_tags"] = extra.get("style_tags")
                        if not c.get("occasion") and extra.get("occasion"):
                            c["occasion"] = extra["occasion"]
            except Exception as e:
                print(f"[recommend_items] embedding hydration failed, rankers fall back to rule-only: {e}")

    # FEEDBACK LOOP, layer 2: penalize candidates that resemble what she's
    # been skipping, even when no single item is an exact repeat. This is
    # the actual fix for "skips 5 similar dresses -> 6th still shown" --
    # layer 1 alone only ever stops a literal repeat.
    if skip_signal_active:
        try:
            from app.services.fashion.feedback_signals import compute_skip_signal, apply_skip_penalty
            dismissed_full = (
                get_supabase()
                .table("inventory")
                .select("id,embedding,color,style_tags")
                .in_("id", list(dismissed_set))
                .execute()
                .data or []
            )
            skip_signal = compute_skip_signal(dismissed_full)
            candidates = apply_skip_penalty(candidates, skip_signal)
            # Soft filter: drop anything that strongly resembles the skip
            # pattern, but never filter below a usable floor -- if the
            # catalog is thin, showing a mediocre match beats showing none.
            SKIP_PENALTY_THRESHOLD = 0.5
            filtered = [c for c in candidates if c.get("skip_penalty", 0) <= SKIP_PENALTY_THRESHOLD]
            if len(filtered) >= max(top_k, 3):
                candidates = filtered
            else:
                # Not enough survivors -- keep the full pool but ensure it's
                # still ordered with the worst skip-matches last.
                candidates.sort(key=lambda c: c.get("skip_penalty", 0))
        except Exception as e:
            print(f"[recommend_items] skip-penalty scoring failed (non-fatal, showing unfiltered): {e}")

    # STAGE B: compatibility re-ranking against the customer's current
    # outfit anchor (cart/tryon/favorites). If no anchor was supplied this
    # is a no-op that leaves Stage A's (skip-penalty-adjusted) ordering alone.
    if anchor_items:
        anchor_ids = [a["id"] for a in anchor_items if a.get("id") and not a.get("embedding")]
        if anchor_ids:
            try:
                anchor_full = (
                    get_supabase()
                    .table("inventory")
                    .select("id,embedding,style_tags,occasion,color,category")
                    .in_("id", anchor_ids)
                    .execute()
                    .data or []
                )
                by_id = {r["id"]: r for r in anchor_full}
                for a in anchor_items:
                    extra = by_id.get(a.get("id"))
                    if extra:
                        a.setdefault("embedding", extra.get("embedding"))
                        a.setdefault("style_tags", extra.get("style_tags"))
                        a.setdefault("occasion", extra.get("occasion"))
                        a.setdefault("color", extra.get("color"))
                        a.setdefault("category", extra.get("category"))
            except Exception as e:
                print(f"[recommend_items] anchor hydration failed: {e}")

        from app.services.fashion.compatibility import rerank_by_compatibility
        # Rerank the WIDER candidate pool, not just top_k, so a great
        # compatibility match that Stage A had at rank 15 can still surface.
        candidates = rerank_by_compatibility(candidates, anchor_items, top_k=max(top_k, 8), session_id=session_id)

    candidates = _apply_budget_filter(candidates, budget_value)[:top_k]

    # Trend / seasonal awareness: tags each item with is_new_arrival (free,
    # from created_at) and is_trending (cross-session engagement, best-
    # effort). Runs on the FINAL top_k slice only -- no point tagging
    # candidates that got filtered out.
    from app.services.fashion.trends import annotate_trend_signals, trend_explanation_fragment
    annotate_trend_signals(candidates, category=category, occasion=occasion)

    for item in candidates:
        why = []
        if item.get("color", "").lower() in [p.lower() for p in palette]:
            why.append(f"'{item['color']}' complements your {undertone} undertone")
        if is_garment_search:
            why.append(f"style suits a {body_shape.replace('_', ' ')} body shape ({body_shape_hints})")
        elif not why:
            why.append("finishes the look in a shade that sits well with your skin tone")
        if gender:
            why.append(f"from the {'men' if gender == 'male' else 'women'}'s range your scan matched")
        if occasion and occasion.lower() in [o.lower() for o in (item.get("occasion") or [])]:
            why.append(f"tagged appropriate for {occasion}")
        if style and _matches_style(item, style):
            why.append(f"matches your {style} style preference")
        if height_hint and item.get("category") in ("dress", "top", "bottom"):
            why.append(height_hint)
        if size_hint and item.get("category") in ("dress", "top", "bottom"):
            why.append(f"sized for a {size} fit" if size else size_hint)
        if glasses_detected and item.get("category") in ("accessory",):
            why.append("picked with your glasses in mind so it doesn't visually compete")
        if item.get("within_budget") is True:
            why.append("within your budget")
        elif item.get("within_budget") is False:
            why.append("closest match found, slightly over your stated budget")
        # Stage B: if compatibility ranking ran, surface the "why it works
        # together" line -- that's specifically about outfit composition,
        # which the palette/occasion/style bullets above don't capture.
        if anchor_items and item.get("compatibility_score") is not None:
            from app.services.fashion.compatibility import compatibility_explanation
            comp_line = compatibility_explanation(item, anchor_items)
            if comp_line:
                why.append(comp_line.rstrip("."))
        # Feedback loop: let the LLM (and customer, if it says so out loud)
        # know this pick was deliberately steered away from a skip pattern --
        # this is the actual "she noticed" moment, not just silent filtering.
        if skip_signal_active and item.get("skip_penalty", 1) < 0.15:
            why.append("picked in a different direction from styles you've been skipping")
        trend_note = trend_explanation_fragment(item)
        if trend_note:
            why.append(trend_note)
        item["explanation"] = "; ".join(why)

    return {
        "query_used": query_text,
        "gender_considered": gender,
        "palette_considered": palette,
        "height_hint": height_hint,
        "size_hint": size_hint,
        "budget_considered": budget_value,
        "results": candidates,
    }


def recommend_complete_look(
    per_category: int = 3,
    categories: list[str] | None = None,
    styled: bool = True,
    **kwargs,
) -> dict:
    """
    styled=True (default) delegates to styled_look.recommend_styled_look:
    every category split into garment TYPES with 2-3 options each plus
    "Outfits by occasion" -- the customer's stated requirement. styled=False
    is the older one-row-per-category look, kept for callers that pass an
    explicit `categories` subset.


    The post-scan recommendation: NOT one ranked list of 8, but one short
    ranked list PER category -- tops, bottoms, dresses, footwear, bags,
    watches, jewellery, accessories -- each searched against the same scan
    profile (palette + body shape + department). A single search over the
    whole catalog can't do this: it's 45% tops by volume, so "what suits this
    body" came back as eight orange t-shirts and no shoes, watch or bag
    (confirmed live), which is not what a customer standing in front of a
    mirror means by "recommend me something".

    kwargs are recommend_items' scan/preference parameters (depth, undertone,
    body_shape, gender, occasion, style, constraints, size, budget,
    dismissed_item_ids, ...). `category`/`top_k` are owned by this function.

    Returns {"sections": [{category, label, items}], "results": <flat>, ...}.
    `results` is round-robin across sections (top #1, bottom #1, shoe #1,
    ..., top #2, ...) so any consumer that only reads the first N -- the
    LLM-facing summary in Aria's tool, the event logger -- still sees a
    spread of the look rather than N tops.
    """
    kwargs.pop("category", None)
    kwargs.pop("top_k", None)
    if styled and not categories:
        from app.services.fashion.styled_look import recommend_styled_look
        return recommend_styled_look(per_group=per_category, **kwargs)
    kwargs.pop("include", None)
    kwargs.pop("strict_occasion", None)
    gender = normalize_gender(kwargs.get("gender"))
    if gender not in ("male", "female"):
        gender = None
    plan = [normalize_category(c) for c in categories] if categories else _LOOK_PLAN[gender]

    # One search per section, run concurrently -- each is an independent
    # CLIP text encode + pgvector RPC (~0.7s serial), and eight of them in a
    # row is a noticeable wait on a mirror. Results are collected back in
    # plan order so the sections always render in the same sequence.
    def _one(cat: str):
        try:
            return cat, recommend_items(category=cat, top_k=per_category, **dict(kwargs))
        except Exception as e:
            print(f"[recommend_complete_look] {cat} search failed: {e}")
            return cat, None

    per_cat = dict(_LOOK_POOL.map(_one, plan))
    # The shared Supabase client can drop a stale keep-alive under concurrent
    # use ("Server disconnected") -- seen live, it cost a men's look its bags
    # and accessories. Anything that failed gets one serial retry; a section
    # is only skipped if that fails too.
    for cat in plan:
        if per_cat.get(cat) is None:
            per_cat[cat] = _one(cat)[1]
            if per_cat[cat] is None:
                print(f"[recommend_complete_look] {cat} failed twice -- section skipped")

    sections: list[dict] = []
    seen_ids: set = set()
    seen_names: set = set()
    query_used: dict[str, str] = {}
    palette: list[str] = []
    for cat in plan:
        r = per_cat.get(cat)
        if not r:
            continue
        palette = r.get("palette_considered") or palette
        query_used[cat] = r.get("query_used", "")
        items = []
        for it in r.get("results", []):
            name = (it.get("name") or "").strip().lower()
            if it.get("id") in seen_ids or (name and name in seen_names):
                continue
            seen_ids.add(it.get("id"))
            if name:
                seen_names.add(name)
            items.append(it)
        if items:
            sections.append({"category": cat, "label": CATEGORY_LABELS.get(cat, cat.title()), "items": items})

    flat: list[dict] = []
    for i in range(per_category):
        for sec in sections:
            if i < len(sec["items"]):
                flat.append(sec["items"][i])

    return {
        "mode": "complete_look",
        "sections": sections,
        "results": flat,
        "query_used": query_used,
        "gender_considered": gender,
        "palette_considered": palette,
    }
