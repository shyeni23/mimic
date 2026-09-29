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
import logging
import time
from functools import lru_cache

from langchain_groq import ChatGroq

from app.config import settings

log = logging.getLogger(__name__)


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


_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_DELAY = 2.0


def invoke_with_retry(structured_llm, messages, *, max_retries=_MAX_RETRIES):
    """Invoke with exponential backoff on transient Groq errors.

    Returns the parsed structured output on success, re-raises on
    non-retryable errors or after exhausting retries.
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return structured_llm.invoke(messages)
        except LLMConfigurationError:
            raise
        except Exception as e:
            err_str = str(e)
            status = getattr(e, "status_code", None)
            is_rate_limit = status == 429 or "rate_limit" in err_str.lower() or "429" in err_str
            is_retryable = is_rate_limit or status in _RETRYABLE_STATUS_CODES or "overloaded" in err_str.lower()

            # A DAILY-quota 429 won't clear in 10s -- retrying only made the
            # customer wait ~30s for the same failure.
            daily_quota = "per day" in err_str.lower() or "(tpd)" in err_str.lower()
            if not is_retryable or daily_quota or attempt == max_retries:
                raise

            delay = _BASE_DELAY * (2 ** attempt)
            if is_rate_limit:
                delay = max(delay, 10.0)
            log.warning("Groq call failed (attempt %d/%d, retrying in %.0fs): %s",
                        attempt + 1, max_retries + 1, delay, err_str[:200])
            last_exc = e
            time.sleep(delay)

    raise last_exc  # unreachable, but satisfies type checkers


@lru_cache
def _cached_agent_llm() -> ChatGroq:
    """Rebuilding ChatGroq on every /api/chat request adds 1-2s of constructor
    + auth overhead per turn -- lru_cache reuses the same client across
    requests (langchain-groq's ChatGroq is a stateless HTTP wrapper so this
    is safe). Reset by process restart, which the dev --reload flag already
    handles cleanly."""
    return _ChatGroqStructured(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=0.3,
        # invoke_with_retry does the retrying; the SDK's own retries made a
        # daily-quota 429 take ~30s to surface.
        max_retries=0,
        # Bumped 400 -> 1200 -> 2400: 2400 lets Aria give richer multi-sentence
        # replies (needed for off-topic chat, jokes, longer explanations)
        # without truncation. Groq gpt-oss-120b runs at ~500 tok/s so the
        # extra headroom adds <3s worst case.
        max_tokens=2400,
        # NOTE: reasoning_effort="low" + reasoning_format="hidden" were tried
        # here but broke json_schema structured output live -- every structured
        # turn returned "Tool choice is none, but model called a tool" 400s from
        # Groq. Root cause: gpt-oss-120b in structured-JSON mode emits the tool
        # call inside its reasoning section, and hiding reasoning strips it
        # from the payload the schema validator then rejects. Reliability over
        # 5s speed win -- keep default reasoning behavior.
    )


def get_agent_llm() -> ChatGroq:
    """Public wrapper -- checks API key at call time, then returns the
    cached client. The check itself is cheap; caching the ChatGroq instance
    saves the ~1-2s per-request construction cost."""
    if not settings.groq_api_key:
        raise LLMConfigurationError(
            "GROQ_API_KEY is not set -- add it to backend/.env to enable the "
            "conversational agent (see backend/.env.example)."
        )
    return _cached_agent_llm()


@lru_cache
def _cached_fast_chat_llm() -> ChatGroq:
    return ChatGroq(
        model=settings.groq_fast_model,
        api_key=settings.groq_api_key,
        temperature=0.3,
        max_tokens=2400,
        max_retries=0,
    )


def get_fast_chat_llm() -> ChatGroq:
    """Plain-text LLM for tool-less calls (graph.py's fast chat path,
    llm_explain.py) -- see config.groq_fast_model for why it's a separate
    model. Never use this with with_structured_output(): structured and
    tool turns stay on get_agent_llm()."""
    if not settings.groq_fast_model:
        return get_agent_llm()
    if not settings.groq_api_key:
        raise LLMConfigurationError(
            "GROQ_API_KEY is not set -- add it to backend/.env to enable the "
            "conversational agent (see backend/.env.example)."
        )
    return _cached_fast_chat_llm()


@lru_cache
def _cached_structured_fallback_llm() -> ChatGroq:
    return _ChatGroqStructured(
        model=settings.groq_fast_model,
        api_key=settings.groq_api_key,
        temperature=0.3,
        max_tokens=2400,
        max_retries=0,
    )


def get_structured_fallback_llm() -> ChatGroq | None:
    """Backup for graph.py's structured/tool path when groq_model fails
    (e.g. its daily quota is spent): the fast model has its own quota. Less
    reliable at structured output than 120b, but better than an apology.
    None when no separate fast model is configured."""
    if not settings.groq_fast_model or settings.groq_fast_model == settings.groq_model:
        return None
    return _cached_structured_fallback_llm()
