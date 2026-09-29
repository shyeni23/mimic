"""
Backfill `inventory.season` / `inventory.year` from the source dataset
(ashraq/fashion-product-images-small) -- these columns exist in the schema
and in the dataset itself, but seed_fashion_dataset.py never captured them
(see schema.sql's "Trend / seasonal awareness" section), so every row seeded
before this script has season=null/year=null.

Matches HF dataset rows to inventory rows BY NAME, same join key
backfill_image_embeddings.py uses. Safe to run multiple times -- only rows
with season IS NULL get touched, and a row with no matching dataset entry
(or a null season/year in the source itself) is simply left alone.

Run:
    python scripts/backfill_season_year.py                # all remaining
    python scripts/backfill_season_year.py --limit 500     # test batch
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from datasets import load_dataset

from app.db.supabase_client import get_supabase


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
    print("Loading HF dataset (cached after first run)...")
    ds = load_dataset("ashraq/fashion-product-images-small", split="train")
    print(f"  {len(ds)} rows in source")

    sb = get_supabase()

    print("Fetching inventory rows still needing season/year...")
    # name -> list of ids -- the inventory table has genuine duplicate
    # productDisplayName values across distinct rows (~12% of rows in a
    # sample check), so a single name can't be collapsed to one id or every
    # row after the first sharing that name silently never gets touched.
    todo_by_name: dict[str, list[str]] = {}
    total_todo = 0
    offset = 0
    while True:
        r = _retry(lambda: sb.table("inventory")
                   .select("id,name")
                   .is_("season", "null")
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
    print(f"  {total_todo} rows need season/year ({len(todo_by_name)} distinct names)")

    if not todo_by_name:
        print("Nothing to do -- every row already has season/year set.")
        return

    batch_ids: list[str] = []
    batch_seasons: list[str] = []
    batch_years: list[int] = []
    processed = 0
    updated = 0
    skipped_no_data = 0
    t0 = time.time()

    def flush():
        nonlocal updated
        if not batch_ids:
            return
        _retry(lambda: sb.rpc("bulk_update_season_year", {
            "ids": batch_ids, "seasons": batch_seasons, "years": batch_years,
        }).execute())
        updated += len(batch_ids)
        elapsed = time.time() - t0
        rate = updated / elapsed if elapsed > 0 else 0
        remaining = total_todo - updated
        eta_min = (remaining / rate / 60) if rate > 0 else float("inf")
        print(f"  updated {updated}/{total_todo}  "
              f"({elapsed:.0f}s elapsed, {rate:.1f} items/s, ETA {eta_min:.1f} min)")
        batch_ids.clear()
        batch_seasons.clear()
        batch_years.clear()

    for row in ds:
        name = (row.get("productDisplayName") or "").strip()
        ids = todo_by_name.get(name)
        if not ids:
            continue

        season = row.get("season")
        year = row.get("year")
        if not season or year is None:
            del todo_by_name[name]
            skipped_no_data += len(ids)
            continue

        # Pop, not peek -- a name can appear multiple times in the source
        # dataset (different colorways etc.); only the first match should
        # apply, otherwise every duplicate re-queues the same ids.
        del todo_by_name[name]
        for item_id in ids:
            batch_ids.append(item_id)
            batch_seasons.append(str(season))
            batch_years.append(int(year))
        processed += len(ids)

        if len(batch_ids) >= batch_size:
            flush()

        if limit and processed >= limit:
            break

    flush()  # final partial batch

    print(f"\nDone: {updated} rows backfilled with season/year in {time.time() - t0:.0f}s")
    if skipped_no_data:
        print(f"{skipped_no_data} matching rows had no season/year in the source dataset, left null.")
    remaining = total_todo - updated - skipped_no_data
    if remaining > 0:
        print(f"{remaining} rows had no matching name in this dataset pass -- "
              f"rerun to pick up any that failed transiently.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Cap total rows processed (for testing)")
    parser.add_argument("--batch-size", type=int, default=200, help="Rows per bulk RPC call")
    args = parser.parse_args()
    run(args.limit, args.batch_size)
