"""
Run once (and any time inventory changes):  python scripts/embed_inventory.py

Reads items from a local CSV (data/inventory_seed.csv) with columns:
  name,category,color,occasion,style_tags,image_path,price,stock
Embeds each image with FashionCLIP, uploads the image to Supabase Storage,
and inserts the row (with embedding) into the inventory table.
"""
import csv
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.fashion.fashion_clip import embed_image_bytes
from app.db.supabase_client import insert_inventory_item, upload_media

SEED_CSV = Path(__file__).resolve().parents[1] / "data" / "inventory_seed.csv"


def run():
    with open(SEED_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            image_path = Path(row["image_path"])
            image_bytes = image_path.read_bytes()

            try:
                embedding = embed_image_bytes(image_bytes)
            except Exception as e:
                print(f"  FashionCLIP unavailable, seeding without embedding: {e}")
                embedding = None

            image_url = upload_media(f"inventory/{image_path.name}", image_bytes, "image/jpeg")

            item = {
                "name": row["name"],
                "category": row["category"],
                "color": row["color"],
                "occasion": [o.strip() for o in row["occasion"].split(";") if o.strip()],
                "style_tags": [t.strip() for t in row["style_tags"].split(";") if t.strip()],
                "image_url": image_url,
                "embedding": embedding,
                "price": float(row["price"]) if row.get("price") else None,
                "stock": int(row["stock"]) if row.get("stock") else 0,
            }
            insert_inventory_item(item)
            print(f"Inserted: {item['name']}")


if __name__ == "__main__":
    run()
