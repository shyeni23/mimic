from fastapi import APIRouter, HTTPException

from app.services.agent.events import get_trigger_message
from app.services.agent.graph import run_agent_turn
from app.services.agent.preferences import extract_prior_preferences
from app.db.supabase_client import append_conversation_turn, get_conversation_history
from app.models.schemas import AgentEventRequest, ChatResponse

router = APIRouter(prefix="/api/agent", tags=["agent events (proactive, Module 2)"])

# Spoken when the LLM is unavailable for these events (see agent_event).
_OFFLINE_REPLIES = {
    "conversation_start": (
        "Hi, I'm Aria, your personal stylist! Tell me what you're shopping for, "
        "or stand still for a quick body scan and I'll pick looks that suit you."
    ),
    "scan_complete": "Your scan is done! Here's a complete look picked for your body shape and skin tone.",
}


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
    trigger_message = get_trigger_message(req.event, req.role, req.context)
    if trigger_message is None:
        raise HTTPException(status_code=400, detail=f"Event '{req.event}' is not defined for role '{req.role}'")

    history = get_conversation_history(req.session_id)
    # Carry the conversation's preferences (occasion above all) into the
    # event turn -- without this, scan_complete ran with an empty "what you
    # already know" and the post-scan picks ignored the occasion she'd named.
    prior_preferences = extract_prior_preferences(history)
    if req.event == "scan_complete" and req.role == "customer":
        # She asked for specific items before the scan ("a wedding saree"):
        # show only those, not the LLM's whole-look recommendation.
        from app.services.agent.shopping_intent import post_scan_turn
        requested = post_scan_turn(req.session_id, prior_preferences)
        if requested:
            append_conversation_turn(req.session_id, "assistant", requested["reply"],
                                     meta={"triggered_by_event": req.event,
                                           "preferences": requested["preferences"]})
            return ChatResponse(session_id=req.session_id, reply=requested["reply"],
                                extracted_context=None, actions=requested["actions"])
    result = run_agent_turn(req.session_id, trigger_message, history, role=req.role,
                            prior_preferences=prior_preferences)

    if result.get("llm_failed"):
        # A proactive event is Aria volunteering a comment. If the LLM is
        # down (Groq daily quota, network...), the right behaviour is to say
        # nothing -- not to pop "Sorry, I hit a little snag" toasts at a
        # customer who never spoke to her (four of them appeared during one
        # scan live). Nothing is persisted either; the transcript shouldn't
        # carry apologies for questions nobody asked.
        # Exception: the greeting and the post-scan line. Silence there makes
        # the mirror look broken, so fall back to a fixed line.
        fallback = _OFFLINE_REPLIES.get(req.event, "")
        if fallback:
            append_conversation_turn(req.session_id, "assistant", fallback,
                                     meta={"triggered_by_event": req.event, "offline_fallback": True})
        return ChatResponse(session_id=req.session_id, reply=fallback, extracted_context=None, actions=[])

    # Persist preferences so the next chat turn still knows them, and the
    # liked item so her "yes" to accessories can resolve to its real id
    # (see graph._last_liked_item).
    meta = {"triggered_by_event": req.event, "preferences": result.get("preferences") or prior_preferences}
    if req.event == "item_liked":
        meta["liked_item"] = {
            "id": str(req.context.get("item_id")),
            "name": req.context.get("name"),
            "category": req.context.get("category"),
        }
    append_conversation_turn(req.session_id, "assistant", result["reply"], meta=meta)

    return ChatResponse(
        session_id=req.session_id,
        reply=result["reply"],
        extracted_context=None,
        actions=result["actions"],
    )
