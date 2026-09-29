"""
Replace the 60x80 product photos with 384x512 ones -- same files, same URLs.

backfill_product_images.py pulled images from ashraq/fashion-product-images
-small, whose images are literally 60x80 px; stretched into ~370px cards on
the Recommendations page they look blurry (user complaint, 2026-09-19).
benitomartin/fashion-product-images-small-384x512 is the same 44,072-row
dataset (same productDisplayName join key) with 384x512 images -- 6x the
resolution, ~2 GB. This script overwrites data/product_images/<id>.jpg in
place, so inventory.image_url and the /media/products mount don't change
and nothing needs a DB write.

Streams the parquet shards (no 2 GB cache copy first) and is resumable: a
file that's already >= 200 px wide is skipped, so re-running after an
interruption only does what's left. Same duplicate-name handling as the
other backfills (one name -> all inventory ids sharing it).

Run (from backend/):
    python scripts/upgrade_product_images_hq.py            # everything
    python scripts/upgrade_product_images_hq.py --limit 300 # quick test
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

# `datasets` must be imported BEFORE `app` -- app/__init__.py installs a
# stub `datasets` module when the real one isn't loaded yet (see there).
from datasets import load_dataset  # noqa: E402
from PIL import Image

from app.db.supabase_client import get_supabase

IMAGES_DIR = Path(__file__).resolve().parents[1] / "data" / "product_images"
HQ_DATASET = "benitomartin/fashion-product-images-small-384x512"
ALREADY_HQ_WIDTH = 200


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


def _needs_upgrade(item_id: str) -> bool:
    fp = IMAGES_DIR / f"{item_id}.jpg"
    if not fp.exists():
        return True
    try:
        with Image.open(fp) as im:
            return im.width < ALREADY_HQ_WIDTH
    except Exception:
        return True


def run(limit: int | None):
    sb = get_supabase()
    print("Fetching inventory names...")
    todo_by_name: dict[str, list[str]] = {}
    total = 0
    offset = 0
    while True:
        r = _retry(lambda: sb.table("inventory").select("id,name").range(offset, offset + 999).execute())
        if not r.data:
            break
        for row in r.data:
            if row.get("name") and _needs_upgrade(row["id"]):
                todo_by_name.setdefault(row["name"].strip(), []).append(row["id"])
                total += 1
        if len(r.data) < 1000:
            break
        offset += 1000
    print(f"  {total} images still low-res ({len(todo_by_name)} distinct names)")
    if not todo_by_name:
        print("Nothing to do -- every product image is already high-res.")
        return

    print(f"Streaming {HQ_DATASET} (~2 GB, shard by shard)...")
    ds = load_dataset(HQ_DATASET, split="train", streaming=True)

    done = 0
    scanned = 0
    t0 = time.time()
    for row in ds:
        scanned += 1
        name = (row.get("productDisplayName") or "").strip()
        ids = todo_by_name.pop(name, None)
        if not ids:
            if scanned % 2000 == 0:
                print(f"  scanned {scanned} dataset rows, upgraded {done}/{total} ({time.time() - t0:.0f}s)")
            continue
        img = row.get("image")
        if img is None:
            continue
        rgb = img.convert("RGB")
        for item_id in ids:
            rgb.save(IMAGES_DIR / f"{item_id}.jpg", format="JPEG", quality=88)
            done += 1
        if done % 500 < len(ids):
            rate = done / max(time.time() - t0, 1)
            print(f"  upgraded {done}/{total}  ({time.time() - t0:.0f}s, {rate:.1f}/s, "
                  f"ETA {(total - done) / max(rate, 0.01) / 60:.0f} min)")
        if limit and done >= limit:
            break
        if not todo_by_name:
            break

    print(f"\nDone: {done} images upgraded to 384x512 in {time.time() - t0:.0f}s.")
    if todo_by_name:
        print(f"{sum(len(v) for v in todo_by_name.values())} inventory rows had no match in the HQ dataset (left as-is).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Stop after this many upgraded images (testing)")
    args = parser.parse_args()
    run(args.limit)
