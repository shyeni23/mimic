from fastapi import APIRouter, HTTPException

from app.db.supabase_client import get_latest_scan
from app.services.fashion.inventory_search import (
    recommend_items, recommend_look_for_occasion, normalize_category, parse_requested_items,
    normalize_occasion,
)
from app.services.user_context import get_user_context
from app.models.schemas import RecommendRequest

router = APIRouter(prefix="/api/recommend", tags=["recommend (Module 1)"])


@router.post("")
def recommend(req: RecommendRequest):
    """
    Uses the customer's most recent body scan (from /api/vision/scan) plus
    the conversation's preferences (via user_context.py) to return ranked,
    explained clothing suggestions from inventory.

    req.occasion/req.category, if passed, OVERRIDE what the conversation
    said (an explicit request always wins over an inferred one) -- but
    occasion/style/constraints/size are no longer *required* from the
    caller the way occasion used to be; they're pulled from user_context.py
    automatically when the caller doesn't specify them. This closes a gap
    an audit found: user_context.py existed as the Module 1<->Module 2
    bridge, but this endpoint (built before user_context.py) was never
    updated to actually use it.
    """
    scan = get_latest_scan(req.session_id)
    if not scan:
        raise HTTPException(status_code=404, detail="No scan found for this session. Call /api/vision/scan first.")

    fashion_preferences = get_user_context(req.session_id)["fashion_preferences"]

    # Customer words -> a real catalog tag ("sister's wedding" -> wedding).
    # An explicit req.occasion the tags don't know passes through unchanged.
    occasion = (normalize_occasion(req.occasion) or req.occasion) if req.occasion else None
    conversation_occasion = False
    if not occasion:
        occasion = normalize_occasion(fashion_preferences.get("occasion"))
        conversation_occasion = occasion is not None

    from app.db.supabase_client import get_session_interaction_signals
    signals = get_session_interaction_signals(req.session_id)

    from app.routers.vision import forced_gender
    locked = forced_gender() is not None
    gender = forced_gender() or scan.get("gender")

    scan_kwargs = dict(
        depth=scan.get("skin_tone_category", "medium"),
        undertone=scan.get("skin_tone_undertone", "neutral"),
        body_shape=scan.get("body_shape", "unknown"),
        occasion=occasion,
        height_cm=scan.get("height_cm"),
        glasses_detected=scan.get("glasses_detected", False),
        hair_length=scan.get("hair_length", "unknown"),
        style=fashion_preferences.get("style"),
        constraints=fashion_preferences.get("constraints"),
        size=scan.get("body_size_estimate"),
        budget=fashion_preferences.get("budget"),
        dismissed_item_ids=signals["dismissed_item_ids"],
        # The scan's gender label (gender_detect.py ensemble, or the customer's
        # own tap on the Range chip) -- keeps a male scan out of the women's
        # department and vice versa. 'unknown' = no filtering. Store/demo mode
        # (FORCE_GENDER) overrides whatever the scan row says.
        gender=gender,
    )
    # Item selection: an explicit list wins over the free-text answer.
    include = req.include or parse_requested_items(req.items_text)
    # An occasion the caller passed, or one she told Aria in conversation, is
    # what she asked for: show only that (recommend_look_for_occasion relaxes
    # it if that would leave the page empty).
    strict_occasion = req.strict_occasion or bool(req.occasion) or conversation_occasion

    category = normalize_category(req.category)
    if req.grouped and not category:
        # The post-scan view: what suits this body, PLUS the footwear, bag,
        # watch, jewellery and accessories that finish it -- one section each.
        result = recommend_look_for_occasion(
            per_category=max(1, min(req.per_category, 6)),
            include=include, strict_occasion=strict_occasion, **scan_kwargs,
        )
    else:
        result = recommend_items(category=category, **scan_kwargs)
    # Echo the scan attributes the picks were actually derived from, so the
    # UI can say "based on your scan: ..." truthfully rather than guessing.
    result["scan_profile"] = {
        "body_shape": scan.get("body_shape"),
        "skin_tone_category": scan.get("skin_tone_category"),
        "skin_tone_undertone": scan.get("skin_tone_undertone"),
        "gender": gender,
        "gender_locked": locked,
        "body_size_estimate": scan.get("body_size_estimate"),
        "height_cm": scan.get("height_cm"),
    }
    return result
