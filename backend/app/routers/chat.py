import traceback
from fastapi import APIRouter

from app.services.voice.nlp_extract import extract_context
from app.services.agent.graph import run_agent_turn
from app.services.agent.preferences import extract_prior_preferences
from app.db.supabase_client import append_conversation_turn, get_conversation_history, update_scan_height
from app.models.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/chat", tags=["chat (Module 2)"])


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest):
    context = extract_context(req.message)

    if context.get("stated_height_cm"):
        try:
            update_scan_height(req.session_id, context["stated_height_cm"], source="spoken")
        except Exception:
            pass

    try:
        history = get_conversation_history(req.session_id)
    except Exception:
        history = []

    # Structured conversation state (occasion/style/colors...) carried over from
    # earlier turns -- persisted in the assistant turn's existing `meta` column
    # (see preferences.py), so it survives across requests without a new table.
    prior_preferences = extract_prior_preferences(history)

    try:
        append_conversation_turn(req.session_id, "user", req.message, meta=context)
    except Exception:
        pass

    try:
        result = run_agent_turn(req.session_id, req.message, history, role=req.role, prior_preferences=prior_preferences)
    except Exception as e:
        traceback.print_exc()
        result = {"reply": "Sorry, something went wrong -- could you try again?", "actions": [], "preferences": prior_preferences}

    try:
        append_conversation_turn(req.session_id, "assistant", result["reply"], meta={"preferences": result.get("preferences", {})})
    except Exception:
        pass

    return ChatResponse(
        session_id=req.session_id,
        reply=result["reply"],
        extracted_context=context,
        actions=result["actions"],
        preferences=result.get("preferences", {}),
    )
