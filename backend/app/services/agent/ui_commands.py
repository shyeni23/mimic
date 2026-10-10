"""
Touchless screen control: instant, rule-based handling of the commands a
customer uses most ("scroll down", "go back", "like the second one", "remove
it from my cart", "what's my total", "dark mode", "stop talking"...).

Action names, params and replies follow docs/dataset/new_actions.json. Rules
run before the LLM, so these work in ~1s and keep working when the Groq quota
is spent; anything they don't recognise falls through to Aria's LLM.

client_state (sent by the frontend with every chat message):
    page                 current route, e.g. "shopping"
    highlighted_item_id  the item Aria/the customer is focused on ("this one")
    screen_items         [{id, name, color}] in on-screen order
    cart                 [{id, name, price, quantity}]
    liked                [{id, name}]

Irreversible actions (remove from cart, empty cart, clear favourites) go
through a yes/no confirmation stored in preferences["pending_confirmation"],
which expires after 20 seconds.
"""
import re
import time

from app.services.agent.actions import start_turn, queue_action, get_queued_actions

CONFIRM_TTL_S = 20

_ORDINALS = {
    "first": 0, "1st": 0, "pehla": 0, "pehle": 0, "second": 1, "2nd": 1, "doosra": 1, "dusra": 1,
    "third": 2, "3rd": 2, "teesra": 2, "fourth": 3, "4th": 3, "fifth": 4, "5th": 4,
    "sixth": 5, "6th": 5, "seventh": 6, "7th": 6, "eighth": 7, "8th": 7, "ninth": 8, "9th": 8,
    "tenth": 9, "10th": 9, "last": -1, "aakhri": -1,
}
_ORDINAL_RE = re.compile(r"\b(" + "|".join(_ORDINALS) + r")\b|\b(?:number|no\.?|option|item|#)\s*(\d{1,2})\b",
                         re.IGNORECASE)
_DEICTIC_RE = re.compile(r"\b(this|that|it|yeh|ye|woh|wo|isko|usko|isse)\b", re.IGNORECASE)
_COLOURS = ["red", "blue", "green", "black", "white", "pink", "yellow", "orange", "purple", "maroon",
            "grey", "gray", "brown", "beige", "cream", "navy", "teal", "gold", "silver", "magenta",
            "olive", "peach", "mustard", "turquoise", "burgundy", "lavender", "multi"]
_COLOUR_RE = re.compile(r"\b(" + "|".join(_COLOURS) + r")\b", re.IGNORECASE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip(" .!?,"))


# ---------------------------------------------------------------- items

def _resolve(text: str, items: list[dict], highlighted: str | None = None) -> dict | None:
    """'the second one', 'last', 'number 4', 'this one', 'the red one',
    'next/previous one' -> one item from `items` (display order)."""
    if not items:
        return None
    m = _ORDINAL_RE.search(text)
    if m:
        idx = _ORDINALS[m.group(1).lower()] if m.group(1) else int(m.group(2)) - 1
        return items[idx] if -len(items) <= idx < len(items) else None
    ids = [str(i.get("id")) for i in items]
    if re.search(r"\b(next|agla|agle)\b", text, re.I) and highlighted in ids:
        return items[min(ids.index(highlighted) + 1, len(items) - 1)]
    if re.search(r"\b(previous|prev|pichla|pichle)\b", text, re.I) and highlighted in ids:
        return items[max(ids.index(highlighted) - 1, 0)]
    c = _COLOUR_RE.search(text)
    if c:
        hits = [i for i in items if c.group(1).lower() in f"{i.get('color') or ''} {i.get('name') or ''}".lower()]
        if len(hits) == 1:
            return hits[0]
    if _DEICTIC_RE.search(text):
        if highlighted:
            hit = next((i for i in items if str(i.get("id")) == highlighted), None)
            if hit:
                return hit
        if len(items) == 1:
            return items[0]
    return None


def _cart_item(text: str, state: dict) -> dict | None:
    """Item in the cart: by position in the cart, name word, 'this', or the
    only item."""
    cart = state.get("cart") or []
    if not cart:
        return None
    hit = _resolve(text, cart, state.get("highlighted_item_id"))
    if hit:
        return hit
    words = [w for w in re.findall(r"[a-z]{4,}", text.lower())
             if w not in {"remove", "delete", "cart", "from", "take", "make", "quantity", "this", "that",
                          "item", "items", "please", "with", "more", "less"}]
    named = [i for i in cart if any(w in (i.get("name") or "").lower() for w in words)]
    if len(named) == 1:
        return named[0]
    return cart[0] if len(cart) == 1 else None


# ---------------------------------------------------------------- results

def _turn(reply: str, actions: list[tuple[str, dict]], prefs: dict) -> dict:
    start_turn()
    for a_type, payload in actions:
        queue_action(a_type, payload)
    return {"reply": reply, "actions": get_queued_actions(), "preferences": prefs}


def _ask_confirmation(prompt: str, action: tuple[str, dict], prefs: dict) -> dict:
    prefs = dict(prefs)
    prefs["pending_confirmation"] = {"type": action[0], "payload": action[1], "prompt": prompt, "at": time.time()}
    return _turn(f"{prompt} Just say yes or no.", [("show_confirmation", {"prompt": prompt})], prefs)


_YES_RE = re.compile(r"^(yes|yeah|yep|yup|sure|ok|okay|confirm|do it|go ahead|haan|haa|ha|ji|ji haan|please do)\b")
_NO_RE = re.compile(r"^(no|nope|nah|cancel|don'?t|stop|never ?mind|nahi|nahin|mat|rehne do)\b")


def _confirmation_turn(text: str, prefs: dict) -> dict | None:
    pending = (prefs or {}).get("pending_confirmation")
    if not pending:
        return None
    prefs = {k: v for k, v in prefs.items() if k != "pending_confirmation"}
    if time.time() - pending.get("at", 0) > CONFIRM_TTL_S:
        return None                       # expired: treat this message normally
    if _YES_RE.search(text):
        done = {"clear_cart": "Your cart is empty now.", "clear_liked": "All cleared.",
                "remove_from_cart": "Removed it from your cart."}.get(pending["type"], "Done.")
        return _turn(done, [("hide_confirmation", {}), (pending["type"], pending.get("payload") or {})], prefs)
    if _NO_RE.search(text):
        return _turn("Okay, cancelled.", [("hide_confirmation", {})], prefs)
    return None


# ---------------------------------------------------------------- rules

_PAGES = {
    "home": "dashboard", "dashboard": "dashboard", "main screen": "dashboard",
    "scanner": "body_scanner", "body scanner": "body_scanner", "scan page": "body_scanner",
    "results": "analysis_results", "analysis": "analysis_results", "my analysis": "analysis_results",
    "recommendations": "recommendations", "recommendation": "recommendations", "suggestions": "recommendations",
    "stylist": "ai_stylist", "chat": "ai_stylist", "outfit builder": "outfit_builder",
    "try on": "virtual_tryon", "try-on": "virtual_tryon", "virtual try on": "virtual_tryon", "trial": "virtual_tryon",
    "personalization": "personalization", "personalisation": "personalization",
    "shopping": "shopping", "shop": "shopping", "store": "shopping", "profile": "profile",
    "my profile": "profile", "settings": "settings",
}
_STAFF_ONLY_PAGES = {"settings"}
_CATEGORY_WORDS = {
    "tops": "top", "top": "top", "bottoms": "bottom", "bottom": "bottom", "dresses": "dress", "dress": "dress",
    "shoes": "footwear", "footwear": "footwear", "bags": "bag", "bag": "bag", "watches": "watch",
    "watch": "watch", "jewellery": "jewelry", "jewelry": "jewelry", "accessories": "accessory", "all": "all",
}
_OCCASIONS = ["smart casual", "casual", "ethnic", "formal", "office", "party", "sports", "travel", "wedding", "all"]


def _amount(t: str) -> str:
    if re.search(r"\b(a (little|bit)|slightly|thoda|little)\b", t):
        return "small"
    if re.search(r"\b(a lot|lots|much|far|way|bahut|full page)\b", t):
        return "large"
    if re.search(r"\bpage\b", t):
        return "page"
    return "medium"


def ui_command_turn(text: str, prior_preferences: dict, client_state: dict | None) -> dict | None:
    """A recognised screen command -> its turn result; None to let the
    shopping rules or the LLM handle the message."""
    t = _norm(text)
    if not t:
        return None
    prefs = dict(prior_preferences or {})
    st = client_state or {}

    confirmed = _confirmation_turn(t, prefs)
    if confirmed:
        return confirmed
    if "pending_confirmation" in prefs and not _YES_RE.search(t) and not _NO_RE.search(t):
        prefs.pop("pending_confirmation", None)     # any other intent clears it

    page = st.get("page") or ""
    screen = st.get("screen_items") or prefs.get("last_shown") or []
    highlighted = st.get("highlighted_item_id")
    cart = st.get("cart") or []
    liked = st.get("liked") or []

    # --- voice & assistant control
    if re.fullmatch(r"(please )?(stop|stop talking|stop speaking|be quiet|quiet|shut up|chup|chup ho jao|bas|enough|ruko)", t):
        return _turn("", [("stop_speaking", {})], prefs)
    if re.search(r"\b(unmute|voice on|speak again|talk again|awaaz (chalu|on))\b", t):
        return _turn("Voice is back on.", [("set_voice_mute", {"muted": False})], prefs)
    if re.search(r"\b(mute|text only|don'?t speak|no voice|awaaz band|silent mode)\b", t):
        return _turn("I'll reply in text on screen.", [("set_voice_mute", {"muted": True})], prefs)
    if re.search(r"\b(help|what can i say|what can you do|commands|kya bol sakte)\b", t) and len(t.split()) <= 7:
        return _turn("You can say things like 'show me sarees', 'like the second one', or 'add this to cart'.",
                     [("show_help", {"screen": page})], prefs)
    if re.search(r"\b(dark mode|dark theme|night mode)\b", t):
        return _turn("Switched to dark mode.", [("set_theme", {"mode": "dark"})], prefs)
    if re.search(r"\b(light mode|light theme|day mode|bright mode)\b", t):
        return _turn("Switched to light mode.", [("set_theme", {"mode": "light"})], prefs)
    if re.search(r"\b(open|show)( the)? (menu|sidebar)\b", t):
        return _turn("Menu is open. Which page would you like?", [("toggle_sidebar", {"state": "open"})], prefs)
    if re.search(r"\b(close|hide)( the)? (menu|sidebar)\b", t):
        return _turn("Menu closed.", [("toggle_sidebar", {"state": "close"})], prefs)
    if re.search(r"\b(hands[- ]?free) (off|band)\b|\bstop listening\b", t):
        return _turn("Hands-free is off. Tap the mic or say 'Hey Aria' when you need me.",
                     [("set_hands_free", {"enabled": False})], prefs)
    if re.search(r"\b(hands[- ]?free) (on|chalu)\b|\bstart listening\b", t):
        return _turn("Hands-free is on. I'm listening.", [("set_hands_free", {"enabled": True})], prefs)
    if re.search(r"\b(minimi[sz]e|close|hide)( the)? (chat|aria|panel|assistant)\b", t):
        return _turn("Panel minimised. Just call me when you need me.", [("set_aria_panel", {"state": "minimize"})], prefs)
    if re.search(r"\b(open|show|expand)( the)? (chat|aria|panel|assistant)\b", t) and "page" not in t:
        return _turn("I'm here.", [("set_aria_panel", {"state": "open"})], prefs)

    # --- scrolling & history
    # Needs a movement word: "show me a top" / "a bottom" are garments.
    _move = r"\b(scroll|go|move|jump|take me|back|all the way)\b"
    if (re.search(_move + r".*\b(top|start)( of (the )?page)?$", t) or re.search(r"sabse upar|upar tak", t)) \
            and len(t.split()) <= 7:
        return _turn("Back to the top.", [("scroll_to", {"position": "top"})], prefs)
    if (re.search(_move + r".*\b(bottom|end)( of (the )?page)?$", t) or re.search(r"sabse neeche|neeche tak", t)) \
            and len(t.split()) <= 7:
        return _turn("All the way down.", [("scroll_to", {"position": "bottom"})], prefs)
    if re.search(r"\b(scroll|move|go)?\s*(down|neeche|niche|downward)\b", t) and len(t.split()) <= 7 \
            and not re.search(r"\b(go down to|calm down)\b", t):
        return _turn("Scrolling down.", [("scroll", {"direction": "down", "amount": _amount(t)})], prefs)
    if re.search(r"\b(scroll|move|go)?\s*(up|upar|upwards?)\b", t) and len(t.split()) <= 7 \
            and re.search(r"\b(scroll|upar|upwards?|^up$|move up|go up)\b", t):
        return _turn("Scrolling up.", [("scroll", {"direction": "up", "amount": _amount(t)})], prefs)
    if re.fullmatch(r"(go )?back|(go to the )?previous (page|screen)|peeche( jao| chalo)?|wapas( jao)?|go back please", t):
        return _turn("Going back.", [("go_back", {})], prefs)
    if re.fullmatch(r"(go )?forward|next (page|screen)|aage( jao| chalo)?", t) and page not in ("shopping",):
        return _turn("Going forward.", [("go_forward", {})], prefs)
    if re.search(r"\b(show|load|see) more\b|\bmore options\b|\baur dikhao\b|^next page$", t) and page in ("shopping", "recommendations"):
        return _turn("Here are a few more.", [("load_more", {"count": 24})], prefs)

    # --- navigation ("go to shopping", "open my profile")
    m = re.search(r"\b(?:go to|open|take me to|show me|switch to|navigate to)(?: the| my)? ([a-z -]+?)(?: page| screen| tab)?$", t)
    if m and m.group(1).strip() in _PAGES:
        target = _PAGES[m.group(1).strip()]
        if target in _STAFF_ONLY_PAGES:
            return _turn("Settings are for store staff only. Shall I call someone to help you?", [], prefs)
        return _turn("Sure, opening it now.", [("navigate", {"page": target})], prefs)

    # --- cart
    if re.search(r"\b(empty|clear)( out)?( my| the)? (cart|bag|fitting room)\b|\bcart khaali\b", t):
        if not cart:
            return _turn("Your cart is already empty.", [], prefs)
        return _ask_confirmation("Empty your whole cart?", ("clear_cart", {}), prefs)
    if re.search(r"\b(remove|delete|take out|hata(o| do)?|nikal(o| do)?)\b", t) and \
            (re.search(r"\b(cart|bag|fitting room)\b", t) or _ORDINAL_RE.search(t) or _DEICTIC_RE.search(t)) \
            and not re.search(r"\b(favou?rites?|liked|wishlist|filter)\b", t):
        if not cart:
            return _turn("Your cart is empty right now.", [], prefs)
        item = _cart_item(t, st)
        if not item:
            return _turn("Which item should I remove? You can say the first, second, or its name.", [("open_cart", {})], prefs)
        return _ask_confirmation(f"Remove the {item['name']} from your cart?",
                                 ("remove_from_cart", {"item_id": item["id"]}), prefs)
    qty = re.search(r"\b(?:make it|set (?:it |the quantity )?to|quantity(?: to)?|change (?:it |quantity )?to)\s*(\d{1,2}|one|two|three|four|five)\b", t)
    if qty and cart:
        words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
        n = int(words.get(qty.group(1), qty.group(1)))
        item = _cart_item(t, st)
        if item:
            return _turn(f"Now {n} of those.", [("set_cart_quantity", {"item_id": item["id"], "quantity": n})], prefs)
    if cart and re.search(r"\b(one more|add another|increase( the)? quantity|ek aur)\b", t):
        item = _cart_item(t, st)
        if item:
            return _turn(f"Now {int(item.get('quantity') or 1) + 1} of those.",
                         [("set_cart_quantity", {"item_id": item["id"], "delta": 1})], prefs)
    if cart and re.search(r"\b(one less|decrease( the)? quantity|reduce( the)? quantity|ek kam)\b", t):
        item = _cart_item(t, st)
        if item:
            return _turn("Done.", [("set_cart_quantity", {"item_id": item["id"], "delta": -1})], prefs)
    if re.search(r"\bhow many\b.*\b(cart|items|things)\b|\b(items|things) in (my |the )?cart\b", t):
        n = sum(int(i.get("quantity") or 1) for i in cart)
        return _turn(f"You have {n} item{'s' if n != 1 else ''} in your cart." if n else "Your cart is empty.",
                     [("read_cart_summary", {"field": "count"})] if n else [], prefs)
    if re.search(r"\b(total|how much (is it|does it come|altogether|in total)|kitna hua|bill)\b", t) and \
            re.search(r"\b(total|cart|altogether|kitna|bill|in total)\b", t):
        total = sum(float(i.get("price") or 0) * int(i.get("quantity") or 1) for i in cart)
        if not cart:
            return _turn("Your cart is empty.", [], prefs)
        return _turn(f"Your total is ₹{total:,.0f}." if total else "Prices for these items aren't listed yet. A staff member can help with the total.",
                     [("read_cart_summary", {"field": "total"})], prefs)
    if re.search(r"\b(close|hide)( the| my)? (cart|bag)\b", t):
        return _turn("Cart closed.", [("close_cart", {})], prefs)
    if re.search(r"\b(show|open|see|view|check|go to)( me)?( my| the)? (cart|bag|fitting room)\b|\bcart (dikhao|kholo)\b", t):
        n = sum(int(i.get("quantity") or 1) for i in cart)
        reply = f"Here's your cart, {n} item{'s' if n != 1 else ''}." if n else \
            "Your cart is empty right now. Want some suggestions?"
        return _turn(reply, [("open_cart", {})], prefs)

    # --- favourites
    if re.search(r"\b(clear|remove all|delete all|empty)( my)? (favou?rites|likes|liked items|wishlist)\b", t):
        if not liked:
            return _turn("Your favourites list is already empty.", [], prefs)
        return _ask_confirmation("Remove all your favourites?", ("clear_liked", {}), prefs)
    if re.search(r"\b(show|open|see|view)( me)?( my)? (favou?rites|likes|liked( items| list)?|wishlist|saved( items)?)\b|\bpasand wale\b", t):
        if not liked:
            return _turn("You haven't liked anything yet. Just say 'like this one' when something catches your eye.", [], prefs)
        n = len(liked)
        return _turn(f"Here {'is your favourite' if n == 1 else f'are your {n} favourites'}.",
                     [("show_liked", {})], prefs)
    if re.search(r"\b(unlike|un-?favou?rite|remove from (my )?(favou?rites|wishlist|likes)|don'?t like)\b", t):
        item = _resolve(t, liked, highlighted) or _resolve(t, screen, highlighted)
        if item and any(str(i.get("id")) == str(item["id"]) for i in liked):
            return _turn("Removed from favourites.", [("unlike_item", {"item_id": item["id"]})], prefs)
        if item:
            return _turn("That one isn't in your favourites.", [], prefs)
    if re.search(r"\b(like|love|favou?rite|save|heart|pasand)\b", t) and \
            (_ORDINAL_RE.search(t) or _DEICTIC_RE.search(t) or _COLOUR_RE.search(t)) and \
            not re.search(r"\b(would like|i'?d like|like to|looking for|show me)\b", t):
        item = _resolve(t, screen, highlighted)
        if item:
            prefs["pending_item"] = {"id": item["id"], "name": item.get("name")}
            if any(str(i.get("id")) == str(item["id"]) for i in liked):
                return _turn(f"The {item.get('name')} is already in your favourites. Shall I add it to your cart?",
                             [("focus_item", {"item_id": item["id"]})], prefs)
            return _turn(f"Added the {item.get('name')} to your favourites! Shall I add it to your cart?",
                         [("like_item", {"item_id": item["id"]}), ("focus_item", {"item_id": item["id"]})], prefs)

    # --- focus ("show me the third one", "next one")
    if screen and re.search(r"\b(show|see|open|go to|focus on|zoom (in )?on|dikhao)\b.*\b(one|item|option|wala)\b|^(next|previous|agla|pichla)( one| item)?$", t):
        item = _resolve(t, screen, highlighted)
        if item:
            return _turn(f"Here's the {item.get('name')}.", [("focus_item", {"item_id": item["id"]})], prefs)

    # --- filters & search
    if re.search(r"\b(clear|remove|reset)( all)?( the)? filters?\b|\bfilter hata", t):
        return _turn("Filters cleared, showing everything.", [("clear_filters", {"scope": "all"})], prefs)
    if re.search(r"\b(men'?s|mens|gents|male)\b.*\b(range|section|side|collection|department)\b|\bswitch to men\b", t):
        nav = [] if page == "recommendations" else [("navigate", {"page": "recommendations"})]
        return _turn("Showing the men's range.", nav + [("set_department", {"department": "men"})], prefs)
    if re.search(r"\b(women'?s|womens|ladies|female)\b.*\b(range|section|side|collection|department)\b|\bswitch to women\b", t):
        nav = [] if page == "recommendations" else [("navigate", {"page": "recommendations"})]
        return _turn("Showing the women's range.", nav + [("set_department", {"department": "women"})], prefs)
    if re.search(r"\b(filter|tab|chip|category)\b", t):
        target_page = page if page in ("shopping", "recommendations") else "shopping"
        nav = [("navigate", {"page": target_page})] if page != target_page else []
        for occ in _OCCASIONS:
            if re.search(rf"\b{occ}\b", t):
                return _turn(f"Showing {occ} styles." if occ != "all" else "Showing all occasions.",
                             nav + [("set_occasion_filter", {"occasion": occ})], prefs)
        for word, cat in _CATEGORY_WORDS.items():
            if re.search(rf"\b{word}\b", t):
                return _turn(f"Here are the {word} options." if cat != "all" else "Showing all categories.",
                             nav + [("set_category_filter", {"category": cat})], prefs)
    s = re.match(r"^(?:search|search for|look up)\s+(.+)$", t)
    if s:
        q = s.group(1).strip()
        return _turn(f"Here's what I found for {q}.", [("search", {"query": q, "refine": False})], prefs)
    if re.search(r"\bclear( the)? search\b|\bsearch hata", t):
        return _turn("Search cleared.", [("clear_search", {})], prefs)

    # --- virtual try-on
    if page == "virtual-tryon" or re.search(r"\b(lighting|camera|photo|picture|selfie)\b", t):
        light = re.search(r"\b(natural|studio|warm|cool)\b.*\b(light|lighting|mode)\b|\b(light|lighting)\b.*\b(natural|studio|warm|cool)\b", t)
        if light:
            mode = light.group(1) or light.group(4)
            return _turn(f"Switched to {mode} lighting.", [("set_lighting", {"mode": mode})], prefs)
        if re.search(r"\b(flip|mirror)( the)? (camera|view)\b", t):
            return _turn("Flipped the view.", [("flip_camera", {})], prefs)
        if re.search(r"\b(retake|take (it )?again|another (photo|picture))\b", t):
            return _turn("Okay, again. Smile! 3, 2, 1.", [("retake_photo", {"countdown_seconds": 3})], prefs)
        if re.search(r"\b(delete|discard|remove)( the| this)? (photo|picture)\b", t):
            return _turn("Photo deleted.", [("dismiss_photo", {})], prefs)
        if re.search(r"\b(take|click|capture)( a| my)? (photo|picture|pic|selfie)\b|\bphoto (lo|khicho)\b", t):
            return _turn("Smile! 3, 2, 1.", [("capture_photo", {"countdown_seconds": 3})], prefs)
        if re.search(r"\bzoom (in|out)\b", t):
            d = "out" if "zoom out" in t else "in"
            return _turn(f"Zoomed {d}.", [("set_tryon_zoom", {"direction": d})], prefs)

    return None
