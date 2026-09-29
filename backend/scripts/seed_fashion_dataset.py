"""
Seeds the `inventory` table from a real, tagged, MIT-licensed public dataset:
"Fashion Product Images Dataset" (Param Aggarwal, Kaggle -- licenseName
confirmed "MIT" via Kaggle's own API), mirrored on HuggingFace as
ashraq/fashion-product-images-small (44,072 items, direct unauthenticated
parquet download, no Kaggle API key needed).

Run once (or with --limit for a smaller sample):
    python scripts/seed_fashion_dataset.py --parquet-dir <dir> --limit 500

    --dry-run prints the mapped rows without touching Supabase or FashionCLIP,
    for validating the category/occasion mapping against real data before
    spending time on embeddings + uploads.

    Images/embeddings are OFF by default -- pass --with-images to also upload
    each item's photo to Supabase Storage and compute its FashionCLIP
    embedding. This is off by default because Storage upload latency is the
    dominant per-item cost (network-bound, confirmed live at ~5-12s/item on a
    freshly-restored free-tier project) and outfit_recommendation.py's
    scoring doesn't use image_url or embedding at all -- only category,
    color, occasion, and style_tags. Rows are inserted in batches
    (--batch-size, default 50) rather than one-by-one to cut network
    round-trips.

Source dataset columns: id, gender, masterCategory, subCategory, articleType,
baseColour, season, year, usage, productDisplayName, image.

Field mapping into this project's `inventory` table:
    productDisplayName -> name
    (see _CATEGORY_MAP)  subCategory -> category
    baseColour          -> color (lowercased)
    usage                -> occasion (single-tag list, lowercased)
    (not mapped)          -> style_tags: left empty. The source dataset has no
                             style/aesthetic tag field distinct from category/
                             color/occasion -- inventing style words (e.g.
                             "chic", "edgy") the data doesn't actually contain
                             would violate the "no invented values" requirement.
    (not in source)       -> price: left null. Not present in this dataset.
    (not in source)       -> stock: set to a fixed placeholder (10) purely so
                             existing rows are visible in category listings --
                             NOT used as a scoring signal anywhere (see
                             outfit_recommendation.py's score_candidate, which
                             deliberately does not filter on stock for exactly
                             this reason).

Only rows whose subCategory maps to a category this project actually uses are
kept (see _CATEGORY_MAP) -- personal care, home goods, kids' items, and
underwear/sleepwear are excluded outright (the last two for the same reason
outfit_recommendation.py's FORBIDDEN_KEYWORDS filter exists).
"""
import argparse
import io
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pandas as pd

# subCategory (source dataset) -> this project's inventory.category
_CATEGORY_MAP = {
    "Topwear": "top",
    "Bottomwear": "bottom",
    "Dress": "dress",
    "Saree": "dress",
    "Shoes": "footwear",
    "Sandal": "footwear",
    "Flip Flops": "footwear",
    "Bags": "bag",
    "Wallets": "bag",
    "Watches": "watch",
    "Jewellery": "jewelry",
    "Belts": "accessory",
    "Eyewear": "accessory",
    "Headwear": "accessory",
    "Scarves": "accessory",
    "Ties": "accessory",
    "Socks": "accessory",
}

# usage (source dataset) -> this project's inventory.occasion tag
_OCCASION_MAP = {
    "Casual": "casual",
    "Ethnic": "ethnic",
    "Formal": "formal",
    "Sports": "sports",
    "Smart Casual": "smart casual",
    "Party": "party",
    "Travel": "travel",
    "Home": "home",
}

PLACEHOLDER_STOCK = 10


def load_dataset(parquet_dir: Path) -> pd.DataFrame:
    parts = sorted(parquet_dir.glob("*.parquet"))
    if not parts:
        raise FileNotFoundError(f"No .parquet files found in {parquet_dir}")
    frames = [pd.read_parquet(p) for p in parts]
    return pd.concat(frames, ignore_index=True)


def map_row(row: dict) -> dict | None:
    """Maps one source dataset row to an inventory row, or None if this
    row's category isn't one this project uses."""
    category = _CATEGORY_MAP.get(row.get("subCategory"))
    if not category:
        return None

    name = row.get("productDisplayName")
    if not name or not isinstance(name, str):
        return None

    color = (row.get("baseColour") or "").strip().lower() or None
    usage = row.get("usage")
    occasion = [_OCCASION_MAP[usage]] if usage in _OCCASION_MAP else []

    return {
        "name": name,
        "category": category,
        "color": color,
        "occasion": occasion,
        "style_tags": [],
        "price": None,
        "stock": PLACEHOLDER_STOCK,
        "_source_id": row.get("id"),
        "_image": row.get("image"),
    }


def stratified_sample(df: pd.DataFrame, limit: int) -> pd.DataFrame:
    """Samples roughly evenly across our target categories rather than taking
    the first N rows -- the raw dataset is dominated by Topwear (7681 rows),
    so a naive head(limit) would seed almost no accessories/jewelry/watches,
    which Module 3 specifically needs."""
    df = df.copy()
    df["_category"] = df["subCategory"].map(_CATEGORY_MAP)
    df = df.dropna(subset=["_category"])
    per_category = max(1, limit // df["_category"].nunique())
    sampled = (
        df.groupby("_category", group_keys=False)
        .apply(lambda g: g.head(per_category))
    )
    return sampled.head(limit)


def run(parquet_dir: Path, limit: int, dry_run: bool, with_images: bool, batch_size: int):
    print(f"Loading dataset from {parquet_dir} ...")
    df = load_dataset(parquet_dir)
    print(f"  {len(df)} total rows in source dataset")

    sampled = stratified_sample(df, limit)
    print(f"  {len(sampled)} rows selected after stratified sampling (limit={limit})")

    mapped_rows = []
    skipped = 0
    for _, row in sampled.iterrows():
        mapped = map_row(row.to_dict())
        if mapped is None:
            skipped += 1
            continue
        mapped_rows.append(mapped)

    print(f"  {len(mapped_rows)} rows mapped successfully, {skipped} skipped")
    print()
    print("Category distribution in the mapped sample:")
    cat_counts = {}
    for r in mapped_rows:
        cat_counts[r["category"]] = cat_counts.get(r["category"], 0) + 1
    for cat, count in sorted(cat_counts.items()):
        print(f"  {cat:10s} {count}")
    print()

    if dry_run:
        print("--dry-run: no Supabase/FashionCLIP calls made. Sample of mapped rows:")
        for r in mapped_rows[:8]:
            preview = {k: v for k, v in r.items() if k != "_image"}
            print(f"  {preview}")
        return

    from app.db.supabase_client import get_supabase

    embed_image_bytes = None
    if with_images:
        from app.services.fashion.fashion_clip import embed_image_bytes as _embed
        from app.db.supabase_client import upload_media
        embed_image_bytes = _embed

    sb = get_supabase()
    embedding_failures = 0
    inserted = 0

    for batch_start in range(0, len(mapped_rows), batch_size):
        batch_source = mapped_rows[batch_start:batch_start + batch_size]
        batch_payload = []

        for r in batch_source:
            image_field = r.pop("_image")
            source_id = r.pop("_source_id")

            image_bytes = None
            if with_images:
                if isinstance(image_field, dict) and "bytes" in image_field:
                    image_bytes = image_field["bytes"]
                elif isinstance(image_field, (bytes, bytearray)):
                    image_bytes = bytes(image_field)

            embedding = None
            image_url = None
            if with_images and image_bytes:
                try:
                    embedding = embed_image_bytes(image_bytes)
                except Exception as e:
                    embedding_failures += 1
                    print(f"  FashionCLIP embedding failed for source id {source_id}: {e}")
                try:
                    image_url = upload_media(f"inventory/fashion-dataset-{source_id}.jpg", image_bytes, "image/jpeg")
                except Exception as e:
                    print(f"  Image upload failed for source id {source_id}: {e}")

            batch_payload.append({**r, "image_url": image_url, "embedding": embedding})

        sb.table("inventory").insert(batch_payload).execute()
        inserted += len(batch_payload)
        print(f"  ...{inserted}/{len(mapped_rows)} inserted")

    print()
    print(f"Done. Inserted {inserted} items, {embedding_failures} embedding failures.")
    if not with_images:
        print("Images/embeddings were skipped (--with-images not passed) -- image_url and "
              "embedding are null for these rows. Outfit scoring doesn't use either (see "
              "outfit_recommendation.py's score_candidate), so this doesn't block Module 3 "
              "testing. Re-run with --with-images later to backfill visuals once Storage is fast.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet-dir", type=Path, required=True,
                         help="Directory containing the downloaded .parquet shard(s)")
    parser.add_argument("--limit", type=int, default=500,
                         help="Max items to seed (stratified across categories)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print mapped rows without touching Supabase/FashionCLIP")
    parser.add_argument("--with-images", action="store_true",
                         help="Upload each item's image to Supabase Storage and compute its "
                              "FashionCLIP embedding. Off by default: outfit_recommendation.py's "
                              "scoring never uses image_url/embedding, and image upload is the "
                              "dominant per-item cost (network-latency bound, not something more "
                              "compute or a bigger batch size fixes). Re-run with this flag later "
                              "to backfill visuals once Storage latency is acceptable.")
    parser.add_argument("--batch-size", type=int, default=50,
                         help="Rows per Supabase insert() call -- batching cuts network "
                              "round-trips compared to one insert per row")
    args = parser.parse_args()
    run(args.parquet_dir, args.limit, args.dry_run, args.with_images, args.batch_size)
