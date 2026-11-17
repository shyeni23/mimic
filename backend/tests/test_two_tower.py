"""
Two-tower inference (app/services/fashion/two_tower.py) -- Module 3's
previously-unwired checkpoint, now Stage C of recommend_items().

Two kinds of coverage here:
1. Tests that must pass regardless of environment -- degrade-quietly
   behaviour when the checkpoint, items, or embeddings are missing or
   malformed. These never touch torch or the real files.
2. Tests gated on is_available() -- end-to-end scoring against the ACTUAL
   checkpoint committed to this machine's data/models/two_tower/ (gitignored,
   so a fresh clone or CI box skips these rather than failing).
"""
import json

import pytest

from app.services.fashion import two_tower

REAL_EMB_DIM = 512  # Marqo-FashionCLIP's native dimension


# ---------------------------------------------------------------- degrade-quietly


def test_score_items_empty_items_returns_empty_dict():
    assert two_tower.score_items({}, []) == {}


def test_score_items_never_raises_on_malformed_embedding():
    items = [
        {"id": "a", "embedding": "not json"},
        {"id": "b", "embedding": None},
        {"id": "c", "embedding": [1, 2, 3]},        # wrong dimension
        {"id": "d"},                                 # no embedding key at all
        {"embedding": [0.1] * REAL_EMB_DIM},         # no id
    ]
    # None of these items are scoreable regardless of checkpoint
    # availability (bad embedding, wrong dimension, or no id), and this
    # must never raise.
    assert two_tower.score_items({"depth": "fair"}, items) == {}


def test_is_available_never_raises():
    # Repeated calls exercise the cached-after-first-call path too.
    assert two_tower.is_available() in (True, False)
    assert two_tower.is_available() in (True, False)


def test_one_hot_unknown_value_is_all_zero():
    assert two_tower._one_hot("not-a-real-value", ["a", "b", "c"]) == [0.0, 0.0, 0.0]
    assert two_tower._one_hot(None, ["a", "b", "c"]) == [0.0, 0.0, 0.0]
    assert two_tower._one_hot("b", ["a", "b", "c"]) == [0.0, 1.0, 0.0]


def test_user_feature_vector_matches_metadata_dimension():
    meta = {
        "occasions_vocab": ["casual", "formal"],
        "depths_vocab": ["fair", "deep"],
        "undertones_vocab": ["warm", "cool"],
        "body_shapes_vocab": ["hourglass", "pear"],
    }
    vec = two_tower._user_feature_vector(
        {"occasion": "formal", "depth": "fair", "undertone": "cool",
         "body_shape": "pear", "height_cm": 175},
        meta,
    )
    expected_len = 2 + 2 + 2 + 2 + 1  # each vocab one-hot + height
    assert len(vec) == expected_len
    assert vec == [0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.5]  # (175-150)/50 = 0.5


def test_user_feature_vector_handles_missing_height():
    meta = {"occasions_vocab": ["casual"], "depths_vocab": ["fair"],
            "undertones_vocab": ["warm"], "body_shapes_vocab": ["pear"]}
    vec = two_tower._user_feature_vector({}, meta)
    assert vec[-1] == 0.0  # no height -> 0, not a crash


def test_parse_embedding_handles_list_string_and_garbage():
    assert two_tower._parse_embedding([1.0, 2.0]) == [1.0, 2.0]
    assert two_tower._parse_embedding(json.dumps([1.0, 2.0])) == [1.0, 2.0]
    assert two_tower._parse_embedding("not json") is None
    assert two_tower._parse_embedding(None) is None
    assert two_tower._parse_embedding(123) is None


# ---------------------------------------------------------------- real checkpoint


requires_checkpoint = pytest.mark.skipif(
    not two_tower.is_available(),
    reason="data/models/two_tower checkpoint not present on this machine "
           "(gitignored, like every other model weight -- run "
           "scripts/train_two_tower.py to generate it locally)",
)


@requires_checkpoint
def test_score_items_against_real_checkpoint_returns_valid_scores():
    items = [
        {"id": "item-1", "embedding": [0.01 * i for i in range(REAL_EMB_DIM)]},
        {"id": "item-2", "embedding": [-0.01 * i for i in range(REAL_EMB_DIM)]},
        {"id": "item-3", "embedding": None},            # should be skipped
        {"id": "item-4"},                                # no embedding at all
    ]
    user_ctx = {"depth": "medium", "undertone": "warm", "body_shape": "hourglass",
                "occasion": "party", "height_cm": 165}
    scores = two_tower.score_items(user_ctx, items)

    assert set(scores.keys()) == {"item-1", "item-2"}   # only the scoreable ones
    for s in scores.values():
        assert 0.0 <= s <= 1.0


@requires_checkpoint
def test_score_items_is_deterministic():
    items = [{"id": "x", "embedding": [0.02] * REAL_EMB_DIM}]
    user_ctx = {"depth": "fair", "undertone": "cool", "body_shape": "rectangle"}
    a = two_tower.score_items(user_ctx, items)
    b = two_tower.score_items(user_ctx, items)
    assert a == b


@requires_checkpoint
def test_score_items_handles_json_string_embeddings_from_supabase():
    """Supabase returns pgvector columns as a JSON-encoded string over the
    wire in some code paths -- the same shape compatibility.py already
    handles. Must work identically to a plain list."""
    emb_list = [0.015] * REAL_EMB_DIM
    items_list = [{"id": "x", "embedding": emb_list}]
    items_str = [{"id": "x", "embedding": json.dumps(emb_list)}]
    user_ctx = {"depth": "tan"}
    assert two_tower.score_items(user_ctx, items_list) == two_tower.score_items(user_ctx, items_str)
