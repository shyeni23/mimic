"""
Path B: native LangChain bind_tools() tool-selection, on a smaller Groq
model, as a genuinely separate implementation from graph.py's Path A
(structured-output tool-selection loop) -- built to be compared head-to-
head against the same scenarios, per this project's own continuity
document's roadmap ("compare structured planner/executor against native
tool calling using the same test set").

WHY a smaller model: two prior attempts at bind_tools() on gpt-oss-120b (a
large MoE model) both failed live reliability testing -- documented in
graph.py's module docstring (the model skipped required calls, or forcing
one tool suppressed parallel calls to others). External research across
several LangChain/Groq agent repos this session found every one that got
native tool-calling working reliably on Groq did so on a smaller model --
none proved bind_tools() reliable on gpt-oss-120b specifically. Those repos
used Meta Llama models, which turned out NOT to be available on this
project's actual Groq account (confirmed live via the API's own /models
list -- 404'd on the first guess, learn from that rather than repeat it).
config.py's groq_native_model defaults to openai/gpt-oss-20b instead: the
smaller sibling of Path A's own model, same vendor/family, which minimizes
confounding variables versus jumping to an architecture nobody here has
tested. This module tests whether smaller-model tool-calling reliability
holds for THIS project's own tools/prompts on the model actually available
to it, rather than assuming a result from someone else's account.

Deliberately NOT LangGraph -- a bounded, hand-rolled Python loop (same
shape as graph.py's, same LOOP_TOOLS, same _execute_native_tool_call
validation boundary imported from graph.py) is enough for a genuine
ReAct-style tool-calling comparison, and avoids adding a new framework
dependency this project doesn't otherwise need.

Return contract matches run_agent_turn exactly ({"reply", "actions",
"preferences"}) so this is a drop-in alternative for comparison purposes,
not a separate API shape callers need to learn. Nothing in chat.py or
agent_events.py imports this module yet -- wiring either path into the
live /api/chat route is a deliberate later choice, not made by this file.

EMPIRICAL RESULT (live-tested the day this module was built): on
openai/gpt-oss-20b, a PLAIN chat turn with no tool need at all ("I like
pastel colors for my outfit") produced a 400 from Groq's own API --
`failed_generation` showed the model inventing a nonexistent "response"
pseudo-tool-call with unquoted/malformed JSON arguments, rather than either
answering directly (no tool_calls) or calling a real bound tool. Caught
cleanly by this function's own exception handling (degrades to the same
friendly fallback graph.py uses), but this means Path A (openai/gpt-oss-120b,
structured-output loop) was measurably MORE reliable than Path B on the
models actually available to this Groq account -- the opposite of what the
external research this module was built from predicted, because that
research's own smaller-model recommendations (llama-3.1-8b-instant,
llama-3.3-70b-versatile) aren't accessible here at all. Don't treat gpt-oss-20b
as validated for production use based on this module's existence -- re-run
the live smoke tests before relying on this path for anything real, and
prefer Path A (graph.py) until/unless a genuinely different model proves
out here.
"""
import json
from typing import Optional

from langchain_core.messages import ToolMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field as PydanticField

from app.config import settings
from app.services.agent.llm import LLMConfigurationError
from app.services.agent.preferences import merge_preferences
from app.services.agent.tools import LOOP_TOOLS
from app.services.agent.actions import start_turn as start_action_turn, get_queued_actions
from app.services.agent.graph import (
    CUSTOMER_PROMPT, ADMIN_PROMPT, _build_messages, _execute_native_tool_call,
    MAX_TOOL_ITERATIONS,
)


class RecordConversationState(BaseModel):
    """Silently record what you've learned about the customer's styling
    preferences so far -- call this whenever they reveal something new or
    changed, alongside any other tool you call this same step. Only pass
    fields that are new or have changed; leave the rest out."""
    occasion: Optional[str] = None
    style: Optional[str] = None
    color_preferences: Optional[list[str]] = None
    disliked_colors: Optional[list[str]] = None
    budget: Optional[str] = None
    fit: Optional[str] = None
    constraints: Optional[list[str]] = PydanticField(
        default=None, description="Things to AVOID, e.g. 'heavy embroidery', 'flashy', 'tight'.")
    notes: Optional[str] = None
    ready_for_recommendation: Optional[bool] = None


# The extraction schema (ConversationState) has no native-tool-calling
# equivalent unless it's ALSO exposed as a tool the model can choose to
# call -- native bind_tools() has no equivalent of graph.py's "always-
# present structured field" mechanism; everything is a tool or nothing.
# This is exactly the "extraction competing with other tools" shape the
# project's own documented history found unreliable on gpt-oss-120b.
# Testing whether a SMALLER model handles that competition better is the
# whole point of this module -- so RecordConversationState is bound
# alongside every real tool, not special-cased.
_ALL_TOOLS = LOOP_TOOLS + [RecordConversationState]


def get_native_agent_llm() -> ChatGroq:
    if not settings.groq_api_key:
        raise LLMConfigurationError(
            "GROQ_API_KEY is not set -- add it to backend/.env to enable the conversational agent."
        )
    return ChatGroq(
        model=settings.groq_native_model,
        api_key=settings.groq_api_key,
        temperature=0.3,
        max_tokens=400,
    )


def run_agent_turn_native(
    session_id: str,
    user_text: str,
    history: list[dict],
    role: str = "customer",
    prior_preferences: dict | None = None,
) -> dict:
    """
    Path B equivalent of graph.py's run_agent_turn -- same signature, same
    return shape, same LOOP_TOOLS, same validation boundary
    (_execute_native_tool_call, imported from graph.py). The variable under
    test: tool selection here is LangChain's native bind_tools() (the model
    emits real tool_calls, Groq's own function-calling mechanism, not this
    project's own structured-output ToolCall field) on a smaller Groq model
    than Path A uses (see get_native_agent_llm/config.py's groq_native_model).
    """
    prior_preferences = prior_preferences or {}

    if not user_text or not user_text.strip():
        return {
            "reply": "Sorry, I didn't quite catch that -- could you say it again?",
            "actions": [],
            "preferences": prior_preferences,
        }

    system_prompt = ADMIN_PROMPT if role == "admin" else CUSTOMER_PROMPT
    if prior_preferences:
        known_fields = [k for k, v in prior_preferences.items() if v is not None and v != "" and v != []]
        system_prompt += (
            "\n\nWHAT YOU ALREADY KNOW ABOUT THIS CUSTOMER (from earlier in this "
            "conversation). These topics are SETTLED -- do NOT ask about them again "
            "unless the customer brings one up to change it:\n" + json.dumps(prior_preferences)
        )
        if known_fields:
            system_prompt += "\n\nAlready answered (do NOT re-ask): " + ", ".join(known_fields) + "."
    system_prompt += (
        "\n\nYou also have a RecordConversationState tool -- call it (alongside any other "
        "tool, in the SAME step, if you're calling one) whenever the customer reveals "
        "something new about what they want. Only pass fields that are new or changed."
    )

    messages = _build_messages(system_prompt, history, user_text)

    start_action_turn()
    turn_delta: dict = {}
    final_reply = None
    shown_item_ids: set = set()
    executed_calls: dict = {}
    llm_configured = True

    try:
        llm = get_native_agent_llm().bind_tools(_ALL_TOOLS)
        for step in range(MAX_TOOL_ITERATIONS + 1):
            response = llm.invoke(messages)
            if response.content:
                final_reply = response.content.strip()
            messages.append(response)

            tool_calls = response.tool_calls or []
            if not tool_calls or step == MAX_TOOL_ITERATIONS:
                break

            for tc in tool_calls:
                if tc["name"] == "RecordConversationState":
                    turn_delta = merge_preferences(turn_delta, tc["args"])
                    messages.append(ToolMessage(content="recorded", tool_call_id=tc["id"]))
                    continue
                result_json = _execute_native_tool_call(
                    session_id, tc["name"], tc["args"], shown_item_ids, executed_calls,
                )
                messages.append(ToolMessage(content=result_json, tool_call_id=tc["id"]))

        if not final_reply:
            final_reply = "Sorry, I got a bit tongue-tied there -- could you say that again?"
    except LLMConfigurationError as e:
        print(f"[conversation-native] {e}")
        final_reply = "Sorry, I'm having trouble connecting right now -- mind trying again in a moment?"
        llm_configured = False
    except Exception as e:
        print(f"[conversation-native] LLM call failed: {e}")
        final_reply = "Sorry, I hit a little snag -- mind trying that again?"

    updated_preferences = merge_preferences(prior_preferences, turn_delta)
    actions = get_queued_actions() if llm_configured else []

    return {"reply": final_reply, "actions": actions, "preferences": updated_preferences}
