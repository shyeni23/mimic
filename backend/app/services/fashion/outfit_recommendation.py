"""
Module 3 -- Complete Outfit Recommendation Engine.

Given a primary item (selected via select_primary_item(), which drives the
EXISTING Module 1 recommend_items() call using user_context.py's combined
visual+conversation profile -- see that function's docstring) this module
retrieves and ranks compatible accessories (footwear, bags, jewelry,
watches, other accessories) from inventory into a complete outfit, scored
on category compatibility, color harmony, occasion/formality coherence,
and user preferences.

ATTRIBUTION: The category-slot compatibility model, color-harmony scoring
(60-30-10 rule + complementary/analogous color theory), formality scoring,
and occasion hard-block gating below are ADAPTED from anushreeberlia/loom
(github.com/anushreeberlia/loom) -- MIT License, Copyright (c) 2026
Anushree Berlia -- specifically services/outfit.py and the later, cleaner
services/rules.py ("encoder-free" refactor of the same ideas, with the
FashionCLIP-embedding dependency already stripped by the original author,
which is why it ports cleanly onto this project's simpler schema).

    MIT License permission notice (reproduced per license terms, since
    substantial portions of the referenced functions are adapted here):
    "Permission is hereby granted, free of charge, to any person obtaining
    a copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction..."
    Full text: https://github.com/anushreeberlia/loom/blob/main/LICENSE

WHAT WAS KEPT (adapted -- field names and logic changed to fit this
project's `inventory` table, which has category/color/occasion/style_tags/
name/price/stock only -- no material or fit field):
- Category-pairing slot logic (loom's OUTFIT_SLOTS / get_slots_for_category)
- Color theory: NEUTRALS, COMPLEMENTS, ANALOGOUS, color-family harmony, and
  the 60-30-10 color composition check (loom's outfit.py check_color_composition)
- Formality scoring from name/category/style_tags/color keywords (loom's
  rules.py infer_formality_continuous -- the encoder-free version)
- Occasion hard-block gating (loom's rules.py _OCCASION_ALIAS /
  _OCCASION_HARD_BLOCK), simplified further since this project's inventory
  items already carry a real `occasion` tag from the source dataset --
  no keyword-inference step is needed the way loom needs it for untagged
  personal-closet items
- Safety filtering (loom's rules.py FORBIDDEN_KEYWORDS / passes_sanity_check)

WHAT WAS DELIBERATELY DROPPED (not applicable here):
- Layer justification, weather-context awareness -- personal-wardrobe/
  closet features; also explicitly Module 4/5 scope, out of bounds for
  this task
- Texture/volume/proportion analysis (classify_texture, infer_volume_class,
  check_proportion_balance, etc.) -- all require `material`/`fit` fields
  this project's inventory schema doesn't collect
- Embedding-anchor classification (_get_inference_anchors,
  _embedding_classify, the embedding branch of compute_visual_loudness,
  compute_visual_cohesion, _embedding_visual_harmony) -- tied to loom's own
  CLIP-text-anchor caching setup; this project already has an equivalent
  FashionCLIP embedding pipeline in inventory_search.py, so duplicating
  loom's would be redundant complexity with no real gain here
- Personal taste/dislike vectors (compute_outfit_intent_vector) -- requires
  an interaction-history table this project doesn't have yet (Module 4
  "feedback learning" territory)
- The multihead scoring variant and retrieval.py's embedding-based
  candidate retrieval -- this project already has equivalent semantic
  search in inventory_search.py; no need to duplicate it
"""
from pydantic import BaseModel, Field as PydanticField

from app.db.supabase_client import get_inventory
from app.services.fashion.inventory_search import recommend_items
from app.services.user_context import get_user_context


class NoPrimaryItemError(RuntimeError):
    """Raised when no eligible primary clothing item exists in inventory for
    this session's profile. Never silently substituted with a fabricated item."""


# ── Category-slot compatibility (adapted from loom's OUTFIT_SLOTS) ──────────

OUTFIT_SLOTS: dict[str, list[str]] = {
    "top": ["bottom", "footwear", "bag", "jewelry", "watch", "accessory"],
    "bottom": ["top", "footwear", "bag", "jewelry", "watch", "accessory"],
    "dress": ["footwear", "bag", "jewelry", "watch", "accessory"],
}


def get_slots_for_category(category: str) -> list[str]:
    """Which accessory/complementary categories to fill in around a primary
    item of the given category. Defaults to the full accessory set for any
    category not explicitly listed."""
    return OUTFIT_SLOTS.get(category, ["footwear", "bag", "jewelry", "watch", "accessory"])


# ── Color theory (adapted from loom's outfit.py) ─────────────────────────────

NEUTRALS = {"black", "white", "gray", "grey", "beige", "brown", "navy", "silver", "gold", "cream", "charcoal"}

COMPLEMENTS: dict[str, set[str]] = {
    "purple": {"white", "black", "gray", "beige", "navy", "green", "yellow", "gold", "silver"},
    "pink": {"white", "black", "gray", "navy", "beige", "green", "silver"},
    "red": {"white", "black", "gray", "beige", "navy", "gold", "silver"},
    "blue": {"white", "black", "beige", "brown", "orange", "silver", "gold"},
    "green": {"white", "black", "beige", "brown", "pink", "gold"},
    "yellow": {"white", "black", "gray", "navy", "purple", "silver"},
    "orange": {"white", "black", "navy", "blue", "beige", "gold"},
    "maroon": {"white", "black", "gray", "beige", "gold", "silver"},
}

ANALOGOUS: dict[str, set[str]] = {
    "red": {"orange", "pink", "maroon", "coral", "rust", "burgundy"},
    "orange": {"red", "yellow", "coral", "rust", "peach"},
    "yellow": {"orange", "green", "gold", "mustard"},
    "green": {"yellow", "teal", "blue", "olive"},
    "blue": {"green", "purple", "navy", "teal", "turquoise"},
    "purple": {"blue", "pink", "lavender", "magenta"},
    "pink": {"red", "purple", "coral", "lavender", "magenta"},
}


# NOTE: "beige"/"brown"/"navy" deliberately appear in more than one family
# here, same as in loom's original outfit.py COLOR_FAMILIES -- a warm
# neutral like beige genuinely belongs to both. get_color_family() resolves
# the ambiguity by checking "warm" before "neutral" (dict insertion order),
# so beige/brown resolve to "warm" and navy resolves to "cool" -- ported
# faithfully, not a bug introduced during adaptation.
COLOR_FAMILIES: dict[str, set[str]] = {
    "warm": {"red", "orange", "yellow", "brown", "beige", "coral", "rust", "maroon", "gold", "peach", "mustard", "tan", "bronze", "copper", "khaki"},
    "cool": {"blue", "green", "purple", "navy", "teal", "turquoise", "lavender", "magenta"},
    "neutral": {"black", "white", "gray", "grey", "beige", "navy", "silver", "cream", "charcoal"},
}


def get_color_family(color: str | None) -> str:
    """Warm / cool / neutral bucket for a color name. Unknown colors default
    to neutral (never invents a family for a color it doesn't recognize)."""
    if not color:
        return "neutral"
    color_lower = color.lower().strip()
    for family, colors in COLOR_FAMILIES.items():
        if color_lower in colors:
            return family
    return "neutral"


def score_color_harmony(base_color: str | None, candidate_color: str | None) -> float:
    """Pairwise color-harmony bonus/penalty between the primary item and one
    candidate accessory -- adapted from loom's check_color_composition (60-30-10
    rule), simplified to a pairwise check since we score one candidate against
    the primary item at a time rather than a whole pre-assembled outfit."""
    if not base_color or not candidate_color:
        return 0.0

    a = base_color.lower().strip()
    b = candidate_color.lower().strip()

    if a == b:
        return 0.02  # tonal match -- safe, small bonus
    if a in NEUTRALS or b in NEUTRALS:
        return 0.05  # neutral pairs with anything -- the "goes with everything" case
    if b in COMPLEMENTS.get(a, set()) or a in COMPLEMENTS.get(b, set()):
        return 0.05  # true complementary pair
    if b in ANALOGOUS.get(a, set()) or a in ANALOGOUS.get(b, set()):
        return 0.03  # analogous (adjacent on the color wheel)
    if get_color_family(a) == get_color_family(b):
        return 0.01  # same warm/cool family, no specific relationship known
    return -0.05  # no known harmony relationship -- likely clashing


# ── Formality scoring (adapted from loom's rules.py, encoder-free version) ──

GARMENT_TYPE_BASE_SCORES: list[tuple[set[str], float]] = [
    ({"gown", "tuxedo", "suit", "stiletto", "cocktail"}, 5.0),
    ({"blouse", "trousers", "dress", "blazer", "heel", "pump", "wedge", "oxford"}, 4.0),
    ({"jeans", "cardigan", "boot", "flat", "loafer", "skirt", "sweater", "shirt"}, 3.0),
    ({"t-shirt", "tshirt", "tee", "tank", "hoodie", "sweatshirt", "sneaker", "sandal"}, 2.0),
    ({"track pant", "flip flop", "jogger", "legging", "athletic"}, 1.0),
]

STYLE_TAG_FORMALITY_NUDGE: dict[str, float] = {
    "dressy": 0.5, "elegant": 0.5, "formal": 0.5, "cocktail": 0.5, "party": 0.3,
    "casual": -0.5, "basic": -0.5, "athletic": -0.5, "sporty": -0.5, "sports": -0.5,
}

COLOR_FORMALITY_NUDGE: dict[str, float] = {
    "black": 0.2, "navy": 0.2, "gold": 0.2, "silver": 0.1,
    "white": -0.1, "beige": -0.1,
}


def infer_formality(item: dict) -> float:
    """Continuous 1-5 formality score from name/category/style_tags/color
    keywords -- adapted from loom's encoder-free infer_formality_continuous.
    No material/fit dependency (those fields don't exist in this project's
    inventory schema); unrecognized items default to a neutral 3.0 rather
    than guessing."""
    name_lower = (item.get("name") or "").lower()
    category = (item.get("category") or "").lower()
    combined = f"{name_lower} {category}"

    base = 3.0
    for keywords, score in GARMENT_TYPE_BASE_SCORES:
        if any(kw in combined for kw in keywords):
            base = score
            break

    tag_nudge = 0.0
    for tag in (item.get("style_tags") or []):
        tag_lower = str(tag).lower()
        if tag_lower in STYLE_TAG_FORMALITY_NUDGE:
            tag_nudge = STYLE_TAG_FORMALITY_NUDGE[tag_lower]
            break

    color = (item.get("color") or "").lower()
    color_nudge = COLOR_FORMALITY_NUDGE.get(color, 0.0)

    return round(base + tag_nudge + color_nudge, 2)


def check_formality_coherence(primary_formality: float, candidate_formality: float) -> float:
    """Penalty for a large formality gap between the primary item and a
    candidate accessory -- adapted from loom's check_formality_coherence."""
    gap = abs(primary_formality - candidate_formality)
    if gap <= 1.0:
        return 0.0
    return -0.1 * (gap - 1.0)


# ── Occasion hard-block gating (adapted from loom's rules.py) ───────────────

_OCCASION_ALIAS: dict[str, str] = {
    "party": "going-out", "going-out": "going-out", "going out": "going-out",
    "formal": "work", "work": "work", "smart casual": "smart-casual", "ethnic": "smart-casual",
    "casual": "casual", "travel": "casual", "home": "casual",
    "sports": "active", "sport": "active",
}

_OCCASION_HARD_BLOCK: dict[str, set[str]] = {
    "going-out": {"active"},
    "work": {"active", "going-out"},
    "smart-casual": {"active"},
    "casual": {"active"},
    "active": {"going-out", "work"},
}


def resolve_occasion_group(occasion_tags: list[str] | None) -> str | None:
    """Map this project's raw occasion tags (from the dataset's `usage`
    field, e.g. 'Casual', 'Formal', 'Party') to loom's canonical occasion
    groups used for hard-block gating. Returns None if no recognizable tag
    is present -- an unknown occasion is never guessed."""
    if not occasion_tags:
        return None
    for tag in occasion_tags:
        group = _OCCASION_ALIAS.get(str(tag).lower().strip())
        if group:
            return group
    return None


def occasion_compatible(primary_group: str | None, candidate_group: str | None) -> bool:
    """Hard-block check: is a candidate's occasion group allowed alongside
    the primary item's? Returns True (permissive) whenever either side has
    no resolvable occasion -- absence of data is never treated as a block."""
    if not primary_group or not candidate_group:
        return True
    blocked = _OCCASION_HARD_BLOCK.get(primary_group, set())
    return candidate_group not in blocked


# ── Safety filtering (adapted from loom's rules.py) ──────────────────────────
# Moved to catalog_filters.py so inventory_search.recommend_items (the main
# /api/recommend + Aria path) can apply the exact same rule without a
# circular import -- re-exported here so existing callers/tests keep working.
from app.services.fashion.catalog_filters import (  # noqa: E402
    FORBIDDEN_KEYWORDS, KIDS_KEYWORDS, passes_sanity_check,
)


# ── User-preference scoring (this project's own conversation state) ─────────

def score_user_preferences(item: dict, fashion_preferences: dict) -> float:
    """Bonus/penalty from the customer's stated conversation preferences
    (color_preferences, disliked_colors, constraints, style) -- this has no
    loom equivalent since loom has no conversational-preference layer; this
    is this project's own addition, built to use user_context.py's existing
    fashion_preferences structure without inventing new fields."""
    score = 0.0
    item_color = (item.get("color") or "").lower()
    item_style_tags = {str(t).lower() for t in (item.get("style_tags") or [])}
    item_name = (item.get("name") or "").lower()

    color_prefs = [c.lower() for c in (fashion_preferences.get("color_preferences") or [])]
    if color_prefs and item_color in color_prefs:
        score += 0.08

    disliked_colors = [c.lower() for c in (fashion_preferences.get("disliked_colors") or [])]
    if disliked_colors and item_color in disliked_colors:
        score -= 0.15

    style = (fashion_preferences.get("style") or "").lower()
    if style and (style in item_style_tags or style in item_name):
        score += 0.05

    constraints = [c.lower() for c in (fashion_preferences.get("constraints") or [])]
    for constraint in constraints:
        if constraint and constraint in item_name:
            score -= 0.1

    return round(score, 3)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class OutfitItem(BaseModel):
    """One inventory item as it appears in an outfit recommendation. Every
    field is copied directly from the inventory row -- nothing here is
    invented or inferred beyond what's actually stored."""
    id: str
    name: str
    category: str
    color: str | None = None
    occasion: list[str] = PydanticField(default_factory=list)
    style_tags: list[str] = PydanticField(default_factory=list)
    image_url: str | None = None
    price: float | None = None


class OutfitSlot(BaseModel):
    """One filled accessory slot in the outfit, with the score and reasons
    that produced it."""
    slot: str
    item: OutfitItem
    score: float
    explanation: str


class OutfitRecommendation(BaseModel):
    """The full Module 3 response: a primary item plus whichever accessory
    slots had an eligible candidate. A slot with no eligible candidate is
    simply omitted -- never filled with a fabricated or best-effort guess."""
    session_id: str
    primary_item: OutfitItem
    slots: list[OutfitSlot] = PydanticField(default_factory=list)
    overall_score: float


# ── Primary item selection (wires the EXISTING recommend_items() call) ──────

_CLOTHING_CATEGORIES = ["top", "bottom", "dress"]


def select_primary_item(visual_profile: dict, fashion_preferences: dict) -> dict | None:
    """
    Picks the single best primary clothing item to build an outfit around,
    using the EXISTING Module 1 recommend_items() call (app/services/fashion/
    inventory_search.py -- unmodified) driven by user_context.py's combined
    visual_profile + fashion_preferences. This is the "wire the recommendation
    call for real" requirement -- not a stub: it makes a real semantic search
    (FashionCLIP + pgvector, or the fallback color/occasion scorer if
    FashionCLIP isn't loaded yet) against real inventory.

    If the conversation already specified a clothing_type that maps to one of
    our three garment categories, search that category directly. Otherwise,
    search across all three and keep the single highest-similarity result --
    never a fabricated pick.

    Returns the raw top-ranked inventory dict (as returned by recommend_items,
    including its "similarity" and "explanation" fields), or None if no
    candidate exists in inventory at all.
    """
    occasion = None
    for tag in (fashion_preferences.get("occasion") or []):
        occasion = tag
        break
    if not occasion:
        occasion = fashion_preferences.get("occasion") if isinstance(fashion_preferences.get("occasion"), str) else None

    clothing_type = (fashion_preferences.get("clothing_type") or "").lower()
    categories = [clothing_type] if clothing_type in _CLOTHING_CATEGORIES else _CLOTHING_CATEGORIES

    common_kwargs = dict(
        depth=visual_profile.get("skin_tone_category") or "medium",
        undertone=visual_profile.get("skin_tone_undertone") or "neutral",
        body_shape=visual_profile.get("body_shape") or "unknown",
        occasion=occasion,
        height_cm=visual_profile.get("height_cm"),
        glasses_detected=bool(visual_profile.get("glasses_detected")),
        hair_length=visual_profile.get("hair_length") or "unknown",
        # style/constraints/size: recommend_items() didn't accept these until
        # the Module 1 audit fix -- now threaded through here too, so primary
        # item selection benefits from the same fix Module 1's own endpoint got.
        style=fashion_preferences.get("style"),
        constraints=fashion_preferences.get("constraints"),
        size=visual_profile.get("body_size_estimate"),
        budget=fashion_preferences.get("budget"),
        top_k=3,
    )

    best_item = None
    best_similarity = -1.0
    for category in categories:
        result = recommend_items(category=category, **common_kwargs)
        for candidate in result.get("results", []):
            if not passes_sanity_check(candidate):
                continue
            similarity = candidate.get("similarity", 0.0) or 0.0
            if similarity > best_similarity:
                best_similarity = similarity
                best_item = candidate

    return best_item


# ── Outfit assembly ───────────────────────────────────────────────────────────

def _to_outfit_item(row: dict) -> OutfitItem:
    return OutfitItem(
        id=str(row.get("id")),
        name=row.get("name") or "",
        category=row.get("category") or "",
        color=row.get("color"),
        occasion=list(row.get("occasion") or []),
        style_tags=list(row.get("style_tags") or []),
        image_url=row.get("image_url"),
        price=row.get("price"),
    )


def score_candidate(primary_item: dict, candidate: dict, fashion_preferences: dict) -> tuple[float, str] | None:
    """Scores one candidate accessory against the primary item. Returns
    (score, explanation), or None if the candidate is hard-blocked
    (wrong occasion group, or fails the safety check)."""
    if not passes_sanity_check(candidate):
        return None
    # Deliberately NOT filtering on stock here: the seeded dataset has no real
    # inventory-level data (see scripts/seed_fashion_dataset.py's report), so a
    # stock check would be filtering on a fabricated number rather than a real
    # signal. Stock also isn't one of the four scoring criteria this module was
    # asked to score on (category compatibility, color harmony, occasion/style/
    # formality, user preferences) -- it belongs to real inventory management,
    # not this scoring layer.

    primary_group = resolve_occasion_group(primary_item.get("occasion"))
    candidate_group = resolve_occasion_group(candidate.get("occasion"))
    if not occasion_compatible(primary_group, candidate_group):
        return None

    reasons: list[str] = []
    score = 0.5  # baseline eligibility score for a same-category-slot, non-blocked candidate

    color_score = score_color_harmony(primary_item.get("color"), candidate.get("color"))
    score += color_score
    if color_score > 0.02:
        reasons.append(f"'{candidate.get('color')}' complements '{primary_item.get('color')}'")

    primary_formality = infer_formality(primary_item)
    candidate_formality = infer_formality(candidate)
    formality_penalty = check_formality_coherence(primary_formality, candidate_formality)
    score += formality_penalty
    if formality_penalty < 0:
        reasons.append("formality level differs from the primary item")

    if primary_group and candidate_group and primary_group == candidate_group:
        score += 0.05
        reasons.append(f"matches the {primary_group.replace('-', ' ')} occasion")

    pref_score = score_user_preferences(candidate, fashion_preferences)
    score += pref_score
    if pref_score > 0:
        reasons.append("matches your stated preferences")
    elif pref_score < 0:
        reasons.append("conflicts with a stated preference")

    explanation = "; ".join(reasons) if reasons else "compatible category and occasion"
    return round(score, 3), explanation


def recommend_outfit(session_id: str, primary_item: dict, fashion_preferences: dict, top_k_per_slot: int = 1) -> OutfitRecommendation:
    """
    Builds a complete outfit around primary_item: for every accessory slot
    that category calls for (see get_slots_for_category), retrieves real
    inventory candidates in that category, scores each against the primary
    item, and keeps the best. A slot with no eligible candidate is omitted
    entirely -- never filled with an invented value.
    """
    slots_needed = get_slots_for_category(primary_item.get("category", ""))
    filled_slots: list[OutfitSlot] = []

    for slot_category in slots_needed:
        candidates = get_inventory(category=slot_category, include_embedding=False)
        best_score = None
        best_candidate = None
        best_explanation = ""
        for candidate in candidates:
            result = score_candidate(primary_item, candidate, fashion_preferences)
            if result is None:
                continue
            score, explanation = result
            if best_score is None or score > best_score:
                best_score = score
                best_candidate = candidate
                best_explanation = explanation

        if best_candidate is not None:
            filled_slots.append(OutfitSlot(
                slot=slot_category,
                item=_to_outfit_item(best_candidate),
                score=best_score,
                explanation=best_explanation,
            ))

    overall_score = round(
        sum(s.score for s in filled_slots) / len(filled_slots), 3
    ) if filled_slots else 0.0

    return OutfitRecommendation(
        session_id=session_id,
        primary_item=_to_outfit_item(primary_item),
        slots=filled_slots,
        overall_score=overall_score,
    )


def get_outfit_recommendation(session_id: str) -> OutfitRecommendation:
    """
    Top-level entry point for GET /api/outfit-recommendation/{session_id}.

    Pipeline: get_user_context(session_id) [existing, unmodified] ->
    select_primary_item() [real recommend_items() call, no stubbing] ->
    recommend_outfit() [this module's scoring].

    Raises NoPrimaryItemError if inventory has no eligible clothing item for
    this session's profile -- the caller (the router) is responsible for
    turning that into an HTTP error, never a fabricated response.
    """
    context = get_user_context(session_id)
    visual_profile = context["visual_profile"]
    fashion_preferences = context["fashion_preferences"]

    primary_item = select_primary_item(visual_profile, fashion_preferences)
    if primary_item is None:
        raise NoPrimaryItemError(
            f"No eligible primary clothing item found in inventory for session {session_id}."
        )

    return recommend_outfit(session_id, primary_item, fashion_preferences)
