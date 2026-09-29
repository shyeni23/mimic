"""
Stage-B compatibility ranker (Module 3).

Stage A (Marqo + pgvector, see inventory_search.semantic_search) retrieves K
candidates that MATCH what the customer asked for. Stage B — this file —
re-ranks those candidates by whether they COMPOSE well with items the
customer has already picked (cart, tryon, favorites, or an explicit anchor
outfit passed in).

Design notes:
- Alex-gecheng's outfit-compatibility-transformer is the target replacement
  for the semantic half here. It needs IMAGE embeddings on the whole
  catalog, which we don't have yet (text-only backfill for now). Once the
  Colab image-embed job runs, swap _semantic_compatibility for a call to
  the transformer's `predict(outfit_items)`. The rule half stays useful as
  a guardrail either way -- a neural ranker still occasionally makes
  formality/occasion errors that rules catch cleanly.
- No new schema, no new dependencies. Uses the Marqo embeddings that are
  already on every inventory row.
- Score in [0, 1]. Higher = more compatible.
"""
from __future__ import annotations
import math

# Formality ranking -- lower distance = more compatible.
# Free-form strings from the catalog are mapped to a compact ordinal scale.
_FORMALITY_RANK = {
    "sports": 0, "gym": 0, "athletic": 0, "activewear": 0,
    "home": 0, "loungewear": 0,
    "casual": 1, "streetwear": 1, "everyday": 1,
    "smart casual": 2, "smart-casual": 2, "business casual": 2,
    "office": 3, "work": 3, "business": 3, "formal": 3,
    "party": 4, "cocktail": 4, "evening": 4,
    "wedding": 5, "ethnic": 5, "traditional": 5, "black tie": 5,
}

# Complementary / analogous color pairs pulled from color theory. Neutrals
# (white, black, beige, grey, brown, navy, cream, ivory, tan) pair with
# anything and score high by default.
_NEUTRAL_COLORS = {
    "white", "black", "grey", "gray", "silver", "beige", "cream", "ivory",
    "tan", "brown", "khaki", "camel", "nude", "off white", "navy", "navy blue",
    "charcoal", "taupe",
}

# Color families that mix well as accent + base.
_COLOR_HARMONY = {
    frozenset({"blue", "beige"}): 0.9,
    frozenset({"blue", "white"}): 0.95,
    frozenset({"blue", "grey"}): 0.9,
    frozenset({"navy", "beige"}): 0.95,
    frozenset({"navy", "white"}): 0.95,
    frozenset({"black", "red"}): 0.9,
    frozenset({"black", "white"}): 1.0,
    frozenset({"black", "gold"}): 0.9,
    frozenset({"pink", "grey"}): 0.85,
    frozenset({"pink", "white"}): 0.9,
    frozenset({"green", "beige"}): 0.85,
    frozenset({"green", "brown"}): 0.85,
    frozenset({"olive", "beige"}): 0.9,
    frozenset({"burgundy", "cream"}): 0.9,
    frozenset({"maroon", "beige"}): 0.85,
    frozenset({"yellow", "navy"}): 0.85,
    frozenset({"purple", "grey"}): 0.8,
    frozenset({"red", "white"}): 0.9,
}


def _formality_rank(text: str | None) -> int | None:
    if not text:
        return None
    lower = text.lower()
    for key, val in _FORMALITY_RANK.items():
        if key in lower:
            return val
    return None


def _formality_compatibility(item: dict, anchors: list[dict]) -> float:
    """Distance-1 formality match on average. Casual + wedding = 0, same rank = 1."""
    item_ranks = [_formality_rank(o) for o in (item.get("occasion") or [])]
    item_r = next((r for r in item_ranks if r is not None), None)
    if item_r is None:
        return 0.7  # unknown -- neutral prior, don't penalize

    scores = []
    for a in anchors:
        anchor_ranks = [_formality_rank(o) for o in (a.get("occasion") or [])]
        a_r = next((r for r in anchor_ranks if r is not None), None)
        if a_r is None:
            continue
        # 5-step scale, distance 0 -> 1.0, distance 5 -> 0.0
        scores.append(max(0.0, 1.0 - abs(item_r - a_r) / 5.0))
    if not scores:
        return 0.7
    return sum(scores) / len(scores)


def _color_pair_score(a: str, b: str) -> float:
    """Score two colors' compatibility. Neutrals with anything = high."""
    if not a or not b:
        return 0.6
    a, b = a.lower().strip(), b.lower().strip()
    if a == b:
        return 0.75  # same color: okay but a bit monochromatic
    if a in _NEUTRAL_COLORS or b in _NEUTRAL_COLORS:
        return 0.9
    key = frozenset({a, b})
    if key in _COLOR_HARMONY:
        return _COLOR_HARMONY[key]
    # Unknown pair -- neutral prior. Rare colors shouldn't kill a candidate
    # just because we don't have a rule for them.
    return 0.55


def _color_compatibility(item: dict, anchors: list[dict]) -> float:
    item_color = item.get("color") or ""
    scores = [_color_pair_score(item_color, a.get("color") or "") for a in anchors]
    return sum(scores) / len(scores) if scores else 0.7


def _style_overlap(item: dict, anchors: list[dict]) -> float:
    """Jaccard overlap on style_tags across anchors. Same tags = coherent look."""
    item_tags = {str(t).lower() for t in (item.get("style_tags") or []) if t}
    if not item_tags:
        return 0.6
    scores = []
    for a in anchors:
        a_tags = {str(t).lower() for t in (a.get("style_tags") or []) if t}
        if not a_tags:
            continue
        inter = len(item_tags & a_tags)
        union = len(item_tags | a_tags)
        scores.append(inter / union if union else 0)
    if not scores:
        return 0.6
    # Jaccard is very sparse (real overlap is ~0-0.3) so boost the raw score
    # into the useful 0.4-0.9 band instead of being stuck near zero.
    raw = sum(scores) / len(scores)
    return round(0.4 + raw * 1.5, 3) if raw > 0 else 0.5


def _category_diversity_bonus(item: dict, anchors: list[dict]) -> float:
    """Reward filling a missing slot in the outfit, penalize duplicates.
    Two tops together in one outfit? Almost certainly not what the
    customer wanted. Missing footwear when they have a top+bottom? Big
    positive signal to recommend footwear."""
    if not anchors:
        return 1.0
    item_cat = (item.get("category") or "").lower()
    anchor_cats = {(a.get("category") or "").lower() for a in anchors}
    if item_cat in anchor_cats:
        return 0.3  # duplicate slot
    return 1.0


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _parse_embedding(raw) -> list[float] | None:
    """Supabase returns pgvector as either a JSON-encoded string or a list."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        import json
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else None
        except Exception:
            return None
    return None


def _raw_semantic_cosine(item: dict, anchors: list[dict]) -> float | None:
    """Cosine between this item's embedding and the AVERAGE anchor embedding.
    Returns None when either side has no usable embedding -- caller decides
    how to handle that (typically: neutral 0.6 as a rule-only fallback)."""
    item_emb = _parse_embedding(item.get("embedding"))
    if not item_emb:
        return None
    anchor_embs = [_parse_embedding(a.get("embedding")) for a in anchors]
    anchor_embs = [e for e in anchor_embs if e]
    if not anchor_embs:
        return None
    dim = len(anchor_embs[0])
    avg = [sum(e[i] for e in anchor_embs) / len(anchor_embs) for i in range(dim)]
    return _cosine(item_emb, avg)


def _rank_normalize(values: list[float]) -> list[float]:
    """Map absolute cosine values to their rank-percentile in the list.
    Modality-invariant -- the ABSOLUTE cosines can be tiny (text-anchor vs
    image-candidates in CLIP space) but the RELATIVE ordering of "which
    candidate is closest to the anchor" is still meaningful. Ties get the
    same percentile."""
    if not values:
        return []
    if len(values) == 1:
        return [0.5]
    sorted_pairs = sorted(enumerate(values), key=lambda p: p[1])
    ranks = [0.0] * len(values)
    n = len(values) - 1
    for rank, (orig_idx, _) in enumerate(sorted_pairs):
        ranks[orig_idx] = rank / n
    return ranks


# Default Stage B weights -- what every session got before the registry
# existed, and what every session still gets unless an A/B test is running
# (see model_registry.py). Registering/activating a config named
# "stage_b_weights" with different values lets two weight sets run side by
# side, with outcomes attributable per-session via deterministic assignment.
DEFAULT_STAGE_B_WEIGHTS = {"semantic": 0.35, "color": 0.30, "formality": 0.20, "style": 0.15}


def score_compatibility(
    item: dict, anchors: list[dict],
    semantic_override: float | None = None,
    weights: dict | None = None,
) -> dict:
    """Full compatibility score for one candidate against the anchor outfit.

    weights: {"semantic","color","formality","style"} -- defaults to
    DEFAULT_STAGE_B_WEIGHTS. Pass a different dict (typically resolved via
    model_registry.get_active_config("stage_b_weights", session_id,
    DEFAULT_STAGE_B_WEIGHTS)) to run an A/B test on the ranking formula
    itself. Weights tuned so no single component can overwhelm the others --
    a neon-orange candidate that happens to have high semantic similarity to
    a beige-tone anchor is still penalized by the color-compat check, and
    a rule-perfect but semantically-off match doesn't dominate either.

    Returns a dict with the total score plus the component breakdown, so
    the recommender can (a) log which piece drove the ranking for
    debugging and (b) surface a real "why this works together" line to the
    customer instead of a generic template.
    """
    if not anchors:
        return {"score": 1.0, "note": "no anchor outfit -- returning as-is"}
    w = weights or DEFAULT_STAGE_B_WEIGHTS

    # semantic_override is set by rerank_by_compatibility, which computes
    # rank-percentile across the whole candidate set (modality-invariant).
    # When called standalone (e.g. from compatibility_explanation), fall
    # back to the raw cosine mapped into a reasonable band.
    if semantic_override is not None:
        semantic = semantic_override
    else:
        raw = _raw_semantic_cosine(item, anchors)
        semantic = 0.6 if raw is None else max(0.0, min(1.0, (raw + 0.1) * 1.2))
    color = _color_compatibility(item, anchors)
    formality = _formality_compatibility(item, anchors)
    style = _style_overlap(item, anchors)
    diversity = _category_diversity_bonus(item, anchors)

    # Multiplicative diversity so a duplicate-slot candidate gets crushed
    # regardless of how well it scores otherwise; additive on the rest.
    base = w["semantic"] * semantic + w["color"] * color + w["formality"] * formality + w["style"] * style
    total = base * diversity
    return {
        "score": round(total, 3),
        "components": {
            "semantic": round(semantic, 3),
            "color": round(color, 3),
            "formality": round(formality, 3),
            "style": round(style, 3),
            "diversity": round(diversity, 3),
        },
    }


def rerank_by_compatibility(
    candidates: list[dict], anchors: list[dict], top_k: int = 3,
    session_id: str | None = None,
) -> list[dict]:
    """Re-rank Stage A retrieval by compatibility with the anchor outfit.

    - candidates: rows from semantic_search() (with `embedding` fetched)
    - anchors: rows the customer has already selected (cart, tryon, fav)
    - top_k: how many to return
    - session_id: when given, resolves the active "stage_b_weights" config
      via model_registry (A/B testing) -- deterministic per session, so a
      customer never sees the ranking formula change mid-conversation.
      Omitted (None) always uses DEFAULT_STAGE_B_WEIGHTS -- existing callers
      that don't pass this keep today's exact behavior, unchanged.

    If no anchors are given, this is a no-op that returns the first top_k
    candidates unchanged -- pure Stage A behavior. That's the right thing
    on the FIRST recommendation of a session (no anchor yet), and lets
    this be called safely from every recommendation path.
    """
    if not candidates:
        return []
    if not anchors:
        return candidates[:top_k]

    weights = DEFAULT_STAGE_B_WEIGHTS
    variant_version = None
    if session_id:
        try:
            from app.services.fashion.model_registry import get_active_config
            from app.db.supabase_client import get_supabase
            sb = get_supabase()
            active = (
                sb.table("recommender_configs")
                .select("version")
                .eq("name", "stage_b_weights").eq("is_active", True)
                .execute().data or []
            )
            weights = get_active_config("stage_b_weights", session_id, DEFAULT_STAGE_B_WEIGHTS)
            if weights is not DEFAULT_STAGE_B_WEIGHTS and active:
                variant_version = active[0].get("version")
        except Exception as e:
            print(f"[compatibility] A/B config lookup failed (non-fatal, using default weights): {e}")

    # Pre-compute raw cosines for every candidate, then rank-normalize them
    # WITHIN this candidate set. Absolute cosines are unreliable when the
    # catalog mixes image and text embeddings (CLIP's cross-modal gap), but
    # relative ordering "which candidate is closest to this anchor" is
    # meaningful regardless of modality. See _rank_normalize.
    raw_cosines = []
    for c in candidates:
        r = _raw_semantic_cosine(c, anchors)
        raw_cosines.append(r if r is not None else 0.0)
    percentiles = _rank_normalize(raw_cosines)

    scored = []
    for c, pct in zip(candidates, percentiles):
        s = score_compatibility(c, anchors, semantic_override=pct, weights=weights)
        c = dict(c)  # don't mutate caller's list
        c["compatibility_score"] = s["score"]
        c["compatibility_breakdown"] = s.get("components")
        if variant_version is not None:
            # Tags which A/B variant produced this ranking -- lets a later
            # analytics query join interactions back to the config version
            # that served them, and actually compare outcomes per variant.
            c["compatibility_breakdown"]["stage_b_variant"] = variant_version
        scored.append(c)

    scored.sort(key=lambda x: x["compatibility_score"], reverse=True)
    return scored[:top_k]


def compatibility_explanation(item: dict, anchors: list[dict]) -> str:
    """One-sentence "why it works together" line for the customer, built
    from the actual winning components -- not a canned template."""
    if not anchors:
        return ""
    s = score_compatibility(item, anchors)
    comp = s.get("components") or {}
    reasons = []
    if comp.get("color", 0) >= 0.85:
        reasons.append(f"the {item.get('color') or 'color'} works with what you already have")
    if comp.get("style", 0) >= 0.75:
        reasons.append("the style tags line up")
    if comp.get("formality", 0) >= 0.85:
        reasons.append("it's the same dress code")
    if comp.get("semantic", 0) >= 0.7:
        reasons.append("the overall vibe matches")
    if comp.get("diversity", 0) < 0.5:
        return "Note: this fills the same slot as another piece you have -- consider swapping instead."
    if not reasons:
        return "Fits the outfit overall."
    return "Pairs well because " + " and ".join(reasons[:2]) + "."
