"""
Stage C (two-tower) blending into Stage B's compatibility ranker
(app/services/fashion/compatibility.py). Pure arithmetic -- no torch, no
checkpoint, no DB -- so these run everywhere, regardless of whether
data/models/two_tower exists on this machine (it's gitignored, see
test_two_tower.py).

The one property that MUST hold: neural_weight=0 (today's default for every
session unless explicitly A/B-assigned) makes every neural-aware function
byte-identical to its pre-Stage-C behaviour. That's what keeps Stage C an
opt-in experiment rather than a silent behaviour change for existing
callers that don't pass the new parameters at all.
"""
from app.services.fashion.compatibility import rerank_by_compatibility, score_compatibility

ANCHOR = [{"id": "anchor-1", "category": "top", "color": "white",
           "occasion": ["casual"], "style_tags": ["minimal"]}]

ITEM = {"id": "item-1", "category": "bottom", "color": "beige",
        "occasion": ["casual"], "style_tags": ["minimal"]}


def test_neural_weight_zero_is_a_no_op():
    """Passing neural_score with weight 0 must score IDENTICALLY to passing
    neither -- this is what makes Stage C safe to wire in without changing
    any existing caller's behaviour."""
    baseline = score_compatibility(ITEM, ANCHOR, semantic_override=0.5)
    with_neural_off = score_compatibility(
        ITEM, ANCHOR, semantic_override=0.5, neural_score=0.99, neural_weight=0.0)
    assert baseline["score"] == with_neural_off["score"]
    assert "neural" not in with_neural_off["components"]


def test_neural_score_none_is_a_no_op_even_with_nonzero_weight():
    """A missing embedding (two_tower.score_items omits it, never scores
    0.0) must not silently zero out the item's compatibility."""
    baseline = score_compatibility(ITEM, ANCHOR, semantic_override=0.5)
    with_neural = score_compatibility(
        ITEM, ANCHOR, semantic_override=0.5, neural_score=None, neural_weight=0.5)
    assert baseline["score"] == with_neural["score"]


def test_neural_score_pulls_total_toward_itself():
    low = score_compatibility(ITEM, ANCHOR, semantic_override=0.5, neural_score=0.0, neural_weight=0.5)
    high = score_compatibility(ITEM, ANCHOR, semantic_override=0.5, neural_score=1.0, neural_weight=0.5)
    mid = score_compatibility(ITEM, ANCHOR, semantic_override=0.5)  # no neural at all
    assert low["score"] < mid["score"] < high["score"]
    assert low["components"]["neural"] == 0.0
    assert high["components"]["neural"] == 1.0


def test_neural_weight_one_makes_rule_score_irrelevant():
    """At weight=1.0 the rule-based total should be fully overridden by the
    neural score -- proves the blend formula, not just its direction."""
    result = score_compatibility(ITEM, ANCHOR, semantic_override=0.5, neural_score=0.73, neural_weight=1.0)
    assert result["score"] == 0.73


def test_rerank_with_neural_weight_zero_matches_rerank_without_the_params():
    candidates = [
        {"id": "a", "category": "bottom", "color": "beige", "occasion": ["casual"], "style_tags": ["minimal"]},
        {"id": "b", "category": "bottom", "color": "red", "occasion": ["party"], "style_tags": ["bold"]},
    ]
    without = rerank_by_compatibility(candidates, ANCHOR, top_k=2)
    with_zero_weight = rerank_by_compatibility(
        candidates, ANCHOR, top_k=2, neural_scores={"a": 0.1, "b": 0.9}, neural_weight=0.0)
    assert [c["id"] for c in without] == [c["id"] for c in with_zero_weight]
    assert [c["compatibility_score"] for c in without] == [c["compatibility_score"] for c in with_zero_weight]


def test_rerank_neural_scores_can_change_the_ranking():
    """With a strong enough neural signal and weight, a candidate that loses
    on rule-based compatibility alone can still win the rerank -- otherwise
    Stage C would be wired in but have no actual power to change anything."""
    candidates = [
        # Rule-favoured: same occasion/style as the anchor.
        {"id": "rule_favourite", "category": "bottom", "color": "beige",
         "occasion": ["casual"], "style_tags": ["minimal"]},
        # Rule-disfavoured: clashing occasion/style/color.
        {"id": "neural_favourite", "category": "bottom", "color": "red",
         "occasion": ["party"], "style_tags": ["bold"]},
    ]
    neural_scores = {"rule_favourite": 0.0, "neural_favourite": 1.0}
    result = rerank_by_compatibility(
        candidates, ANCHOR, top_k=2, neural_scores=neural_scores, neural_weight=0.9)
    assert result[0]["id"] == "neural_favourite"


def test_rerank_missing_neural_scores_dict_defaults_to_no_blend():
    """neural_scores omitted entirely (every pre-Stage-C caller) must behave
    exactly as before -- this is the real-world default, not just weight=0."""
    candidates = [{"id": "a", "category": "bottom", "color": "beige",
                   "occasion": ["casual"], "style_tags": ["minimal"]}]
    result = rerank_by_compatibility(candidates, ANCHOR, top_k=1)
    assert "neural" not in result[0]["compatibility_breakdown"]
