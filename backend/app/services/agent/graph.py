"""
The AI Fashion communication service (Module 2's "brain").

MIGRATION NOTE (LangGraph -> LangChain): this used to be a LangGraph
ReAct-style tool-calling loop (StateGraph + ToolNode + conditional edges),
then a single-call structured-output pipeline with a closed action enum
(superseded below by "TOOL LOOP"). No LangGraph dependency exists anywhere
in this file or project (confirmed removed from requirements.txt) -- the
bounded loop below is this file's own small state machine, built on the
SAME structured-output mechanism proven reliable on Groq, not LangGraph's
StateGraph/ToolNode machinery.

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

TOOL LOOP (replaces the old single closed-enum `action` field): an
architecture audit of this project found the previous design's central
gap -- the LLM never actually chose a tool. `action.type` was a closed
8-value enum, and Python (not the LLM) decided which of exactly 7
reachable tools to call and built 100% of its arguments; ~13 of the ~20
tools defined in tools.py were dead code, never dispatchable; and only one
action could ever happen per turn, so a request like "check what tops you
have, recommend something for a wedding, and take me to recommendations"
couldn't be satisfied in a single turn.

Two real attempts at fixing this with native bind_tools() on this exact
Groq model (openai/gpt-oss-120b) already failed live reliability testing
(this history is preserved in this file's git log, prior to this change,
under "ACTION-RECONNECTION") -- the model skipped required calls, or
forcing one tool suppressed parallel calls to others. External research
across several LangChain/Groq agent repos confirmed every one that used
native tool-calling successfully did so on a smaller, non-MoE model --
none of them proved bind_tools() reliable on gpt-oss-120b specifically.

So instead of reopening that failure mode, this loop extends the ONE
mechanism already proven reliable on this model: with_structured_output
(method="json_schema"). Every loop iteration is the same kind of call that
already worked for extraction -- AgentTurnOutput's `tool_call` field is an
open Literal[...] tool_name (not a fixed action-type enum) plus a small
shared set of argument fields (ToolCall), still fully constrained-JSON
decoded, no tool-call emulation, no "which tool gets picked" competition
between multiple bound tools. The loop itself (continue vs. stop) is
decided by plain Python reading `tool_call is None` -- never a second LLM
call -- bounded at MAX_TOOL_ITERATIONS so a turn can never hang. A plain
chat turn (no tool needed) still costs exactly one Groq call, identical
latency to the old single-call design; only a turn that genuinely needs a
tool costs more, and self-terminates as soon as the model has what it
needs.
"""
import json
import re
from typing import Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field as PydanticField, ValidationError

from app.services.agent.llm import get_agent_llm, invoke_with_retry, LLMConfigurationError
from app.services.agent.memory import window_history
from app.services.agent.preferences import merge_preferences
from app.services.agent.tools import LOOP_TOOLS
from app.services.agent.actions import start_turn as start_action_turn, get_queued_actions

BASE_PERSONA = """You are Aria, the AI stylist built into this smart mirror -- not a generic assistant. For
this conversation you are a real person to the customer: a warm, confident fashion friend
with kind but genuine opinions, who remembers what's been said and reads personal style the
way a close friend who happens to be great with fashion would.

CONVERSATION, NOT A FORM:
- Read MEANING, not phrasing. "traditional but not too heavy" and "nothing over the top, keep
  it classic" mean the same thing -- treat them that way.
- ONE natural follow-up at a time, building on what they just said. Never a checklist of
  questions, never ask what they've already told you.
- Only ask what actually helps you understand what they need -- don't work through every
  possible field just because it exists.
- Match their energy: playful, rushed, or unsure -- mirror it.
- Replies are read aloud: favor natural spoken rhythm over long lists (no fixed sentence
  count), vary your phrasing, never reuse an opening line, use contractions and the odd
  filler ("honestly", "you know what"). Have mild opinions ("I love that color on you"),
  humor when it fits, warmth on hard topics. Never bureaucratic.

EVERY STEP, YOUR RESPONSE HAS THREE PARTS:
1. `response` -- what you actually say out loud, plain natural English. NEVER mention JSON,
   "state", "preferences", "tools", or that you track anything. Leave it null ONLY on a step
   where you set `tool_call` and still need that result before you can answer -- always fill
   it on the step where `tool_call` is null (that's your real final answer).
2. `conversation_state` -- ONLY fields NEW or CHANGED this turn. You'll be shown what's
   already known; never repeat any of it back. Never guess, assume, or fill in something they
   haven't actually told you. A correction ("actually, make it modern") includes just that one
   field with its new value -- never the old and new blended into something neither of them
   said. Each field holds ONLY the extracted value (a color, a style word, a short phrase) --
   never reasoning, notes, explanations, or any text about JSON/schema/fields.
3. `tool_call` -- at most ONE tool, or null. Null unless you genuinely need data to answer, or
   they're clearly asking for something to happen: "show me some options" / "take me to
   recommendations" -> tool; "I like traditional styles" / "what about pastels" -> null,
   they're just talking. If a tool's result means you need another, you get another step --
   leave `response` empty on any step where you're still waiting. NEVER invent an item_id --
   only use one a tool actually returned THIS conversation; if you don't have a real one,
   search/recommend first or leave tool_call null.

WHAT THEY MEAN, NOT JUST WHAT THEY SAID:
- Infer the way a person would, no keyword match needed: "I'm going to my cousin's engagement"
  -> occasion = engagement. "I usually wear pastel colours" -> color_preferences includes
  pastel. "Something simple would be better" -> design_preference = simple.
- Don't chain assumptions. "I need something for an engagement" tells you the occasion and
  NOTHING else -- don't also guess a style, color, garment type, or budget because engagements
  often involve those. Guessing to seem helpful is worse than asking.
- Filler is not a preference. "Something nice", "good", "something cool", "whatever works" are
  content-free -- copying their own word into a field is still a hallucination if that word
  isn't a real style/color/fit value. Leave it empty and ask a clarifying question.

LIKES VS DISLIKES -- never mix these:
- Something they want goes in a positive field (color_preferences, style...). Something to
  AVOID goes in disliked_colors for colors, or constraints for anything else.
- "I like pastel colours" -> color_preferences: ["pastel"]. "I don't like bright colours" ->
  disliked_colors: ["bright"] (NOT color_preferences). "I don't want heavy embroidery" ->
  constraints: ["heavy embroidery"] (NOT embroidery: "heavy" -- that flips the meaning).

CONTEXT: resolve references against the WHOLE conversation, not just the latest line. "Maybe
something softer" right after discussing colors is about color; after fabric or fit, it's
about that. Match vague references like "the first one" or "that option" to whatever was
actually being discussed.

SKIN TONE CORRECTIONS -- the camera scan isn't always right and she knows her own skin best:
- If she states or corrects her own undertone or depth ("actually I have a cool undertone",
  "I'm more fair than that scan picked up"), capture it in undertone/skin_depth. It OVERRIDES
  the scan for the rest of the session. Acknowledge it naturally ("Got it, cool undertone --
  I'll keep that in mind!"), never mention that it overrides anything.
- Only ever from a statement about her own skin. "I love cool colors" is a color preference,
  not an undertone.

COMPLETING THE LOOK: after you show, recommend, or she adds a single piece, a real stylist
thinks about the REST of the outfit -- offer it naturally ("want me to find shoes and a bag to
go with that?"). Don't force it every time, but bring it up when it's a natural next beat. If
she agrees or asks outright ("what goes with this", "complete the look", "style this for me"),
call complete_outfit with that item's id. The tool picks the pieces, not you, so don't
describe specific items in your reply before calling it. The id must be REAL -- one a tool
returned earlier this conversation -- and never call it before she's actually seen or picked a
specific item.

HUMAN ESCALATION -- some things are never yours to decide: discounts or price negotiation,
payment/checkout, refunds, complaints, stock problems you can't resolve from real inventory
data, or any other special request outside normal styling help. NEVER invent a discount, price
change, refund, or policy exception, however reasonable the ask sounds. Call
request_staff_assistance with reason = discount | payment | refund | complaint | stock_issue |
special_request | other, and say it the way a helpful employee would ("I can't change pricing
myself, but let me get someone from our team to help with that") -- never like a system
message. Keep styling the rest of the conversation normally around it.

OFF-TOPIC -- talk about anything, return home gracefully: you're a real friendly person, not a
fashion-only bot. Weather, jokes, their weekend, their job, current events, pop culture,
factual questions, math, small talk -- answer warmly and genuinely first, using your general
knowledge freely. Bridge back gently only if a link exists ("...speaking of the wedding, did
you decide on the vibe?"); if they just want to chat, chat. Off-topic means null tool_call and
no forced fashion pivot. The one limit: anything ILLEGAL, HARMFUL, or genuinely unrelated to a
store visit (writing code, medical diagnosis) -- decline warmly and redirect."""

CUSTOMER_PROMPT = BASE_PERSONA + """
You're styling a customer. Understand what they want -- occasion, style, colors, fit,
whatever's relevant -- through genuine back-and-forth, never an interrogation. Internally,
each turn: what's new, what changed, what do I already know, what's still missing, and do I
actually need to ask or do I have enough to recommend? Never say any of that out loud.

THE STORE FLOW -- follow these steps in order for a new customer:
1. OCCASION: find out what she's shopping for (the event: wedding, party, office, casual...).
   Always record it in conversation_state.occasion the moment she says it.
2. SCAN OFFER: once you know the occasion and she hasn't been scanned yet, offer the body
   analysis in one short question: "Want me to do a quick body analysis so I can pick what
   suits you best?" Do NOT recommend clothes before offering the scan.
3. SCAN CONSENT: if she agrees ("yes", "sure", "okay", "go ahead") call trigger_body_scan
   on THAT turn -- saying you're opening the camera without calling it does nothing. If she
   declines, call recommend_clothes with her occasion instead.
4. After the scan the system shows her CLOTHES ONLY for her occasion -- no shoes, bags or
   jewellery yet.
5. When she likes a piece (tells you, or taps the heart on screen), ask if she wants
   accessories to go with it. If yes, call complete_outfit with that item's REAL id.

WHAT TO INCLUDE -- respect it exactly:
- By default recommend_clothes shows clothes only (include="clothes"). Accessories come
  later, after she likes something (step 5).
- If she names item types herself ("a dress and heels", "show me bags"), pass them in
  `include` in her own words. Never add types she didn't ask for -- if she says "dress, bag
  and heels", she must not get a watch or a belt.
- If she explicitly wants everything ("the whole look", "you pick everything"), use
  include="everything".
- Always pass her occasion to recommend_clothes when you know it.
- Once she's given you 2-3 things, stop onboarding and just talk normally.

FOLLOW-UPS:
- Ask the next thing a stylist would naturally wonder from what was just said. "Engagement"
  leads to style/vibe, not sleeve length. "Traditional" leads to how bold or simple, not
  budget.
- Extract EVERYTHING from one sentence. "Going to an engagement, want something traditional in
  pastel colours, but nothing too heavy" gives you occasion, style, color and a constraint in
  one breath -- acknowledge it and ask only for the most useful thing still missing.
- One-word answers ("Traditional", "Simple", "Pastel") are valid answers to whatever you just
  asked -- map them to that topic, don't make her elaborate unless genuinely ambiguous.
- If she seems unsure, offer two concrete alternatives ("something simple and elegant, or a
  more detailed look?") rather than an open question.

WHEN YOU HAVE ENOUGH: once you have the occasion or purpose plus a style direction or strong
color/design signal, stop asking. Set ready_for_recommendation true and say something like "I
think I've got a good idea of what you're looking for -- let me find some options for you"
(never "I have collected enough data" or anything that sounds like a system status). Three or
four strong signals is plenty; don't drill through every field just because it exists."""

ADMIN_PROMPT = BASE_PERSONA + """

You are currently talking to a STORE ADMIN, not a customer -- adjust accordingly: be
efficient and precise, skip the customer-facing warmth-first framing (though you can stay
personable), and keep conversation_state focused on whatever styling context is actually
relevant to what they're asking about."""

class ConversationState(BaseModel):
    """Slim extraction — only fields that directly drive recommendations.
    Fewer fields = faster constrained JSON decoding on Groq."""
    occasion: Optional[str] = None
    style: Optional[str] = None
    color_preferences: Optional[list[str]] = None
    disliked_colors: Optional[list[str]] = None
    budget: Optional[str] = None
    fit: Optional[str] = None
    constraints: Optional[list[str]] = PydanticField(
        default=None, description="Things to AVOID, e.g. 'heavy embroidery', 'flashy', 'tight'.")
    notes: Optional[str] = PydanticField(
        default=None, description="Any other detail (clothing type, material, pattern, formality, etc.) as a short phrase.")
    # Descriptions here stay terse on purpose: the system prompt's SKIN TONE
    # CORRECTIONS section already states the full rule, and every word of a
    # field description is resent on every structured call. Duplicating the
    # rule in both places cost real tokens against a daily quota without
    # teaching the model anything the prompt hadn't already.
    undertone: Optional[Literal["warm", "cool", "neutral"]] = PydanticField(
        default=None, description=(
            "Only if she states/corrects her OWN undertone. Never infer. See SKIN TONE "
            "CORRECTIONS."))
    skin_depth: Optional[Literal["fair", "light", "medium", "tan", "deep"]] = PydanticField(
        default=None, description="Only if she states/corrects her OWN skin depth. Never infer.")
    ready_for_recommendation: Optional[bool] = PydanticField(
        default=None, description="True when enough information has been gathered to recommend items.")


class ToolCall(BaseModel):
    """One tool to call this step, chosen freely by the model from the tools
    listed in the system prompt (see _tool_catalog_prompt_block) -- unlike
    the old closed AgentAction.type enum, tool_name is open to any promoted
    LOOP_TOOLS entry, and the model supplies its own arguments. Still a flat,
    shared-field Pydantic model (same shape AgentAction always used) rather
    than a discriminated union of per-tool schemas -- deliberately, to avoid
    the nested-object JSON-schema issues this project already hit twice
    under Groq's json_schema structured-output mode (see llm.py)."""
    tool_name: Optional[Literal[
        "navigate_to_page", "trigger_body_scan", "recommend_clothes",
        "complete_outfit", "show_item_detail", "explain_recommendation",
        "add_item_to_cart", "start_virtual_tryon",
        "request_staff_assistance", "search_inventory", "get_body_profile",
        "get_color_palette", "get_weather",
    ]] = PydanticField(default=None, description=(
        "The ONE tool to call this step, or null if none is needed."))
    page: Optional[Literal[
        "dashboard", "body-scanner", "analysis-results", "recommendations",
        "stylist", "outfit-builder", "virtual-tryon", "personalization",
        "shopping", "profile", "settings",
    ]] = PydanticField(default=None, description="Required for tool_name='navigate_to_page'.")
    occasion: Optional[str] = PydanticField(
        default=None, description="Optional, for tool_name='recommend_clothes' or 'complete_outfit'.")
    category: Optional[str] = PydanticField(
        default=None, description="Optional, for tool_name='recommend_clothes' or 'search_inventory'.")
    include: Optional[str] = PydanticField(
        default=None, description=(
            "For tool_name='recommend_clothes': which item types she asked for, in her own "
            "words -- 'clothes', 'clothes and heels', 'dress, bag, heels', 'everything'. "
            "Only those get shown. Null means clothes only."))
    item_id: Optional[str] = PydanticField(
        default=None,
        description="Required for show_item_detail/add_item_to_cart/start_virtual_tryon/"
                     "complete_outfit. Must be an id a tool returned this conversation.")
    reason: Optional[Literal[
        "discount", "payment", "refund", "complaint", "stock_issue", "special_request", "other",
    ]] = PydanticField(default=None, description="Required for tool_name='request_staff_assistance'.")
    message: Optional[str] = PydanticField(
        default=None, description="Optional context for tool_name='request_staff_assistance', e.g. what they asked for.")
    skin_depth: Optional[str] = PydanticField(
        default=None, description="Required for tool_name='get_color_palette'. fair/light/medium/tan/deep.")
    undertone: Optional[str] = PydanticField(
        default=None, description="Required for tool_name='get_color_palette'. warm/cool/neutral.")
    query: Optional[str] = PydanticField(
        default=None,
        description="For search_inventory: what she wants in one short phrase (e.g. 'blue oxford "
                    "shirt for office'). Null if she only named a category.")


class AgentTurnOutput(BaseModel):
    """One step of the tool loop (see run_agent_turn). Replaces the old
    ConversationTurnOutput/AgentAction closed-enum design -- see the module
    docstring's "TOOL LOOP" section."""
    response: Optional[str] = PydanticField(default=None, description=(
        "Your natural spoken reply. Null ONLY while waiting on a tool result."))
    conversation_state: ConversationState
    tool_call: Optional[ToolCall] = None


def _build_messages(system_prompt: str, history: list[dict], user_text: str) -> list:
    messages = [SystemMessage(content=system_prompt)]
    for turn in history:
        if turn.get("role") == "user":
            messages.append(HumanMessage(content=turn["content"]))
        elif turn.get("role") == "assistant":
            messages.append(AIMessage(content=turn["content"]))
    messages.append(HumanMessage(content=user_text))
    return messages


_TOOLS_BY_NAME = {t.name: t for t in LOOP_TOOLS}

MAX_TOOL_ITERATIONS = 2  # up to 3 total Groq calls/turn worst case
# Lowered from an initial 3 after live testing: this account's Groq tier caps at
# 8,000 tokens/minute, and the full system prompt (persona + tool catalog) resends
# on every loop iteration -- a 3-4-call turn measurably approached/exceeded that cap
# (a live 413 was hit during testing). 2 leaves real headroom; retune upward only
# after confirming a higher account tier.


def _tool_catalog_prompt_block() -> str:
    """Generated from each promoted tool's own .description (which LangChain's
    @tool decorator derives from its docstring) rather than hand-duplicating
    that text a second time here -- so the prompt can't drift out of sync
    with tools.py as tools are added/changed."""
    lines = ["\n\nTOOLS YOU CAN CALL (set tool_call.tool_name to exactly one of these, "
             "or leave tool_call null if you don't need one this step):"]
    for t in LOOP_TOOLS:
        lines.append(f"- {t.name}: {t.description}")
    lines.append(
        "\nOnly fill in the ToolCall fields that tool actually needs (see its description "
        "above for which arguments it takes) -- leave every other field null. Never invent "
        "a session_id; the app always supplies the real one. At most one tool call per step."
    )
    return "\n".join(lines)


def _build_tool_args(tool_name: str, call: ToolCall, session_id: str) -> dict:
    """Builds this tool's arguments from the ToolCall fields actually relevant
    to tool_name -- never blindly passing every field on ToolCall through."""
    if tool_name == "navigate_to_page":
        args = {"page": call.page}
    elif tool_name == "recommend_clothes":
        args = {"occasion": call.occasion or "", "category": call.category or "",
                "include": call.include or ""}
    elif tool_name == "search_inventory":
        args = {"category": call.category or "", "query": call.query or ""}
    elif tool_name == "complete_outfit":
        args = {"item_id": call.item_id, "occasion": call.occasion or ""}
    elif tool_name in ("show_item_detail", "add_item_to_cart", "start_virtual_tryon", "explain_recommendation"):
        args = {"item_id": call.item_id}
    elif tool_name == "request_staff_assistance":
        args = {"reason": call.reason or "other", "message": call.message or ""}
    elif tool_name == "get_color_palette":
        args = {"skin_depth": call.skin_depth or "", "undertone": call.undertone or ""}
    else:  # trigger_body_scan, get_body_profile -- no model-supplied args beyond session_id
        args = {}

    tool = _TOOLS_BY_NAME[tool_name]
    if "session_id" in tool.args:
        # Never trust an LLM-supplied session_id -- always the real one this turn is running for.
        args["session_id"] = session_id
    return args


def _extract_item_ids(tool_name: str, result_json: str) -> set[str]:
    """Pulls real inventory item ids out of a search_inventory/recommend_clothes
    result so later steps in the SAME turn can validate show_item_detail/
    add_item_to_cart/start_virtual_tryon against ids the customer was actually
    shown -- structural enforcement, not just a prompt instruction (see
    _execute_tool_call). Turn-scoped only: this doesn't reach across turns,
    matching (not regressing) the old design, which had no cross-turn
    structural check either -- conversation history text sent to the model
    never carried raw item ids from a prior turn's tool result either way."""
    if tool_name not in ("search_inventory", "recommend_clothes", "complete_outfit"):
        return set()
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return set()
    items = data.get("results", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return set()
    return {str(item["id"]) for item in items if isinstance(item, dict) and item.get("id")}


def _execute_tool_call(
    session_id: str,
    call: ToolCall,
    shown_item_ids: set,
    executed_calls: dict,
) -> str:
    """
    Validates and executes one tool call from the loop, returning a JSON
    string to feed back to the model as this step's tool result. Never
    raises -- any failure (unknown tool, invalid/fabricated args, a tool
    exception) comes back as a {"error": ...} JSON string instead, so the
    model can see what went wrong and adapt next step, rather than the
    failure being silently swallowed the way the old _execute_action did.
    """
    tool_name = call.tool_name
    tool = _TOOLS_BY_NAME.get(tool_name)
    if not tool:
        return json.dumps({"error": f"unknown tool '{tool_name}'"})

    if tool_name in ("show_item_detail", "add_item_to_cart", "start_virtual_tryon", "complete_outfit", "explain_recommendation"):
        if not call.item_id or call.item_id not in shown_item_ids:
            return json.dumps({
                "error": "no such item_id was shown to the customer this conversation",
                "instruction": "Never invent an item_id -- search_inventory or recommend_clothes "
                                "first to get real ids, or ask the customer which item they mean.",
            })

    args = _build_tool_args(tool_name, call, session_id)

    cache_key = (tool_name, tuple(sorted(args.items())))
    if cache_key in executed_calls:
        return executed_calls[cache_key]

    if tool.args_schema is not None:
        try:
            tool.args_schema.model_validate(args)
        except ValidationError as e:
            result = json.dumps({"error": f"invalid arguments for {tool_name}: {e}"})
            executed_calls[cache_key] = result
            return result

    try:
        raw_result = tool.invoke(args)
    except Exception as e:
        print(f"[conversation] tool '{tool_name}' failed (non-fatal): {e}")
        result = json.dumps({"error": str(e), "tool": tool_name})
        executed_calls[cache_key] = result
        return result

    shown_item_ids |= _extract_item_ids(tool_name, raw_result)
    executed_calls[cache_key] = raw_result
    return raw_result


def _execute_native_tool_call(
    session_id: str,
    tool_name: str,
    args: dict,
    shown_item_ids: set,
    executed_calls: dict,
) -> str:
    """
    Same validation boundary as _execute_tool_call above (item_id
    enforcement, session_id override, args_schema validation, exception
    handling, repeat cache), adapted for graph_native.py's Path B: a native
    bind_tools() tool_call is already a plain {name, args} pair Groq/
    LangChain produced, not this file's own flat ToolCall schema, so there's
    no _build_tool_args translation step needed here. Kept as its own small
    function (deliberately duplicating a few lines from _execute_tool_call)
    rather than refactoring that already-verified function, so Path A's
    tested behavior is never put at risk by Path B's existence -- both
    share _TOOLS_BY_NAME/_extract_item_ids so the actual safety guarantees
    stay identical, which is what makes a head-to-head comparison fair.
    """
    tool = _TOOLS_BY_NAME.get(tool_name)
    if not tool:
        return json.dumps({"error": f"unknown tool '{tool_name}'"})

    if tool_name in ("show_item_detail", "add_item_to_cart", "start_virtual_tryon", "complete_outfit", "explain_recommendation"):
        item_id = args.get("item_id")
        if not item_id or item_id not in shown_item_ids:
            return json.dumps({
                "error": "no such item_id was shown to the customer this conversation",
                "instruction": "Never invent an item_id -- search_inventory or recommend_clothes "
                                "first to get real ids, or ask the customer which item they mean.",
            })

    args = dict(args)
    if "session_id" in tool.args:
        args["session_id"] = session_id  # never trust an LLM-supplied session_id

    cache_key = (tool_name, tuple(sorted(args.items())))
    if cache_key in executed_calls:
        return executed_calls[cache_key]

    if tool.args_schema is not None:
        try:
            tool.args_schema.model_validate(args)
        except ValidationError as e:
            result = json.dumps({"error": f"invalid arguments for {tool_name}: {e}"})
            executed_calls[cache_key] = result
            return result

    try:
        raw_result = tool.invoke(args)
    except Exception as e:
        print(f"[conversation-native] tool '{tool_name}' failed (non-fatal): {e}")
        result = json.dumps({"error": str(e), "tool": tool_name})
        executed_calls[cache_key] = result
        return result

    shown_item_ids |= _extract_item_ids(tool_name, raw_result)
    executed_calls[cache_key] = raw_result
    return raw_result


# Regex signal for "this turn probably needs a tool". Keyword-triggered
# because a lightweight heuristic is much cheaper than another LLM classifier
# call, and the false-positive cost (unnecessary structured JSON turn) is
# small compared to the false-negative cost (customer says "add it to cart"
# and we handle it as chit-chat).
_ACTION_KEYWORDS = re.compile(
    r"\b("
    r"show|find|search|browse|look|see|display|list|display"
    r"|recommend|suggest|pick|choose|find\s+me|help\s+me\s+find"
    r"|add|buy|order|cart|purchase|checkout|reserve"
    r"|try|tryon|try\s+on|virtual"
    r"|navigate|take\s+me|go\s+to|open|switch\s+to"
    r"|scan|body\s+scan"
    r"|staff|help|associate|human|discount|refund|price|payment"
    r"|item|product|dress|shirt|top|bottom|jeans|shoes|bag|watch|shoe|jacket"
    r"|complete|outfit|matching|goes\s+with|pair|accessorize"
    r"|blue|red|black|white|pastel|colour|color|size|budget|under\s+\d"
    r"|for\s+a\s+(wedding|party|office|meeting|date|event|dinner|casual)"
    # Occasion answers on their own ("my sister's wedding", "a party") --
    # these must reach the structured path so the occasion gets extracted
    # into conversation_state; the fast path never saves preferences.
    r"|wedding|marriage|engagement|reception|sangeet|mehendi|haldi|party|birthday"
    r"|office|work|meeting|interview|formal|casual|ethnic|traditional|festival|diwali"
    r"|puja|pooja|eid|date|dinner|travel|trip|vacation|holiday|gym|sports?|college|function"
    r"|clothes|clothing|accessor(?:y|ies)|jewell?ery|heels?|footwear"
    r")\b",
    re.IGNORECASE,
)

# A short reply to something Aria just ASKED ("yes", "sure, go ahead", "no
# thanks") is almost always consent to an offer -- the scan, accessories for
# a liked dress -- and consent has to be able to trigger a tool. The keyword
# regex above can't see that ("yes" names nothing), so it used to go down the
# tool-less fast path: Aria said "pulling up the camera!" and nothing happened.
_SHORT_REPLY_WORDS = 8
_AFFIRMATIVE_RE = re.compile(
    r"\b(yes|yeah|yep|yup|sure|ok|okay|alright|please|go\s+ahead|let'?s\s+do\s+it|do\s+it"
    r"|why\s+not|of\s+course|definitely|absolutely|haan|ha|ji|no|nope|nah|not\s+now)\b",
    re.IGNORECASE,
)


def _cart_context_block(session_id: str) -> str:
    """Look up items the customer has engaged with THIS session (add_to_cart,
    tryon, click) and inject their names/categories/colors into the system
    prompt. Fixes the "Aria asks 'what did you add?' when the app already
    knows" moment: the interactions table has the item_id, we can just
    hydrate and tell her. Fails silently on any DB error -- interaction
    unavailability shouldn't ever break a chat response.
    """
    try:
        from app.db.supabase_client import get_session_interaction_signals, get_supabase
        signals = get_session_interaction_signals(session_id)
        engaged_ids = signals.get("engaged_item_ids") or []
        if not engaged_ids:
            return ""
        rows = (
            get_supabase()
            .table("inventory")
            .select("id,name,category,color,price")
            .in_("id", engaged_ids[-5:])  # last 5 engagements, enough context
            .execute()
            .data or []
        )
        if not rows:
            return ""
        pretty = [f"{r.get('name')} ({r.get('category')}, {r.get('color') or 'no color'})" for r in rows]
        block = (
            "\n\nCART / OUTFIT SO FAR — items the customer has ALREADY interacted with "
            "this session (added to cart, tried on, or opened for detail). You KNOW what "
            "these are -- do NOT ask her to describe them again. Reference them by name "
            "when relevant, and use them as the anchor for outfit compatibility:\n- "
            + "\n- ".join(pretty)
        )
        print(f"[cart-context] injecting for session {session_id[:8]}: {len(rows)} items")
        return block
    except Exception as e:
        print(f"[cart-context] hydration failed (non-fatal): {e}")
        return ""


# How many recently-shown items to keep addressable across turns. Bounded so
# a long browsing session doesn't blow up the prompt -- "the one from
# earlier" almost always means something from the last handful of things
# shown, not something from 40 turns ago.
RECENT_SHOWN_ITEMS_LIMIT = 12


def _last_liked_item(history: list[dict]) -> dict | None:
    """The item the customer most recently liked on screen (heart / Add to
    Outfit), as recorded by the item_liked event in the assistant turn's
    meta (see routers/agent_events.py). The event's trigger text is never
    persisted, so without this her "yes" to "want accessories with it?"
    arrives with no way for the model to know WHICH item's id to use."""
    for turn in reversed(history or []):
        liked = (turn.get("meta") or {}).get("liked_item") if turn.get("role") == "assistant" else None
        if liked and liked.get("id"):
            return liked
    return None


def _liked_item_block(liked: dict | None) -> str:
    if not liked:
        return ""
    return (
        f"\n\nLAST ITEM SHE LIKED ON SCREEN: {liked.get('name') or 'an item'} "
        f"({liked.get('category') or 'item'}) [id: {liked['id']}]. If she says yes to "
        "accessories / completing the look for it, call complete_outfit with this exact id."
    )


def _recent_shown_items_block(session_id: str) -> str:
    """BUG FIX: cross-turn item memory. Every tool call this turn that shows
    items (search_inventory, recommend_clothes, complete_outfit) feeds
    shown_item_ids into the SAME-turn structural validation used by
    show_item_detail/add_item_to_cart/start_virtual_tryon/complete_outfit --
    but that set was rebuilt empty at the start of EVERY turn (see
    run_agent_turn's `shown_item_ids: set = set()`), so "add the one from
    earlier" always failed the id-ownership check on any turn after the one
    that showed it, even though the frontend has been logging `view` and
    `recommend_shown` interaction events the whole time.

    Fix has two halves (both needed):
      1. This function -- injects the recently-shown items' NAMES and REAL
         ids into the prompt so the model can actually resolve "the blue one
         from earlier" to a specific id (it can't guess opaque UUIDs; the
         prompt has to supply them, exactly like tool-result JSON does
         within a single turn).
      2. run_agent_turn seeds its `shown_item_ids` validation set from
         get_session_interaction_signals()'s cross-turn `shown_item_ids`
         BEFORE the loop starts, not just from this turn's own tool calls --
         otherwise the model could name the right id here and still get
         rejected by the same-turn-only check.

    Session-scoped (not cross-session) -- matches how cart-context and every
    other interaction signal already works. Fails silently on any DB error.
    """
    try:
        from app.db.supabase_client import get_session_interaction_signals, get_supabase
        signals = get_session_interaction_signals(session_id)
        shown_ids = signals.get("shown_item_ids") or []
        if not shown_ids:
            return ""
        rows = (
            get_supabase()
            .table("inventory")
            .select("id,name,category,color,price")
            .in_("id", shown_ids[-RECENT_SHOWN_ITEMS_LIMIT:])
            .execute()
            .data or []
        )
        if not rows:
            return ""
        pretty = [
            f"{r.get('name')} ({r.get('category')}, {r.get('color') or 'no color'}) [id: {r['id']}]"
            for r in rows
        ]
        block = (
            "\n\nITEMS SHOWN EARLIER THIS SESSION — the customer has SEEN these (not "
            "necessarily added to cart) via search results or recommendations, possibly "
            "several turns ago. If she refers back to one vaguely (\"the one from earlier\", "
            "\"that blue shirt you showed me\", \"the second option\"), match it to the closest "
            "item below by name/color/category and use the EXACT id shown in brackets for any "
            "tool call that needs an item_id -- do NOT ask her to re-describe something already "
            "listed here, and do NOT invent an id that isn't in this list:\n- "
            + "\n- ".join(pretty)
        )
        return block
    except Exception as e:
        print(f"[shown-items-context] hydration failed (non-fatal): {e}")
        return ""


_JSON_LEAK_RE = re.compile(
    r'["\']?tool_(?:name|call)["\']?\s*:|"arguments"\s*:|^\s*\{\s*"response"'
    # General case: a `{` followed (anywhere in the reply, not just at the
    # very start) by a quoted key and a colon -- confirmed live that the
    # fast path can append a well-formed natural-language sentence with a
    # TRAILING structured-preferences blob, e.g. '...shopping for?\n\n'
    # '{"color_preferences": ["earthy", "neutral"]}', which the old
    # start-anchored checks never saw since the leak wasn't at position 0.
    r'|\{\s*"[A-Za-z_][A-Za-z0-9_]*"\s*:',
    re.IGNORECASE,
)


def _looks_like_json_leak(text: str) -> bool:
    """Detect whether text is (or contains) a raw tool-call/structured-output
    JSON blob rather than pure natural-language reply. Safety net for the fast
    path, which has no tool-execution capability and must never surface this
    shape to the customer -- see stream_agent_turn's bug note for the
    incident this guards against."""
    if not text:
        return False
    stripped = text.lstrip()
    if stripped.startswith("{") and ('"tool_call"' in text or '"tool_name"' in text
                                      or '"conversation_state"' in text):
        return True
    return bool(_JSON_LEAK_RE.search(text))


def _looks_like_action(user_text: str, history: list[dict]) -> bool:
    """Heuristic: does this turn plausibly need a store tool? Chat-only turns
    ("hi", "how are you", "tell me a joke", "what's 5+5") skip the structured
    JSON schema entirely -- plain non-structured Groq calls are ~5x faster
    and don't emit the reasoning chain-of-thought.

    Deliberately biased toward false-positives: an unnecessary structured
    turn is a few extra seconds; a missed tool call ("add to cart" treated
    as chit-chat) is a broken customer moment.
    """
    if not user_text or not user_text.strip():
        return False
    if _ACTION_KEYWORDS.search(user_text):
        return True
    # Short yes/no answer to a question Aria just asked -> she may need to act
    # on it (start the scan, pull accessories), so give her the tool path.
    last_assistant = next(
        (t.get("content") or "" for t in reversed(history or []) if t.get("role") == "assistant"),
        "",
    )
    if (isinstance(last_assistant, str) and "?" in last_assistant
            and len(user_text.split()) <= _SHORT_REPLY_WORDS
            and _AFFIRMATIVE_RE.search(user_text)):
        return True
    return False


def _build_fast_prompt(role: str, prior_preferences: dict, session_id: str, digest: str) -> str:
    """System prompt for the fast (non-tool-capable) path -- deliberately
    NEVER includes _tool_catalog_prompt_block(). See the bug note at both
    call sites (run_agent_turn and stream_agent_turn) for why: teaching this
    path the tool-call JSON shape caused it to leak that JSON as plain text
    whenever the model correctly judged a tool was needed but had no way to
    actually invoke one."""
    prompt = ADMIN_PROMPT if role == "admin" else CUSTOMER_PROMPT
    prompt += (
        "\n\nMODE NOTE: You are in a quick-response turn and cannot call any "
        "tool or take any screen action right now -- respond in plain natural "
        "language only. Never output JSON, a tool name, or anything "
        "resembling {\"tool_call\": ...} -- if you genuinely need to look "
        "something up or perform an action, just tell the customer naturally "
        "that you're on it (e.g. \"Let me pull that up for you\") without "
        "literally describing tool internals."
    )
    if prior_preferences:
        known_fields = [k for k, v in prior_preferences.items()
                        if v is not None and v != "" and v != []]
        prompt += (
            "\n\nWHAT YOU ALREADY KNOW ABOUT THIS CUSTOMER:\n"
            + json.dumps(prior_preferences)
        )
        if known_fields:
            prompt += "\n\nAlready answered (do NOT re-ask): " + ", ".join(known_fields) + "."
    prompt += _cart_context_block(session_id)
    if digest:
        prompt += "\n\n" + digest
    return prompt


def _fast_chat_turn(
    system_prompt: str,
    windowed_history: list[dict],
    user_text: str,
    prior_preferences: dict,
) -> dict:
    """Fast path for chat-only turns: plain non-structured Groq call, no
    JSON schema, no tool loop. Returns the same run_agent_turn shape so
    chat.py doesn't need to know which path ran.

    Returns None to signal "fall through to the structured path" -- used
    both on LLM failure and when the reply looks like a leaked tool-call
    JSON blob (see _looks_like_json_leak)."""
    fast_llm = get_agent_llm()  # no with_structured_output()
    messages = _build_messages(system_prompt, windowed_history, user_text)
    try:
        result = fast_llm.invoke(messages)
        reply = (result.content if hasattr(result, "content") else str(result)).strip()
    except Exception as e:
        print(f"[fast-chat] LLM failed, falling back to structured path: {e}")
        return None  # caller falls through to structured path

    if _looks_like_json_leak(reply):
        print("[fast-chat] detected JSON/tool-call leak, falling back to structured path")
        return None

    return {"reply": reply or "Sorry, could you say that again?", "actions": [], "preferences": prior_preferences}


def stream_agent_turn(
    session_id: str,
    user_text: str,
    history: list[dict],
    role: str = "customer",
    prior_preferences: dict | None = None,
):
    """Streaming variant of run_agent_turn for chat-only turns.

    Yields (chunk_type, payload) tuples:
      ("delta", text_chunk) -- next token(s) of the reply
      ("done", {"reply": full_reply, "actions": [], "preferences": {...}}) -- terminator
      ("fallback", full_result_dict) -- this turn needed the structured path,
                                        result is the final non-streamed answer

    The caller (chat router) turns these into SSE events. Structured/tool
    turns can't stream (Groq's json_schema mode returns full JSON at once),
    so we emit a single 'fallback' event with the completed result and let
    the client render it as normal.
    """
    prior_preferences = prior_preferences or {}
    if not user_text or not user_text.strip():
        yield "done", {"reply": "Sorry, I didn't catch that -- could you say it again?",
                       "actions": [], "preferences": prior_preferences}
        return

    digest, windowed_history = window_history(history)

    # Structured path can't stream -- fall back to non-streaming and emit
    # the full result as a single 'fallback' event. Checked BEFORE building
    # the fast-path prompt because the two paths use deliberately different
    # system prompts (see bug note below).
    if _looks_like_action(user_text, windowed_history):
        result = run_agent_turn(session_id, user_text, history, role=role,
                                prior_preferences=prior_preferences)
        yield "fallback", result
        return

    # BUG FIX (2026-09): the fast path used to reuse the SAME system prompt
    # as the structured path, including _tool_catalog_prompt_block() -- the
    # block that teaches the model the {"tool_name": ..., "arguments": {...}}
    # JSON shape. But the fast path calls a plain, non-structured LLM with no
    # tool-execution capability at all. When _looks_like_action's heuristic
    # missed a turn that genuinely needed a tool (e.g. "sleek metallic" as
    # the answer to "which clutch style?"), the model correctly decided it
    # needed search_inventory -- and the ONLY way it had to express that was
    # to write the tool-call JSON out as plain text, which streamed straight
    # to the customer as a raw JSON blob. Fix: the fast-path prompt never
    # mentions tools or their JSON shape at all, so the model has no schema
    # to leak -- worst case it answers in prose without actually running the
    # tool, which is a much smaller failure than a JSON leak. Layer 2 below
    # (the JSON-leak sniff) is the safety net for anything that slips through.
    fast_system_prompt = _build_fast_prompt(role, prior_preferences, session_id, digest)

    fast_llm = get_agent_llm()
    messages = _build_messages(fast_system_prompt, windowed_history, user_text)
    accumulated = []
    leaked = False
    try:
        for chunk in fast_llm.stream(messages):
            text = chunk.content if hasattr(chunk, "content") else str(chunk)
            if not text:
                continue
            accumulated.append(text)
            # Safety net (layer 2): if the model starts emitting something
            # that looks like a tool-call JSON blob despite the prompt fix
            # above, stop streaming it to the customer and fall back to the
            # real structured/tool path instead. Checked cheaply on every
            # chunk since accumulated text is short until this fires.
            so_far = "".join(accumulated)
            if _looks_like_json_leak(so_far):
                leaked = True
                break
            yield "delta", text
    except Exception as e:
        print(f"[stream-fast] LLM stream failed, falling back: {e}")
        yield "fallback", {"reply": "Sorry, hit a snag -- try again?", "actions": [],
                           "preferences": prior_preferences}
        return

    if leaked:
        print("[stream-fast] detected JSON/tool-call leak mid-stream, re-routing to structured path")
        result = run_agent_turn(session_id, user_text, history, role=role,
                                prior_preferences=prior_preferences)
        yield "fallback", result
        return

    full_reply = "".join(accumulated).strip() or "Sorry, could you say that again?"
    yield "done", {"reply": full_reply, "actions": [], "preferences": prior_preferences}


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

    Returns: {"reply": str, "actions": list[dict], "preferences": dict}
    Signature and return shape are unchanged -- chat.py and agent_events.py
    call this exactly the same way. Internally this now runs a bounded loop
    (see the module docstring's "TOOL LOOP" section) instead of one call: a
    plain chat turn still costs exactly one Groq call (the loop breaks
    immediately when the model leaves tool_call null), and a turn that
    genuinely needs one or more tools costs one call per step, up to
    MAX_TOOL_ITERATIONS.
    """
    prior_preferences = prior_preferences or {}

    if not user_text or not user_text.strip():
        return {
            "reply": "Sorry, I didn't quite catch that -- could you say it again?",
            "actions": [],
            "preferences": prior_preferences,
        }

    digest, windowed_history = window_history(history)

    # FAST PATH: if this turn doesn't look like it needs a tool (chit-chat,
    # general knowledge, math, jokes, emotional support, follow-up questions),
    # skip the structured JSON schema and use a plain non-structured LLM call.
    # That path is ~5x faster because it avoids constrained decoding AND the
    # reasoning chain-of-thought that json_schema mode triggers on gpt-oss-120b.
    #
    # BUG FIX (2026-09): this used to reuse the tool-catalog-bearing prompt
    # built below for the structured path. The fast path has no tool-
    # execution capability, so when the heuristic missed a turn that
    # genuinely needed a tool, the model's only way to express "I need
    # search_inventory" was to write the tool-call JSON out as plain text --
    # which then streamed/returned straight to the customer as a raw JSON
    # blob (see the incident this fixed: "sleek metallic" -> literal
    # {"tool_call": {"tool_name": "search_inventory", ...}} in the chat).
    # Fix: the fast path gets its OWN prompt that never mentions tools or
    # their JSON shape at all -- see _build_fast_prompt.
    if not _looks_like_action(user_text, windowed_history):
        fast_prompt = _build_fast_prompt(role, prior_preferences, session_id, digest)
        fast_result = _fast_chat_turn(fast_prompt, windowed_history, user_text, prior_preferences)
        if fast_result is not None:
            return fast_result
        # fell through -- structured path handles it below

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
    system_prompt += _tool_catalog_prompt_block()
    system_prompt += _cart_context_block(session_id)
    system_prompt += _recent_shown_items_block(session_id)
    liked_item = _last_liked_item(history)
    system_prompt += _liked_item_block(liked_item)
    if digest:
        system_prompt += "\n\n" + digest

    messages = _build_messages(system_prompt, windowed_history, user_text)

    start_action_turn()  # ONCE per turn -- every tool call this turn queues into the same list
    turn_delta: dict = {}
    final_reply = None
    # BUG FIX (cross-turn item memory): seed with items shown in EARLIER
    # turns of this session (frontend already logs `view`/`recommend_shown`
    # interaction events for everything shown -- see get_session_interaction_
    # signals), not just an empty set. Without this, "add the one from
    # earlier" always failed item-id validation on any turn after the one
    # that originally showed it, even when _recent_shown_items_block (above)
    # correctly told the model the real id to use -- the model could name it
    # right and still get rejected by this same-turn-only check.
    shown_item_ids: set = set()
    try:
        from app.db.supabase_client import get_session_interaction_signals
        shown_item_ids |= set(get_session_interaction_signals(session_id).get("shown_item_ids", []))
    except Exception as e:
        print(f"[cross-turn-recall] failed to seed shown_item_ids (non-fatal): {e}")
    if liked_item:
        shown_item_ids.add(str(liked_item["id"]))
    executed_calls: dict = {}
    llm_configured = True
    llm_failed = False
    last_call_signature = None
    nudged = False

    try:
        structured_llm = get_agent_llm().with_structured_output(AgentTurnOutput)
        for step in range(MAX_TOOL_ITERATIONS + 1):
            result = invoke_with_retry(structured_llm, messages)
            if result.response:
                final_reply = result.response.strip()
            turn_delta = merge_preferences(turn_delta, result.conversation_state.model_dump(exclude_none=True))

            call = result.tool_call
            if not call or not call.tool_name or step == MAX_TOOL_ITERATIONS:
                break

            call_args = {k: v for k, v in call.model_dump(exclude_none=True).items() if k != "tool_name"}
            call_signature = (call.tool_name, tuple(sorted(call_args.items())))

            # Live testing surfaced a real failure mode: the model can request the
            # EXACT same tool+args repeatedly without ever producing a final answer,
            # even once it already has the result -- observed 4/4 identical
            # search_inventory calls in a row on gpt-oss-120b. One explicit
            # correction beats silently feeding it the same cached result again
            # (which taught it nothing) or burning the whole iteration budget on
            # calls that can never produce new information.
            if call_signature == last_call_signature:
                if nudged:
                    break
                nudged = True
                messages.append(SystemMessage(content=(
                    "[SYSTEM] You already called this exact tool with these exact arguments -- "
                    "its result is already above in this conversation. Calling it again will not "
                    "give you anything new. Answer the customer now using what you already have "
                    "(leave tool_call null), or call a genuinely DIFFERENT tool if you actually "
                    "need something else."
                )))
                continue
            last_call_signature = call_signature

            tool_result_json = _execute_tool_call(session_id, call, shown_item_ids, executed_calls)
            # AIMessage(tool_calls=...) + ToolMessage is the standard tool-round-trip
            # shape this model was actually trained on -- deliberately NOT a bare
            # SystemMessage injection (an earlier version of this loop used that and
            # the model didn't reliably recognize it as "your request was already
            # answered," which is the direct cause of the repeat-call failure above).
            tool_call_id = f"call_{step}"
            messages.append(AIMessage(
                content=result.response or "",
                tool_calls=[{"name": call.tool_name, "args": call_args, "id": tool_call_id}],
            ))
            messages.append(ToolMessage(content=tool_result_json, tool_call_id=tool_call_id))

        if not final_reply:
            final_reply = "Sorry, I got a bit tongue-tied there -- could you say that again?"
    except LLMConfigurationError as e:
        print(f"[conversation] {e}")
        final_reply = "Sorry, I'm having trouble connecting right now -- mind trying again in a moment?"
        llm_configured = False
    except Exception as e:
        print(f"[conversation] LLM call failed: {e}")
        final_reply = "Sorry, I hit a little snag -- mind trying that again?"
        llm_failed = True

    updated_preferences = merge_preferences(prior_preferences, turn_delta)
    actions = get_queued_actions() if llm_configured else []

    return {
        "reply": final_reply, "actions": actions, "preferences": updated_preferences,
        # True when `reply` is an apology for a failed/unconfigured LLM call
        # rather than something Aria actually said -- proactive events use
        # this to stay silent instead of apologising to a customer who
        # never asked her anything (see routers/agent_events.py).
        "llm_failed": llm_failed or not llm_configured,
    }
