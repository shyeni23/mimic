"""
Proactive (non-speech-triggered) agent reactions.

Everything built so far is REACTIVE: user speaks -> agent responds. This adds
the other half -- specific SYSTEM EVENTS (scan finished, item lingered on,
etc.) that should make Aria react on her own, without anyone saying anything.

Mechanism: when an event fires, we hand the agent a synthetic instruction
(never shown to the user, not a real "message") describing what just
happened, and let it decide -- using the exact same tools/persona as normal
chat -- what to say and do about it. This keeps ONE agent brain for both
reactive and proactive behavior, instead of maintaining two separate systems.
"""

EVENT_TRIGGERS = {
    "conversation_start": (
        "[SYSTEM EVENT -- not something the customer said] Someone just stepped in "
        "front of the mirror and this is the very first moment of a brand new "
        "conversation -- you have no history with them yet (no scan, no prior "
        "chat). Greet them warmly and briefly, like a friendly stylist noticing "
        "someone walk up, and ask a light, open question to get things going -- "
        "e.g. what they're getting ready for today, or what brings them in. Do "
        "NOT call trigger_body_scan, recommend_clothes, or any other tool yet -- "
        "just open the conversation naturally with words, nothing else."
    ),
    "scan_complete": (
        "[SYSTEM EVENT -- not something the customer said] A body scan for this "
        "customer just finished processing. React naturally and briefly, like you "
        "just glanced over and noticed something about them -- don't announce that "
        "a 'scan' happened, that's invisible to them. Then CALL recommend_clothes "
        "NOW -- do not ask anything first. Set `occasion` to the occasion they "
        "told you earlier in this conversation (check WHAT YOU ALREADY KNOW and "
        "the chat history); leave it empty only if they never mentioned one. "
        "Leave `include` empty -- this first set is CLOTHES ONLY; accessories "
        "come later, once they like a piece. Talk about the picks briefly as "
        "outfits for their occasion rather than listing items one by one, and "
        "tell them to tap the heart on anything they like. Call get_body_profile "
        "first only if you genuinely need the scan details to say something "
        "specific."
    ),
    # Formatted with the liked item's details (see routers/agent_events.py).
    "item_liked": (
        "[SYSTEM EVENT -- not something the customer said] The customer just "
        "liked this item on screen: {item_name} ({item_category}) [id: {item_id}]. "
        "React warmly in one short line, then ASK whether they'd like you to "
        "find accessories to go with it (shoes, a bag, jewellery). Do NOT call "
        "any tool yet -- wait for their answer. If they say yes on the next "
        "turn, call complete_outfit with item_id {item_id}. If this item is "
        "itself an accessory (footwear, bag, watch, jewellery), just acknowledge "
        "it briefly instead of offering accessories."
    ),
    "recommendations_idle": (
        "[SYSTEM EVENT] The customer has been looking at recommendations for a while "
        "without saying anything. Offer a light, non-pushy nudge -- e.g. point out "
        "your favorite from the set and why, or ask if they want to see something "
        "different. Keep it brief and casual, not salesy."
    ),
    "item_focused_long": (
        "[SYSTEM EVENT] The customer has been focused on one specific item for a "
        "while without saying anything. React as if you noticed them looking at it -- "
        "share a quick opinion or styling tip on that item, or ask if they'd like to "
        "see it on / add it to their fitting room."
    ),
    "cart_item_added": (
        "[SYSTEM EVENT -- not something the customer said] The customer just added "
        "an item to their cart on their own. React like a shop friend who noticed -- "
        "briefly acknowledge, then offer something that would go with it (a bottom for a "
        "top, a bag/watch for a dress, a bag+shoes for an outfit). Use search_inventory "
        "to find something that pairs. Keep it low-pressure -- one suggestion, not a pitch."
    ),
    "skipped_multiple": (
        "[SYSTEM EVENT] The customer has skipped/dismissed several recent recommendations "
        "in a row -- what you've been suggesting isn't landing. Do NOT just pull more "
        "of the same. Instead, name what you're noticing ('looks like the fitted "
        "styles aren't hitting -- want to try something more relaxed?') and offer a "
        "clearly different direction (different silhouette, color family, or formality "
        "level). If you're unsure what to pivot to, ask one open question about what "
        "they'd rather see. Never sound salesy."
    ),
    "long_pause": (
        "[SYSTEM EVENT] The customer hasn't spoken in a while but is still standing "
        "at the mirror. Softly check in -- a light, non-pushy 'still there? any of these "
        "catching your eye?' -- so they know you're available without pressuring. If "
        "conversation history shows a goal they had (occasion, style), gently remind "
        "them where you left off. Keep it short."
    ),
}

# Which events are safe to fire for which role -- keeps proactive behavior
# scoped the same way reactive tools are (see tools.py CUSTOMER_TOOLS/ADMIN_TOOLS).
ALLOWED_EVENTS_BY_ROLE = {
    "customer": {
        "conversation_start", "scan_complete", "item_liked", "recommendations_idle",
        "item_focused_long", "cart_item_added", "skipped_multiple", "long_pause",
    },
    "admin": set(),  # no proactive admin events defined yet
}


def get_trigger_message(event: str, role: str, context: dict | None = None) -> str | None:
    if event not in ALLOWED_EVENTS_BY_ROLE.get(role, set()):
        return None
    message = EVENT_TRIGGERS.get(event)
    if message and event == "item_liked":
        ctx = context or {}
        if not ctx.get("item_id"):
            return None
        message = message.format(
            item_id=ctx["item_id"],
            item_name=ctx.get("name") or "an item",
            item_category=ctx.get("category") or "item",
        )
    return message
