"""Rule-based touchless commands (app/services/agent/ui_commands.py) -- no DB, no LLM."""
import time

import pytest

from app.services.agent.ui_commands import ui_command_turn

SCREEN = [
    {"id": "a1", "name": "Fabindia Teal Green Saree", "color": "teal"},
    {"id": "a2", "name": "FNF Red Sari", "color": "red"},
    {"id": "a3", "name": "Prafful Maroon Saree", "color": "maroon"},
]
CART = [{"id": "a1", "name": "Fabindia Teal Green Saree", "price": 2500, "quantity": 1},
        {"id": "a3", "name": "Prafful Maroon Saree", "price": 1800, "quantity": 2}]
STATE = {"page": "recommendations", "screen_items": SCREEN, "cart": CART,
         "liked": [{"id": "a2", "name": "FNF Red Sari"}], "highlighted_item_id": "a2"}


def actions(text, prefs=None, state=STATE):
    r = ui_command_turn(text, prefs or {}, state)
    return None if r is None else [(a["type"], a["payload"]) for a in r["actions"]]


@pytest.mark.parametrize("text, expected", [
    ("scroll down", "scroll"), ("scroll up a little", "scroll"), ("neeche", "scroll"),
    ("go to the top", "scroll_to"), ("scroll to the bottom", "scroll_to"),
    ("go back", "go_back"), ("stop talking", "stop_speaking"), ("mute your voice", "set_voice_mute"),
    ("dark mode", "set_theme"), ("open the menu", "toggle_sidebar"), ("what can i say", "show_help"),
    ("show my cart", "open_cart"), ("close the cart", "close_cart"),
    ("show my favourites", "show_liked"), ("clear filters", "clear_filters"),
    ("go to shopping", "navigate"), ("search for silk saree", "search"),
    ("show the third one", "focus_item"), ("next one", "focus_item"),
    ("filter by bags", "set_category_filter"), ("party filter", "set_occasion_filter"),
])
def test_command_maps_to_action(text, expected):
    got = actions(text)
    assert got, f"{text!r} was not recognised"
    assert expected in [a for a, _ in got], f"{text!r} -> {got}"


@pytest.mark.parametrize("text", [
    "show me a top", "I am looking for saree", "something for a wedding", "hi how are you",
    "show me a bottom for office", "add the first one to my cart", "yes", "thanks",
])
def test_not_a_screen_command(text):
    assert actions(text) is None, f"{text!r} should be left to the shopping rules / LLM"


def test_like_resolves_on_screen_order():
    got = actions("I like the third one")
    assert ("like_item", {"item_id": "a3"}) in got


def test_like_this_uses_highlight():
    got = actions("like this one", state={**STATE, "liked": []})
    assert ("like_item", {"item_id": "a2"}) in got


def test_remove_from_cart_needs_confirmation_then_yes():
    r = ui_command_turn("remove the maroon saree from my cart", {}, STATE)
    assert [a["type"] for a in r["actions"]] == ["show_confirmation"]
    pending = r["preferences"]["pending_confirmation"]
    assert pending["type"] == "remove_from_cart" and pending["payload"] == {"item_id": "a3"}
    done = ui_command_turn("yes", r["preferences"], STATE)
    assert [a["type"] for a in done["actions"]] == ["hide_confirmation", "remove_from_cart"]
    assert "pending_confirmation" not in done["preferences"]


def test_confirmation_no_cancels():
    r = ui_command_turn("empty my cart", {}, STATE)
    done = ui_command_turn("no", r["preferences"], STATE)
    assert [a["type"] for a in done["actions"]] == ["hide_confirmation"]


def test_confirmation_expires():
    prefs = {"pending_confirmation": {"type": "clear_cart", "payload": {}, "prompt": "x", "at": time.time() - 60}}
    assert ui_command_turn("yes", prefs, STATE) is None


def test_cart_total_and_count():
    assert "₹6,100" in ui_command_turn("what's my total", {}, STATE)["reply"]
    assert "3 items" in ui_command_turn("how many items in my cart", {}, STATE)["reply"]


def test_settings_refused_for_customers():
    r = ui_command_turn("open settings", {}, STATE)
    assert r["actions"] == [] and "staff" in r["reply"].lower()
