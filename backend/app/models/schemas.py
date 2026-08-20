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


class CalibrationRequest(BaseModel):
    pixel_height: float   # top-of-head to ankle, in pixels, from a known-height reference person
    real_height_cm: float


class RecommendRequest(BaseModel):
    session_id: str
    occasion: str | None = None
    category: str | None = None


class ChatRequest(BaseModel):
    session_id: str
    message: str
    role: str = "customer"   # "customer" | "admin" -- controls which tools/actions the agent may use


class AgentEventRequest(BaseModel):
    session_id: str
    event: str                # e.g. "scan_complete", "recommendations_idle", "item_focused_long"
    role: str = "customer"


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
