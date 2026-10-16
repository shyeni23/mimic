from fastapi import APIRouter, Query, HTTPException

from app.db.supabase_client import get_inventory, get_supabase

router = APIRouter(prefix="/api/inventory", tags=["inventory (Module 3)"])


@router.get("/browse")
def browse_inventory(
    category: str | None = Query(None),
    occasion: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """Browse real inventory for the Shopping page."""
    # include_embedding=False -- this endpoint only ever displays name/
    # category/color/price to the browser. Shipping ~200 512-float embeddings
    # over HTTP was pure wasted bandwidth -- confirmed live, it stretched
    # OutfitBuilder.js's initial palette load to several seconds (long enough
    # to look frozen/broken behind its fake-placeholder fallback) and a
    # similar unfiltered fetch elsewhere hit Supabase's statement timeout.
    items = get_inventory(category=category, in_stock_only=True, include_embedding=False)
    if occasion:
        o = occasion.lower()
        items = [i for i in items if o in [t.lower() for t in (i.get("occasion") or [])]]
    if search:
        q = search.lower()
        items = [i for i in items if q in (i.get("name") or "").lower()
                 or q in (i.get("category") or "").lower()
                 or q in (i.get("color") or "").lower()]
    total = len(items)
    items = items[offset:offset + limit]
    return {"items": items, "total": total}


@router.get("/categories")
def list_categories():
    """Distinct categories in the live inventory."""
    sb = get_supabase()
    # Paginate rather than one unpaginated .select() -- PostgREST caps a
    # single response at 1000 rows, which for a ~37K-row table would only
    # ever see a fixed slice (harmless today since all ~9 categories show up
    # even in a random 1000, but the same silent-truncation shape that bit
    # check_training_readiness.py once the interactions table grew).
    cats: set[str] = set()
    offset = 0
    while True:
        page = sb.table("inventory").select("category").range(offset, offset + 999).execute()
        if not page.data:
            break
        cats.update(row["category"] for row in page.data if row.get("category"))
        if len(page.data) < 1000:
            break
        offset += 1000
    return {"categories": sorted(cats)}


@router.get("/occasions")
def list_occasions():
    """Distinct occasion tags actually present in the live inventory --
    drives the occasion filter chips on Shopping/Recommendations instead of
    hardcoding a guessed list that might not match what's really tagged."""
    sb = get_supabase()
    tags: set[str] = set()
    offset = 0
    while True:
        page = sb.table("inventory").select("occasion").range(offset, offset + 999).execute()
        if not page.data:
            break
        for row in page.data:
            tags.update(t.lower() for t in (row.get("occasion") or []))
        if len(page.data) < 1000:
            break
        offset += 1000
    return {"occasions": sorted(tags)}


@router.get("/{item_id}/cutout")
def item_cutout(item_id: str):
    """Garment with its studio backdrop removed, as a transparent PNG, for
    the try-on overlay. Pasting the raw catalog photo on a camera feed looks
    like a sticker.

    Segmented with GrabCut on the server rather than flood-filled in the
    browser: the browser version ate a white garment on a white backdrop
    whole (96% of pixels cleared) and couldn't follow a soft edge. Results
    are cached on disk -- the same product always cuts out identically.

    404 means "no cutout for this one" (busy backdrop, implausible result),
    and the caller should fall back to the original photo rather than show
    nothing.
    """
    from pathlib import Path
    from fastapi.responses import FileResponse
    from app.services.fashion.cutout import make_cutout

    images_dir = Path(__file__).resolve().parents[2] / "data" / "product_images"
    src = images_dir / f"{item_id}.jpg"
    if not src.exists():
        raise HTTPException(status_code=404, detail="no product image for that item")
    out = make_cutout(src)
    if out is None:
        raise HTTPException(status_code=404, detail="no cutout available for that image")
    # Immutable: the cutout for a given product never changes.
    return FileResponse(out, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})
