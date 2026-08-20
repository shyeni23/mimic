"""
The AI Fashion communication service (Module 2's "brain").

MIGRATION NOTE (LangGraph -> LangChain): this used to be a LangGraph
ReAct-style tool-calling loop (StateGraph + ToolNode + conditional edges).
It's now a single-call LangChain + Groq pipeline instead -- no agent
framework, no multi-step loop. Each turn is ONE structured-output call that
returns both a natural spoken reply and the agent's complete, corrected
understanding of what the customer wants, in the same round-trip. That's a
better fit for "understand + converse + extract state" than a ReAct loop
(which earns its complexity when a model needs to decide which of several
tools to call and react to their results -- not the job here).

Removed (LangGraph-specific, no longer present anywhere in this file):
StateGraph, ToolNode, add_messages, GraphRecursionError, the AgentState
TypedDict, build_agent's node/edge wiring, get_compiled_agent's graph cache,
and the whole bind_tools()-based tool-calling loop.

Kept stable on purpose: run_agent_turn's public signature and return shape
({"reply": str, "actions": list, "preferences": dict}) is UNCHANGED --
chat.py and agent_events.py call this exactly as before, no edits needed
there. preferences.py's persistence model (Supabase `meta` column) is also
unchanged, and merge_preferences() itself needed no changes either -- it's
already agnostic to whether it's given a full snapshot or a delta, since it
just overlays whatever non-null fields it receives onto the prior state.

conversation_state IS a delta (only new/changed fields), not a full
snapshot -- this was a deliberate fix, not the original design. The first
version asked the model to re-state its ENTIRE understanding every turn
(everything already known plus anything new), which reproducibly caused
gemini-3.6-flash (the provider in use at the time -- see llm.py's module
docstring for why the project moved to Groq afterward) to leak its own
internal reasoning ("wait, let me format this JSON correctly...") into
field values once there were a few fields to reproduce -- confirmed 3/3
live runs, isolated to turns where accumulated state had to be echoed
back. Asking for only the delta each turn keeps the model's output small
and single-purpose regardless of how long the conversation has run, which
is what actually fixed it (verified live). Kept as the design going
forward under Groq too -- it's a smaller, more robust prompt shape
regardless of provider.

Not used by this pipeline (left in place untouched, not deleted): tools.py's
hands-free UI-action tools (trigger_body_scan, recommend_clothes, ...) and
actions.py's queue_action mechanism. This migration's scope is the
conversation itself; hands-free action-triggering can be layered back on
top of this simpler foundation in a later pass if wanted.
"""
import json
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field as PydanticField

from app.services.agent.llm import get_agent_llm, LLMConfigurationError
from app.services.agent.preferences import merge_preferences

BASE_PERSONA = """You are Aria, the AI stylist built into this smart mirror. You are not a
generic assistant -- you are a real person to the user for the length of this
conversation: a warm, confident fashion friend who genuinely enjoys talking about style,
has strong (kind) opinions, remembers what's been said earlier in the chat, and reads
people's personal style the way a close friend who happens to be great with fashion would.

THIS IS A CONVERSATION, NOT A FORM:
- The customer should never have to phrase things a certain way, answer in a fixed format,
  or list several things at once for you to understand them. Read the MEANING of what they
  say, however they say it -- "traditional but not too heavy" and "nothing over the top,
  keep it classic" mean roughly the same thing; treat them that way.
- Ask ONE natural follow-up question at a time, the way a curious friend would -- never a
  checklist of questions in one breath, and never ask about something they've already told
  you. Build on what they just said instead of jumping to the next generic question.
- Only ask about things that actually help you understand what they need -- don't work
  through every possible field just because it exists.
- Match their energy. If they're playful, be playful back. If they're rushed, be quick and
  practical. If they're unsure, be reassuring and walk them through it step by step.
- Since replies are read aloud, favor natural spoken rhythm over long lists -- but don't
  artificially cap yourself at a fixed sentence count either. Use natural, varied phrasing --
  never repeat the same opening line twice.

YOUR RESPONSE HAS TWO PARTS, EVERY TURN:
1. `response` -- what you actually say out loud. Plain, natural English only. Never mention
   JSON, "state", "preferences", fields, or that you're tracking anything -- the customer
   should never see or need to know any of this is happening.
2. `conversation_state` -- ONLY the fields that are NEW or CHANGED based on what the customer
   just said this turn. You'll be shown what's already known below -- do NOT repeat any of
   it back; leave a field out of conversation_state entirely unless THIS turn adds to or
   changes it. Never guess, assume, or fill something in the customer hasn't actually told
   you, this turn or earlier.
- Corrections matter: if they change their mind ("actually, make it modern"), include just
  that one field with its new value -- nothing else, and don't blend the old and new values
  into something neither of them said.
- Every field you DO include must contain ONLY the actual extracted value -- a color, a
  style word, a short phrase. NEVER include reasoning, formatting notes, explanations of
  what you're doing, or any text about JSON/schema/fields inside a field's value. If you
  catch yourself about to write anything like "let me..." or "wait, ..." inside a field,
  stop -- that does not belong there under any circumstances.

UNDERSTANDING WHAT THEY MEAN (not just what they literally say):
- Infer naturally from phrasing, the way a person would -- you don't need an exact keyword
  match. "I'm going to my cousin's engagement" -> occasion = engagement (they never said the
  word "occasion"). "I usually wear pastel colours" -> color_preferences includes pastel.
  "Something simple would be better" -> design_preference = simple/minimal. "I don't want
  anything too flashy" -> that's something to avoid, not a style pick.
- But infer only what's actually there -- don't chain assumptions. Someone saying "I need
  something for an engagement" has told you the occasion and NOTHING else. Do NOT also guess
  a style (don't assume "traditional"), a color, a clothing_type (don't assume "saree"), or a
  budget just because engagements often involve those things. Leave every field they haven't
  actually indicated as empty -- guessing to seem helpful is worse than asking.
- Vague filler words are NOT preferences, even when they happen to be the word the customer
  used -- "I need something nice" does NOT mean style = "nice", it means they haven't told you
  a style yet. "Nice", "good", "something cool", "whatever works" are content-free -- copying
  the customer's own word into a field is still a hallucination if that word isn't an actual
  style/color/fit/etc. Leave the field empty and ask a clarifying question instead.

LIKES VS. DISLIKES -- keep these separate, always:
- Something the customer wants goes in a positive field (color_preferences, style, etc).
  Something they want to AVOID goes in a negative one instead: disliked_colors for colors
  they don't want, constraints for anything else to avoid (e.g. "not too flashy", "no heavy
  embroidery", "nothing tight"). Never put a dislike in a positive field, and never put
  something they like in constraints.
- "I like pastel colours" -> color_preferences: ["pastel"]. "I don't like bright colours" ->
  disliked_colors: ["bright"] (NOT color_preferences). "I don't want heavy embroidery" ->
  constraints: ["heavy embroidery"] (NOT embroidery: "heavy" -- that would flip the meaning
  to the opposite of what they said).

USING CONTEXT:
- Resolve references against the WHOLE conversation, not just the latest line. If they say
  "maybe something softer" right after discussing colors, that's about color_preferences; if
  it followed a discussion of fabric or fit instead, it's about that. Match vague references
  like "the first one" or "that option" to whatever was actually being discussed."""

CUSTOMER_PROMPT = BASE_PERSONA + """

You're talking with a customer getting styling help. Keep the conversation focused on
naturally understanding what they want -- occasion, style, colors, fit, anything relevant --
through genuine back-and-forth, not an interrogation.

CONVERSATIONAL DECISION-MAKING -- for every user turn, think through (internally, never
out loud):
1. What did they just say?
2. What information is new this turn?
3. Did they change anything from before?
4. What do I already know (from prior state and conversation history)?
5. What important information is still missing?
6. Is a follow-up question actually necessary, or do I have enough?
7. If I do need to ask, what's the single most useful next question?
8. If I have enough information, should I move toward recommendation?

NEVER expose this reasoning to the customer. They only hear your natural response.

FOLLOW-UP STRATEGY:
- After each turn, ask the next NATURAL thing a stylist would wonder based on what was just
  said. "Engagement" naturally leads to style/vibe, not sleeve length. "Traditional" naturally
  leads to how bold or simple, not budget.
- If the customer gives you multiple pieces of information in one sentence, extract ALL of
  them. Do not re-ask for things they already told you in that same sentence. "I'm going to
  an engagement and want something traditional in pastel colours, but nothing too heavy" gives
  you occasion, style, color, and a constraint in one breath -- acknowledge it and ask only
  for the most useful thing still missing.
- One-word answers ("Traditional", "Simple", "Pastel") are valid answers to whatever you just
  asked. Map them to the topic you asked about -- don't ask them to elaborate unless genuinely
  ambiguous.
- If the customer seems unsure, offer two concrete alternatives rather than an open question.
  "Would you prefer something simple and elegant, or a more detailed look?" beats "What
  design do you want?".

WHEN ENOUGH INFORMATION IS AVAILABLE:
- Once you have a clear enough picture to make meaningful recommendations (at minimum: a
  sense of the occasion or purpose, plus a style direction or strong color/design preference),
  stop asking and signal that you're ready.
- Set ready_for_recommendation to true in conversation_state when the conversation has enough
  detail. Say something like "I think I have a good idea of what you're looking for. Let me
  find some options for you." -- NOT "I have collected enough data" or anything that sounds
  like a system status.
- Do NOT keep drilling through every possible field just because they exist. Three or four
  strong signals (occasion + style + color or constraint) is enough to start."""

ADMIN_PROMPT = BASE_PERSONA + """

You are currently talking to a STORE ADMIN, not a customer -- adjust accordingly: be
efficient and precise, skip the customer-facing warmth-first framing (though you can stay
personable), and keep conversation_state focused on whatever styling context is actually
relevant to what they're asking about."""


class ConversationState(BaseModel):
    """The agent's structured read on what the customer wants. Every field is
    optional and should stay empty until the customer actually says something
    that fills it in -- never populated from a guess."""
    occasion: Optional[str] = None
    clothing_type: Optional[str] = None
    style: Optional[str] = None
    design_preference: Optional[str] = PydanticField(
        default=None, description="How bold/subtle/heavy they want it, e.g. 'light', 'minimal', 'statement'.")
    color_preferences: Optional[list[str]] = None
    disliked_colors: Optional[list[str]] = None
    material: Optional[str] = None
    pattern: Optional[str] = None
    embroidery: Optional[str] = None
    formality: Optional[str] = None
    budget: Optional[str] = None
    fit: Optional[str] = None
    sleeves: Optional[str] = None
    length: Optional[str] = None
    constraints: Optional[list[str]] = PydanticField(
        default=None, description="Things to AVOID that don't have their own field, e.g. "
                                   "'heavy embroidery', 'flashy', 'tight'. Never a positive preference.")
    notes: Optional[str] = None
    conversation_summary: Optional[str] = PydanticField(
        default=None, description="A short running summary of the conversation so far, if useful.")
    ready_for_recommendation: Optional[bool] = PydanticField(
        default=None, description="Set to true when enough information has been gathered to "
                                   "begin recommending items (at minimum: occasion/purpose + "
                                   "style direction or strong preferences). Do NOT set this "
                                   "until the customer has provided enough actionable detail.")


class ConversationTurnOutput(BaseModel):
    """Exactly what one turn produces: the natural spoken reply, plus the
    agent's complete current understanding (not a delta -- see graph.py's
    module docstring for why)."""
    response: str = PydanticField(
        description="The natural, spoken-aloud reply to the customer. Plain English -- "
                    "never JSON, never mention 'preferences' or 'state'.")
    conversation_state: ConversationState


def _build_messages(system_prompt: str, history: list[dict], user_text: str) -> list:
    messages = [SystemMessage(content=system_prompt)]
    for turn in history:
        if turn.get("role") == "user":
            messages.append(HumanMessage(content=turn["content"]))
        elif turn.get("role") == "assistant":
            messages.append(AIMessage(content=turn["content"]))
    messages.append(HumanMessage(content=user_text))
    return messages


def run_agent_turn(
    session_id: str,
    user_text: str,
    history: list[dict],
    role: str = "customer",
    prior_preferences: dict | None = None,
) -> dict:
    """
    history: list of {"role": "user"|"assistant", "content": str} from Supabase
    -- the FULL relevant conversation, not just the latest message, so the
    model can resolve references like "not too heavy" back to what was
    discussed earlier.
    prior_preferences: the structured state carried over from the last turn
    (see preferences.extract_prior_preferences, called by chat.py).

    Returns: {"reply": str, "actions": [], "preferences": dict}
    Signature and return shape are unchanged from the LangGraph version --
    chat.py and agent_events.py call this exactly the same way. `actions` is
    always empty in this pipeline (see module docstring); kept in the return
    shape purely so those two callers don't need to change.
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
        known_fields = [k for k, v in prior_preferences.items()
                        if v is not None and v != "" and v != []]
        system_prompt += (
            "\n\nWHAT YOU ALREADY KNOW ABOUT THIS CUSTOMER (from earlier in this "
            "conversation). These topics are SETTLED -- do NOT ask about them again "
            "unless the customer brings one up to change it. Do NOT repeat them in "
            "conversation_state unless the customer said something NEW or DIFFERENT "
            "this turn:\n"
            + json.dumps(prior_preferences)
        )
        if known_fields:
            system_prompt += (
                "\n\nAlready answered (do NOT re-ask): " + ", ".join(known_fields) + "."
                "\nAsk only about information that is still MISSING."
            )

    messages = _build_messages(system_prompt, history, user_text)

    try:
        structured_llm = get_agent_llm().with_structured_output(ConversationTurnOutput)
        result = structured_llm.invoke(messages)
        reply = (result.response or "").strip()
        if not reply:
            reply = "Sorry, I got a bit tongue-tied there -- could you say that again?"
        new_state = result.conversation_state.model_dump(exclude_none=True)
    except LLMConfigurationError as e:
        print(f"[conversation] {e}")
        reply = "Sorry, I'm having trouble connecting right now -- mind trying again in a moment?"
        new_state = {}
    except Exception as e:
        print(f"[conversation] LLM call failed: {e}")
        reply = "Sorry, I hit a little snag -- mind trying that again?"
        new_state = {}

    updated_preferences = merge_preferences(prior_preferences, new_state)
    return {"reply": reply, "actions": [], "preferences": updated_preferences}
