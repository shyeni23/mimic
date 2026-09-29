"""
Module 3 -- Complete Outfit Recommendation Engine tests.

Two layers, same pattern as Module 2's tests:

1. Deterministic tests: pure scoring-function logic (color harmony,
   formality, occasion gating, sanity filtering, user-preference scoring)
   plus mocked-dependency tests for select_primary_item/recommend_outfit/
   get_outfit_recommendation -- no network, no Supabase, always run.

2. Live tests: call real Supabase (get_inventory, get_outfit_recommendation
   end-to-end). Skipped automatically when Supabase is unreachable, rather
   than failing the whole suite in an environment where it's down.
"""
import pytest
from unittest.mock import patch, MagicMock

from app.services.fashion.outfit_recommendation import (
    get_slots_for_category,
    get_color_family,
    score_color_harmony,
    infer_formality,
    check_formality_coherence,
    resolve_occasion_group,
    occasion_compatible,
    passes_sanity_check,
    score_user_preferences,
    score_candidate,
    select_primary_item,
    recommend_outfit,
    get_outfit_recommendation,
    NoPrimaryItemError,
    OutfitRecommendation,
)


def _supabase_reachable() -> bool:
    try:
        from app.db.supabase_client import get_supabase
        get_supabase().table("inventory").select("id").limit(1).execute()
        return True
    except Exception:
        return False


_skip_no_supabase = pytest.mark.skipif(
    not _supabase_reachable(),
    reason="Supabase is unreachable -- these tests need a real database connection.",
)


# ---------------------------------------------------------------------------
# Layer 1 -- pure scoring functions (no mocks needed, no network)
# ---------------------------------------------------------------------------

class TestCategorySlots:
    def test_top_pairs_with_bottom_and_accessories(self):
        slots = get_slots_for_category("top")
        assert "bottom" in slots
        assert "footwear" in slots
        assert "bag" in slots
        assert "jewelry" in slots
        assert "watch" in slots
        assert "accessory" in slots
        assert "top" not in slots  # never pairs with itself

    def test_dress_does_not_need_top_or_bottom(self):
        slots = get_slots_for_category("dress")
        assert "top" not in slots
        assert "bottom" not in slots
        assert "footwear" in slots

    def test_unknown_category_falls_back_to_accessory_set(self):
        slots = get_slots_for_category("something-unrecognized")
        assert slots == ["footwear", "bag", "jewelry", "watch", "accessory"]


class TestColorHarmony:
    def test_warm_color_family(self):
        assert get_color_family("red") == "warm"
        assert get_color_family("gray") == "neutral"

    def test_unknown_color_defaults_to_neutral_not_invented(self):
        assert get_color_family("nonexistent-color-xyz") == "neutral"
        assert get_color_family(None) == "neutral"

    def test_same_color_gets_small_bonus(self):
        assert score_color_harmony("black", "black") > 0

    def test_neutral_pairs_with_anything(self):
        assert score_color_harmony("red", "black") > 0
        assert score_color_harmony("black", "purple") > 0

    def test_complementary_colors_score_positive(self):
        assert score_color_harmony("blue", "orange") > 0

    def test_analogous_colors_score_positive(self):
        assert score_color_harmony("red", "orange") > 0

    def test_clashing_colors_score_negative(self):
        # red and green have no known harmony relationship in our tables
        assert score_color_harmony("red", "green") < 0

    def test_missing_color_is_neutral_not_penalized(self):
        assert score_color_harmony(None, "red") == 0.0
        assert score_color_harmony("red", None) == 0.0


class TestFormality:
    def test_formal_garment_scores_high(self):
        item = {"name": "Elegant Tuxedo Jacket", "category": "top", "style_tags": []}
        assert infer_formality(item) >= 4.5

    def test_casual_garment_scores_low(self):
        # "Sneakers" cleanly hits the 2.0 bucket with no substring collision.
        # ("T-shirt" is NOT used here: it contains "shirt", which sits in a
        # higher-priority 3.0 bucket and is checked first -- inherited
        # directly from loom's own bucket ordering, not introduced here.)
        item = {"name": "Athletic Sneakers", "category": "footwear", "style_tags": []}
        assert infer_formality(item) <= 2.5

    def test_unrecognized_item_defaults_to_neutral_not_invented(self):
        item = {"name": "Mystery Item 12345", "category": "top", "style_tags": []}
        assert infer_formality(item) == 3.0

    def test_style_tag_nudges_formality(self):
        formal_item = {"name": "Mystery Item", "category": "top", "style_tags": ["formal"]}
        casual_item = {"name": "Mystery Item", "category": "top", "style_tags": ["casual"]}
        assert infer_formality(formal_item) > infer_formality(casual_item)

    def test_small_gap_no_penalty(self):
        assert check_formality_coherence(3.0, 3.5) == 0.0

    def test_large_gap_penalized(self):
        assert check_formality_coherence(5.0, 1.0) < 0


class TestOccasionGating:
    def test_known_alias_resolves(self):
        assert resolve_occasion_group(["Party"]) == "going-out"
        assert resolve_occasion_group(["casual"]) == "casual"
        assert resolve_occasion_group(["Sports"]) == "active"

    def test_unrecognized_tag_returns_none_not_guessed(self):
        assert resolve_occasion_group(["totally-unknown-tag"]) is None
        assert resolve_occasion_group([]) is None
        assert resolve_occasion_group(None) is None

    def test_going_out_blocks_active(self):
        assert occasion_compatible("going-out", "active") is False

    def test_work_blocks_active_and_going_out(self):
        assert occasion_compatible("work", "active") is False
        assert occasion_compatible("work", "going-out") is False

    def test_same_group_is_compatible(self):
        assert occasion_compatible("casual", "casual") is True

    def test_missing_occasion_is_permissive_not_blocked(self):
        assert occasion_compatible(None, "active") is True
        assert occasion_compatible("work", None) is True


class TestSanityFilter:
    def test_clean_item_passes(self):
        assert passes_sanity_check({"name": "Blue Denim Jacket"}) is True

    def test_forbidden_keyword_rejected(self):
        assert passes_sanity_check({"name": "Floral Bikini Top"}) is False
        assert passes_sanity_check({"name": "Silk Lingerie Set"}) is False

    def test_kids_item_rejected(self):
        assert passes_sanity_check({"name": "Girls Party Dress"}) is False


class TestUserPreferenceScoring:
    def test_preferred_color_bonus(self):
        item = {"color": "pastel", "style_tags": [], "name": "Item"}
        prefs = {"color_preferences": ["pastel"]}
        assert score_user_preferences(item, prefs) > 0

    def test_disliked_color_penalty(self):
        item = {"color": "bright", "style_tags": [], "name": "Item"}
        prefs = {"disliked_colors": ["bright"]}
        assert score_user_preferences(item, prefs) < 0

    def test_constraint_keyword_penalty(self):
        item = {"color": "black", "style_tags": [], "name": "Heavy Embroidery Top"}
        prefs = {"constraints": ["heavy embroidery"]}
        assert score_user_preferences(item, prefs) < 0

    def test_no_preferences_is_neutral(self):
        item = {"color": "black", "style_tags": [], "name": "Item"}
        assert score_user_preferences(item, {}) == 0.0


class TestScoreCandidate:
    def test_compatible_candidate_scores_positive(self):
        primary = {"name": "Black Dress", "category": "dress", "color": "black", "occasion": ["party"]}
        candidate = {"name": "Gold Heels", "category": "footwear", "color": "gold", "occasion": ["party"]}
        result = score_candidate(primary, candidate, {})
        assert result is not None
        score, explanation = result
        assert score > 0
        assert explanation

    def test_occasion_blocked_candidate_returns_none(self):
        primary = {"name": "Cocktail Dress", "category": "dress", "color": "black", "occasion": ["party"]}
        candidate = {"name": "Gym Sneakers", "category": "footwear", "color": "white", "occasion": ["sports"]}
        assert score_candidate(primary, candidate, {}) is None

    def test_forbidden_candidate_returns_none(self):
        primary = {"name": "Top", "category": "top", "color": "black", "occasion": ["casual"]}
        candidate = {"name": "Bikini Bottom", "category": "bottom", "color": "black", "occasion": ["casual"]}
        assert score_candidate(primary, candidate, {}) is None


# ---------------------------------------------------------------------------
# Layer 2 -- mocked-dependency tests (get_inventory / recommend_items mocked)
# ---------------------------------------------------------------------------

class TestRecommendOutfit:
    def test_builds_outfit_from_mocked_inventory(self):
        primary = {"id": "p1", "name": "Black Dress", "category": "dress", "color": "black", "occasion": ["party"], "style_tags": []}

        fake_inventory = {
            "footwear": [{"id": "f1", "name": "Gold Heels", "category": "footwear", "color": "gold", "occasion": ["party"], "style_tags": [], "stock": 5}],
            "bag": [{"id": "b1", "name": "Black Clutch", "category": "bag", "color": "black", "occasion": ["party"], "style_tags": [], "stock": 5}],
            "jewelry": [],
            "watch": [],
            "accessory": [],
        }

        def fake_get_inventory(category=None, include_embedding=True):
            return fake_inventory.get(category, [])

        with patch("app.services.fashion.outfit_recommendation.get_inventory", side_effect=fake_get_inventory):
            result = recommend_outfit("session-1", primary, {})

        assert isinstance(result, OutfitRecommendation)
        assert result.primary_item.name == "Black Dress"
        filled_slot_names = {s.slot for s in result.slots}
        assert "footwear" in filled_slot_names
        assert "bag" in filled_slot_names
        assert "jewelry" not in filled_slot_names  # no candidates -- omitted, not invented

    def test_empty_inventory_produces_no_slots_not_fake_ones(self):
        primary = {"id": "p1", "name": "Blue Top", "category": "top", "color": "blue", "occasion": ["casual"], "style_tags": []}

        with patch("app.services.fashion.outfit_recommendation.get_inventory", return_value=[]):
            result = recommend_outfit("session-2", primary, {})

        assert result.slots == []
        assert result.overall_score == 0.0
        assert result.primary_item.name == "Blue Top"  # primary item itself is still real


class TestSelectPrimaryItem:
    def test_picks_highest_similarity_across_categories(self):
        def fake_recommend_items(category, **kwargs):
            results_by_cat = {
                "top": [{"id": "t1", "name": "Red Top", "category": "top", "similarity": 0.6}],
                "bottom": [{"id": "b1", "name": "Blue Jeans", "category": "bottom", "similarity": 0.9}],
                "dress": [{"id": "d1", "name": "Black Dress", "category": "dress", "similarity": 0.4}],
            }
            return {"results": results_by_cat.get(category, [])}

        with patch("app.services.fashion.outfit_recommendation.recommend_items", side_effect=fake_recommend_items):
            best = select_primary_item({"skin_tone_category": "medium"}, {})

        assert best["id"] == "b1"  # highest similarity (0.9)

    def test_respects_explicit_clothing_type(self):
        calls = []

        def fake_recommend_items(category, **kwargs):
            calls.append(category)
            return {"results": [{"id": "d1", "name": "Green Dress", "category": "dress", "similarity": 0.7}]}

        with patch("app.services.fashion.outfit_recommendation.recommend_items", side_effect=fake_recommend_items):
            best = select_primary_item({}, {"clothing_type": "dress"})

        assert calls == ["dress"]  # only searched the one specified category
        assert best["id"] == "d1"

    def test_no_candidates_returns_none_not_fabricated(self):
        with patch("app.services.fashion.outfit_recommendation.recommend_items", return_value={"results": []}):
            assert select_primary_item({}, {}) is None

    def test_forbidden_candidate_excluded(self):
        def fake_recommend_items(category, **kwargs):
            return {"results": [{"id": "x1", "name": "Girls Bikini Top", "category": category, "similarity": 0.99}]}

        with patch("app.services.fashion.outfit_recommendation.recommend_items", side_effect=fake_recommend_items):
            assert select_primary_item({}, {}) is None


class TestGetOutfitRecommendationPipeline:
    def test_full_pipeline_with_mocked_context_and_inventory(self):
        fake_context = {
            "session_id": "s1",
            "visual_profile": {"skin_tone_category": "medium", "skin_tone_undertone": "warm", "body_shape": "pear"},
            "fashion_preferences": {"occasion": ["party"], "color_preferences": ["gold"]},
        }

        def fake_recommend_items(category, **kwargs):
            if category == "dress":
                return {"results": [{"id": "d1", "name": "Black Dress", "category": "dress", "color": "black", "occasion": ["party"], "style_tags": [], "similarity": 0.8}]}
            return {"results": []}

        with patch("app.services.fashion.outfit_recommendation.get_user_context", return_value=fake_context), \
             patch("app.services.fashion.outfit_recommendation.recommend_items", side_effect=fake_recommend_items), \
             patch("app.services.fashion.outfit_recommendation.get_inventory", return_value=[
                 {"id": "f1", "name": "Gold Heels", "category": "footwear", "color": "gold", "occasion": ["party"], "style_tags": [], "stock": 5}
             ]):
            result = get_outfit_recommendation("s1")

        assert result.session_id == "s1"
        assert result.primary_item.name == "Black Dress"
        assert any(s.slot == "footwear" for s in result.slots)

    def test_no_primary_item_raises_not_returns_empty(self):
        fake_context = {"session_id": "s2", "visual_profile": {}, "fashion_preferences": {}}
        with patch("app.services.fashion.outfit_recommendation.get_user_context", return_value=fake_context), \
             patch("app.services.fashion.outfit_recommendation.recommend_items", return_value={"results": []}):
            with pytest.raises(NoPrimaryItemError):
                get_outfit_recommendation("s2")


# ---------------------------------------------------------------------------
# Layer 3 -- live tests against real Supabase/pgvector
# ---------------------------------------------------------------------------

class TestLiveOutfitRecommendation:
    @_skip_no_supabase
    def test_inventory_table_reachable(self):
        from app.db.supabase_client import get_inventory
        items = get_inventory()
        assert isinstance(items, list)

    @_skip_no_supabase
    def test_live_pipeline_does_not_crash_on_empty_or_seeded_inventory(self):
        """Runs the real pipeline against whatever session/inventory state
        actually exists. Accepts either a real recommendation or a clean
        NoPrimaryItemError (e.g. before the dataset has been seeded) --
        the point is verifying the live wiring itself doesn't crash."""
        from app.db.supabase_client import create_session

        session = create_session()
        session_id = session["id"]

        try:
            result = get_outfit_recommendation(session_id)
            assert isinstance(result, OutfitRecommendation)
            assert result.session_id == session_id
        except NoPrimaryItemError:
            pass  # acceptable: no inventory seeded yet, but the call didn't crash
