"""
Interaction event logger (Module 3, implicit-feedback pipeline).

Captures every implicit signal the customer generates -- card impressions,
clicks, tryon requests, add-to-cart, skips, recommend_shown -- as future
training data for the deep-learning recommender's user tower. Until we have
enough volume to train, this endpoint is a passive log; the recommender still
runs off content-based similarity + rules. That's deliberate: we can't start
training a two-tower model without interaction data, and we can't collect
interaction data without shipping this endpoint first.

Batching is the default from the frontend (see src/hooks/useEventLogger.js's
500ms debounce) so a page rendering 20 cards doesn't fire 20 separate POSTs.
Individual /api/events still exists for eager events (add_to_cart, tryon).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db.supabase_client import get_supabase

router = APIRouter(prefix="/api/events", tags=["events"])


class InteractionEvent(BaseModel):
    session_id: str
    item_id: str | None = None  # optional -- e.g. recommend_shown is per-session, not per-item
    event_type: str = Field(..., pattern="^(view|click|tryon|add_to_cart|skip|dismiss|recommend_shown)$")
    user_id: str | None = None
    context: dict = {}


@router.post("")
def log_event(evt: InteractionEvent):
    """Log a single interaction event. Used by eager events (add_to_cart,
    tryon) that shouldn't wait 500ms for the batch flush."""
    try:
        get_supabase().table("interactions").insert(evt.model_dump()).execute()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"event log failed: {e}") from e


@router.post("/batch")
def log_events(events: list[InteractionEvent]):
    """Batch endpoint -- the frontend's default path. Impressions and scrolls
    debounce here so a browse session doesn't spam the DB."""
    if not events:
        return {"ok": True, "count": 0}
    try:
        payload = [e.model_dump() for e in events]
        get_supabase().table("interactions").insert(payload).execute()
        return {"ok": True, "count": len(events)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"batch event log failed: {e}") from e
