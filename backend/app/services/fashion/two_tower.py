"""
Two-tower neural personalization (Module 3, Stage C).

The checkpoint in data/models/two_tower/ (trained by scripts/train_two_tower.py)
sat unused: nothing in the serving path loaded it. This module is the missing
inference half -- it loads the two small MLP towers and scores how well a
customer's SCAN CONTEXT (skin tone, body shape, occasion, height) matches a
catalog item's Marqo-FashionCLIP embedding, in the shared 128-dim space the
towers were trained to agree on.

HONESTY ABOUT WHAT THIS IS: the checkpoint was trained on 15,625 SYNTHETIC
interaction triples (scripts/generate_synthetic_interactions.py's persona
archetypes), not real customer behaviour -- see HANDOFF_MODULE3.md open
issue #5. That means this model has learned to imitate the HEURISTIC that
generated its training labels, not genuine human preference. It is wired in
here as a measurable experiment (model_registry's "stage_c_neural_blend" A/B
config, see inventory_search.recommend_items), not as a trusted replacement
for the rule-based Stage B ranker, which stays the default for every session
unless this config is explicitly activated.

Degrades the same way every optional model in this codebase does (weather.py,
Replicate try-on, HF token): if the checkpoint, torch, or a shape mismatch
makes loading fail, is_available() returns False and every caller already
checks that before using this, so a fresh clone with no checkpoint (data/
models/ is gitignored, same as every other model weight) just runs the
rule-based ranker exactly as before -- this file changes nothing by its mere
presence.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parents[3] / "data" / "models" / "two_tower"
# Hidden-layer widths are a training-time architecture choice, not recorded
# in metadata.json -- must match scripts/train_two_tower.py's UserTower/
# ItemTower exactly, or the checkpoint's state_dict simply won't load (caught
# below as "unavailable", never a crash).
_USER_HIDDEN = 64
_ITEM_HIDDEN = 256

_lock = threading.Lock()
_state: dict = {"loaded": False, "ok": False, "user_tower": None, "item_tower": None,
                 "meta": None, "torch": None}


def _try_load() -> None:
    """Loads once per process; every outcome (success or failure) is cached
    so a missing checkpoint doesn't retry a filesystem+import check on every
    recommendation call."""
    if _state["loaded"]:
        return
    with _lock:
        if _state["loaded"]:  # re-check inside the lock (another thread won the race)
            return
        _state["loaded"] = True
        try:
            import torch
            import torch.nn as nn
            import torch.nn.functional as F

            meta_path = MODEL_DIR / "metadata.json"
            user_path = MODEL_DIR / "user_tower.pt"
            item_path = MODEL_DIR / "item_tower.pt"
            if not (meta_path.exists() and user_path.exists() and item_path.exists()):
                print("[two_tower] checkpoint not found (data/models/two_tower/ is gitignored, "
                      "same as every other model weight -- run scripts/train_two_tower.py to "
                      "generate it locally). Stage C stays off; rule-based ranking is unaffected.")
                return
            meta = json.loads(meta_path.read_text())

            class _UserTower(nn.Module):
                def __init__(self, in_dim: int, out_dim: int):
                    super().__init__()
                    self.net = nn.Sequential(
                        nn.Linear(in_dim, _USER_HIDDEN), nn.ReLU(),
                        nn.Linear(_USER_HIDDEN, out_dim),
                    )

                def forward(self, x):
                    return F.normalize(self.net(x), dim=-1)

            class _ItemTower(nn.Module):
                def __init__(self, in_dim: int, out_dim: int):
                    super().__init__()
                    self.net = nn.Sequential(
                        nn.Linear(in_dim, _ITEM_HIDDEN), nn.ReLU(),
                        nn.Linear(_ITEM_HIDDEN, out_dim),
                    )

                def forward(self, x):
                    return F.normalize(self.net(x), dim=-1)

            user_tower = _UserTower(meta["user_feature_dim"], meta["shared_dim"])
            item_tower = _ItemTower(meta["item_embed_dim"], meta["shared_dim"])
            user_tower.load_state_dict(torch.load(user_path, map_location="cpu"))
            item_tower.load_state_dict(torch.load(item_path, map_location="cpu"))
            user_tower.eval()
            item_tower.eval()

            _state.update(ok=True, user_tower=user_tower, item_tower=item_tower,
                           meta=meta, torch=torch)
            note = " (dry-run weights -- not meaningful)" if meta.get("dry_run") else ""
            print(f"[two_tower] loaded checkpoint, trained on {meta.get('trained_on_triples')} "
                  f"synthetic triples{note}")
        except Exception as e:
            # Any failure (missing torch, corrupt file, hidden-size mismatch
            # from a retrain with different architecture) degrades to
            # "unavailable", exactly like every other optional model here.
            print(f"[two_tower] checkpoint failed to load, Stage C stays off (non-fatal): {e}")


def is_available() -> bool:
    _try_load()
    return bool(_state["ok"])


def _one_hot(value: str | None, vocab: list[str]) -> list[float]:
    v = [0.0] * len(vocab)
    if value and value in vocab:
        v[vocab.index(value)] = 1.0
    return v


def _user_feature_vector(user_ctx: dict, meta: dict) -> list[float]:
    """Mirrors scripts/train_two_tower.py's build_user_feature_vector exactly
    -- same features, same concatenation order -- but reads the vocab lists
    FROM the checkpoint's own metadata.json rather than importing the
    training script, so serving always matches whatever checkpoint is
    actually loaded, even after a retrain with a different vocab."""
    occasion = _one_hot(user_ctx.get("occasion"), meta["occasions_vocab"])
    depth = _one_hot(user_ctx.get("depth"), meta["depths_vocab"])
    undertone = _one_hot(user_ctx.get("undertone"), meta["undertones_vocab"])
    body_shape = _one_hot(user_ctx.get("body_shape"), meta["body_shapes_vocab"])
    height = user_ctx.get("height_cm")
    height_norm = [((height - 150) / 50) if height else 0.0]
    return occasion + depth + undertone + body_shape + height_norm


def _parse_embedding(raw) -> list[float] | None:
    """Supabase returns pgvector as either a JSON-encoded string or a list --
    same shape compatibility.py and train_two_tower.py already handle."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else None
        except Exception:
            return None
    return None


def score_items(user_ctx: dict, items: list[dict]) -> dict[str, float]:
    """Score how well each item fits this customer's scan context, in [0, 1].

    user_ctx: {"depth", "undertone", "body_shape", "occasion", "height_cm"} --
    exactly the fields recommend_items() already has on hand from the scan,
    no extra lookup needed.

    Returns {item_id: score} -- items with no id or no usable embedding are
    simply absent from the result (never a 0.0, which would read as "bad
    fit" rather than "no opinion"). Callers blend this additively with
    whatever ranking signal they already have, weighted by how much they
    trust it; an item missing from this dict should be left at its
    unblended score, not penalized.

    Never raises: a scoring failure degrades to an empty dict, same as
    is_available() returning False -- the rule-based ranker is always a
    safe fallback.
    """
    if not items or not is_available():
        return {}
    try:
        torch = _state["torch"]
        meta = _state["meta"]
        user_vec = _user_feature_vector(user_ctx, meta)

        valid_ids, valid_embs = [], []
        for it in items:
            iid = it.get("id")
            emb = _parse_embedding(it.get("embedding"))
            if iid and emb and len(emb) == meta["item_embed_dim"]:
                valid_ids.append(iid)
                valid_embs.append(emb)
        if not valid_ids:
            return {}

        with torch.no_grad():
            u = torch.tensor([user_vec], dtype=torch.float32)
            i = torch.tensor(valid_embs, dtype=torch.float32)
            u_proj = _state["user_tower"](u)        # (1, shared_dim), L2-normalized
            i_proj = _state["item_tower"](i)         # (N, shared_dim), L2-normalized
            sim = (u_proj @ i_proj.T).squeeze(0)     # (N,) cosine in [-1, 1]
            scores = ((sim + 1.0) / 2.0).clamp(0.0, 1.0).tolist()

        return dict(zip(valid_ids, (round(s, 4) for s in scores)))
    except Exception as e:
        print(f"[two_tower] scoring failed (non-fatal, falling back to rule-only ranking): {e}")
        return {}
