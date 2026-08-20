"""
Thin wrapper so the rest of the app talks to an LLM through LangChain's
standard chat-model interface (keeps callers provider-agnostic -- they only
ever import get_agent_llm from here, never anything Groq-specific).

Uses Groq (via langchain-groq's ChatGroq) -- previously used Gemini, called
directly over Gemini's REST API via httpx because every official Gemini SDK
path requires protobuf>=5, which conflicts with this project's pinned
mediapipe==0.10.14 (protobuf<5). Gemini's free tier also proved unreliable
in practice for this project: daily quota exhaustion (20 requests/day/model
on the free tier), transient 503 "high demand" errors, and a structured-
output bug where the model would leak its own reasoning into field values
once conversation state had several fields to reproduce.

Groq has no such SDK/protobuf conflict -- `groq`'s only dependencies are
anyio, distro, httpx, pydantic, sniffio, typing-extensions, none of which
touch protobuf -- and `langchain-groq` provides a first-party ChatGroq chat
model with native with_structured_output support, so this file no longer
needs a hand-rolled REST client, schema cleaner, or $ref resolver the way
the Gemini wrapper did.
"""
from langchain_groq import ChatGroq

from app.config import settings


class _ChatGroqStructured(ChatGroq):
    """ChatGroq with structured-output defaults tuned for reliability.

    ChatGroq.with_structured_output()'s default method="function_calling"
    emulates structured output via a tool call -- observed live to
    intermittently fail on openai/gpt-oss-120b with "attempted to call tool
    'json' which was not in request.tools" (the model occasionally names its
    own synthetic tool call "json" instead of the schema-derived tool name
    LangChain registered, and Groq's API rejects the mismatch).

    method="json_schema" uses Groq's native structured-output API (constrained
    decoding at the token level, not a tool-call emulation). strict=True was
    tried too (only supported for openai/gpt-oss-20b/120b, which this project
    uses) but Groq rejects it live: strict mode requires
    additionalProperties:false on every nested object in the schema, and
    LangChain's auto-generated schema for ConversationState (a nested
    Pydantic model inside ConversationTurnOutput) doesn't set that at the
    nested level -- confirmed live, every call 400'd with "additionalProperties:false
    must be set on every object". method="json_schema" alone (strict
    omitted/False) sidesteps that requirement while still avoiding the
    function-calling tool-name bug above. graph.py calls
    get_agent_llm().with_structured_output(...) with no method kwarg, so this
    override keeps that call provider-agnostic -- no other file needs to know
    this exists."""

    def with_structured_output(self, schema, **kwargs):
        kwargs.setdefault("method", "json_schema")
        return super().with_structured_output(schema, **kwargs)


class LLMConfigurationError(RuntimeError):
    """Raised when GROQ_API_KEY is missing.

    Deliberately raised lazily (only when a turn actually tries to call the
    model) rather than at construction time. graph.py's run_agent_turn()
    already wraps every llm.invoke() call in a try/except that falls back to
    a friendly "Sorry, I hit a little snag" reply and logs the real
    exception -- so raising here, and only here, turns a missing key into
    that same clean, logged, non-crashing behavior on every call path
    (/api/chat and /api/agent/event alike) without needing to touch graph.py
    or any router.
    """


def get_agent_llm() -> ChatGroq:
    if not settings.groq_api_key:
        raise LLMConfigurationError(
            "GROQ_API_KEY is not set -- add it to backend/.env to enable the "
            "conversational agent (see backend/.env.example)."
        )
    return _ChatGroqStructured(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=0.3,
        max_tokens=1024,
    )
