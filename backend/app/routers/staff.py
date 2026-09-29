import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.db.supabase_client import (
    get_pending_staff_requests, get_recent_staff_requests, update_staff_request_status,
)
from app.models.schemas import StaffRequestStatusUpdate
from app.services.notifications import hub

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/staff", tags=["staff escalation (Module 5)"])


@router.get("/requests")
def list_staff_requests(status: str = "pending"):
    """Closes the audit's own G6 gap ("no confirmed staff/admin UI or
    notification consumer exists") -- this is that consumer's data source.
    status='pending' (default) for the actionable queue; status='all' for a
    recent-history view that also shows acknowledged/resolved requests."""
    try:
        if status == "all":
            return get_recent_staff_requests()
        return get_pending_staff_requests()
    except Exception as e:
        if "staff_requests" in str(e):
            log.warning("staff_requests table not found -- returning empty list (run schema.sql to create it)")
            return JSONResponse(content={"data": [], "warning": "staff_requests table not yet created"})
        raise


@router.post("/requests/{request_id}/status")
def set_staff_request_status(request_id: str, req: StaffRequestStatusUpdate):
    if req.status not in ("pending", "acknowledged", "resolved"):
        raise HTTPException(status_code=400, detail="status must be one of: pending, acknowledged, resolved")
    try:
        updated = update_staff_request_status(request_id, req.status)
    except Exception as e:
        if "staff_requests" in str(e):
            raise HTTPException(status_code=503, detail="staff_requests table not yet created -- run schema.sql")
        raise
    if not updated:
        raise HTTPException(status_code=404, detail=f"No staff request with id {request_id}")
    hub.broadcast_sync("staff", {"type": "status_update", "request": updated})
    return updated


@router.websocket("/ws")
async def staff_ws(ws: WebSocket):
    await hub.connect("staff", ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.disconnect("staff", ws)
