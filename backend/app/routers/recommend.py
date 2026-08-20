from fastapi import APIRouter, HTTPException

from app.db.supabase_client import get_latest_scan
from app.services.fashion.inventory_search import recommend_items
from app.models.schemas import RecommendRequest

router = APIRouter(prefix="/api/recommend", tags=["recommend (Module 1)"])


@router.post("")
def recommend(req: RecommendRequest):
    """
    Uses the customer's most recent body scan (from /api/vision/scan) plus
    optional occasion/category filters to return ranked, explained
    clothing suggestions from inventory.
    """
    scan = get_latest_scan(req.session_id)
    if not scan:
        raise HTTPException(status_code=404, detail="No scan found for this session. Call /api/vision/scan first.")

    result = recommend_items(
        depth=scan.get("skin_tone_category", "medium"),
        undertone=scan.get("skin_tone_undertone", "neutral"),
        body_shape=scan.get("body_shape", "unknown"),
        occasion=req.occasion,
        category=req.category,
        height_cm=scan.get("height_cm"),
        glasses_detected=scan.get("glasses_detected", False),
        hair_length=scan.get("hair_length", "unknown"),
    )
    return result
