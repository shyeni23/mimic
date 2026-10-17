"""
Photorealistic try-on endpoint (Module 5).

The live mirror overlay stays as it is -- instant, free, good enough to
judge colour and proportion. This is the "and now show me properly" step:
one photo in, a generated image of the customer actually wearing the
garment out, with real drape and fit.

Disabled cleanly when REPLICATE_API_TOKEN isn't set, so the app works
without it.
"""
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.db.supabase_client import get_supabase
from app.services.fashion.photoreal_tryon import generate_tryon, is_available, model_category, readiness

router = APIRouter(prefix="/api/tryon", tags=["virtual try-on (Module 5)"])

MAX_PHOTO_BYTES = 8 * 1024 * 1024


@router.get("/available")
def tryon_available() -> dict:
    """So the UI can hide the button rather than offer something that errors."""
    # Only promise what will actually work: an unconfigured free backend
    # reports needs_token so the UI hides the button rather than failing in
    # front of a customer.
    r = readiness()
    return {"available": r["state"] == "ready", **r}


@router.post("/generate")
async def tryon_generate(
    item_id: str = Form(...),
    photo: UploadFile = File(...),
    session_id: str = Form(""),
) -> dict:
    """A frame of the customer + the garment -> them wearing it."""
    if not is_available():
        raise HTTPException(status_code=503,
                            detail="Photorealistic try-on isn't set up on this mirror.")

    photo_bytes = await photo.read()
    if not photo_bytes:
        raise HTTPException(status_code=400, detail="empty photo")
    if len(photo_bytes) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="photo too large")

    try:
        rows = (get_supabase().table("inventory")
                .select("id,name,category,image_url")
                .eq("id", item_id).limit(1).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"could not look up that item: {e}") from e
    if not rows:
        raise HTTPException(status_code=404, detail="item not found")
    item = rows[0]

    category = model_category(item.get("category"))
    if not category:
        # Bags, watches and jewellery aren't worn on the torso; the model has
        # no slot for them.
        raise HTTPException(status_code=400,
                            detail=f"{item.get('category') or 'that'} can't be tried on this way.")
    if not item.get("image_url"):
        raise HTTPException(status_code=400, detail="that item has no photo to try on")

    result = generate_tryon(photo_bytes, item["image_url"],
                            category=category, description=item.get("name") or "")
    if "error" in result:
        # 502: the upstream model failed, not the customer's request. The UI
        # falls back to the live overlay.
        raise HTTPException(status_code=502, detail=result["error"])

    if session_id:
        try:
            get_supabase().table("interactions").insert({
                "session_id": session_id, "item_id": item_id, "event_type": "tryon",
                "context": {"source": "photoreal_tryon", "item_name": item.get("name")},
            }).execute()
        except Exception as e:
            print(f"[tryon] event log failed (non-fatal): {e}")

    meta = {"id": item["id"], "name": item.get("name")}
    if "image_data" in result:
        # The free Space hands back the image itself, not a hosted URL, so
        # inline it rather than standing up storage for a transient result.
        import base64
        b64 = base64.b64encode(result["image_data"]).decode()
        return {"image_url": f"data:{result.get('mime', 'image/png')};base64,{b64}", "item": meta}
    return {"image_url": result["image_url"], "item": meta}
