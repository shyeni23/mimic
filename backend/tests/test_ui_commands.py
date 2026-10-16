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
    "show me a bottom for office", "yes", "thanks",
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


@pytest.mark.parametrize("text, expected", [
    ("can you move the page a bit lower", "scroll"), ("take me back", "go_back"), ("go home", "navigate"),
    ("put the first one in my bag", "add_to_cart"), ("add this to cart", "add_to_cart"),
    ("isko cart mein daal do", "add_to_cart"), ("get rid of that", "open_cart"),  # 'that' isn't in the cart -> asks which
    ("how much do i have to pay", "read_cart_summary"), ("shh", "stop_speaking"),
    ("talk slower", "set_speech_rate"), ("speak louder", "set_voice_volume"),
    ("make the screen dark", "set_theme"), ("compare the first two", "compare_items"),
    ("rate this five stars", "rate_item"), ("zoom in on it", "zoom_item_image"), ("close", "close_item_detail"),
])
def test_more_natural_phrasings(text, expected):
    got = actions(text)
    assert got and expected in [a for a, _ in got], f"{text!r} -> {got}"


def test_in_my_bag_is_not_a_handbag_request():
    from app.services.agent.shopping_intent import parse_shopping_request
    assert parse_shopping_request("put the first one in my bag") is None
    assert parse_shopping_request("show me a black bag") is not None


def test_softer_style_is_not_a_volume_command():
    assert actions("maybe something softer") is None


def test_face_shape_hint_per_category():
    from app.services.fashion.inventory_search import face_shape_hint
    assert "V-neck" in face_shape_hint("round", "top")
    assert "long drop earrings" in face_shape_hint("round", "jewelry")
    assert "angular sunglasses" in face_shape_hint("round", "accessory")
    # Bottoms are unaffected by face shape -- no hint.
    assert face_shape_hint("round", "bottom") is None
    assert face_shape_hint(None, "top") is None
    assert face_shape_hint("unknown", "top") is None
    # Alias handling: frontend sends "long" for oblong.
    assert face_shape_hint("long", "top") == face_shape_hint("oblong", "top")


def test_recommend_items_adds_face_shape_to_query(monkeypatch):
    import app.services.fashion.inventory_search as mod
    seen = {}
    def fake_search(query_text, **kw):
        seen["q"] = query_text
        return [{"id": "x1", "name": "Round Earrings", "category": "jewelry", "color": "gold",
                 "occasion": [], "stock": 1, "gender": "female"}]
    monkeypatch.setattr(mod, "semantic_search", fake_search)
    monkeypatch.setattr(mod, "apply_catalog_filters", lambda c, g: c)
    import app.services.fashion.trends as trends_mod
    monkeypatch.setattr(trends_mod, "annotate_trend_signals", lambda *a, **k: None)
    monkeypatch.setattr(trends_mod, "trend_explanation_fragment", lambda i: None)
    r = mod.recommend_items(depth="medium", undertone="neutral", body_shape="rectangle",
                            gender="female", category="jewelry", face_shape="round")
    assert "long drop earrings" in seen["q"]
    assert any("round face shape" in (i.get("explanation") or "") for i in r["results"])


@pytest.mark.parametrize("text, expected_id", [
    ("i want to try third", "a3"),
    ("i want to try the third one", "a3"),
    ("try third one", "a3"),
    ("let me try the third", "a3"),
    ("try the third on", "a3"),
    ("i wanna try the red one", "a2"),
    ("can i try the second one", "a2"),
    ("wear the first one", "a1"),
])
def test_try_on_phrasings(text, expected_id):
    """'I want to try the third one' has no 'on' in it -- the natural phrasing
    was missed by a try...on rule, so try-on never fired for most customers."""
    got = actions(text)
    assert got, f"{text!r} not recognised"
    assert ("start_tryon", {"item_id": expected_id, "item": SCREEN[int(expected_id[1]) - 1]}) in got, got


@pytest.mark.parametrize("text", [
    "try something else", "try to find a red dress", "i want to try these on",
])
def test_not_a_try_on(text):
    got = actions(text) or []
    assert "start_tryon" not in [a for a, _ in got], f"{text!r} -> {got}"


def test_wedding_dress_means_ethnic_wear_in_an_indian_store():
    """722 items sit in the `dress` category but only ONE is tagged wedding,
    and the 308 sarees live there untagged -- so a wedding request was
    returning Western midi dresses."""
    from app.services.fashion.requested_items import ethnic_terms_for
    assert "saree" in ethnic_terms_for("dress", "wedding", "female")
    assert "lehenga" in ethnic_terms_for("dress", "engagement", "female")
    assert "sherwani" in ethnic_terms_for("outfit", "wedding", "male")
    # A non-traditional occasion keeps Western dresses.
    assert ethnic_terms_for("dress", "party", "female") is None
    assert ethnic_terms_for("dress", None, "female") is None
    # A specific garment request is never overridden.
    assert ethnic_terms_for("gown", "wedding", "female") is None
    assert ethnic_terms_for("heels", "wedding", "female") is None
