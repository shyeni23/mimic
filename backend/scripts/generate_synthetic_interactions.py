"""
Generates SYNTHETIC customer interactions to get the two-tower model
(scripts/train_two_tower.py) past its 10,000-positive-interaction data
floor (see check_training_readiness.py) for demo purposes -- the real
store only has ~100 interactions so far, nowhere near enough for that
model to learn real structure.

This is explicitly NOT real customer data and never claims to be:
- Every row this script writes is tagged {"synthetic": true, "persona": ...}
  in interactions.context, so it can be identified, reported on, or wiped
  later without touching real interaction history.
- It does not invent a preference at random -- each of a handful of
  "persona" archetypes is built from this app's OWN real color-matching
  logic (app/services/vision/skin_tone.py's FLATTERING_PALETTES, keyed by
  the same depth/undertone/body_shape vocabulary train_two_tower.py
  already trains on) and picks REAL inventory items whose color/occasion
  actually match that persona, so the model has genuine learnable
  structure to find (persona X reliably engages with warm-toned casual
  items, persona Y with cool-toned formal items, etc.) rather than
  memorizing pure noise. It is still not real customer behavior --
  training on this proves the PIPELINE works end-to-end, it does not
  produce a model that has learned anything about actual customers.

Run:
    python scripts/generate_synthetic_interactions.py                  # ~11K positives (safely over the 10K floor)
    python scripts/generate_synthetic_interactions.py --target-positives 500 --dry-run   # sanity check first
    python scripts/generate_synthetic_interactions.py --wipe           # delete all synthetic rows, nothing else
"""
import argparse
import random
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.supabase_client import get_supabase

POSITIVE_EVENTS = ["click", "click", "click", "add_to_cart", "tryon"]  # weighted -- click most common
NEGATIVE_EVENTS = ["skip", "skip", "dismiss"]

# Each persona = a real (undertone, depth) key from skin_tone.py's
# FLATTERING_PALETTES, a body_shape from train_two_tower.py's own vocab,
# an occasion this persona shops for, and colors PULLED FROM THE REAL
# INVENTORY (see comment) that plausibly match that palette's warm/cool/
# neutral character -- not invented, and not the exact (often multi-word,
# e.g. "burnt orange") FLATTERING_PALETTES strings, since inventory.color
# uses simpler single/double-word values (checked live: black, blue,
# white, brown, silver, grey, red, green, purple, pink, navy blue, beige,
# gold, maroon, yellow, steel, cream, orange, olive, charcoal, rust,
# magenta, teal, lavender...).
PERSONAS = [
    {"name": "warm_medium_casual", "undertone": "warm", "depth": "medium", "body_shape": "hourglass",
     "occasion": "casual", "colors": ["orange", "brown", "gold", "maroon", "rust", "beige", "olive", "yellow"],
     "height_range": (155, 175)},
    {"name": "cool_light_formal", "undertone": "cool", "depth": "light", "body_shape": "rectangle",
     "occasion": "formal", "colors": ["blue", "navy blue", "purple", "teal", "lavender", "silver", "grey"],
     "height_range": (160, 185)},
    {"name": "neutral_tan_ethnic", "undertone": "neutral", "depth": "tan", "body_shape": "pear",
     "occasion": "ethnic", "colors": ["olive", "navy blue", "cream", "rust", "beige", "brown"],
     "height_range": (150, 170)},
    {"name": "cool_deep_party", "undertone": "cool", "depth": "deep", "body_shape": "inverted_triangle",
     "occasion": "party", "colors": ["white", "purple", "magenta", "teal", "black"],
     "height_range": (165, 190)},
    {"name": "warm_fair_travel", "undertone": "warm", "depth": "fair", "body_shape": "apple",
     "occasion": "travel", "colors": ["beige", "gold", "olive", "orange", "cream"],
     "height_range": (155, 178)},
    {"name": "neutral_medium_sports", "undertone": "neutral", "depth": "medium", "body_shape": "hourglass",
     "occasion": "sports", "colors": ["teal", "maroon", "charcoal", "grey", "navy blue"],
     "height_range": (158, 182)},
]

SYNTHETIC_MARKER = {"synthetic": True}


def _retry(fn, tries=4, delay=2):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"  retry {i + 1}/{tries} after error: {type(e).__name__}: {str(e)[:100]}")
            time.sleep(delay * (i + 1))
    raise last


def batch_insert(sb, table: str, rows: list[dict], chunk: int = 500) -> list[dict]:
    out = []
    for i in range(0, len(rows), chunk):
        batch = rows[i:i + chunk]
        res = _retry(lambda b=batch: sb.table(table).insert(b).execute())
        out.extend(res.data)
    return out


def wipe_synthetic(sb):
    print("Deleting synthetic interactions...")
    _retry(lambda: sb.table("interactions").delete().eq("context->>synthetic", "true").execute())
    print("Done. (Synthetic sessions/scans/conversations are harmless leftovers -- "
          "they carry no 'synthetic' flag of their own since sessions/scans have no "
          "free-form JSON column, but they're inert without their interactions and "
          "match no real customer.)")


def run(target_positives: int, dry_run: bool, sessions_per_persona: int | None):
    sb = get_supabase()

    print("Loading real inventory (name/category/color/occasion only)...")
    # PostgREST caps a single response at 1000 rows by default -- paginate
    # or this silently only sees the first 1000 of ~37K items (confirmed
    # live), badly understating every persona's real match pool.
    items = []
    offset = 0
    while True:
        page = _retry(lambda o=offset: sb.table("inventory").select("id,category,color,occasion")
                       .gt("stock", 0).range(o, o + 999).execute())
        if not page.data:
            break
        items.extend(page.data)
        if len(page.data) < 1000:
            break
        offset += 1000
    print(f"  {len(items)} in-stock items")

    by_persona_match: dict[str, list[dict]] = {}
    by_persona_mismatch: dict[str, list[dict]] = {}
    for p in PERSONAS:
        colors = set(p["colors"])
        match = [i for i in items if (i.get("color") or "") in colors]
        mismatch = [i for i in items if (i.get("color") or "") not in colors]
        by_persona_match[p["name"]] = match
        by_persona_mismatch[p["name"]] = mismatch
        print(f"  persona {p['name']}: {len(match)} matching-color items, {len(mismatch)} mismatched")

    # ~4.5 positive events/session on average (see POSITIVE_EVENTS sampling
    # below) -- back into how many sessions/persona are needed to clear the
    # target, split evenly across all personas.
    avg_positives_per_session = 4.5
    if sessions_per_persona is None:
        total_sessions_needed = max(1, int(target_positives / avg_positives_per_session))
        sessions_per_persona = max(1, total_sessions_needed // len(PERSONAS))

    print(f"\nPlan: {sessions_per_persona} synthetic sessions x {len(PERSONAS)} personas "
          f"= {sessions_per_persona * len(PERSONAS)} sessions "
          f"(~{int(sessions_per_persona * len(PERSONAS) * avg_positives_per_session)} positive interactions)")

    if dry_run:
        print("\n--dry-run: no rows written.")
        return

    t0 = time.time()
    total_positive = 0
    total_negative = 0

    for p in PERSONAS:
        match_pool = by_persona_match[p["name"]]
        mismatch_pool = by_persona_mismatch[p["name"]]
        if len(match_pool) < 3:
            print(f"  skipping {p['name']}: too few matching items ({len(match_pool)})")
            continue

        print(f"\nPersona {p['name']}: creating {sessions_per_persona} sessions...")
        session_rows = batch_insert(sb, "sessions", [{"user_id": None} for _ in range(sessions_per_persona)])
        session_ids = [r["id"] for r in session_rows]

        scan_rows = [{
            "session_id": sid,
            "body_shape": p["body_shape"],
            "face_shape": random.choice(["oval", "round", "square", "heart", "long"]),
            "skin_tone_hex": "#C68863",
            "skin_tone_category": p["depth"],
            "skin_tone_undertone": p["undertone"],
            "body_size_estimate": random.choice(["S", "M", "L"]),
            "height_cm": round(random.uniform(*p["height_range"]), 1),
            "height_source": "camera",
            "glasses_detected": random.random() < 0.2,
            "hair_length": random.choice(["short", "medium", "long"]),
            "gender": random.choice(["male", "female"]),
        } for sid in session_ids]
        batch_insert(sb, "scans", scan_rows)

        # One assistant conversation turn per session carrying this persona's
        # occasion as a "preference" -- extract_prior_preferences() (used by
        # both the live agent and train_two_tower.py's feature builder) reads
        # occasion from conversation meta, not from scans.
        convo_rows = [{
            "session_id": sid, "role": "assistant",
            "content": f"Here are some {p['occasion']} options for you.",
            "meta": {"preferences": {"occasion": p["occasion"]}},
        } for sid in session_ids]
        batch_insert(sb, "conversations", convo_rows)

        interaction_rows = []
        for sid in session_ids:
            n_positive = random.randint(3, 6)
            n_negative = random.randint(1, 3)
            for item in random.sample(match_pool, min(n_positive, len(match_pool))):
                interaction_rows.append({
                    "session_id": sid, "item_id": item["id"],
                    "event_type": random.choice(POSITIVE_EVENTS),
                    "context": {**SYNTHETIC_MARKER, "persona": p["name"]},
                })
                total_positive += 1
            for item in random.sample(mismatch_pool, min(n_negative, len(mismatch_pool))):
                interaction_rows.append({
                    "session_id": sid, "item_id": item["id"],
                    "event_type": random.choice(NEGATIVE_EVENTS),
                    "context": {**SYNTHETIC_MARKER, "persona": p["name"]},
                })
                total_negative += 1

        batch_insert(sb, "interactions", interaction_rows)
        print(f"  wrote {len(interaction_rows)} interactions "
              f"({sum(1 for r in interaction_rows if r['event_type'] in ('click', 'add_to_cart', 'tryon'))} positive)")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s: {total_positive} positive + {total_negative} negative "
          f"synthetic interactions written across {len(PERSONAS)} personas.")
    print("Run scripts/check_training_readiness.py to confirm the floor is cleared, "
          "then scripts/train_two_tower.py to actually train.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-positives", type=int, default=11_000,
                         help="Roughly how many positive interactions to generate (default clears the 10K floor)")
    parser.add_argument("--sessions-per-persona", type=int, default=None,
                         help="Override the computed session count directly instead of deriving it from --target-positives")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without writing anything")
    parser.add_argument("--wipe", action="store_true", help="Delete all synthetic interactions and exit")
    args = parser.parse_args()

    if args.wipe:
        wipe_synthetic(get_supabase())
    else:
        run(args.target_positives, args.dry_run, args.sessions_per_persona)
