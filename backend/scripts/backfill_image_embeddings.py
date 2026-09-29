"""
Upgrade inventory rows from TEXT embeddings (name+color+category) to real
Marqo-FashionCLIP IMAGE embeddings -- captures color nuance, pattern, and
silhouette that text alone can't. The 44K bulk seed only had text embeddings
because computing 44K image embeddings on CPU takes ~2 hours; this script
does the same job in ~10-15 min on a free Colab T4 GPU (auto-detects CUDA,
falls back to CPU with a time estimate printed up front).

Matches HF dataset rows to already-seeded inventory rows BY NAME (same join
key the original seed script used), so this is safe to run multiple times --
only rows with embedding_source='text' get touched (see schema.sql's
`embedding_source` column and `bulk_update_embeddings` RPC).

Run:
    python scripts/backfill_image_embeddings.py                 # all remaining
    python scripts/backfill_image_embeddings.py --limit 500      # test batch
    python scripts/backfill_image_embeddings.py --batch-size 64  # tune for your GPU

For the Colab version (recommended -- 10-15 min vs ~2h on CPU), see
scripts/colab_backfill_image_embeddings.ipynb.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

# IMPORT ORDER MATTERS: `datasets` must be imported BEFORE fashion_clip._load()
# runs (which loads the Marqo model via open_clip/huggingface_hub). Loading
# that model triggers an internal lazy probe that -- observed live, confirmed
# by reproducing it in isolation -- registers a BROKEN placeholder module
# under sys.modules['datasets'] (no __file__, no load_dataset attribute),
# permanently shadowing the real installed package for the rest of the
# process. Importing the real `datasets` first means it's already fully
# loaded in sys.modules by the time that probe runs, so the probe finds
# (and leaves alone) the real module instead of stubbing a broken one in.
from datasets import load_dataset

import torch

from app.db.supabase_client import get_supabase
from app.services.fashion.fashion_clip import _load  # reuse the cached model loader


SUBCAT_MAP = {
    "Topwear": "top", "Bottomwear": "bottom",
    "Dress": "dress", "Saree": "dress",
    "Shoes": "footwear", "Sandal": "footwear", "Flip Flops": "footwear",
    "Bags": "bag", "Wallets": "bag",
    "Watches": "watch", "Jewellery": "jewelry",
    "Belts": "accessory", "Eyewear": "accessory", "Headwear": "accessory",
    "Scarves": "accessory", "Ties": "accessory", "Socks": "accessory",
    "Innerwear": "top", "Loungewear and Nightwear": "top",
}


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


def embed_images_batch(model, preprocess, device, images) -> list[list[float]]:
    """Batch-encode a list of PIL images with Marqo-FashionCLIP. Batching is
    what makes GPU worthwhile -- a single forward pass over 32-64 images is
    far more efficient than 32-64 separate calls."""
    tensors = torch.stack([preprocess(img.convert("RGB")) for img in images]).to(device)
    with torch.no_grad():
        features = model.encode_image(tensors)
        features = features / features.norm(dim=-1, keepdim=True)
    return [f.tolist() for f in features.cpu()]


def run(limit: int | None, batch_size: int):
    model, preprocess, _tokenizer, device = _load()
    print(f"Model loaded on device: {device}")
    if device == "cpu":
        print(
            "WARNING: running on CPU. ~44K images at this batch size will take "
            "roughly 1.5-2.5 hours. For 10-15 min instead, run this on a free "
            "Colab T4 GPU -- see scripts/colab_backfill_image_embeddings.ipynb."
        )

    print("Loading HF dataset (cached after first run)...")
    ds = load_dataset("ashraq/fashion-product-images-small", split="train")
    print(f"  {len(ds)} rows in source")

    sb = get_supabase()

    print("Fetching inventory rows still needing image embeddings...")
    todo_by_name: dict[str, str] = {}  # name -> id
    offset = 0
    while True:
        r = _retry(lambda: sb.table("inventory")
                   .select("id,name")
                   .eq("embedding_source", "text")
                   .range(offset, offset + 999)
                   .execute())
        if not r.data:
            break
        for row in r.data:
            if row.get("name"):
                todo_by_name[row["name"]] = row["id"]
        if len(r.data) < 1000:
            break
        offset += 1000
    print(f"  {len(todo_by_name)} rows need image embeddings")

    if not todo_by_name:
        print("Nothing to do -- every row already has an image embedding.")
        return

    # Walk the HF dataset, batch up matches, embed, bulk-update.
    batch_ids: list[str] = []
    batch_images = []
    processed = 0
    updated = 0
    t0 = time.time()

    def flush():
        nonlocal updated
        if not batch_ids:
            return
        embeddings = embed_images_batch(model, preprocess, device, batch_images)
        # Stringify each embedding as a vector literal ("[0.1,0.2,...]") --
        # the RPC's `embeddings` param is text[], cast to vector(512) inside
        # the SQL function. See schema.sql's bulk_update_embeddings for why
        # (PostgREST can't reliably serialize vector(512)[] params directly).
        embedding_strs = ["[" + ",".join(str(x) for x in e) + "]" for e in embeddings]
        _retry(lambda: sb.rpc("bulk_update_embeddings", {
            "ids": batch_ids, "embeddings": embedding_strs,
        }).execute())
        updated += len(batch_ids)
        elapsed = time.time() - t0
        rate = updated / elapsed if elapsed > 0 else 0
        remaining = len(todo_by_name) - updated
        eta_min = (remaining / rate / 60) if rate > 0 else float("inf")
        print(f"  updated {updated}/{len(todo_by_name)}  "
              f"({elapsed:.0f}s elapsed, {rate:.1f} items/s, ETA {eta_min:.1f} min)")
        batch_ids.clear()
        batch_images.clear()

    for row in ds:
        name = (row.get("productDisplayName") or "").strip()
        if name not in todo_by_name:
            continue
        img = row.get("image")
        if img is None:
            continue

        batch_ids.append(todo_by_name[name])
        batch_images.append(img)
        processed += 1

        if len(batch_ids) >= batch_size:
            flush()

        if limit and processed >= limit:
            break

    flush()  # final partial batch

    print(f"\nDone: {updated} rows upgraded to real image embeddings in {time.time() - t0:.0f}s")
    remaining = len(todo_by_name) - updated
    if remaining > 0:
        print(f"{remaining} rows had no matching image in this dataset pass -- "
              f"rerun to pick up any that failed transiently.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Cap total rows processed (for testing)")
    parser.add_argument("--batch-size", type=int, default=32, help="Images per GPU/CPU batch")
    args = parser.parse_args()
    run(args.limit, args.batch_size)
