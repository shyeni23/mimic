import json
import traceback
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.services.voice.nlp_extract import extract_context
from app.services.agent.graph import run_agent_turn, stream_agent_turn
from app.services.agent.preferences import extract_prior_preferences
from app.services.agent.shopping_intent import scan_first_turn, offline_shopping_turn
from app.db.supabase_client import (
    append_conversation_turn, get_conversation_history, update_scan_height, get_latest_scan,
)
from app.models.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/chat", tags=["chat (Module 2)"])


def _has_scan(session_id: str) -> bool:
    try:
        return get_latest_scan(session_id) is not None
    except Exception:
        return True  # can't tell -- don't bounce her to the scanner on a DB hiccup


def _pre_agent_turn(req: ChatRequest, prior_preferences: dict) -> dict | None:
    """Shopping request before any scan -> open the scanner (no LLM needed)."""
    if req.role != "customer":
        return None
    return scan_first_turn(req.session_id, req.message, prior_preferences, _has_scan(req.session_id))


def _offline_if_failed(req: ChatRequest, result: dict, prior_preferences: dict) -> dict:
    """Shopping request that ended with nothing on screen -- LLM down (Groq
    quota: "Sorry, I hit a little snag") or the backup model just asked a
    question -> open the recommendations for that request instead."""
    if req.role == "customer" and (result.get("llm_failed") or not result.get("actions")):
        return offline_shopping_turn(req.session_id, req.message, prior_preferences) or result
    return result


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
        result = (_pre_agent_turn(req, prior_preferences)
                  or _offline_if_failed(req, run_agent_turn(req.session_id, req.message, history, role=req.role,
                                                            prior_preferences=prior_preferences),
                                        prior_preferences))
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


@router.post("/stream")
def chat_stream(req: ChatRequest):
    """Streaming variant of /api/chat -- server-sent events (SSE).

    Events:
      event: delta   data: {"text": "next chunk"}
      event: done    data: {"reply": "...", "actions": [...], "preferences": {...}, "extracted_context": {...}}
      event: fallback data: same shape as done -- turn had to use structured path (couldn't stream)

    Frontend renders delta events as they arrive to show words appearing in
    real time (perceived latency ~2s), while under the hood the model may
    still be generating for another 10-30s. For tool turns, no delta events
    are sent -- the full result arrives in a single fallback event.
    """
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

    prior_preferences = extract_prior_preferences(history)

    try:
        append_conversation_turn(req.session_id, "user", req.message, meta=context)
    except Exception:
        pass

    def sse_event(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    def stream():
        final_reply = ""
        final_actions: list = []
        final_prefs = prior_preferences
        try:
            pre = _pre_agent_turn(req, prior_preferences)
            turns = ([("fallback", pre)] if pre else stream_agent_turn(
                req.session_id, req.message, history,
                role=req.role, prior_preferences=prior_preferences,
            ))
            for chunk_type, payload in turns:
                if chunk_type == "fallback":
                    payload = _offline_if_failed(req, payload, prior_preferences)
                if chunk_type == "delta":
                    final_reply += payload
                    yield sse_event("delta", {"text": payload})
                elif chunk_type == "fallback":
                    final_reply = payload.get("reply", "")
                    final_actions = payload.get("actions", [])
                    final_prefs = payload.get("preferences", prior_preferences)
                    yield sse_event("fallback", {
                        "reply": final_reply,
                        "actions": final_actions,
                        "preferences": final_prefs,
                        "extracted_context": context,
                    })
                elif chunk_type == "done":
                    final_reply = payload.get("reply", final_reply)
                    final_actions = payload.get("actions", final_actions)
                    final_prefs = payload.get("preferences", final_prefs)
                    yield sse_event("done", {
                        "reply": final_reply,
                        "actions": final_actions,
                        "preferences": final_prefs,
                        "extracted_context": context,
                    })
        except Exception:
            traceback.print_exc()
            yield sse_event("done", {
                "reply": "Sorry, something went wrong -- could you try again?",
                "actions": [],
                "preferences": prior_preferences,
                "extracted_context": context,
            })
            return

        try:
            append_conversation_turn(
                req.session_id, "assistant", final_reply,
                meta={"preferences": final_prefs},
            )
        except Exception:
            pass

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
