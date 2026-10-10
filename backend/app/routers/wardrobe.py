"""
Wardrobe matching (Module 4): the customer saves what she already owns, and
future recommendations complete the look from those pieces rather than
starting from scratch.

Storage reuses the existing `interactions` table -- no schema change needed
(the Supabase migrations go through the user) -- by writing one row per saved
item with event_type='click' and context.source='wardrobe'. The row carries
the full item snapshot in context so a later rename or stock change in the
catalog can't delete things she "already owns".
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import get_supabase, get_inventory

router = APIRouter(prefix="/api/wardrobe", tags=["wardrobe (Module 4)"])


class WardrobeAddRequest(BaseModel):
    session_id: str
    item_id: str


class WardrobeRemoveRequest(BaseModel):
    session_id: str
    item_id: str


_WARDROBE_FIELDS = "id,name,category,color,occasion,image_url,price,stock,gender"


@router.get("/{session_id}")
def list_wardrobe(session_id: str) -> dict:
    """Items this customer has saved as "mine, I already own this"."""
    sb = get_supabase()
    rows = (sb.table("interactions").select("item_id,context")
            .eq("session_id", session_id).eq("event_type", "click")
            .eq("context->>source", "wardrobe").limit(1000).execute().data or [])
    seen, items = set(), []
    for row in rows:
        iid = row.get("item_id")
        if not iid or iid in seen:
            continue
        seen.add(iid)
        snap = (row.get("context") or {}).get("item")
        if snap:
            items.append(snap)
    # Backfill anything missing a snapshot by looking the id up in inventory.
    missing = [iid for iid in seen if not any(i.get("id") == iid for i in items)]
    if missing:
        try:
            fetched = (sb.table("inventory").select(_WARDROBE_FIELDS)
                       .in_("id", list(missing)).execute().data or [])
            items.extend(fetched)
        except Exception as e:
            print(f"[wardrobe] inventory lookup failed (non-fatal): {e}")
    return {"session_id": session_id, "items": items, "count": len(items)}


@router.post("/add")
def add_to_wardrobe(req: WardrobeAddRequest) -> dict:
    sb = get_supabase()
    try:
        snap = (sb.table("inventory").select(_WARDROBE_FIELDS)
                .eq("id", req.item_id).limit(1).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"inventory lookup failed: {e}") from e
    if not snap:
        raise HTTPException(status_code=404, detail=f"item {req.item_id} not found")
    sb.table("interactions").insert({
        "session_id": req.session_id, "item_id": req.item_id, "event_type": "click",
        "context": {"source": "wardrobe", "action": "add", "item": snap[0]},
    }).execute()
    return {"ok": True, "item": snap[0]}


@router.post("/remove")
def remove_from_wardrobe(req: WardrobeRemoveRequest) -> dict:
    sb = get_supabase()
    sb.table("interactions").insert({
        "session_id": req.session_id, "item_id": req.item_id, "event_type": "dismiss",
        "context": {"source": "wardrobe", "action": "remove"},
    }).execute()
    return {"ok": True}


@router.get("/{session_id}/complete")
def complete_from_wardrobe(session_id: str, item_id: str | None = None,
                           occasion: str | None = None, top_k: int = 6) -> dict:
    """Pieces that go with what she already owns. If `item_id` is given it's
    the anchor; otherwise every wardrobe item is treated as an anchor."""
    wardrobe = list_wardrobe(session_id)["items"]
    if not wardrobe:
        return {"anchors": [], "results": [], "note": "wardrobe is empty"}
    anchors = [i for i in wardrobe if i.get("id") == item_id] if item_id else wardrobe
    if not anchors:
        anchors = wardrobe

    # Reuse the existing rule-based compatibility reranker (Stage B).
    from app.services.fashion.compatibility import rerank_by_compatibility
    from app.services.fashion.inventory_search import semantic_search, apply_catalog_filters
    anchor_categories = {a.get("category") for a in anchors if a.get("category")}
    missing_categories = [c for c in ("top", "bottom", "footwear", "bag", "accessory")
                          if c not in anchor_categories]
    results = []
    for cat in missing_categories[:3]:
        a = anchors[0]
        query = " ".join([x for x in (a.get("color"), occasion, cat) if x])
        try:
            cands = semantic_search(query, category=cat, top_k=20, occasion=occasion,
                                     gender=a.get("gender"))
            cands = apply_catalog_filters(cands, a.get("gender"))
            # Exclude anything already in the wardrobe.
            owned = {i.get("id") for i in wardrobe}
            cands = [c for c in cands if c.get("id") not in owned]
            ranked = rerank_by_compatibility(cands, anchors, top_k=max(1, top_k // 3),
                                             session_id=session_id)
            results.extend(ranked)
        except Exception as e:
            print(f"[wardrobe] match failed for {cat} (non-fatal): {e}")
    return {"anchors": anchors, "results": results[:top_k]}
