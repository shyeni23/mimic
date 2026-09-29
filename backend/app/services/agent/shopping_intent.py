"""
Deterministic handling of shopping requests and "thanks" -- works with no LLM.

Rules (user-specified):
- "I'm looking for X" before any scan -> Aria remembers the request and opens
  the body-scan page first, so her picks fit the body shape and skin tone.
- The request narrows the picks to ONLY what was asked: "saree" shows sarees,
  not kurtis. The item words and occasion are saved into the conversation
  preferences (`requested_items`, `occasion`), which /api/recommend reads, so
  the post-scan page shows the same narrowed set.
- After the scan, a request is answered directly with those items.
- "Thanks" / "that's all" -> a warm goodbye and the chat ends.

Shopping requests never go through the LLM: its recommend tool builds a
whole look (tops, bottoms, accessories...), which is exactly the "I asked
for a saree and got kurtis too" problem.
"""
import random
import re

from app.services.agent.actions import start_turn, queue_action, get_queued_actions
from app.services.agent.preferences import merge_preferences

_GARMENT_RE = re.compile(
    r"\b("
    r"dress(?:es)?|gowns?|sarees?|saris?|lehengas?|lehnga|kurtas?|kurtis?|salwar|churidar|dupattas?|anarkali"
    r"|sherwanis?|suits?|blazers?|jackets?|coats?|shirts?|t-?shirts?|tops?|blouses?|tunics?|sweaters?|hoodies?"
    r"|jeans|trousers|pants|skirts?|shorts|leggings|palazzos?|jumpsuits?|co-?ords?"
    r"|shoes|heels|sandals|flats|sneakers|boots|footwear|loafers|slippers|juttis?"
    r"|bags?|handbags?|clutch(?:es)?|purses?|wallets?|watch(?:es)?|jewell?ery|earrings|necklaces?"
    r"|bangles?|bracelets?|rings?|belts?|sunglasses|scarf|scarves|ties?|accessor(?:y|ies)"
    r"|outfits?|clothes|clothing|attire"
    r")\b",
    re.IGNORECASE,
)
_SHOPPING_RE = re.compile(
    r"\b(looking\s+for|look\s+for|shopping\s+for|searching\s+for|need|want|show\s+me|find|buy"
    r"|get\s+me|suggest|recommend|something|wear)\b",
    re.IGNORECASE,
)
_OCCASION_RE = re.compile(
    r"\b(wedding|marriage|engagement|anniversary|reception|sangeet|mehendi|haldi|party|birthday"
    r"|office|work|meeting|interview|formal|casual|ethnic|traditional|festival|festive|diwali|eid"
    r"|puja|pooja|date|dinner|travel|trip|vacation|holiday|gym|sports?|college|function|brunch|beach)\b",
    re.IGNORECASE,
)
_CLOSING_RE = re.compile(
    r"\b(thanks?|thank\s*(?:you|u)|thx|ty|that'?s\s+all|that'?s\s+it|bye|good\s*bye|see\s+you)\b",
    re.IGNORECASE,
)
_GOODBYES = [
    "You're very welcome! It was lovely styling you today. Enjoy your shopping!",
    "My pleasure! You're going to look wonderful. Have a lovely day!",
    "You're welcome! Come back anytime you need a stylist. Take care!",
]
# Occasions the catalog has no tag for -> the closest one it has.
_OCCASION_ALIASES = {"anniversary": "party"}


def parse_shopping_request(text: str) -> dict | None:
    """{"garments": [...], "occasion": str|None} if `text` asks for items,
    else None. Needs a garment word, or a shopping verb plus an occasion
    ("I need something for a wedding")."""
    if not text:
        return None
    garments = []
    for g in _GARMENT_RE.findall(text):
        if g.lower() not in garments:
            garments.append(g.lower())
    occ = _OCCASION_RE.search(text)
    occasion = occ.group(1).lower() if occ else None
    if garments or (occasion and _SHOPPING_RE.search(text)):
        return {"garments": garments, "occasion": occasion}
    return None


def is_closing(text: str) -> bool:
    """'thanks', 'thank you for recommending', "that's all" -- but not
    'thanks, now show me shoes' (a new request)."""
    return bool(text and len(text.split()) <= 12 and _CLOSING_RE.search(text)
                and not _SHOPPING_RE.search(text))


def _describe(req: dict) -> str:
    what = " and ".join(req["garments"][:2]) if req["garments"] else "outfit"
    return f"{req['occasion']} {what}" if req["occasion"] else what


def _prefs_with_request(prior: dict, text: str, req: dict) -> dict:
    delta = {"notes": text.strip()}
    if req["occasion"]:
        delta["occasion"] = _OCCASION_ALIASES.get(req["occasion"], req["occasion"])
    prefs = merge_preferences(prior or {}, delta)
    prefs.pop("conversation_ended", None)
    # Always overwritten (merge_preferences skips []): a new request replaces
    # the last one instead of piling up "saree" + "shoes" + ...
    prefs["requested_items"] = req["garments"]
    return prefs


def _build_look(session_id: str, prefs: dict) -> dict | None:
    """/api/recommend's own result for these preferences, or None."""
    from app.routers.recommend import recommend
    from app.models.schemas import RecommendRequest
    try:
        look = recommend(RecommendRequest(
            session_id=session_id, grouped=True, occasion=prefs.get("occasion"),
            requested_items=prefs.get("requested_items") or [],
        ))
    except Exception as e:
        print(f"[shopping_intent] recommendations failed (non-fatal): {e}")
        return None
    return look if look.get("results") else None


def _show_look(session_id: str, prefs: dict, lead: str) -> str:
    """Queue the recommendations and return the sentence that introduces them."""
    look = _build_look(session_id, prefs)
    if not look:
        queue_action("navigate", {"page": "recommendations"})
        return f"{lead} Here are my picks, chosen for your body shape and skin tone."
    queue_action("show_recommendations", {"results": look["results"], "sections": look.get("sections")})
    if look.get("mode") == "requested_items":
        labels = " and ".join(s["label"].lower() for s in look["sections"])
        occ = f" for your {prefs['occasion']}" if prefs.get("occasion") else ""
        return f"{lead} Here are {len(look['results'])} {labels}{occ}, picked for your body shape and skin tone."
    return f"{lead} Here's a look picked for your body shape and skin tone."


def scan_first_turn(session_id: str, text: str, prior_preferences: dict, has_scan: bool) -> dict | None:
    """Shopping request + no scan yet -> open the scanner. None otherwise."""
    req = parse_shopping_request(text)
    if not req or has_scan:
        return None
    start_turn()
    queue_action("start_scan", {})
    desc = _describe(req)
    article = "an" if desc[:1] in "aeiou" else "a"
    reply = (f"Lovely, {article} {desc}! Let me do a quick body scan first so I can pick "
             f"ones that suit your body shape and skin tone. Please stand in front of the mirror.")
    return {"reply": reply, "actions": get_queued_actions(),
            "preferences": _prefs_with_request(prior_preferences, text, req)}


def show_request_turn(session_id: str, text: str, prior_preferences: dict) -> dict | None:
    """Shopping request after the scan -> show exactly what was asked for."""
    req = parse_shopping_request(text)
    if not req:
        return None
    prefs = _prefs_with_request(prior_preferences, text, req)
    start_turn()
    reply = _show_look(session_id, prefs, "Great choice!")
    return {"reply": reply, "actions": get_queued_actions(), "preferences": prefs}


def post_scan_turn(session_id: str, prefs: dict) -> dict | None:
    """scan_complete after she asked for specific items -> show only those
    (instead of the LLM's whole-look recommendation). None if she didn't."""
    if not (prefs or {}).get("requested_items"):
        return None
    start_turn()
    reply = _show_look(session_id, prefs, "Your scan is done!")
    return {"reply": reply, "actions": get_queued_actions(), "preferences": prefs}


def closing_turn(text: str) -> dict | None:
    """'thanks' -> goodbye + end the chat; preferences reset for a fresh start."""
    if not is_closing(text):
        return None
    start_turn()
    queue_action("end_conversation", {})
    return {"reply": random.choice(_GOODBYES), "actions": get_queued_actions(),
            "preferences": {"conversation_ended": True}}
