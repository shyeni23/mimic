"""
Stage C wiring in recommend_items() (app/services/fashion/inventory_search.py)
-- the two-tower checkpoint is now loaded and scored, gated behind the
"stage_c_neural_blend" model_registry config (default off) and
two_tower.is_available() (checkpoint presence).

All mocked: no DB, no torch, no checkpoint required to run these. They
verify the WIRING -- that the right things get called when the config says
to, and nothing extra happens when it doesn't -- not the two-tower model's
actual output (see test_two_tower.py for that) or the blend arithmetic (see
test_compatibility_neural_blend.py for that).
"""
import copy
from unittest.mock import MagicMock, patch

from app.services.fashion.inventory_search import recommend_items

SAMPLE_ITEMS = [
    {"id": "1", "name": "Minimalist Black Blazer", "category": "top", "color": "black",
     "occasion": ["work"], "style_tags": ["minimalist", "classic"]},
    {"id": "2", "name": "Bold Sequin Party Top", "category": "top", "color": "gold",
     "occasion": ["party"], "style_tags": ["statement", "bold"]},
]

_NO_FASHION_CLIP = patch(
    "app.services.fashion.inventory_search.embed_text",
    side_effect=Exception("no FashionCLIP in test"))
_INVENTORY = patch(
    "app.services.fashion.inventory_search.get_inventory",
    return_value=copy.deepcopy(SAMPLE_ITEMS))


class TestStageCStaysOffByDefault:
    def test_no_session_id_never_touches_the_registry_or_two_tower(self):
        """The overwhelming majority of existing calls (no session_id) must
        incur zero extra cost from Stage C -- not even a registry lookup."""
        with _INVENTORY, _NO_FASHION_CLIP, \
             patch("app.services.fashion.model_registry.get_active_config") as mock_cfg, \
             patch("app.services.fashion.two_tower.is_available") as mock_avail:
            result = recommend_items(depth="medium", undertone="warm", body_shape="pear")

        mock_cfg.assert_not_called()
        mock_avail.assert_not_called()
        assert result["results"]

    def test_session_id_with_no_active_config_behaves_exactly_as_before(self):
        """get_active_config's real default-return behaviour (nothing
        registered) must leave results unaffected -- this is what every
        session gets today, and after this change, until the config is
        explicitly activated."""
        with _INVENTORY, _NO_FASHION_CLIP:
            without_session = recommend_items(depth="medium", undertone="warm", body_shape="pear")
            with_session = recommend_items(
                depth="medium", undertone="warm", body_shape="pear", session_id="s-1")

        ids_a = [r["id"] for r in without_session["results"]]
        ids_b = [r["id"] for r in with_session["results"]]
        assert ids_a == ids_b

    def test_checkpoint_unavailable_skips_hydration_even_if_config_enabled(self):
        """A registered-and-active config can't do anything if the checkpoint
        itself isn't on this machine -- must degrade quietly, not error."""
        with _INVENTORY, _NO_FASHION_CLIP, \
             patch("app.services.fashion.model_registry.get_active_config",
                   return_value={"enabled": True, "weight": 0.5}), \
             patch("app.services.fashion.two_tower.is_available", return_value=False), \
             patch("app.services.fashion.inventory_search.get_supabase") as mock_sb:
            result = recommend_items(
                depth="medium", undertone="warm", body_shape="pear", session_id="s-1")

        mock_sb.assert_not_called()  # no hydration query was ever issued
        assert result["results"]


class TestStageCWhenActive:
    def _supabase_hydration_mock(self):
        """A minimal stand-in for get_supabase().table(...).select(...)
        .in_(...).execute().data -- returns an embedding for every item."""
        sb = MagicMock()
        sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
            {"id": it["id"], "embedding": [0.01] * 512, "style_tags": [], "occasion": []}
            for it in SAMPLE_ITEMS
        ]
        return sb

    def test_enabled_config_triggers_hydration_and_scoring(self):
        with _INVENTORY, _NO_FASHION_CLIP, \
             patch("app.services.fashion.model_registry.get_active_config",
                   return_value={"enabled": True, "weight": 0.4}), \
             patch("app.services.fashion.two_tower.is_available", return_value=True), \
             patch("app.services.fashion.two_tower.score_items",
                   return_value={"1": 0.9, "2": 0.1}) as mock_score, \
             patch("app.services.fashion.inventory_search.get_supabase",
                   return_value=self._supabase_hydration_mock()):
            result = recommend_items(
                depth="medium", undertone="warm", body_shape="pear", session_id="s-1")

        mock_score.assert_called_once()
        # score_items was called with the hydrated candidate list.
        _, items_arg = mock_score.call_args[0]
        assert all("embedding" in it for it in items_arg)
        assert result["results"]

    def test_neural_score_changes_ranking_when_it_disagrees_with_stage_a(self):
        """End-to-end proof that Stage C can actually move the needle on the
        FIRST recommendation of a session (no anchor items), where Stage B
        is otherwise a complete no-op."""
        with _INVENTORY, _NO_FASHION_CLIP, \
             patch("app.services.fashion.model_registry.get_active_config",
                   return_value={"enabled": True, "weight": 0.95}), \
             patch("app.services.fashion.two_tower.is_available", return_value=True), \
             patch("app.services.fashion.two_tower.score_items",
                   return_value={"1": 0.0, "2": 1.0}), \
             patch("app.services.fashion.inventory_search.get_supabase",
                   return_value=self._supabase_hydration_mock()):
            result = recommend_items(
                depth="medium", undertone="warm", body_shape="pear", session_id="s-1")

        # Item 2 was pushed to the top by an overwhelming neural preference,
        # despite whatever Stage A's cosine similarity said.
        assert result["results"][0]["id"] == "2"

    def test_disabled_config_explicitly_skips_stage_c(self):
        with _INVENTORY, _NO_FASHION_CLIP, \
             patch("app.services.fashion.model_registry.get_active_config",
                   return_value={"enabled": False, "weight": 0.9}), \
             patch("app.services.fashion.two_tower.is_available", return_value=True), \
             patch("app.services.fashion.two_tower.score_items") as mock_score:
            result = recommend_items(
                depth="medium", undertone="warm", body_shape="pear", session_id="s-1")

        mock_score.assert_not_called()
        assert result["results"]
