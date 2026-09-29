"""
Module 1 gap-fix tests: style/constraints/size scoring in recommend_items().

An audit against the project's reference doc found recommend_items() was
silently ignoring three of the five scoring factors the doc calls for
("body-shape suitability, color compatibility, occasion, style and user
constraints") -- style and constraints weren't parameters at all, and size
was captured by the CV scan but never used. These tests verify the fix.

All deterministic (mocked get_inventory, no network) -- these exercise the
_fallback_search path directly, which is what actually runs while
FashionCLIP weights aren't fully downloaded (the common case in this
project so far, per prior verified live runs).
"""
import copy
from unittest.mock import patch

from app.services.fashion.inventory_search import (
    _fallback_search,
    _matches_style,
    _matches_constraint,
    _size_hint_text,
    recommend_items,
)


SAMPLE_ITEMS = [
    {"id": "1", "name": "Minimalist Black Blazer", "category": "top", "color": "black",
     "occasion": ["work"], "style_tags": ["minimalist", "classic"]},
    {"id": "2", "name": "Bold Sequin Party Top", "category": "top", "color": "gold",
     "occasion": ["party"], "style_tags": ["statement", "bold"]},
    {"id": "3", "name": "Heavy Embroidery Kurta", "category": "top", "color": "red",
     "occasion": ["ethnic"], "style_tags": ["traditional"]},
]


class TestStyleAndConstraintHelpers:
    def test_matches_style_via_tags(self):
        assert _matches_style(SAMPLE_ITEMS[0], "minimalist") is True

    def test_matches_style_via_name(self):
        item = {"name": "Modern Chic Top", "style_tags": []}
        assert _matches_style(item, "chic") is True

    def test_no_style_match(self):
        assert _matches_style(SAMPLE_ITEMS[0], "sporty") is False

    def test_matches_constraint_via_name(self):
        assert _matches_constraint(SAMPLE_ITEMS[2], "heavy embroidery") is True

    def test_no_constraint_match(self):
        assert _matches_constraint(SAMPLE_ITEMS[0], "heavy embroidery") is False

    def test_size_hint_known_size(self):
        assert _size_hint_text("M") == "medium fit"
        assert _size_hint_text("XL") == "extra large fit"

    def test_size_hint_unknown_or_missing(self):
        assert _size_hint_text("unknown") is None
        assert _size_hint_text(None) is None
        assert _size_hint_text("") is None


class TestFallbackSearchScoring:
    """_fallback_search mutates each item dict in place (item['similarity'] =
    ...) -- pre-existing behavior, not something this fix introduced. Every
    test here must hand it a FRESH copy of SAMPLE_ITEMS per call, or two
    calls in the same test end up mutating the same shared dict objects and
    silently corrupt each other's results (exactly what happened on the
    first version of these tests -- both sides of a comparison read back
    the SECOND call's mutation)."""

    def test_style_match_boosts_score(self):
        with patch("app.services.fashion.inventory_search.get_inventory", return_value=copy.deepcopy(SAMPLE_ITEMS)):
            no_style = _fallback_search("q", None, [], None, None, None, 10)
        with patch("app.services.fashion.inventory_search.get_inventory", return_value=copy.deepcopy(SAMPLE_ITEMS)):
            with_style = _fallback_search("q", None, [], None, "minimalist", None, 10)

        item1_no_style = next(i for i in no_style if i["id"] == "1")
        item1_with_style = next(i for i in with_style if i["id"] == "1")
        assert item1_with_style["similarity"] > item1_no_style["similarity"]

    def test_constraint_penalizes_matching_item(self):
        with patch("app.services.fashion.inventory_search.get_inventory", return_value=copy.deepcopy(SAMPLE_ITEMS)):
            no_constraint = _fallback_search("q", None, [], None, None, None, 10)
        with patch("app.services.fashion.inventory_search.get_inventory", return_value=copy.deepcopy(SAMPLE_ITEMS)):
            with_constraint = _fallback_search("q", None, [], None, None, ["heavy embroidery"], 10)

        item3_no_constraint = next(i for i in no_constraint if i["id"] == "3")
        item3_with_constraint = next(i for i in with_constraint if i["id"] == "3")
        assert item3_with_constraint["similarity"] < item3_no_constraint["similarity"]

    def test_constraint_avoiding_item_ranks_above_violating_item(self):
        with patch("app.services.fashion.inventory_search.get_inventory", return_value=copy.deepcopy(SAMPLE_ITEMS)):
            results = _fallback_search("q", None, [], None, None, ["heavy embroidery"], 10)

        ranked_ids = [i["id"] for i in results]
        assert ranked_ids.index("3") > ranked_ids.index("1")  # embroidery item ranks lower

    def test_no_style_or_constraints_still_works(self):
        """Backward-compat: calling with style=None, constraints=None (the old
        call shape) must not crash or change unrelated scoring."""
        with patch("app.services.fashion.inventory_search.get_inventory", return_value=copy.deepcopy(SAMPLE_ITEMS)):
            results = _fallback_search("q", None, [], None, None, None, 10)
        assert len(results) == 3


class TestRecommendItemsIntegration:
    def test_style_and_constraints_reach_fallback_search(self):
        """End-to-end (through recommend_items -> semantic_search -> fallback,
        since FashionCLIP isn't available in the test environment): style and
        constraints actually influence the final ranked+explained results.

        Uses undertone="cool" (palette: sapphire/plum/true red/cool teal) so
        neither item1 (black) nor item2 (gold) gets a color-match bonus --
        isolating style's effect. (undertone="warm" would have given item2's
        "gold" color a real +0.3 palette-match bonus that legitimately
        outweighs item1's +0.15 style bonus -- not a bug, just not what this
        test is trying to isolate.)"""
        with patch("app.services.fashion.inventory_search.get_inventory", return_value=copy.deepcopy(SAMPLE_ITEMS)), \
             patch("app.services.fashion.inventory_search.embed_text", side_effect=Exception("no FashionCLIP in test")):
            result = recommend_items(
                depth="medium", undertone="cool", body_shape="pear",
                style="minimalist", constraints=["heavy embroidery"], size="M",
            )

        assert "size_hint" in result
        assert result["size_hint"] == "medium fit"
        top_result = result["results"][0]
        assert top_result["id"] == "1"  # minimalist blazer should rank highest
        assert "matches your minimalist style preference" in top_result["explanation"]

    def test_size_hint_appears_in_query_and_response(self):
        with patch("app.services.fashion.inventory_search.get_inventory", return_value=copy.deepcopy(SAMPLE_ITEMS)), \
             patch("app.services.fashion.inventory_search.embed_text", side_effect=Exception("no FashionCLIP in test")):
            result = recommend_items(depth="medium", undertone="warm", body_shape="unknown", size="L")

        assert result["size_hint"] == "large fit"
        assert "large fit" in result["query_used"]

    def test_missing_size_produces_no_hint_not_invented(self):
        with patch("app.services.fashion.inventory_search.get_inventory", return_value=copy.deepcopy(SAMPLE_ITEMS)), \
             patch("app.services.fashion.inventory_search.embed_text", side_effect=Exception("no FashionCLIP in test")):
            result = recommend_items(depth="medium", undertone="warm", body_shape="unknown")

        assert result["size_hint"] is None

    def test_backward_compatible_without_new_params(self):
        """Existing callers that don't pass style/constraints/size (e.g. any
        code not yet updated) must still work exactly as before."""
        with patch("app.services.fashion.inventory_search.get_inventory", return_value=copy.deepcopy(SAMPLE_ITEMS)), \
             patch("app.services.fashion.inventory_search.embed_text", side_effect=Exception("no FashionCLIP in test")):
            result = recommend_items(depth="medium", undertone="warm", body_shape="pear", occasion="work")

        assert result["results"]
        assert result["query_used"]


class TestGenderAndSafetyFilters:
    """Scan -> recommendations: the scan's gender label must keep the picks in
    the right department, and innerwear/kids items must never surface on the
    main path (they used to -- see catalog_filters.py)."""

    GENDERED_ITEMS = [
        {"id": "m1", "name": "Lee Men Blue Shirt", "category": "top", "color": "sapphire", "occasion": ["casual"], "style_tags": [], "stock": 5},
        {"id": "f1", "name": "W Women Sapphire Kurta", "category": "top", "color": "sapphire", "occasion": ["casual"], "style_tags": [], "stock": 5},
        {"id": "u1", "name": "Puma Unisex Sapphire Cap", "category": "accessory", "color": "sapphire", "occasion": ["casual"], "style_tags": [], "stock": 5},
        {"id": "n1", "name": "Levis Sapphire Slim Jeans", "category": "bottom", "color": "sapphire", "occasion": ["casual"], "style_tags": [], "stock": 5},
        {"id": "x1", "name": "Biara Women Sapphire Bra", "category": "top", "color": "sapphire", "occasion": ["casual"], "style_tags": [], "stock": 5},
        {"id": "x2", "name": "FCUK Underwear Men Sapphire Brief", "category": "top", "color": "sapphire", "occasion": ["casual"], "style_tags": [], "stock": 5},
        {"id": "k1", "name": "Nike Boys Sapphire T-shirt", "category": "top", "color": "sapphire", "occasion": ["casual"], "style_tags": [], "stock": 5},
        # column set explicitly -- wins over the name
        {"id": "c1", "name": "Plain Sapphire Tee", "gender": "female", "category": "top", "color": "sapphire", "occasion": ["casual"], "style_tags": [], "stock": 5},
    ]

    def _run(self, **kw):
        with patch("app.services.fashion.inventory_search.get_inventory", return_value=copy.deepcopy(self.GENDERED_ITEMS)),              patch("app.services.fashion.inventory_search.embed_text", side_effect=Exception("no FashionCLIP in test")):
            return recommend_items(depth="medium", undertone="cool", body_shape="rectangle", **kw)

    def test_male_scan_excludes_womens_and_keeps_unisex_unknown(self):
        ids = {r["id"] for r in self._run(gender="male")["results"]}
        assert "m1" in ids and "u1" in ids and "n1" in ids
        assert "f1" not in ids and "c1" not in ids

    def test_female_scan_excludes_mens(self):
        ids = {r["id"] for r in self._run(gender="female")["results"]}
        assert "f1" in ids and "c1" in ids and "u1" in ids and "n1" in ids
        assert "m1" not in ids

    def test_unknown_gender_means_no_department_filter(self):
        ids = {r["id"] for r in self._run(gender="unknown")["results"]}
        assert {"m1", "f1", "u1", "n1", "c1"} <= ids

    def test_innerwear_and_kids_never_surface_on_any_path(self):
        for g in ("male", "female", "unknown", None):
            ids = {r["id"] for r in self._run(gender=g)["results"]}
            assert not ({"x1", "x2", "k1"} & ids), (g, ids)

    def test_gender_reaches_query_and_explanation(self):
        result = self._run(gender="male")
        assert result["query_used"].startswith("men's ")
        assert result["gender_considered"] == "male"
        assert any("men's range" in r["explanation"] for r in result["results"])
        # men's wording for the body-shape hint -- not "belted" (retrieves belts)
        assert "belted" not in result["query_used"]
