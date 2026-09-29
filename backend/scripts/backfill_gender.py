"""
Backfill `inventory.gender` from the source dataset
(ashraq/fashion-product-images-small) -- the dataset's `gender` field
(Men / Women / Boys / Girls / Unisex) was never captured by
seed_fashion_dataset.py, and until it exists the body scan's gender label
has nothing to filter against (see catalog_filters.py).

Matches dataset rows to inventory rows BY NAME, same join key as
backfill_season_year.py / backfill_image_embeddings.py, including its
handling of duplicate names (one name -> many ids). Rows the dataset
can't match fall back to catalog_filters.infer_gender_from_name() so the
column is as complete as possible; rows neither can classify are left null
(never guessed) -- the live filter treats null as "unknown, let it through".

Values written: male | female | unisex | kids.

REQUIRES module3_missing_migrations.sql section 6 (the `gender` column and
the bulk_update_gender RPC) to have been run first.

Run:
    python scripts/backfill_gender.py                # all remaining
    python scripts/backfill_gender.py --limit 500     # test batch
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from datasets import load_dataset

from app.db.supabase_client import get_supabase
from app.services.fashion.catalog_filters import infer_gender_from_name, normalize_gender


def _retry(fn, tries=4, delay=3):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"  retry {i + 1}/{tries} after error: {type(e).__name__}: {str(e)[:100]}")
            time.sleep(delay * (i + 1))
    raise last


def run(limit: int | None, batch_size: int):
    sb = get_supabase()

    print("Fetching inventory rows still needing gender...")
    todo_by_name: dict[str, list[str]] = {}
    total_todo = 0
    offset = 0
    while True:
        r = _retry(lambda: sb.table("inventory")
                   .select("id,name")
                   .is_("gender", "null")
                   .range(offset, offset + 999)
                   .execute())
        if not r.data:
            break
        for row in r.data:
            if row.get("name"):
                todo_by_name.setdefault(row["name"], []).append(row["id"])
                total_todo += 1
        if len(r.data) < 1000:
            break
        offset += 1000
    print(f"  {total_todo} rows need gender ({len(todo_by_name)} distinct names)")

    if not todo_by_name:
        print("Nothing to do -- every row already has gender set.")
        return

    print("Loading HF dataset (cached after first run)...")
    ds = load_dataset("ashraq/fashion-product-images-small", split="train")
    print(f"  {len(ds)} rows in source")

    batch_ids: list[str] = []
    batch_genders: list[str] = []
    updated = 0
    from_dataset = 0
    from_name = 0
    unknown = 0
    t0 = time.time()

    def flush():
        nonlocal updated
        if not batch_ids:
            return
        _retry(lambda: sb.rpc("bulk_update_gender", {
            "ids": batch_ids, "genders": batch_genders,
        }).execute())
        updated += len(batch_ids)
        elapsed = time.time() - t0
        rate = updated / elapsed if elapsed > 0 else 0
        print(f"  updated {updated}/{total_todo}  ({elapsed:.0f}s elapsed, {rate:.0f} items/s)")
        batch_ids.clear()
        batch_genders.clear()

    def queue(ids: list[str], gender: str):
        for item_id in ids:
            batch_ids.append(item_id)
            batch_genders.append(gender)
        if len(batch_ids) >= batch_size:
            flush()

    # Pass 1: authoritative value from the dataset.
    for row in ds:
        name = (row.get("productDisplayName") or "").strip()
        ids = todo_by_name.get(name)
        if not ids:
            continue
        gender = normalize_gender(row.get("gender"))
        if not gender:
            continue  # leave for pass 2
        del todo_by_name[name]  # pop -- a name can repeat in the source
        queue(ids, gender)
        from_dataset += len(ids)
        if limit and from_dataset >= limit:
            break

    # Pass 2: whatever the dataset couldn't match, classify by name.
    for name, ids in list(todo_by_name.items()):
        gender = infer_gender_from_name(name)
        if gender == "unknown":
            unknown += len(ids)
            continue
        queue(ids, gender)
        from_name += len(ids)

    flush()

    print(f"\nDone: {updated} rows backfilled in {time.time() - t0:.0f}s "
          f"({from_dataset} from the dataset, {from_name} inferred from name).")
    if unknown:
        print(f"{unknown} rows could not be classified either way and were left null "
              f"(treated as 'unknown' -- shown to everyone -- by the live filter).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Cap dataset-matched rows (for testing)")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per bulk RPC call")
    args = parser.parse_args()
    run(args.limit, args.batch_size)
