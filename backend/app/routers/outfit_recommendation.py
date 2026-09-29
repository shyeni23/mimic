from fastapi import APIRouter, HTTPException

from app.services.fashion.outfit_recommendation import get_outfit_recommendation, NoPrimaryItemError

router = APIRouter(prefix="/api/outfit-recommendation", tags=["outfit recommendation (Module 3)"])


@router.get("/{session_id}")
def outfit_recommendation(session_id: str):
    """
    Module 3: complete outfit recommendation for a session. Combines the
    visual profile (CV scan) and conversation preferences (via
    user_context.py) to pick a primary clothing item, then ranks compatible
    footwear/bag/jewelry/watch/accessory candidates from inventory around it.
    """
    try:
        return get_outfit_recommendation(session_id)
    except NoPrimaryItemError as e:
        raise HTTPException(status_code=404, detail=str(e))
