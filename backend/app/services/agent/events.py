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
        "a 'scan' happened, that's invisible to them. Then decide: if it feels right, "
        "go ahead and show them some recommendations now; otherwise ask what they're "
        "dressing for so you can tailor it. Call get_body_profile first if you need it."
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
}

# Which events are safe to fire for which role -- keeps proactive behavior
# scoped the same way reactive tools are (see tools.py CUSTOMER_TOOLS/ADMIN_TOOLS).
ALLOWED_EVENTS_BY_ROLE = {
    "customer": {"conversation_start", "scan_complete", "recommendations_idle", "item_focused_long"},
    "admin": set(),  # no proactive admin events defined yet
}


def get_trigger_message(event: str, role: str) -> str | None:
    if event not in ALLOWED_EVENTS_BY_ROLE.get(role, set()):
        return None
    return EVENT_TRIGGERS.get(event)
