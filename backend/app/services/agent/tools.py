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

from app.db.supabase_client import get_latest_scan, get_inventory, create_staff_request
from app.services.fashion.inventory_search import recommend_items, recommend_complete_look, normalize_category
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
    # SESSION-CONTEXT RE-RANKING: report whatever the customer has spoken-
    # corrected in conversation (undertone/skin_depth), not the stale camera
    # value -- same override recommend_clothes applies. Otherwise asking
    # "what's my undertone?" right after correcting it would confusingly
    # echo back the scan's original (wrong, per the customer) answer.
    from app.services.user_context import get_user_context
    fashion_preferences = get_user_context(session_id)["fashion_preferences"]
    return json.dumps({
        "body_shape": scan.get("body_shape"),
        "face_shape": scan.get("face_shape"),
        "skin_tone_category": fashion_preferences.get("skin_depth") or scan.get("skin_tone_category"),
        "skin_tone_undertone": fashion_preferences.get("undertone") or scan.get("skin_tone_undertone"),
        "body_size_estimate": scan.get("body_size_estimate"),
        "height_cm": scan.get("height_cm"),
        "height_source": scan.get("height_source"),
        "glasses_detected": scan.get("glasses_detected"),
        "hair_length": scan.get("hair_length"),
    })


@tool
def search_inventory(session_id: str, category: str = "", query: str = "") -> str:
    """Search available inventory. Provide `category` (top, bottom, dress,
    footwear, bag, jewelry, watch, accessory) and/or a free-text `query`
    describing what the customer wants (e.g. "blue oxford shirt for office",
    "elegant black midi dress"). Uses Marqo-FashionCLIP semantic search
    when a query is given; falls back to a plain category listing otherwise.
    The returned rows are ranked by real embedding similarity to `query`,
    not by keyword matching."""
    # Capped at 8, not 20 -- this result gets injected into the agent loop's
    # message history (graph.py) and resent on every subsequent iteration of
    # the SAME turn, so its size directly multiplies against the Groq
    # account's tokens-per-minute budget. 8 real items is still plenty for
    # the model to describe options from.
    from app.services.fashion.inventory_search import semantic_search

    # Semantic path -- Marqo embeds `query` and pgvector returns the closest
    # in-stock matches. If no query text was given, synthesize one from the
    # category so the retriever still runs (and produces relevance-ranked
    # results) instead of a raw catalog dump.
    search_query = query or (f"{category} clothing" if category else "clothing")
    try:
        items = semantic_search(
            search_query, category=(category or None), top_k=8,
        )
    except Exception as e:
        print(f"[search_inventory] semantic search failed, falling back: {e}")
        items = get_inventory(category=category or None, include_embedding=False)[:8]

    trimmed = [
        {
            "id": i["id"], "name": i["name"], "category": i["category"],
            "color": i.get("color"), "price": i.get("price"),
            "similarity": round(i.get("similarity", 0), 3) if i.get("similarity") is not None else None,
        }
        for i in items[:8]
    ]
    # CROSS-TURN MEMORY: this tool has no queue_action, so the frontend never
    # renders these and never logs its own `view` events -- log server-side
    # so "add the one from earlier" works on a LATER turn, not just this one.
    from app.db.supabase_client import log_shown_items
    log_shown_items(session_id, [t["id"] for t in trimmed], "search_inventory")
    return json.dumps(trimmed)


@tool
def get_color_palette(skin_depth: str, undertone: str) -> str:
    """Get the flattering color palette for a given skin depth (fair/light/medium/tan/deep)
    and undertone (warm/cool/neutral)."""
    return json.dumps({"palette": recommended_palette(skin_depth, undertone)})


@tool
def get_weather() -> str:
    """Get the store's current weather (condition, temperature) to factor into styling advice --
    e.g. suggesting waterproof shoes on a rainy day, or breathable fabrics when it's hot. Call
    this before a recommendation if weather might reasonably change what you'd suggest."""
    from app.services.weather import get_current_weather
    weather = get_current_weather()
    if not weather:
        return json.dumps({"available": False, "note": "Weather isn't configured for this store yet."})
    return json.dumps({"available": True, **weather})


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


def _effective_gender(scan: dict) -> str | None:
    """Store/demo FORCE_GENDER beats the scan row, same as /api/recommend."""
    from app.routers.vision import forced_gender
    return forced_gender() or scan.get("gender")


@tool
def recommend_clothes(session_id: str, occasion: str = "", category: str = "", include: str = "") -> str:
    """Recommend items for the customer based on their scanned profile and the given
    occasion, AND bring them up on screen hands-free.

    occasion: what she's shopping for, in her words ("sister's wedding", "party").

    include: which item types the customer said she wants, comma-separated or in her
    own words -- "clothes", "clothes, heels", "dress, bag, heels", "everything",
    "only clothes". ONLY those are shown. Empty = clothes only (accessories are
    offered later, once she likes a piece)."""
    scan = get_latest_scan(session_id)
    if not scan:
        # No scan yet: open the scanner and nothing else. This used to also
        # queue show_recommendations with cold-start picks, and since the
        # frontend runs actions in order, that second navigate yanked her
        # straight off the scanner page to /recommendations. Recommendations
        # follow automatically once the scan completes (scan_complete event).
        queue_action("start_scan")
        return json.dumps({
            "status": "scan_triggered",
            "instruction": (
                "There is no body scan yet, so the scanner is opening on screen now. "
                "Tell her you're opening the body analysis first and her picks will "
                "appear right after it. Do not call any other tool this turn."
            ),
        })

    # style/constraints/size pulled from the conversation (via user_context.py) --
    # same Module 1 gap-fix as recommend.py's router: recommend_items() used to
    # silently ignore these even though it accepted occasion.
    from app.services.user_context import get_user_context
    from app.db.supabase_client import get_session_interaction_signals
    fashion_preferences = get_user_context(session_id)["fashion_preferences"]

    # FEEDBACK LOOP -- items the customer already dismissed this session don't
    # come back. Solves the "recommends the same skirt she just skipped" bug.
    signals = get_session_interaction_signals(session_id)

    # STAGE B -- items she's already engaged with (clicked, added to cart,
    # tried on) become the outfit ANCHOR. When she asks for "a top" and has
    # beige pants in her cart, the ranker prefers tops that visually and
    # stylistically go with those pants. Anchors are hydrated with
    # embedding/style_tags inside recommend_items so we only pay for that
    # DB round-trip when Stage B will actually run.
    anchor_items = [{"id": iid} for iid in signals.get("engaged_item_ids", [])[-5:]] or None

    # SESSION-CONTEXT RE-RANKING: a spoken correction to skin undertone/depth
    # (ConversationState.undertone/skin_depth -- see graph.py) OVERRIDES the
    # original camera scan for every recommendation from here on, same
    # pattern chat.py already uses for a spoken height correction
    # (update_scan_height). Without this, "actually I have a cool undertone"
    # would be acknowledged in the reply but silently ignored by every
    # recommend_clothes call afterward, since recommend_items() always used
    # to read straight from the scan row with no way for the conversation to
    # ever win.
    depth = fashion_preferences.get("skin_depth") or scan.get("skin_tone_category", "medium")
    undertone = fashion_preferences.get("undertone") or scan.get("skin_tone_undertone", "neutral")

    # WEATHER NUDGE (Module 4): applied automatically on every recommendation
    # rather than left to the model to remember calling get_weather first --
    # same reasoning as the skip-penalty/cart-anchor biases above, both of
    # which are also unconditional. A rainy day should bias footwear away
    # from sandals and toward waterproof options without the customer or the
    # LLM having to ask. No-ops cleanly (empty terms, no note) when weather
    # isn't configured or conditions are unremarkable -- see weather.py.
    from app.services.weather import get_current_weather, weather_style_hints
    weather = get_current_weather()
    weather_hints = weather_style_hints(weather)
    combined_constraints = list(fashion_preferences.get("constraints") or []) + weather_hints["avoid_terms"]

    # No specific category asked for (the scan_complete event, "style me",
    # "what suits me") -> the COMPLETE LOOK: one short list per category
    # (tops, bottoms, dress, footwear, bag, watch, jewellery, accessories),
    # so the screen shows an outfit plus what finishes it, not eight tops.
    # A specific category ("show me watches") -> the single ranked list.
    category = normalize_category(category)
    from app.services.fashion.inventory_search import (
        parse_requested_items, normalize_occasion, recommend_look_for_occasion, CLOTHES_CATEGORIES,
    )
    # Clothes only unless she asked for other item types -- accessories are
    # offered once she likes a piece (item_liked -> complete_outfit).
    include_cats = (parse_requested_items(include) if include else None) or list(CLOTHES_CATEGORIES)
    # The occasion she named earlier counts even if the model left the arg
    # empty, and it's mapped onto a real catalog tag ("sister's wedding" ->
    # wedding) so the strict filter can actually match something.
    occasion = normalize_occasion(occasion) or normalize_occasion(fashion_preferences.get("occasion")) or ""
    recommend_fn = recommend_items if category else recommend_look_for_occasion
    result = recommend_fn(
        depth=depth,
        undertone=undertone,
        body_shape=scan.get("body_shape", "unknown"),
        occasion=occasion or None,
        category=category,
        height_cm=scan.get("height_cm"),
        glasses_detected=scan.get("glasses_detected", False),
        hair_length=scan.get("hair_length", "unknown"),
        style=fashion_preferences.get("style"),
        constraints=combined_constraints or None,
        size=scan.get("body_size_estimate"),
        budget=fashion_preferences.get("budget"),
        dismissed_item_ids=signals["dismissed_item_ids"],
        anchor_items=anchor_items,
        extra_query_terms=weather_hints["prefer_terms"],
        session_id=session_id,
        gender=_effective_gender(scan),
        **({} if category else {"include": include_cats, "strict_occasion": bool(occasion)}),
    )
    if weather_hints["note"]:
        for item in result.get("results", []):
            if item.get("explanation"):
                item["explanation"] += f"; {weather_hints['note']}"
    queue_action("show_recommendations", {
        "occasion": occasion, "category": category,
        "requested_categories": result.get("requested_categories"),
        "results": result.get("results", []),
        # Present only for the complete look -- the page renders these as
        # headed sections and falls back to the flat grid otherwise.
        "sections": result.get("sections"),
    })
    # CROSS-TURN MEMORY: also log server-side (redundant with whatever the
    # frontend logs when it renders these on /recommendations, but keeps
    # this tool correct even if the customer is voice-only and never looks
    # at the screen -- see search_inventory's identical note).
    from app.db.supabase_client import log_shown_items
    log_shown_items(session_id, [r["id"] for r in result.get("results", []) if r.get("id")], "recommend_clothes")
    # The LLM-facing return is deliberately smaller than what queue_action just
    # sent to the UI above (which keeps the full result -- image_url,
    # explanation, etc.) -- this text gets fed back into the agent loop's
    # message history and resent on every remaining iteration of the SAME
    # turn (see graph.py), so trimming it directly cuts per-turn token cost.
    llm_facing = {"results": [
        {"id": r.get("id"), "name": r.get("name"), "category": r.get("category"),
         "color": r.get("color"), "price": r.get("price"), "within_budget": r.get("within_budget")}
        for r in result.get("results", [])[:6]
    ]}
    if weather_hints["note"]:
        llm_facing["weather_note"] = weather_hints["note"]
        llm_facing["weather_instruction"] = (
            "Weather genuinely affected this recommendation -- mention it naturally if it fits "
            "(e.g. 'it's rainy today, so I leaned toward waterproof options'). Don't force it if "
            "the reply is already getting long."
        )
    return json.dumps(llm_facing)


@tool
def complete_outfit(session_id: str, item_id: str, occasion: str = "") -> str:
    """Build the REST of an outfit around one item the customer has already seen or
    picked this conversation -- fills in the missing pieces (bottom, footwear, bag,
    accessory; or just footwear/bag/accessory if the item is a dress) with items that
    actually go well with it, and shows them on screen. Use this when the customer
    says things like "complete the look", "what goes with this", "style this for me",
    or after showing/adding an item when offering to finish the outfit makes sense.
    item_id MUST be an id you already showed the customer this conversation --
    never invent one."""
    from app.services.fashion.outfit_completion import complete_outfit as build_outfit
    from app.db.supabase_client import get_session_interaction_signals

    signals = get_session_interaction_signals(session_id)
    from app.services.user_context import get_user_context
    budget = get_user_context(session_id)["fashion_preferences"].get("budget")

    result = build_outfit(
        item_id, occasion=occasion or None, budget=budget,
        dismissed_item_ids=signals["dismissed_item_ids"],
    )
    if result.get("error"):
        return json.dumps(result)

    queue_action("show_recommendations", {
        "occasion": occasion, "category": None, "results": result.get("results", []),
    })
    # CROSS-TURN MEMORY -- see search_inventory's identical note.
    from app.db.supabase_client import log_shown_items
    log_shown_items(session_id, [r["id"] for r in result.get("results", []) if r.get("id")], "complete_outfit")
    # Trimmed for the LLM-facing return -- same reasoning as recommend_clothes
    # above: this text resends on every remaining loop iteration this turn.
    # Shape kept as "results": [{"id": ...}] (not a custom "slots_filled" key)
    # so graph.py's _extract_item_ids can validate a same-turn follow-up like
    # "add the shoes to cart" against these ids exactly the way it already
    # does for search_inventory/recommend_clothes results.
    llm_facing = {
        "primary_item": result["primary_item"]["name"],
        "results": [
            {"id": r.get("id"), "slot": r["slot"], "name": r["name"],
             "color": r.get("color"), "price": r.get("price")}
            for r in result.get("results", [])
        ],
        "slots_missing": result.get("slots_missing", []),
    }
    return json.dumps(llm_facing)


@tool
def show_item_detail(item_id: str) -> str:
    """Bring a specific inventory item into focus on screen -- use when the customer
    refers to a specific item ("show me that blue one", "tell me more about the dress")."""
    queue_action("show_item", {"item_id": item_id})
    return json.dumps({"status": "item_focused", "item_id": item_id})


@tool
def explain_recommendation(session_id: str, item_id: str) -> str:
    """Give a richer, specific explanation for why THIS particular item was recommended --
    use when the customer directly asks "why this one?", "why did you pick this?", or seems
    unconvinced and wants real reasoning beyond what you've already said. This is a genuine
    LLM-generated rationale (a few seconds slower than a normal reply), so only call it when
    the customer is actually asking for deeper reasoning on ONE specific item -- not for every
    item in a list. item_id MUST be one you already showed the customer this conversation."""
    from app.db.supabase_client import get_supabase
    from app.services.user_context import get_user_context
    from app.services.fashion.llm_explain import generate_llm_rationale

    item = get_supabase().table("inventory").select("id,name,category,color,style_tags").eq("id", item_id).limit(1).execute().data
    if not item:
        return json.dumps({"error": "item not found"})
    item = item[0]

    ctx = get_user_context(session_id)
    fashion_preferences = ctx["fashion_preferences"]
    visual_profile = ctx["visual_profile"]
    user_context_for_llm = {
        "occasion": fashion_preferences.get("occasion"),
        "style": fashion_preferences.get("style"),
        "undertone": fashion_preferences.get("undertone") or visual_profile.get("skin_tone_undertone"),
        "body_shape": visual_profile.get("body_shape"),
    }

    rationale = generate_llm_rationale(item, user_context_for_llm)
    if not rationale:
        return json.dumps({
            "rationale": None,
            "instruction": "Rationale generation failed -- just give your best explanation "
                            "yourself based on what you already know about the customer and this item.",
        })
    return json.dumps({"rationale": rationale})


@tool
def start_virtual_tryon(item_id: str) -> str:
    """Start virtual try-on for a specific item -- still in development, so this
    shows a 'coming soon' state rather than a real try-on right now."""
    queue_action("start_tryon", {"item_id": item_id})
    return json.dumps({"status": "tryon_requested", "item_id": item_id, "note": "Module 5 not yet implemented"})


@tool
def add_item_to_cart(item_id: str) -> str:
    """Add an item to the customer's cart/fitting room hands-free."""
    queue_action("add_to_cart", {"item_id": item_id})
    return json.dumps({"status": "added_to_cart", "item_id": item_id})


# ---------------- ACTION tools: human-in-the-loop escalation ----------------

@tool
def request_staff_assistance(session_id: str, reason: str, message: str = "") -> str:
    """Escalate to a human store associate hands-free -- use for anything the agent
    isn't authorized to decide itself: discount negotiation, payment/checkout, refunds,
    complaints, stock problems, or other special requests. Never invent a discount,
    price change, or policy exception yourself -- always escalate instead."""
    row = create_staff_request(session_id, reason, message)
    queue_action("escalate_to_staff", {"reason": reason, "message": message})
    from app.services.notifications import hub
    hub.broadcast_sync("staff", {"type": "new_request", "request": row})
    return json.dumps({"status": "staff_notified", "reason": reason})


# ---------------- ACTION tools: navigation ----------------

@tool
def navigate_to_page(page: str) -> str:
    """Navigate hands-free to a screen of the app (see the `page` field's allowed values)."""
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


# ---------------- Core action-tool subset ----------------
# Deliberately NOT the full CUSTOMER_TOOLS list below. That list includes tools
# whose target pages operate on hardcoded/mock data (Shopping.js, Personalization.js,
# Profile.js, Settings.js -- see the CAUTION comments above each), plus
# update_preferences, which is dead code from the old LangGraph tool-calling loop
# and is INCOMPATIBLE with the current delta-merge extraction pipeline (it writes
# to the dormant contextvar queue in preferences.py, which nothing reads anymore).
# This subset is only the tools with real, working effects: real navigation, a
# real body scan trigger, a real recommend_items() call, real item focus/cart
# actions, and real staff escalation.
CORE_ACTION_TOOLS = [
    navigate_to_page,
    trigger_body_scan,
    recommend_clothes,
    complete_outfit,
    show_item_detail,
    explain_recommendation,
    add_item_to_cart,
    start_virtual_tryon,
    request_staff_assistance,
]

# ---------------- Tools reachable by the agent's tool-selection loop ----------------
# graph.py's run_agent_turn() binds exactly this list -- the model freely
# chooses which of these to call (see graph.py's "TOOL LOOP" module
# docstring section), not a closed action-type enum. CORE_ACTION_TOOLS above
# plus four real read tools that let the model check state before acting
# instead of guessing: search real inventory, check for an existing body
# scan, look up a flattering color palette, and check real weather (Module 4
# -- get_weather is a real OpenWeatherMap call now, see app/services/
# weather.py; recommend_clothes already applies the weather bias
# automatically on every call, so this tool is for the customer directly
# asking "what's the weather" and getting a real answer instead of the
# fast-path's "I'm not linked to live data"). Deliberately still NOT the
# full CUSTOMER_TOOLS list -- everything excluded from CORE_ACTION_TOOLS
# above (mock-data pages, dead update_preferences) is excluded here too,
# plus the admin-only tools (admin_update_stock mutates real inventory and
# deserves its own confirmation-gated design later; admin role keeps its
# current behavior unchanged for now).
LOOP_TOOLS = CORE_ACTION_TOOLS + [
    search_inventory,
    get_body_profile,
    get_color_palette,
    get_weather,
]


CUSTOMER_TOOLS = [
    update_preferences,
    get_body_profile, search_inventory, get_color_palette, get_weather,
    trigger_body_scan, recommend_clothes, show_item_detail, start_virtual_tryon, add_item_to_cart,
    request_staff_assistance,
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
