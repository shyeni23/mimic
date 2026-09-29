"""
Path B (graph_native.py) -- mocked tests, no live Groq calls. Mirrors the
mocked-LLM test style in test_natural_language_extraction.py's
TestRunAgentTurnToolLoop, adapted for native bind_tools()-shaped responses
(AIMessage.tool_calls, not this project's own ToolCall/AgentTurnOutput
schema) so both agent designs get comparable test coverage.
"""
from unittest.mock import patch, MagicMock

from langchain_core.messages import AIMessage

from app.services.agent.graph_native import run_agent_turn_native
from app.services.agent.llm import LLMConfigurationError


def _ai_message(content="", tool_calls=None):
    """A LangChain AIMessage shaped like what ChatGroq.bind_tools() returns:
    .content (empty on a tool-calling step, filled on the terminal step)
    and .tool_calls (a list of {"name","args","id"} dicts, empty/None when
    no tool is needed)."""
    return AIMessage(content=content, tool_calls=tool_calls or [])


def _mock_bound_llm(*responses):
    """Patches get_native_agent_llm so llm.bind_tools(...).invoke(...)
    returns `responses` in order (one per loop iteration)."""
    mock_bound = MagicMock()
    mock_bound.invoke.side_effect = list(responses)
    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_bound
    return patch("app.services.agent.graph_native.get_native_agent_llm", return_value=mock_llm), mock_bound


class TestRunAgentTurnNative:
    def test_plain_chat_turn_costs_exactly_one_llm_call(self):
        patcher, mock_bound = _mock_bound_llm(_ai_message("Pastels are lovely on you!"))
        with patcher:
            result = run_agent_turn_native("n1", "I like pastel colors.", [])
        assert result["reply"] == "Pastels are lovely on you!"
        assert result["actions"] == []
        assert mock_bound.invoke.call_count == 1

    def test_tool_call_then_final_reply(self):
        """Two-step: step 1 requests navigate_to_page (empty content), step 2
        (after the ToolMessage is fed back) gives the final reply with no
        further tool_calls."""
        step1 = _ai_message(content="", tool_calls=[
            {"name": "navigate_to_page", "args": {"page": "shopping"}, "id": "call_1"},
        ])
        step2 = _ai_message(content="Sure, taking you there now!")
        patcher, mock_bound = _mock_bound_llm(step1, step2)
        with patcher:
            result = run_agent_turn_native("n2", "Take me to shopping.", [])
        assert result["reply"] == "Sure, taking you there now!"
        assert len(result["actions"]) == 1
        assert result["actions"][0]["type"] == "navigate"
        assert mock_bound.invoke.call_count == 2

    def test_record_conversation_state_extracted_alongside_a_tool_call(self):
        """RecordConversationState can fire in parallel with a real tool in
        the SAME response -- native bind_tools() supports multiple tool_calls
        per step, unlike Path A's single ToolCall field."""
        step1 = _ai_message(content="", tool_calls=[
            {"name": "navigate_to_page", "args": {"page": "shopping"}, "id": "call_1"},
            {"name": "RecordConversationState", "args": {"style": "modern"}, "id": "call_2"},
        ])
        step2 = _ai_message(content="Got it, heading to shopping now!")
        patcher, mock_bound = _mock_bound_llm(step1, step2)
        with patcher:
            result = run_agent_turn_native("n3", "Take me to shopping, I like modern styles.", [])
        assert result["preferences"]["style"] == "modern"
        assert len(result["actions"]) == 1

    def test_missing_item_id_never_fabricated(self):
        """add_item_to_cart with an item_id never shown this conversation
        must not fire -- same structural enforcement as Path A, shared via
        _execute_native_tool_call."""
        step1 = _ai_message(content="", tool_calls=[
            {"name": "add_item_to_cart", "args": {"item_id": "fabricated-id"}, "id": "call_1"},
        ])
        step2 = _ai_message(content="I don't have that item pulled up -- could you point it out?")
        patcher, mock_bound = _mock_bound_llm(step1, step2)
        with patcher:
            result = run_agent_turn_native("n4", "Add the blue jacket to my cart.", [])
        assert result["actions"] == []

    def test_bound_hit_still_returns_a_reply(self):
        """If the model keeps requesting tools past MAX_TOOL_ITERATIONS, the
        loop must still return a valid reply, never hang or crash."""
        looping_step = _ai_message(content="", tool_calls=[
            {"name": "get_body_profile", "args": {}, "id": "call_x"},
        ])
        mock_bound = MagicMock()
        mock_bound.invoke.return_value = looping_step  # always wants another tool
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_bound

        with patch("app.services.agent.graph_native.get_native_agent_llm", return_value=mock_llm), \
             patch("app.services.agent.tools.get_latest_scan", return_value=None):
            result = run_agent_turn_native("n5", "keep going", [])

        assert result["reply"]
        assert isinstance(result["actions"], list)

    def test_llm_configuration_error_skips_tool_dispatch_entirely(self):
        with patch(
            "app.services.agent.graph_native.get_native_agent_llm",
            side_effect=LLMConfigurationError("no key"),
        ) as mock_get_llm:
            result = run_agent_turn_native("n6", "anything", [])
        assert result["actions"] == []
        assert mock_get_llm.call_count == 1

    def test_empty_input_preserves_state(self):
        prior = {"occasion": "engagement", "style": "modern"}
        result = run_agent_turn_native("n7", "", [], prior_preferences=prior)
        assert result["reply"]
        assert result["preferences"] == prior
        assert result["actions"] == []
