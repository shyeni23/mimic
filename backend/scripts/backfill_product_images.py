"""
Backfill `inventory.image_url` with real product photos.

The 37K-item bulk seed (seed_fashion_dataset.py) never uploaded images --
its --with-images flag was never used for the big import, since Supabase
Storage upload is network-bound at ~5-12s/item (see that script's own
docstring), which for 37K items is 50+ hours. This script instead saves
each image to local disk and serves it via the FastAPI static mount added
in app/main.py (`/media/products/<id>.jpg`) -- this whole app already only
ever runs as a local kiosk (backend + frontend both on localhost), so
there's no reason to pay Storage's network cost for something a local file
read serves just as well, in minutes instead of days.

Matches HF dataset rows to inventory rows BY NAME, same join pattern as
backfill_image_embeddings.py / backfill_season_year.py. Handles duplicate
names as backfill_season_year.py's fix does: a name maps to ALL inventory
ids that share it, not just one.

Run:
    python scripts/backfill_product_images.py                # all remaining
    python scripts/backfill_product_images.py --limit 500     # test batch
    python scripts/backfill_product_images.py --base-url http://localhost:8000
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from datasets import load_dataset

from app.db.supabase_client import get_supabase

IMAGES_DIR = Path(__file__).resolve().parents[1] / "data" / "product_images"


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


def run(limit: int | None, batch_size: int, base_url: str):
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading HF dataset (cached after first run)...")
    ds = load_dataset("ashraq/fashion-product-images-small", split="train")
    print(f"  {len(ds)} rows in source")

    sb = get_supabase()

    print("Fetching inventory rows still needing an image...")
    todo_by_name: dict[str, list[str]] = {}
    total_todo = 0
    offset = 0
    while True:
        r = _retry(lambda: sb.table("inventory")
                   .select("id,name")
                   .is_("image_url", "null")
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
    print(f"  {total_todo} rows need an image ({len(todo_by_name)} distinct names)")

    if not todo_by_name:
        print("Nothing to do -- every row already has an image.")
        return

    batch_ids: list[str] = []
    batch_urls: list[str] = []
    processed = 0
    updated = 0
    saved_files = 0
    t0 = time.time()

    def flush():
        nonlocal updated
        if not batch_ids:
            return
        _retry(lambda: sb.rpc("bulk_update_image_url", {
            "ids": batch_ids, "urls": batch_urls,
        }).execute())
        updated += len(batch_ids)
        elapsed = time.time() - t0
        rate = updated / elapsed if elapsed > 0 else 0
        remaining = total_todo - updated
        eta_min = (remaining / rate / 60) if rate > 0 else float("inf")
        print(f"  updated {updated}/{total_todo}  "
              f"({elapsed:.0f}s elapsed, {rate:.1f} items/s, ETA {eta_min:.1f} min)")
        batch_ids.clear()
        batch_urls.clear()

    for row in ds:
        name = (row.get("productDisplayName") or "").strip()
        ids = todo_by_name.get(name)
        if not ids:
            continue

        img = row.get("image")
        if img is None:
            del todo_by_name[name]
            continue

        del todo_by_name[name]  # one dataset match per name, same as backfill_season_year.py
        rgb = img.convert("RGB")
        for item_id in ids:
            file_path = IMAGES_DIR / f"{item_id}.jpg"
            rgb.save(file_path, format="JPEG", quality=85)
            saved_files += 1
            batch_ids.append(item_id)
            batch_urls.append(f"{base_url}/media/products/{item_id}.jpg")
        processed += len(ids)

        if len(batch_ids) >= batch_size:
            flush()

        if limit and processed >= limit:
            break

    flush()

    print(f"\nDone: {updated} rows given a real image_url, {saved_files} files saved, in {time.time() - t0:.0f}s")
    remaining = total_todo - updated
    if remaining > 0:
        print(f"{remaining} rows had no matching name in this dataset pass -- "
              f"rerun to pick up any that failed transiently.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Cap total rows processed (for testing)")
    parser.add_argument("--batch-size", type=int, default=200, help="Rows per bulk DB update")
    parser.add_argument("--base-url", default="http://localhost:8000",
                         help="Backend origin the frontend/agent will fetch images from")
    args = parser.parse_args()
    run(args.limit, args.batch_size, args.base_url)
