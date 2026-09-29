"""
Deterministic handling of "I'm looking for X" requests -- works with no LLM.

Rule (user-specified): when a customer asks for any item and hasn't been
scanned yet, Aria remembers the request and opens the body-scan page first,
so the looks she picks afterwards fit the customer's body shape and skin
tone. The request's occasion is saved into the conversation preferences,
which /api/recommend already reads (user_context.py), so the post-scan
recommendations are filtered to what was asked for.

Also provides the no-LLM fallback for a shopping request when the scan
already exists but the LLM is unavailable (Groq quota): go straight to the
recommendations for that request instead of "Sorry, I hit a little snag".
"""
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


def _describe(req: dict) -> str:
    garments = req["garments"]
    what = " and ".join(garments[:2]) if garments else "outfit"
    return f"{req['occasion']} {what}" if req["occasion"] else what


def _prefs_with_request(prior: dict, text: str, req: dict) -> dict:
    delta = {"notes": text.strip()}
    if req["occasion"]:
        # Occasions the catalog has no tag for -> the closest one it has.
        delta["occasion"] = {"anniversary": "party"}.get(req["occasion"], req["occasion"])
    return merge_preferences(prior or {}, delta)


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


def offline_shopping_turn(session_id: str, text: str, prior_preferences: dict) -> dict | None:
    """LLM unavailable + shopping request with a scan -> show recommendations."""
    req = parse_shopping_request(text)
    if not req:
        return None
    start_turn()
    queue_action("navigate", {"page": "recommendations"})
    reply = f"Here are my picks for your {_describe(req)}, chosen for your body shape and skin tone."
    return {"reply": reply, "actions": get_queued_actions(),
            "preferences": _prefs_with_request(prior_preferences, text, req)}
