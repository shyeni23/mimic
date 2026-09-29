from pydantic import BaseModel


class ScanResponse(BaseModel):
    session_id: str
    body_shape: str
    body_shape_confidence: float
    body_shape_reason: str
    face_shape: str
    face_shape_confidence: float
    face_shape_reason: str
    skin_tone_hex: str | None
    skin_tone_depth: str
    skin_tone_undertone: str
    size_estimate: str
    height_cm: float | None
    height_source: str          # "spoken" | "camera"
    height_confidence: float
    glasses_detected: bool
    hair_length: str            # "short" | "medium" | "long" | "unknown"
    gender: str                 # "male" | "female" | "unknown"
    gender_confidence: float


class ScanGenderRequest(BaseModel):
    session_id: str
    gender: str   # 'male' | 'female' | 'unknown' (unknown = show both departments)


class CalibrationRequest(BaseModel):
    pixel_height: float   # top-of-head to ankle, in pixels, from a known-height reference person
    real_height_cm: float


class RecommendRequest(BaseModel):
    session_id: str
    occasion: str | None = None
    category: str | None = None
    # grouped=True (and no category) returns the post-scan "complete look":
    # one short ranked list PER category (tops, bottoms, dresses, footwear,
    # bags, watches, jewellery, accessories) as `sections`, plus a
    # round-robin flattened `results`. See inventory_search.recommend_complete_look.
    grouped: bool = False
    per_category: int = 3
    # Item types she named ("saree", "heels") -> only those are shown. None =
    # use what the conversation saved (shopping_intent.py); [] = no narrowing.
    requested_items: list[str] | None = None
    # Which item categories the customer actually wants shown, e.g.
    # ["dress", "bag", "footwear"] -- nothing else is built. Empty/None =
    # the full look. `items_text` is the raw answer to "what should I
    # include?" and is parsed server-side (parse_requested_items) so the
    # frontend and the agent don't each need their own vocabulary.
    include: list[str] | None = None
    items_text: str | None = None
    # True when the customer named the occasion herself -- every group is
    # then hard-filtered to it instead of treating it as a preference.
    strict_occasion: bool = False


class ChatRequest(BaseModel):
    session_id: str
    message: str
    role: str = "customer"   # "customer" | "admin" -- controls which tools/actions the agent may use


class AgentEventRequest(BaseModel):
    session_id: str
    event: str                # e.g. "scan_complete", "recommendations_idle", "item_focused_long"
    role: str = "customer"
    context: dict = {}        # event details, e.g. item_liked -> {item_id, name, category}


class UIAction(BaseModel):
    type: str
    payload: dict = {}


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    extracted_context: dict | None = None
    actions: list[UIAction] = []
    preferences: dict = {}   # structured conversation state (occasion, style, colors...) -- see agent/preferences.py


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None


class StaffRequestStatusUpdate(BaseModel):
    status: str   # "pending" | "acknowledged" | "resolved"
