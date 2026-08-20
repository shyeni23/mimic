from fastapi import APIRouter, HTTPException

from app.services.agent.events import get_trigger_message
from app.services.agent.graph import run_agent_turn
from app.db.supabase_client import append_conversation_turn, get_conversation_history
from app.models.schemas import AgentEventRequest, ChatResponse

router = APIRouter(prefix="/api/agent", tags=["agent events (proactive, Module 2)"])


@router.post("/event", response_model=ChatResponse)
def agent_event(req: AgentEventRequest):
    """
    Fires a PROACTIVE agent reaction to a system event -- no user speech involved.
    The frontend calls this automatically at the right moment (see the event
    table in the addendum), e.g. right after /api/vision/scan succeeds, or after
    a few seconds of inactivity on the recommendations screen.

    Returns the exact same shape as /api/chat (reply + actions) -- the frontend
    handles it identically: speak `reply` via TTS, execute each queued action.
    The synthetic trigger text is never shown to the user and is not persisted
    as a 'user' turn -- only Aria's reply goes into conversation history, so the
    transcript still reads naturally if ever displayed.
    """
    trigger_message = get_trigger_message(req.event, req.role)
    if trigger_message is None:
        raise HTTPException(status_code=400, detail=f"Event '{req.event}' is not defined for role '{req.role}'")

    history = get_conversation_history(req.session_id)
    result = run_agent_turn(req.session_id, trigger_message, history, role=req.role)

    append_conversation_turn(req.session_id, "assistant", result["reply"], meta={"triggered_by_event": req.event})

    return ChatResponse(
        session_id=req.session_id,
        reply=result["reply"],
        extracted_context=None,
        actions=result["actions"],
    )
