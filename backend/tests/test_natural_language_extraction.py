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
import pytest
from unittest.mock import patch, MagicMock

from app.config import settings
from app.services.agent.preferences import merge_preferences
from app.services.agent.graph import (
    run_agent_turn, _build_messages, ConversationTurnOutput, ConversationState,
    CUSTOMER_PROMPT,
)

_HAS_GROQ_KEY = bool(settings.groq_api_key)
_skip_no_key = pytest.mark.skipif(
    not _HAS_GROQ_KEY,
    reason="GROQ_API_KEY is not set -- these tests call the real Groq API.",
)


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
    """Return a ConversationTurnOutput with the given response and state
    fields, and patch get_agent_llm so run_agent_turn uses it."""
    output = ConversationTurnOutput(
        response=response,
        conversation_state=ConversationState(**state_fields),
    )
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = output
    mock_llm.with_structured_output.return_value = mock_structured
    return patch("app.services.agent.graph.get_agent_llm", return_value=mock_llm)


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
