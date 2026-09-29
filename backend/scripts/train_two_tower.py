"""
Two-tower user-preference model (Module 3's final DL piece).

Architecture: User tower (small MLP over hand-engineered context features)
and Item tower (small MLP on top of the Marqo-FashionCLIP embedding already
computed for every inventory row -- see fashion_clip.py) project into a
SHARED 128-dim space. Trained with in-batch negative sampling: for each
positive (user, item) pair in a batch, every other item in the batch acts
as an implicit negative, and the loss pulls matching pairs' embeddings
together while pushing non-matching pairs apart (standard contrastive/
softmax retrieval loss -- the same approach two-tower recommenders use in
production, e.g. YouTube/Google's original two-tower paper).

GATED behind a minimum-data check (see check_training_readiness.py) --
refuses to run for real unless there's enough positive-signal volume,
because a two-tower model trained on too few examples doesn't learn real
preference structure, it memorizes noise. Use --dry-run to exercise the
full pipeline (feature extraction, batching, one training step, checkpoint
save) on WHATEVER data exists right now, bypassing the gate -- this proves
the code is mechanically correct without claiming the resulting weights
mean anything. Real training should only ever be run without --dry-run
once check_training_readiness.py says READY.

Run:
    python scripts/train_two_tower.py --dry-run          # proves the pipeline works, any data volume
    python scripts/train_two_tower.py                    # real training, refuses below the readiness gate
    python scripts/train_two_tower.py --min-interactions 50 --epochs 3   # override gate for controlled testing
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import torch
import torch.nn as nn
import torch.nn.functional as F

from app.db.supabase_client import get_supabase

MODEL_DIR = Path(__file__).resolve().parents[1] / "data" / "models" / "two_tower"
ITEM_EMBED_DIM = 512  # Marqo-FashionCLIP's native dimension -- see fashion_clip.py
SHARED_DIM = 128       # projection target both towers learn into
POSITIVE_EVENT_TYPES = ("click", "add_to_cart", "tryon")
NEGATIVE_EVENT_TYPES = ("skip", "dismiss")

# Fixed vocabulary for one-hot-ish user context features. Kept small and
# explicit (not learned embeddings for categoricals) because with only a
# few thousand training examples, a large learned-embedding vocabulary
# would itself be undertrained -- simple wins at this data scale.
OCCASIONS = ["casual", "formal", "office", "party", "wedding", "date", "travel", "sports", "ethnic", "home"]
DEPTHS = ["fair", "light", "medium", "tan", "deep"]
UNDERTONES = ["warm", "cool", "neutral"]
BODY_SHAPES = ["hourglass", "pear", "inverted_triangle", "rectangle", "apple"]
USER_FEATURE_DIM = len(OCCASIONS) + len(DEPTHS) + len(UNDERTONES) + len(BODY_SHAPES) + 1  # +1 for height (normalized)


def _one_hot(value: str | None, vocab: list[str]) -> list[float]:
    v = [0.0] * len(vocab)
    if value and value in vocab:
        v[vocab.index(value)] = 1.0
    return v


def build_user_feature_vector(scan: dict | None, preferences: dict | None) -> list[float]:
    """Same override logic as tools.py's recommend_clothes: a conversational
    correction to undertone/depth wins over the scan value. Keeps the
    training-time feature construction consistent with what the live
    inference path will eventually use."""
    scan = scan or {}
    preferences = preferences or {}
    occasion = _one_hot(preferences.get("occasion"), OCCASIONS)
    depth = _one_hot(preferences.get("skin_depth") or scan.get("skin_tone_category"), DEPTHS)
    undertone = _one_hot(preferences.get("undertone") or scan.get("skin_tone_undertone"), UNDERTONES)
    body_shape = _one_hot(scan.get("body_shape"), BODY_SHAPES)
    height = scan.get("height_cm")
    height_norm = [((height - 150) / 50) if height else 0.0]  # rough 150-200cm -> [0,1]
    return occasion + depth + undertone + body_shape + height_norm


class UserTower(nn.Module):
    def __init__(self, in_dim: int = USER_FEATURE_DIM, out_dim: int = SHARED_DIM):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, 64), nn.ReLU(),
            nn.Linear(64, out_dim),
        )

    def forward(self, x):
        return F.normalize(self.net(x), dim=-1)


class ItemTower(nn.Module):
    """Projects the FIXED Marqo embedding (not retrained) into the shared
    space -- reuses the DL work already done (fashion_clip.py) instead of
    learning image/text understanding from scratch on a tiny dataset."""
    def __init__(self, in_dim: int = ITEM_EMBED_DIM, out_dim: int = SHARED_DIM):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, 256), nn.ReLU(),
            nn.Linear(256, out_dim),
        )

    def forward(self, x):
        return F.normalize(self.net(x), dim=-1)


def _parse_embedding(raw):
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


def _paginated_select(sb, table: str, columns: str, event_types: tuple[str, ...]) -> list[dict]:
    """PostgREST caps a single response at 1000 rows by default -- a plain
    .select().execute() on `interactions` silently truncated once the table
    passed that size (confirmed live: 15,839 real rows, only the first 1000
    ever reached training). Page through with .range() instead."""
    rows = []
    offset = 0
    while True:
        page = (sb.table(table).select(columns).in_("event_type", event_types)
                .range(offset, offset + 999).execute())
        if not page.data:
            break
        rows.extend(page.data)
        if len(page.data) < 1000:
            break
        offset += 1000
    return rows


def _chunked_in_select(sb, table: str, id_column: str, ids: list[str], columns: str,
                        id_chunk: int = 200) -> list[dict]:
    """Same 1000-row cap applies to .in_(...) queries too, and a multi-
    thousand-UUID IN-list is also just an unreasonably large query string --
    chunk the input AND paginate each chunk's response."""
    rows = []
    for i in range(0, len(ids), id_chunk):
        chunk = ids[i:i + id_chunk]
        offset = 0
        while True:
            page = (sb.table(table).select(columns).in_(id_column, chunk)
                     .range(offset, offset + 999).execute())
            if not page.data:
                break
            rows.extend(page.data)
            if len(page.data) < 1000:
                break
            offset += 1000
    return rows


def extract_training_triples(sb) -> list[dict]:
    """Build (user_context_vector, item_embedding, label) training rows --
    one per positive OR negative interaction, joined against that
    interaction's session (for user context) and item (for the Marqo
    embedding already computed). This is the same event taxonomy
    get_session_interaction_signals() already uses elsewhere in the
    codebase (engaged vs dismissed), just flattened into a training set
    instead of a per-session live signal.
    """
    interactions = _paginated_select(
        sb, "interactions", "session_id,item_id,event_type",
        POSITIVE_EVENT_TYPES + NEGATIVE_EVENT_TYPES,
    )
    if not interactions:
        return []

    session_ids = list({r["session_id"] for r in interactions if r.get("session_id")})
    item_ids = list({r["item_id"] for r in interactions if r.get("item_id")})

    scans_by_session: dict[str, dict] = {}
    if session_ids:
        for row in _chunked_in_select(sb, "scans", "session_id", session_ids, "*"):
            sid = row.get("session_id")
            # Keep only the latest scan per session (rows already come back
            # unordered from a plain select -- last-write-wins is fine here
            # since we just need SOME representative scan, not history).
            scans_by_session[sid] = row

    # Conversation-extracted preferences per session -- reuse the exact
    # persistence helper the live agent already uses (meta on assistant
    # turns), so training features match what inference will eventually see.
    # Batched (chunked IN) rather than one request per session -- with
    # thousands of sessions, a per-session loop here was thousands of
    # sequential network round trips.
    from app.services.agent.preferences import extract_prior_preferences
    history_by_session: dict[str, list[dict]] = {sid: [] for sid in session_ids}
    if session_ids:
        for row in _chunked_in_select(sb, "conversations", "session_id", session_ids, "session_id,role,meta"):
            sid = row.get("session_id")
            if sid in history_by_session:
                history_by_session[sid].append({"role": row.get("role"), "meta": row.get("meta")})
    prefs_by_session: dict[str, dict] = {}
    for sid in session_ids:
        try:
            prefs_by_session[sid] = extract_prior_preferences(history_by_session.get(sid, []))
        except Exception:
            prefs_by_session[sid] = {}

    items_by_id: dict[str, dict] = {}
    if item_ids:
        for row in _chunked_in_select(sb, "inventory", "id", item_ids, "id,embedding"):
            items_by_id[row["id"]] = row

    triples = []
    for r in interactions:
        sid, iid, et = r.get("session_id"), r.get("item_id"), r.get("event_type")
        if not sid or not iid:
            continue
        item_row = items_by_id.get(iid)
        if not item_row:
            continue
        item_emb = _parse_embedding(item_row.get("embedding"))
        if not item_emb:
            continue

        user_vec = build_user_feature_vector(scans_by_session.get(sid), prefs_by_session.get(sid))
        label = 1.0 if et in POSITIVE_EVENT_TYPES else 0.0
        triples.append({"user_vec": user_vec, "item_emb": item_emb, "label": label})

    return triples


def train(triples: list[dict], epochs: int, batch_size: int, lr: float):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Training on {len(triples)} triples, device={device}")

    user_tower = UserTower().to(device)
    item_tower = ItemTower().to(device)
    optimizer = torch.optim.Adam(
        list(user_tower.parameters()) + list(item_tower.parameters()), lr=lr,
    )

    user_x = torch.tensor([t["user_vec"] for t in triples], dtype=torch.float32).to(device)
    item_x = torch.tensor([t["item_emb"] for t in triples], dtype=torch.float32).to(device)
    labels = torch.tensor([t["label"] for t in triples], dtype=torch.float32).to(device)

    n = len(triples)
    for epoch in range(epochs):
        perm = torch.randperm(n)
        total_loss = 0.0
        n_batches = 0
        for start in range(0, n, batch_size):
            idx = perm[start:start + batch_size]
            if len(idx) < 2:
                continue  # in-batch negatives need at least 2 examples
            bu, bi, bl = user_x[idx], item_x[idx], labels[idx]

            u_emb = user_tower(bu)
            i_emb = item_tower(bi)
            # In-batch similarity matrix -- diagonal is the "true" pair for
            # positives; negatives (label=0) are down-weighted in the loss
            # rather than excluded, since a skip is real negative SIGNAL,
            # not just an absent positive.
            sim = u_emb @ i_emb.T  # (batch, batch)
            targets = torch.arange(len(idx), device=device)
            per_example_loss = F.cross_entropy(sim, targets, reduction="none")
            # Positives get full weight; negatives get down-weighted (they
            # still contribute -- a skip means "this specific pairing is
            # bad," which the diagonal-matching loss doesn't directly
            # capture, so this is an approximation, not a perfect
            # negative-mining objective. Documented limitation.)
            weights = torch.where(bl > 0, torch.ones_like(bl), torch.full_like(bl, 0.3))
            loss = (per_example_loss * weights).mean()

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
            n_batches += 1

        avg_loss = total_loss / max(n_batches, 1)
        print(f"  epoch {epoch + 1}/{epochs}  avg_loss={avg_loss:.4f}")

    return user_tower, item_tower


def save_checkpoint(user_tower, item_tower, n_triples: int, dry_run: bool):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "_dryrun" if dry_run else ""
    torch.save(user_tower.state_dict(), MODEL_DIR / f"user_tower{suffix}.pt")
    torch.save(item_tower.state_dict(), MODEL_DIR / f"item_tower{suffix}.pt")
    meta = {
        "trained_on_triples": n_triples,
        "dry_run": dry_run,
        "shared_dim": SHARED_DIM,
        "item_embed_dim": ITEM_EMBED_DIM,
        "user_feature_dim": USER_FEATURE_DIM,
        "occasions_vocab": OCCASIONS, "depths_vocab": DEPTHS,
        "undertones_vocab": UNDERTONES, "body_shapes_vocab": BODY_SHAPES,
    }
    with open(MODEL_DIR / f"metadata{suffix}.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Saved checkpoint to {MODEL_DIR} (suffix={suffix or '(none)'})")


def run(min_interactions: int, epochs: int, batch_size: int, lr: float, dry_run: bool):
    sb = get_supabase()

    positive_count = (
        sb.table("interactions")
        .select("id", count="exact")
        .in_("event_type", POSITIVE_EVENT_TYPES)
        .limit(1)
        .execute()
        .count
    )
    print(f"Positive-signal interactions available: {positive_count}")

    if not dry_run and positive_count < min_interactions:
        print(
            f"\nNOT ENOUGH DATA: {positive_count} < {min_interactions} threshold. "
            f"Training refused -- a model trained on this little data would memorize "
            f"noise, not learn real preferences.\n"
            f"Run scripts/check_training_readiness.py for an ETA, or pass --dry-run "
            f"to exercise the pipeline anyway (weights won't be meaningful)."
        )
        sys.exit(1)

    print("Extracting training triples...")
    triples = extract_training_triples(sb)
    print(f"  {len(triples)} usable triples (after joining against scans + item embeddings)")

    if len(triples) < 2:
        print("Not enough joinable data to run even one training batch. Aborting.")
        sys.exit(1)

    user_tower, item_tower = train(triples, epochs, batch_size, lr)
    save_checkpoint(user_tower, item_tower, len(triples), dry_run)

    if dry_run:
        print(
            "\nDRY RUN COMPLETE: pipeline is mechanically correct end-to-end "
            "(feature extraction, batching, training loop, checkpoint save all "
            "worked). These weights are NOT meaningful -- do not wire them into "
            "the live recommend_items() path. Re-run without --dry-run once "
            "check_training_readiness.py reports READY."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-interactions", type=int, default=10_000,
                        help="Positive-signal floor before real training is allowed.")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--dry-run", action="store_true",
                        help="Run the full pipeline on whatever data exists now, "
                             "bypassing the data-volume gate, to prove the code works.")
    args = parser.parse_args()
    run(args.min_interactions, args.epochs, args.batch_size, args.lr, args.dry_run)
