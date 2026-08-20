"""
Tools available to the agent -- split by ROLE, since a customer and an admin
should be able to trigger very different things hands-free.

Two kinds of tools here:
1. READ tools: look something up, return data to the LLM.
2. ACTION tools: also call queue_action() to tell the frontend to DO
   something (navigate, start the camera, show a product...). These are
   what make the agent actually *drive the mirror app*, not just talk about it.

Scope reminder: every action queued here is an app-level UI action, executed
by the React frontend. Nothing here touches the OS, filesystem, or anything
outside the smart mirror application itself.
"""
import json
from typing import Optional
from langchain_core.tools import tool

from app.db.supabase_client import get_latest_scan, get_inventory
from app.services.fashion.inventory_search import recommend_items
from app.services.vision.skin_tone import recommended_palette
from app.services.agent.actions import queue_action
from app.services.agent.preferences import record_preference_update


# ---------------- Conversation-state tool (customer role) ----------------

@tool
def update_preferences(
    occasion: str = "",
    style: str = "",
    design_preference: str = "",
    color_preference: Optional[list[str]] = None,
    notes: str = "",
) -> str:
    """Quietly record or update what you've learned about the customer's
    styling preferences so far -- call this in the background whenever they
    reveal something relevant, without announcing it or treating it as a
    form. Only pass fields that are new or have changed; leave the rest out.
    occasion: what they're dressing for (e.g. 'engagement', 'wedding', 'office').
    style: overall style direction (e.g. 'traditional', 'modern', 'casual').
    design_preference: how bold/subtle/heavy they want it (e.g. 'light', 'minimal', 'statement').
    color_preference: any colors they like, as a list (e.g. ['pastel', 'gold']).
    notes: anything else worth remembering that doesn't fit the fields above."""
    updates = {}
    if occasion:
        updates["occasion"] = occasion
    if style:
        updates["style"] = style
    if design_preference:
        updates["design_preference"] = design_preference
    if color_preference:
        updates["color_preference"] = color_preference
    if notes:
        updates["notes"] = notes
    record_preference_update(updates)
    return json.dumps({"status": "recorded", "updates": updates})


# ---------------- READ tools (available to both roles) ----------------

@tool
def get_body_profile(session_id: str) -> str:
    """Get the customer's most recently scanned body shape, face shape, skin tone,
    height, glasses, and hair length for this session. Call this before recommending
    clothes if you don't already have the customer's profile in context."""
    scan = get_latest_scan(session_id)
    if not scan:
        return json.dumps({
            "error": "No scan found for this session.",
            "instruction": (
                "Do not call this tool again in this turn. If you already called "
                "trigger_body_scan, the scan will not be ready instantly -- it "
                "requires the customer to physically step in front of the mirror "
                "camera, which takes real time. Just continue the conversation "
                "naturally and mention you're ready whenever they're in view."
            ),
        })
    return json.dumps({
        "body_shape": scan.get("body_shape"),
        "face_shape": scan.get("face_shape"),
        "skin_tone_category": scan.get("skin_tone_category"),
        "skin_tone_undertone": scan.get("skin_tone_undertone"),
        "body_size_estimate": scan.get("body_size_estimate"),
        "height_cm": scan.get("height_cm"),
        "height_source": scan.get("height_source"),
        "glasses_detected": scan.get("glasses_detected"),
        "hair_length": scan.get("hair_length"),
    })


@tool
def search_inventory(category: str = "") -> str:
    """List available inventory items, optionally filtered by category
    (top, bottom, dress, footwear, bag, jewelry, watch, accessory)."""
    items = get_inventory(category=category or None)
    trimmed = [
        {"id": i["id"], "name": i["name"], "category": i["category"], "color": i.get("color"), "price": i.get("price")}
        for i in items[:20]
    ]
    return json.dumps(trimmed)


@tool
def get_color_palette(skin_depth: str, undertone: str) -> str:
    """Get the flattering color palette for a given skin depth (fair/light/medium/tan/deep)
    and undertone (warm/cool/neutral)."""
    return json.dumps({"palette": recommended_palette(skin_depth, undertone)})


@tool
def get_weather(location: str) -> str:
    """Get current weather for a location, used to adjust clothing recommendations.
    Placeholder until Module 4 wires OPENWEATHER_API_KEY."""
    return json.dumps({"note": "Weather integration lands in Module 4.", "location": location})


# ---------------- ACTION tools (customer role) ----------------

@tool
def trigger_body_scan() -> str:
    """Start the camera body scan flow hands-free -- use this when the customer asks to
    be scanned/analyzed, or when recommending clothes requires a scan that doesn't exist yet."""
    queue_action("start_scan")
    return json.dumps({
        "status": "scan_triggered",
        "instruction": (
            "The scan is starting on screen now but will NOT have results yet -- "
            "do not call get_body_profile again this turn. Just tell the customer "
            "you're pulling up the camera and keep the conversation going."
        ),
    })


@tool
def recommend_clothes(session_id: str, occasion: str = "", category: str = "") -> str:
    """Recommend clothing items for the customer based on their scanned profile and the
    given occasion, AND bring up the recommendations on screen for them hands-free."""
    scan = get_latest_scan(session_id)
    if not scan:
        queue_action("start_scan")
        return json.dumps({
            "error": "No body scan available yet -- triggering a scan now.",
            "instruction": (
                "Do not call get_body_profile or recommend_clothes again this turn -- "
                "the scan needs the customer to step in front of the camera first. "
                "Just tell them you're pulling up the scan and keep talking."
            ),
        })

    result = recommend_items(
        depth=scan.get("skin_tone_category", "medium"),
        undertone=scan.get("skin_tone_undertone", "neutral"),
        body_shape=scan.get("body_shape", "unknown"),
        occasion=occasion or None,
        category=category or None,
        height_cm=scan.get("height_cm"),
        glasses_detected=scan.get("glasses_detected", False),
        hair_length=scan.get("hair_length", "unknown"),
    )
    queue_action("show_recommendations", {"occasion": occasion, "category": category, "results": result.get("results", [])})
    return json.dumps(result)


@tool
def show_item_detail(item_id: str) -> str:
    """Bring a specific inventory item into focus on screen -- use when the customer
    refers to a specific item ("show me that blue one", "tell me more about the dress")."""
    queue_action("show_item", {"item_id": item_id})
    return json.dumps({"status": "item_focused", "item_id": item_id})


@tool
def start_virtual_tryon(item_id: str) -> str:
    """Start virtual try-on for a specific item. NOTE: Module 5 (AR try-on) isn't built
    yet -- this queues the UI action so the frontend can show a 'coming soon' state,
    and will drive the real try-on once IDM-VTON/CatVTON is integrated."""
    queue_action("start_tryon", {"item_id": item_id})
    return json.dumps({"status": "tryon_requested", "item_id": item_id, "note": "Module 5 not yet implemented"})


@tool
def add_item_to_cart(item_id: str) -> str:
    """Add an item to the customer's cart/fitting room hands-free."""
    queue_action("add_to_cart", {"item_id": item_id})
    return json.dumps({"status": "added_to_cart", "item_id": item_id})


# ---------------- ACTION tools: navigation ----------------

@tool
def navigate_to_page(page: str) -> str:
    """Navigate hands-free to a screen of the app. Valid values: dashboard, body-scanner,
    analysis-results, recommendations, stylist, outfit-builder, virtual-tryon,
    personalization, shopping, profile, settings."""
    queue_action("navigate", {"page": page})
    return json.dumps({"status": "navigated", "page": page})


# ---------------- ACTION tools: OutfitBuilder.js ----------------

@tool
def select_outfit_category(category: str) -> str:
    """Switch the active category tab in the Outfit Builder. One of:
    top, bottom, shoes, bag, watch, accessories."""
    queue_action("select_outfit_category", {"category": category})
    return json.dumps({"status": "category_selected", "category": category})


@tool
def set_outfit_item(category: str, item_description: str) -> str:
    """Select an item within a category of the Outfit Builder by describing it
    (e.g. category='top', item_description='denim jacket'). NOTE: this matches
    against a fixed local demo item list, not the real store inventory."""
    queue_action("set_outfit_item", {"category": category, "item_description": item_description})
    return json.dumps({"status": "item_set", "category": category, "item_description": item_description})


@tool
def remove_outfit_item(category: str) -> str:
    """Clear the item currently in a given Outfit Builder slot/category."""
    queue_action("remove_outfit_item", {"category": category})
    return json.dumps({"status": "item_removed", "category": category})


@tool
def save_current_outfit(outfit_name: str = "") -> str:
    """Save the outfit currently being built. NOTE: as of this build this only
    triggers a save animation in the UI -- it is not yet persisted to any database."""
    if outfit_name:
        queue_action("set_outfit_name", {"name": outfit_name})
    queue_action("save_outfit")
    return json.dumps({"status": "save_triggered", "note": "not yet persisted to a database"})


# ---------------- ACTION tools: Shopping.js ----------------
# CAUTION: Shopping.js currently operates on a hardcoded mock product catalog,
# NOT the real Supabase inventory used by recommend_clothes(). An item id here
# refers to the mock catalog (numeric 1-12), not a real inventory UUID, until
# that data-model gap is closed (see Module 2 addendum).

@tool
def search_shopping_catalog(query: str) -> str:
    """Search the Shopping page's product catalog by name or brand."""
    queue_action("search_shopping", {"query": query})
    return json.dumps({"status": "search_applied", "query": query})


@tool
def filter_shopping_catalog(filter_name: str) -> str:
    """Filter the Shopping page catalog. One of: All, New Arrivals, Trending, Sale."""
    queue_action("filter_shopping", {"filter": filter_name})
    return json.dumps({"status": "filter_applied", "filter": filter_name})


@tool
def toggle_wishlist_item(item_id: str) -> str:
    """Add or remove an item from the customer's wishlist on the Shopping page."""
    queue_action("toggle_wishlist", {"item_id": item_id})
    return json.dumps({"status": "wishlist_toggled", "item_id": item_id})


@tool
def update_cart_item_quantity(item_id: str, delta: int) -> str:
    """Increase or decrease the quantity of an item already in the cart. delta is +1 or -1."""
    queue_action("update_cart_quantity", {"item_id": item_id, "delta": delta})
    return json.dumps({"status": "quantity_updated", "item_id": item_id, "delta": delta})


@tool
def open_shopping_cart() -> str:
    """Open the cart sidebar on the Shopping page."""
    queue_action("open_cart")
    return json.dumps({"status": "cart_opened"})


# ---------------- ACTION tools: Personalization.js ----------------
# CAUTION: weather, wardrobe stats, favorite colors, and "AI insight" cards on
# this page are currently hardcoded demo data, not derived from real scans,
# real weather, or a real feedback-learning system (that's Module 4 scope).

@tool
def refresh_personalized_recommendations() -> str:
    """Trigger a refresh of the AI insight cards on the Personalization page."""
    queue_action("refresh_recommendations")
    return json.dumps({"status": "refresh_triggered"})


@tool
def rate_ai_insight(insight_id: str, stars: int) -> str:
    """Give a star rating (1-5) to one of the AI insight cards on the Personalization page."""
    queue_action("rate_recommendation", {"insight_id": insight_id, "stars": stars})
    return json.dumps({"status": "rated", "insight_id": insight_id, "stars": stars})


# ---------------- ACTION tools: Profile.js ----------------
# CAUTION: measurements here are stored locally in this page's React state only --
# NOT synced with the real height_cm captured by the body scan (scans table).
# A good future integration: prefill this from the latest scan instead of static demo data.

@tool
def update_profile_measurement(measurement_id: str, value: str) -> str:
    """Update a measurement on the Profile page. measurement_id is one of:
    height, weight, chest, waist, hips."""
    queue_action("update_measurement", {"measurement_id": measurement_id, "value": value})
    return json.dumps({"status": "measurement_updated", "measurement_id": measurement_id, "value": value})


@tool
def toggle_style_preference_tag(tag: str) -> str:
    """Toggle a style preference tag on the Profile page (e.g. 'Minimalist', 'Streetwear')."""
    queue_action("toggle_style_tag", {"tag": tag})
    return json.dumps({"status": "tag_toggled", "tag": tag})


# ---------------- ACTION tools: Settings.js ----------------

@tool
def toggle_app_theme() -> str:
    """Switch the mirror display between light and dark mode."""
    queue_action("toggle_theme")
    return json.dumps({"status": "theme_toggled"})


@tool
def toggle_notification_preference(setting_key: str) -> str:
    """Toggle a notification setting. One of: email, push, sound, outfitReminders,
    weatherAlerts, promotions, weeklyDigest. NOTE: not yet persisted across reloads."""
    queue_action("toggle_notification_setting", {"key": setting_key})
    return json.dumps({"status": "setting_toggled", "key": setting_key})


CUSTOMER_TOOLS = [
    update_preferences,
    get_body_profile, search_inventory, get_color_palette, get_weather,
    trigger_body_scan, recommend_clothes, show_item_detail, start_virtual_tryon, add_item_to_cart,
    navigate_to_page,
    select_outfit_category, set_outfit_item, remove_outfit_item, save_current_outfit,
    search_shopping_catalog, filter_shopping_catalog, toggle_wishlist_item,
    update_cart_item_quantity, open_shopping_cart,
    refresh_personalized_recommendations, rate_ai_insight,
    update_profile_measurement, toggle_style_preference_tag,
    toggle_app_theme, toggle_notification_preference,
]


# ---------------- ACTION tools (admin role only) ----------------

@tool
def admin_update_stock(item_id: str, new_stock: int) -> str:
    """ADMIN ONLY: update the stock count for an inventory item hands-free."""
    from app.db.supabase_client import get_supabase
    sb = get_supabase()
    res = sb.table("inventory").update({"stock": new_stock}).eq("id", item_id).execute()
    queue_action("admin_update_stock", {"item_id": item_id, "new_stock": new_stock})
    return json.dumps({"status": "updated", "item": res.data[0] if res.data else None})


@tool
def admin_show_analytics(session_id: str) -> str:
    """ADMIN ONLY: bring up session/conversation analytics on screen hands-free."""
    from app.db.supabase_client import get_conversation_history
    history = get_conversation_history(session_id, limit=50)
    queue_action("admin_show_analytics", {"session_id": session_id, "turn_count": len(history)})
    return json.dumps({"status": "analytics_shown", "turn_count": len(history)})


@tool
def admin_logout_action() -> str:
    """ADMIN ONLY: end the current admin shift and log out, hands-free.
    This is a real action -- it calls the app's actual AuthContext logout()."""
    queue_action("admin_logout")
    return json.dumps({"status": "logout_triggered"})


ADMIN_TOOLS = CUSTOMER_TOOLS + [admin_update_stock, admin_show_analytics, admin_logout_action]

# Kept for anything importing the old flat list -- defaults to customer scope.
ALL_TOOLS = CUSTOMER_TOOLS
