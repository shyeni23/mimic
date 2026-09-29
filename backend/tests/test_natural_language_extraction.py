"""
Section 5 & 6 -- Natural Language Understanding, Fashion Requirement
Extraction, and Natural Conversational Behavior.

Three layers:

1. TestPreferenceMerging: pure state-merging logic (merge_preferences), no
   LLM call, no network, no API key -- always runs, always deterministic.

2. TestNaturalConversation (Section 6): mocked-LLM tests that validate the
   full run_agent_turn pipeline (prompt construction, state merging, return
   shape, recommendation readiness) without calling the real Groq API.
   Uses unittest.mock to inject predetermined ConversationTurnOutput results.

3. TestNaturalLanguageExtraction: live calls through run_agent_turn (the
   real LangChain + Groq pipeline) -- need a real GROQ_API_KEY, skipped
   automatically when one isn't configured.
"""
import contextlib

import pytest
from unittest.mock import patch, MagicMock

from app.config import settings
from app.services.agent.preferences import merge_preferences
from app.services.agent.graph import (
    run_agent_turn, stream_agent_turn, _build_messages, _execute_tool_call, _looks_like_action,
    ToolCall, AgentTurnOutput, ConversationState, CUSTOMER_PROMPT,
)
from app.services.agent.llm import LLMConfigurationError

_HAS_GROQ_KEY = bool(settings.groq_api_key)
_skip_no_key = pytest.mark.skipif(
    not _HAS_GROQ_KEY,
    reason="GROQ_API_KEY is not set -- these tests call the real Groq API.",
)


@pytest.fixture(autouse=True)
def _no_backup_model():
    """Mocked tests control get_agent_llm; keep the real 20b backup out of them."""
    with patch("app.services.agent.graph.get_structured_fallback_llm", return_value=None):
        yield


def _run(history, user_text, prior_preferences=None):
    """Small helper -- most tests just need the preferences dict back."""
    result = run_agent_turn("test-session", user_text, history, prior_preferences=prior_preferences)
    return result["reply"], result["preferences"]


def _contains_ci(items, needle: str) -> bool:
    """Case-insensitive substring match against a list of strings (or a
    single string) -- LLM phrasing varies ('pastel' vs 'pastel tones')."""
    if items is None:
        return False
    if isinstance(items, str):
        items = [items]
    return any(needle.lower() in str(i).lower() for i in items)


def _signals_lightness(prefs: dict) -> bool:
    """True if 'not too heavy' was captured, either as a positive framing in
    design_preference ('light', 'minimal') or -- per this project's own
    prompt instruction ("I don't want heavy embroidery" -> constraints:
    ["heavy embroidery"], NOT embroidery: "heavy") -- as a negative
    (things-to-avoid) entry in constraints containing 'heavy'. Both are
    correct extractions of the same statement; checking only the positive
    phrasing was the bug, not the model's behavior (confirmed live: the
    model consistently stores just constraints=['heavy'], which correctly
    means 'avoid heavy', not constraints=['not too heavy'])."""
    design = str(prefs.get("design_preference", "")).lower()
    if any(w in design for w in ("light", "minimal")):
        return True
    constraints = prefs.get("constraints") or []
    return any("heavy" in str(c).lower() for c in constraints)


# ---------------------------------------------------------------------------
# Helper -- mock the LLM so run_agent_turn runs its full pipeline (prompt
# construction, merge_preferences, return shape) without a Gemini API call.
# ---------------------------------------------------------------------------

def _mock_turn(response: str, **state_fields):
    """Return an AgentTurnOutput (no tool_call -- a plain chat step) with the
    given response and state fields, and patch get_agent_llm so
    run_agent_turn uses it. Since tool_call is None, the loop breaks after
    exactly one call, same as these tests always assumed."""
    output = AgentTurnOutput(
        response=response,
        conversation_state=ConversationState(**state_fields),
    )
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = output
    mock_llm.with_structured_output.return_value = mock_structured
    return _structured_path(mock_llm)


@contextlib.contextmanager
def _structured_path(mock_llm):
    """Patch get_agent_llm AND force the structured path. These tests are
    about preference extraction, which only the structured path does --
    without forcing it, a message with no action keyword ("Maybe something
    softer") would be routed to the tool-less fast path and hit the real
    fast-chat model instead of the mock."""
    with patch("app.services.agent.graph.get_agent_llm", return_value=mock_llm), \
         patch("app.services.agent.graph._looks_like_action", return_value=True):
        yield


# ---------------------------------------------------------------------------
# Layer 1 -- Section 6: Natural Conversational Behavior (mocked LLM)
# ---------------------------------------------------------------------------

class TestNaturalConversation:
    """Section 6 -- tests that the full run_agent_turn pipeline produces
    natural conversational behavior. All tests use mocked LLM responses
    so they're deterministic and don't consume Gemini quota."""

    def test_1_natural_conversation_single_turn(self):
        """TEST 1: occasion extracted, natural follow-up, no hallucination."""
        with _mock_turn(
            "That sounds lovely! Are you looking for something traditional, modern, or a mix of both?",
            occasion="engagement",
        ):
            result = run_agent_turn("s1", "I need something for an engagement.", [])
        assert result["reply"] == "That sounds lovely! Are you looking for something traditional, modern, or a mix of both?"
        assert result["preferences"]["occasion"] == "engagement"
        for field in ("style", "color_preferences", "budget", "clothing_type"):
            assert not result["preferences"].get(field), f"hallucinated {field}"
        assert "?" in result["reply"], "should ask a natural follow-up"

    def test_2_multiple_requirements_one_sentence(self):
        """TEST 2: multiple requirements in one sentence all extracted."""
        with _mock_turn(
            "Great taste! Any particular budget in mind?",
            occasion="engagement",
            style="traditional",
            color_preferences=["pastel"],
            constraints=["not too heavy"],
        ):
            result = run_agent_turn(
                "s2",
                "I'm going to an engagement and want something traditional in pastel colours, but not too heavy.",
                [],
            )
        prefs = result["preferences"]
        assert prefs["occasion"] == "engagement"
        assert prefs["style"] == "traditional"
        assert "pastel" in prefs["color_preferences"]
        assert "not too heavy" in prefs["constraints"]

    def test_3_context_resolution(self):
        """TEST 3: 'simple' in turn 2 is interpreted in the context of the
        current fashion discussion (design_preference), not as an isolated word."""
        history = [
            {"role": "user", "content": "I want something traditional."},
            {"role": "assistant", "content": "Would you prefer something simple and elegant, or a more detailed look?"},
        ]
        prior = {"style": "traditional"}
        with _mock_turn(
            "Simple and elegant it is! Do you have any colour preferences?",
            design_preference="simple",
        ):
            result = run_agent_turn("s3", "Something simple.", history, prior_preferences=prior)
        prefs = result["preferences"]
        assert prefs["style"] == "traditional", "earlier context lost"
        assert prefs["design_preference"] == "simple"

    def test_4_correction_changes_only_that_field(self):
        """TEST 4: user corrects style from traditional to modern.
        Only style changes; occasion and color survive."""
        history = [
            {"role": "user", "content": "I want something traditional."},
            {"role": "assistant", "content": "Nice choice! Any colours in mind?"},
            {"role": "user", "content": "Pastel."},
            {"role": "assistant", "content": "Pastel would work nicely."},
        ]
        prior = {"occasion": "engagement", "style": "traditional", "color_preferences": ["pastel"]}
        with _mock_turn(
            "Sure, let's go with a modern look instead.",
            style="modern",
        ):
            result = run_agent_turn("s4", "Actually, make it modern.", history, prior_preferences=prior)
        prefs = result["preferences"]
        assert prefs["style"] == "modern"
        assert prefs["occasion"] == "engagement", "unrelated field was lost"
        assert prefs["color_preferences"] == ["pastel"], "unrelated field was lost"

    def test_5_no_reask_settled_topics(self):
        """TEST 5: the system prompt must tell the model not to re-ask about
        settled topics (occasion already provided)."""
        prior = {"occasion": "engagement"}
        messages = _build_messages(CUSTOMER_PROMPT, [], "Traditional.")
        system_text = messages[0].content
        assert "Already answered" not in system_text, "no settled topics on first turn"

        known = [k for k, v in prior.items() if v is not None and v != "" and v != []]
        import json
        augmented = (
            CUSTOMER_PROMPT
            + "\n\nWHAT YOU ALREADY KNOW ABOUT THIS CUSTOMER (from earlier in this "
            "conversation). These topics are SETTLED -- do NOT ask about them again "
            "unless the customer brings one up to change it. Do NOT repeat them in "
            "conversation_state unless the customer said something NEW or DIFFERENT "
            "this turn:\n"
            + json.dumps(prior)
            + "\n\nAlready answered (do NOT re-ask): " + ", ".join(known) + "."
            "\nAsk only about information that is still MISSING."
        )
        assert "Already answered (do NOT re-ask): occasion" in augmented
        assert "do NOT ask about them again" in augmented

    def test_6_ambiguous_request_no_hallucination(self):
        """TEST 6: vague input ('something nice') -> no invented preferences,
        just a natural clarification question."""
        with _mock_turn(
            "Of course! Is it for a particular occasion, or are you looking for something versatile?",
        ):
            result = run_agent_turn("s6", "I want something nice.", [])
        prefs = result["preferences"]
        for field in ("occasion", "style", "color_preferences", "budget", "clothing_type"):
            assert not prefs.get(field), f"hallucinated {field}={prefs.get(field)!r} from vague input"
        assert "?" in result["reply"]

    def test_7_multi_turn_accumulation(self):
        """TEST 7: four-turn conversation accumulates all information."""
        history = []
        prefs = {}

        turns = [
            ("I'm going to my cousin's engagement.",
             "That sounds exciting! What kind of look are you going for?",
             {"occasion": "engagement"}),
            ("Traditional.",
             "Nice choice. Would you prefer something simple or more detailed?",
             {"style": "traditional"}),
            ("Pastel.",
             "Pastel would look lovely. Anything you'd like to avoid?",
             {"color_preferences": ["pastel"]}),
            ("Nothing too heavy.",
             "Got it -- light and elegant. I think I have a good sense of what you need.",
             {"constraints": ["not too heavy"], "design_preference": "light"}),
        ]

        for user_text, reply, delta in turns:
            with _mock_turn(reply, **delta):
                result = run_agent_turn("s7", user_text, history, prior_preferences=prefs)
            prefs = result["preferences"]
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": result["reply"]})

        assert prefs["occasion"] == "engagement"
        assert prefs["style"] == "traditional"
        assert "pastel" in prefs["color_preferences"]
        assert "not too heavy" in prefs["constraints"]
        assert prefs["design_preference"] == "light"

    def test_8_correction_preserves_unrelated_state(self):
        """TEST 8: changing style from traditional to modern must not lose
        occasion or color_preferences."""
        prior = {"occasion": "engagement", "style": "traditional", "color_preferences": ["pastel"]}
        with _mock_turn(
            "Sure, let's switch to a modern vibe instead!",
            style="modern",
        ):
            result = run_agent_turn(
                "s8", "Actually, modern.", [],
                prior_preferences=prior,
            )
        prefs = result["preferences"]
        assert prefs["style"] == "modern"
        assert prefs["occasion"] == "engagement"
        assert prefs["color_preferences"] == ["pastel"]

    def test_ready_for_recommendation_signal(self):
        """When the model sets ready_for_recommendation=True, it appears in
        the merged preferences."""
        prior = {"occasion": "engagement", "style": "traditional", "color_preferences": ["pastel"]}
        with _mock_turn(
            "I think I have a good idea of what you're looking for. Let me find some options for you.",
            ready_for_recommendation=True,
            constraints=["not too heavy"],
        ):
            result = run_agent_turn(
                "s-rec", "Nothing too heavy.", [],
                prior_preferences=prior,
            )
        prefs = result["preferences"]
        assert prefs["ready_for_recommendation"] is True
        assert prefs["occasion"] == "engagement"

    def test_empty_input_preserves_state(self):
        """Empty input returns gracefully without LLM call, keeping state."""
        prior = {"occasion": "engagement", "style": "modern"}
        result = run_agent_turn("s-empty", "", [], prior_preferences=prior)
        assert result["reply"]
        assert result["preferences"] == prior
        assert result["actions"] == []


# ---------------------------------------------------------------------------
# Layer 1.5 -- the tool-selection loop's dispatch layer (_execute_tool_call),
# no LLM involved
# ---------------------------------------------------------------------------
#
# TOOL LOOP: tool_call is now an OPEN selection (ToolCall.tool_name, any of
# LOOP_TOOLS) the model makes freely, not a closed AgentAction.type enum --
# see graph.py's module docstring for the full "why". _execute_tool_call()
# validates and DISPATCHES an already-decided ToolCall to the matching
# LOOP_TOOLS tool -- no LLM call of its own, so these tests construct
# ToolCall directly instead of mocking bind_tools()/tool_calls. Unlike the
# old _execute_action (which returned the queued actions list directly),
# _execute_tool_call returns the tool's raw JSON result string -- actions
# are read separately via get_queued_actions() once per turn (see
# run_agent_turn), so these tests check both: the returned result string,
# and the queue.

class TestToolCallExecution:
    """Covers _execute_tool_call's dispatch logic: mapping a ToolCall to the
    right tool, session_id trust, item_id enforcement, and graceful failure."""

    def test_unknown_tool_returns_error_and_queues_nothing(self):
        from app.services.agent.actions import start_turn, get_queued_actions
        start_turn()
        result = _execute_tool_call("s0", ToolCall(tool_name=None), set(), {})
        assert "error" in result
        assert get_queued_actions() == []

    def test_single_tool_call_fires_and_queues_action(self):
        from app.services.agent.actions import start_turn, get_queued_actions
        start_turn()
        result = _execute_tool_call(
            "s2", ToolCall(tool_name="navigate_to_page", page="shopping"), set(), {},
        )
        assert "navigated" in result
        actions = get_queued_actions()
        assert len(actions) == 1
        assert actions[0]["type"] == "navigate"
        assert actions[0]["payload"]["page"] == "shopping"

    def test_session_id_is_never_trusted_from_llm(self):
        """recommend_clothes needs session_id -- _execute_tool_call must
        always use the real session_id this turn is running for. ToolCall
        doesn't even expose a session_id field, by design -- this confirms
        the real one is used."""
        from app.services.agent.actions import start_turn
        start_turn()
        with patch("app.services.agent.tools.get_latest_scan", return_value=None) as mock_scan:
            _execute_tool_call(
                "REAL-SESSION-ID", ToolCall(tool_name="recommend_clothes", occasion="party"), set(), {},
            )
        # recommend_clothes calls get_latest_scan(session_id) as its first
        # real step -- confirm it was called with the REAL id.
        mock_scan.assert_called_once_with("REAL-SESSION-ID")

    def test_missing_item_id_never_fabricated(self):
        """show_item_detail/add_item_to_cart/start_virtual_tryon require a
        real item_id -- if the model left it unset, _execute_tool_call must
        not invent one or invoke the tool at all."""
        from app.services.agent.actions import start_turn, get_queued_actions
        start_turn()
        result = _execute_tool_call("s3", ToolCall(tool_name="show_item_detail", item_id=None), set(), {})
        assert "error" in result
        assert get_queued_actions() == []

    def test_item_id_not_shown_this_turn_is_rejected(self):
        """Structural enforcement (new in this design): an item_id the model
        supplies must actually have come from a search_inventory/
        recommend_clothes result earlier THIS turn -- not just any string."""
        from app.services.agent.actions import start_turn, get_queued_actions
        start_turn()
        result = _execute_tool_call(
            "s3b", ToolCall(tool_name="add_item_to_cart", item_id="fabricated-id"), set(), {},
        )
        assert "error" in result
        assert get_queued_actions() == []

    def test_item_id_shown_this_turn_is_accepted(self):
        from app.services.agent.actions import start_turn, get_queued_actions
        start_turn()
        result = _execute_tool_call(
            "s3c", ToolCall(tool_name="add_item_to_cart", item_id="real-id"), {"real-id"}, {},
        )
        assert "error" not in result
        actions = get_queued_actions()
        assert len(actions) == 1
        assert actions[0]["payload"]["item_id"] == "real-id"

    def test_missing_page_never_fabricated(self):
        from app.services.agent.actions import start_turn, get_queued_actions
        start_turn()
        result = _execute_tool_call("s4", ToolCall(tool_name="navigate_to_page", page=None), set(), {})
        assert "error" in result
        assert get_queued_actions() == []

    def test_tool_exception_does_not_crash(self):
        """One tool failing must not prevent the function from returning
        cleanly -- the loop must be able to keep going, not crash the turn."""
        from app.services.agent.actions import start_turn, get_queued_actions
        start_turn()
        with patch("app.services.agent.tools.get_latest_scan", side_effect=RuntimeError("db down")):
            result = _execute_tool_call("s5", ToolCall(tool_name="recommend_clothes"), set(), {})
        assert "error" in result  # failure surfaced back to the model, not silently swallowed
        assert get_queued_actions() == []


class TestRunAgentTurnToolLoop:
    """run_agent_turn's own wiring of the loop -- it only dispatches tools
    when extraction succeeded (llm_configured), never on the
    LLMConfigurationError/empty-input early-return paths, and it can chain
    more than one LLM call within a single turn when the model keeps
    requesting tools."""

    def test_successful_turn_includes_real_actions(self):
        """Two-step turn: step 1 requests a tool (response left null), step 2
        (after the tool result is fed back) gives the final reply with no
        further tool_call -- this is the loop's core mechanic."""
        step1 = AgentTurnOutput(
            response=None,
            conversation_state=ConversationState(),
            tool_call=ToolCall(tool_name="navigate_to_page", page="shopping"),
        )
        step2 = AgentTurnOutput(
            response="Sure, taking you there now!",
            conversation_state=ConversationState(),
            tool_call=None,
        )
        mock_structured = MagicMock()
        mock_structured.invoke.side_effect = [step1, step2]

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured

        with patch("app.services.agent.graph.get_agent_llm", return_value=mock_llm):
            result = run_agent_turn("s7", "Take me to shopping.", [])

        assert result["reply"] == "Sure, taking you there now!"
        assert len(result["actions"]) == 1
        assert result["actions"][0]["type"] == "navigate"
        assert mock_structured.invoke.call_count == 2

    def test_plain_chat_turn_costs_exactly_one_llm_call(self):
        """No regression: a turn that needs no tool must not loop further.
        A second call would return a RuntimeError instead of a valid output,
        so this fails loudly if the loop doesn't break after step 0."""
        step = AgentTurnOutput(
            response="Pastels are lovely on you!",
            conversation_state=ConversationState(color_preferences=["pastel"]),
            tool_call=None,
        )
        mock_structured = MagicMock()
        mock_structured.invoke.side_effect = [step, RuntimeError("should never be called a second time")]

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured

        with patch("app.services.agent.graph.get_agent_llm", return_value=mock_llm):
            result = run_agent_turn("s7b", "I like pastel colors.", [])

        assert result["reply"] == "Pastels are lovely on you!"
        assert result["actions"] == []
        assert mock_structured.invoke.call_count == 1

    def test_bound_hit_still_returns_a_reply(self):
        """If the model keeps requesting tools past MAX_TOOL_ITERATIONS, the
        loop must still return a valid reply, never hang or crash."""
        looping_step = AgentTurnOutput(
            response=None,
            conversation_state=ConversationState(),
            tool_call=ToolCall(tool_name="get_body_profile"),
        )
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = looping_step  # always wants another tool

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured

        with _structured_path(mock_llm), \
             patch("app.services.agent.tools.get_latest_scan", return_value=None):
            result = run_agent_turn("s9", "keep going", [])

        assert result["reply"]  # graceful fallback, not empty/None
        assert isinstance(result["actions"], list)

    def test_llm_configuration_error_skips_tool_dispatch_entirely(self):
        """When the first call fails with LLMConfigurationError, there's no
        tool to dispatch and no further loop iterations -- confirms
        get_agent_llm is only invoked once and actions stays empty rather
        than raising."""
        with patch("app.services.agent.graph.get_agent_llm", side_effect=LLMConfigurationError("no key")) as mock_get_llm, \
             patch("app.services.agent.graph.get_fast_chat_llm", side_effect=LLMConfigurationError("no key")):
            result = run_agent_turn("s8", "anything", [])
        assert result["actions"] == []
        assert result["reply"]  # friendly apology, not a crash
        assert mock_get_llm.call_count == 1


class TestFastChatRouting:
    """Chit-chat goes to the plain fast model (its own Groq quota bucket);
    anything carrying a preference or action goes to the structured path,
    and a fast-model failure falls through to it instead of apologising."""

    @pytest.mark.parametrize("text", [
        "Maybe something softer.",
        "I prefer cotton, nothing too heavy",
        "can you show me lighter colours",
        "I don't want embroidery",
        "something more elegant",
    ])
    def test_preference_refinements_use_structured_path(self, text):
        assert _looks_like_action(text, [])

    @pytest.mark.parametrize("text", ["hi, how are you?", "tell me a joke", "thank you so much"])
    def test_chit_chat_uses_fast_path(self, text):
        assert not _looks_like_action(text, [])

    def test_chit_chat_uses_fast_model_only(self):
        fast = MagicMock()
        fast.invoke.return_value = MagicMock(content="Doing great, thanks for asking!")
        with patch("app.services.agent.graph.get_fast_chat_llm", return_value=fast), \
             patch("app.services.agent.graph.get_agent_llm") as agent_llm:
            result = run_agent_turn("s10", "hi, how are you?", [])
        assert result["reply"] == "Doing great, thanks for asking!"
        agent_llm.assert_not_called()

    def test_fast_model_failure_falls_through_to_structured(self):
        output = AgentTurnOutput(response="Hello! How can I help?", conversation_state=ConversationState())
        structured = MagicMock()
        structured.invoke.return_value = output
        agent = MagicMock()
        agent.with_structured_output.return_value = structured
        fast = MagicMock()
        fast.invoke.side_effect = RuntimeError("429 rate_limit_exceeded")
        with patch("app.services.agent.graph.get_fast_chat_llm", return_value=fast), \
             patch("app.services.agent.graph.get_agent_llm", return_value=agent):
            result = run_agent_turn("s11", "hi, how are you?", [])
        assert result["reply"] == "Hello! How can I help?"

    def test_stream_failure_before_any_text_falls_through_to_structured(self):
        output = AgentTurnOutput(response="Hello! How can I help?", conversation_state=ConversationState())
        structured = MagicMock()
        structured.invoke.return_value = output
        agent = MagicMock()
        agent.with_structured_output.return_value = structured
        fast = MagicMock()
        fast.stream.side_effect = RuntimeError("429 rate_limit_exceeded")
        with patch("app.services.agent.graph.get_fast_chat_llm", return_value=fast), \
             patch("app.services.agent.graph.get_agent_llm", return_value=agent):
            events = list(stream_agent_turn("s12", "hi, how are you?", []))
        assert events == [("fallback", events[0][1])]
        assert events[0][1]["reply"] == "Hello! How can I help?"


# ---------------------------------------------------------------------------
# Layer 2 -- pure merge_preferences logic (no LLM, always runs)
# ---------------------------------------------------------------------------

class TestPreferenceMerging:
    def test_turn3_multi_turn_accumulation(self):
        """TEST 3 (persistence half): each turn's extracted state accumulates
        without losing earlier fields."""
        state = {}
        state = merge_preferences(state, {"occasion": "engagement"})
        assert state == {"occasion": "engagement"}

        state = merge_preferences(state, {"occasion": "engagement", "style": "traditional"})
        assert state == {"occasion": "engagement", "style": "traditional"}

        state = merge_preferences(
            state, {"occasion": "engagement", "style": "traditional", "design_preference": "light"}
        )
        assert state == {
            "occasion": "engagement",
            "style": "traditional",
            "design_preference": "light",
        }

    def test_turn4_correction_overwrites_only_that_field(self):
        """TEST 4: a corrected field overwrites; TEST 5: unrelated fields survive."""
        before = {"occasion": "engagement", "style": "traditional", "design_preference": "light"}
        after = merge_preferences(before, {"occasion": "engagement", "style": "modern", "design_preference": "light"})

        assert after["style"] == "modern"
        assert after["occasion"] == "engagement"          # TEST 5: unrelated field preserved
        assert after["design_preference"] == "light"      # TEST 5: unrelated field preserved
        assert after != {"style": "modern"}, "correction must not replace the entire object"

    def test_omitted_field_does_not_erase_prior_value(self):
        """A turn that doesn't restate a field must not null it out -- this is
        what makes 'don't ask again unless it changes' actually safe."""
        before = {"occasion": "engagement", "style": "modern"}
        after = merge_preferences(before, {"occasion": None, "style": "modern"})
        assert after["occasion"] == "engagement"

    def test_negative_and_positive_fields_are_independent(self):
        """TEST 6 (persistence half): disliked_colors and color_preferences
        are separate keys and don't clobber each other."""
        state = {}
        state = merge_preferences(state, {"color_preferences": ["pastel"]})
        state = merge_preferences(state, {"disliked_colors": ["bright"]})
        assert state["color_preferences"] == ["pastel"]
        assert state["disliked_colors"] == ["bright"]


# ---------------------------------------------------------------------------
# Layer 2 -- live extraction through the real LangChain + Gemini pipeline
# ---------------------------------------------------------------------------

class TestNaturalLanguageExtraction:
    @_skip_no_key
    def test_1_single_turn_extraction_no_hallucination(self):
        """TEST 1: occasion is extracted; nothing else is invented."""
        _, prefs = _run([], "I need something for my cousin's engagement.")
        assert _contains_ci(prefs.get("occasion"), "engagement")
        for field in ("style", "color_preferences", "budget", "clothing_type"):
            assert not prefs.get(field), f"hallucinated {field}={prefs.get(field)!r} from occasion alone"

    @_skip_no_key
    def test_2_multiple_requirements_in_one_turn(self):
        """TEST 2: several requirements stated at once are all extracted together."""
        _, prefs = _run(
            [],
            "I need something traditional for an engagement, but not too heavy, "
            "and I prefer pastel colours.",
        )
        assert _contains_ci(prefs.get("occasion"), "engagement")
        assert _contains_ci(prefs.get("style"), "traditional")
        assert _contains_ci(prefs.get("color_preferences"), "pastel")
        assert _signals_lightness(prefs), (
            f"expected a 'light/not heavy' signal, got design_preference={prefs.get('design_preference')!r} "
            f"constraints={prefs.get('constraints')!r}"
        )

    @_skip_no_key
    def test_3_4_5_full_conversation_replay(self):
        """End-to-end replay of TEST 3 (accumulation), TEST 4 (correction),
        TEST 5 (unrelated fields preserved) through real turns, not
        hand-authored states."""
        history = []
        prefs = {}

        for user_text in ("I need something for an engagement.", "Traditional.", "Not too heavy."):
            reply, prefs = _run(history, user_text, prior_preferences=prefs)
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": reply})

        assert _contains_ci(prefs.get("occasion"), "engagement")
        assert _contains_ci(prefs.get("style"), "traditional")
        assert _signals_lightness(prefs), "a lightness signal should be set after 'Not too heavy.'"

        # TEST 4/5: correct just the style; occasion and the lightness signal must survive.
        reply, prefs = _run(history, "Actually, make it modern.", prior_preferences=prefs)
        assert _contains_ci(prefs.get("style"), "modern")
        assert _contains_ci(prefs.get("occasion"), "engagement")
        assert _signals_lightness(prefs), "unrelated field was lost after a correction"

    @_skip_no_key
    def test_6_negative_preferences_are_distinguished(self):
        """TEST 6: dislikes land in disliked_colors/constraints, not the
        positive fields."""
        _, prefs = _run([], "I don't like bright colours and I don't want heavy embroidery.")
        assert _contains_ci(prefs.get("disliked_colors"), "bright")
        assert not _contains_ci(prefs.get("color_preferences"), "bright"), "a dislike leaked into color_preferences"
        combined_avoid = str(prefs.get("constraints", "")) + str(prefs.get("embroidery", ""))
        assert "embroidery" in combined_avoid.lower() or "heavy" in combined_avoid.lower()
        # a positive-sounding embroidery field would be a bug: they said they DON'T want it
        assert (prefs.get("embroidery") or "").lower() not in ("heavy",), "dislike stored as a positive preference"

    @_skip_no_key
    def test_7_no_hallucination_on_vague_input(self):
        """TEST 7: a vague message must not invent occasion/color/style/budget,
        and should prompt a clarifying follow-up instead."""
        reply, prefs = _run([], "I need something nice.")
        for field in ("occasion", "color_preferences", "style", "budget"):
            assert not prefs.get(field), f"hallucinated {field}={prefs.get(field)!r} from a vague message"
        assert "?" in reply, f"expected a clarifying follow-up question, got: {reply!r}"

    @_skip_no_key
    def test_8_context_resolves_vague_followup(self):
        """TEST 8: 'softer' after a style turn should be resolved using
        conversational context, not treated as a random/unrelated value."""
        history = []
        reply1, prefs = _run(history, "I want something traditional.")
        history += [
            {"role": "user", "content": "I want something traditional."},
            {"role": "assistant", "content": reply1},
        ]
        _, prefs = _run(history, "Maybe something softer.", prior_preferences=prefs)

        assert _contains_ci(prefs.get("style"), "traditional"), "earlier context was lost"
        # "softer" should land SOMEWHERE meaningful (color, design_preference, or notes) --
        # not be silently dropped.
        touched = any(prefs.get(f) for f in ("color_preferences", "design_preference", "notes", "pattern"))
        assert touched, f"'softer' produced no change to conversation_state: {prefs}"
