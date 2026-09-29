"""
Bridges the agent's tool calls to actual UI actions in the React frontend.

The chat flow is still request/reply (user speaks -> POST /api/chat -> agent
replies) -- there's no need for websockets here, because every action is
triggered BY a user's voice turn, not pushed spontaneously. So instead of a
persistent connection, each /api/chat response carries an `actions` list
alongside the spoken `reply`. The frontend executes those actions (navigate,
start camera, show a product, etc.) right after playing the TTS reply.

Tools that should DO something (not just look something up) call
queue_action() during the agent's turn; the router collects and returns
them. This uses a contextvar so it's safe even if multiple requests are
being handled concurrently by the server.
"""
import contextvars
from typing import Literal

ActionType = Literal[
    # Navigation (works today, no data dependency)
    "navigate",               # go to any of the 11 known routes
    "repeat_last_reply",

    # Module 1 (works today, real data)
    "start_scan",
    "show_recommendations",
    "show_item",
    "start_tryon",            # Module 5 hook, no-op until try-on exists

    # Human-in-the-loop escalation -- real: persists a staff_requests row
    # (see app/db/supabase_client.py::create_staff_request) for a human to act on.
    "escalate_to_staff",

    # OutfitBuilder.js -- works today against ITEMS_DATA (frontend-local, not real inventory)
    "select_outfit_category", # switch category tab: top/bottom/shoes/bag/watch/accessories
    "set_outfit_item",        # select an item within the current category by name match
    "remove_outfit_item",     # clear a filled slot by category
    "set_outfit_name",
    "save_outfit",            # currently only plays a save animation -- not persisted anywhere yet

    # Shopping.js -- CAUTION: operates on hardcoded mock products, NOT the real Supabase inventory.
    # See Module 2 addendum "Data Model Gap" section before relying on these for real orders.
    "search_shopping",
    "filter_shopping",        # All / New Arrivals / Trending / Sale
    "add_to_cart",
    "remove_from_cart",
    "update_cart_quantity",
    "toggle_wishlist",
    "open_cart",
    "close_cart",
    "reserve_in_store",       # currently a no-op in the frontend -- flagged, not yet wired to anything
    "checkout",               # currently a no-op in the frontend -- flagged, not yet wired to anything

    # Personalization.js -- CAUTION: weather/wardrobe/color/AI-insight data is hardcoded, not real yet
    "refresh_recommendations",
    "rate_recommendation",    # star rating on a specific AI insight card
    "recommendation_feedback",# thumbs up/down on a specific AI insight card
    "submit_overall_rating",

    # Profile.js -- measurements are LOCAL ONLY, not synced with the real scans table yet
    "edit_profile",
    "save_profile",
    "update_profile_field",   # name / email / location
    "edit_measurements",
    "save_measurements",
    "update_measurement",     # height / weight / chest / waist / hips
    "toggle_style_tag",
    "delete_saved_outfit",

    # Settings.js -- toggle actions work today but are NOT persisted anywhere (reset on reload)
    "toggle_theme",
    "toggle_notification_setting",
    "toggle_privacy_setting",
    "change_language",
    "admin_logout",           # this one IS real -- calls the actual AuthContext.logout()

    # Admin-only
    "admin_update_stock",
    "admin_show_analytics",
]

_action_queue: contextvars.ContextVar[list] = contextvars.ContextVar("action_queue", default=None)


def start_turn():
    """Call once at the start of each agent turn to reset the queue."""
    _action_queue.set([])


def queue_action(action_type: ActionType, payload: dict | None = None):
    queue = _action_queue.get()
    if queue is None:
        queue = []
        _action_queue.set(queue)
    queue.append({"type": action_type, "payload": payload or {}})


def get_queued_actions() -> list[dict]:
    return _action_queue.get() or []
