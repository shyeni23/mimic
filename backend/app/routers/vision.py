from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks

from app.services.vision.landmarks import extract_all, decode_image, extract_pose_landmarks
from app.services.vision.body_shape import classify_body_shape, estimate_body_size
from app.services.vision.face_shape import classify_face_shape
from app.services.vision.skin_tone import extract_skin_tone
from app.services.vision.height_estimate import estimate_height_from_camera, merge_height
from app.services.vision.accessory_detect import detect_glasses, detect_hair_length
from app.services.vision.gender_detect import detect_gender
from app.db.supabase_client import (
    save_scan_result, upload_media, get_mirror_calibration, set_mirror_calibration,
    update_scan_frame_url, update_scan_gender,
)
from app.models.schemas import ScanResponse, CalibrationRequest, ScanGenderRequest

router = APIRouter(prefix="/api/vision", tags=["vision (Module 1)"])


def forced_gender() -> str | None:
    """config.force_gender normalised, or None when the detector decides."""
    from app.config import settings
    from app.services.fashion.catalog_filters import normalize_gender
    g = normalize_gender(settings.force_gender)
    return g if g in ("male", "female") else None


def _upload_frame_in_background(session_id: str, frame_bytes: bytes, content_type: str):
    """Runs AFTER the scan response has already been sent to the client --
    Storage upload latency (network-dependent, can be 200ms-1s+) must never
    be on the critical path. NOTE: the scan DB row itself is NOT deferred
    here (unlike the image) -- the agent's scan_complete event and
    /api/recommend both read the scan straight back via get_latest_scan()
    immediately after the frontend gets this response, so that write has to
    be visible before we return, or those reads would race an empty table."""
    try:
        frame_url = upload_media(f"scans/{session_id}.jpg", frame_bytes, content_type)
        update_scan_frame_url(session_id, frame_url)
    except Exception:
        pass


@router.post("/scan", response_model=ScanResponse)
async def scan(background_tasks: BackgroundTasks, session_id: str = Form(...), frame: UploadFile = File(...)):
    """
    Core Module 1 endpoint: takes one camera frame, runs MediaPipe to get
    face + pose landmarks, then derives body shape, face shape, skin tone,
    height, glasses, hair length, and gender. Persists the result to Supabase
    for the agent (Module 2) and recommendation engine to use afterward.

    PERFORMANCE: designed to respond in well under 1 second on typical hardware --
    models are pre-warmed at server startup (see app/main.py lifespan), frames are
    downscaled before inference (see landmarks.decode_image), and the Storage image
    upload is deferred to a background task so it never blocks the response.
    """
    frame_bytes = await frame.read()

    try:
        extraction = extract_all(frame_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    image = extraction.pop("_image")

    # A frame with no detectable person must be a hard failure, not a
    # "successful" scan of all-unknowns -- confirmed live: a blank frame came
    # back 200 with body/face/skin/gender all 'unknown', the UI showed "Scan
    # Complete" and moved on to un-personalised recommendations. The
    # customer needs to be told to step into frame instead. The face is the
    # minimum: skin tone, undertone and gender (the palette and department
    # every recommendation is built on) all come from it.
    if extraction["face_landmarks"] is None:
        if extraction["pose_landmarks"] is None:
            raise HTTPException(
                status_code=422,
                detail="No person detected. Please stand in front of the mirror so your face and shoulders are in view.",
            )
        raise HTTPException(
            status_code=422,
            detail="Couldn't see your face clearly. Please face the mirror and check the lighting, then try again.",
        )

    body = classify_body_shape(extraction["pose_landmarks"])
    face = classify_face_shape(extraction["face_landmarks"], image)
    skin = extract_skin_tone(image, extraction["face_landmarks"])

    px_per_cm = get_mirror_calibration()
    size = estimate_body_size(extraction["pose_landmarks"], extraction["image_shape"]["height"], px_per_cm)
    camera_height = estimate_height_from_camera(extraction["pose_landmarks"], px_per_cm, extraction["face_landmarks"])
    height = merge_height(spoken_height_cm=None, camera_result=camera_height)  # spoken height merges in via /api/chat later

    glasses = detect_glasses(image, extraction["face_landmarks"])
    hair = detect_hair_length(image, extraction["face_landmarks"])
    gender = detect_gender(image, extraction["face_landmarks"])
    if forced_gender():
        # Store/demo mode (config.force_gender): the department is fixed, so
        # don't even let the detector's answer into the record -- every
        # downstream reader (/api/recommend, Aria) takes gender from the scan
        # row, and that must never disagree with what the store sells.
        gender = {"gender": forced_gender(), "confidence": 1.0, "model": "forced by FORCE_GENDER config"}

    scan_record = {
        "body_shape": body["body_shape"],
        "face_shape": face["face_shape"],
        "skin_tone_hex": skin["skin_tone_hex"],
        "skin_tone_category": skin["depth"],
        "skin_tone_undertone": skin["undertone"],
        "body_size_estimate": size["size_estimate"],
        "height_cm": height["height_cm"],
        "height_source": height["source"],
        "glasses_detected": glasses["glasses_detected"],
        "hair_length": hair["hair_length"],
        "gender": gender["gender"],
        "landmarks": {
            "face": extraction["face_landmarks"],
            "pose": extraction["pose_landmarks"],
        },
        "frame_url": None,  # filled in shortly after by the background task below
    }
    # Synchronous: /api/recommend and /api/chat both read this scan back from
    # Supabase immediately after -- a background write would race and they'd
    # see "no scan found" for ~300ms after every real scan.
    save_scan_result(session_id, scan_record)

    # Fire-and-forget: do NOT await this before responding.
    background_tasks.add_task(_upload_frame_in_background, session_id, frame_bytes, frame.content_type or "image/jpeg")

    return ScanResponse(
        session_id=session_id,
        body_shape=body["body_shape"],
        body_shape_confidence=body["confidence"],
        body_shape_reason=body["reason"],
        face_shape=face["face_shape"],
        face_shape_confidence=face["confidence"],
        face_shape_reason=face["reason"],
        skin_tone_hex=skin["skin_tone_hex"],
        skin_tone_depth=skin["depth"],
        skin_tone_undertone=skin["undertone"],
        size_estimate=size["size_estimate"],
        height_cm=height["height_cm"],
        height_source=height["source"],
        height_confidence=height["confidence"],
        glasses_detected=glasses["glasses_detected"],
        hair_length=hair["hair_length"],
        gender=gender["gender"],
        gender_confidence=gender["confidence"],
    )


@router.post("/scan/gender")
def confirm_gender(req: ScanGenderRequest):
    """
    Customer confirms or corrects the department (men's / women's) the
    scan detected -- the "Range" chip on the Recommendations page. The
    gender ensemble (gender_detect.py) is right ~95% of the time, but a
    mirror must never be stuck on the wrong department, so one tap wins.
    Applies to the most recent scan of this session; every later
    recommendation call (page or Aria) reads it from there.
    """
    from app.services.fashion.catalog_filters import normalize_gender
    if forced_gender():
        # Locked by config -- acknowledge without changing anything.
        return {"session_id": req.session_id, "gender": forced_gender(), "source": "forced", "locked": True}
    gender = normalize_gender(req.gender) or "unknown"
    if gender not in ("male", "female", "unknown"):
        raise HTTPException(status_code=400, detail="gender must be male, female or unknown")
    updated = update_scan_gender(req.session_id, gender)
    if not updated:
        raise HTTPException(status_code=404, detail="No scan found for this session. Call /api/vision/scan first.")
    return {"session_id": req.session_id, "gender": gender, "source": "customer"}


@router.post("/calibrate")
def calibrate(req: CalibrationRequest):
    """
    One-time setup for THIS mirror's fixed camera position: stand a person of
    known real height at the normal standing spot, capture a frame, and pass
    their pixel height (top-of-head to ankle, from a /api/vision/scan debug
    call) alongside their real height here. Stores pixels-per-cm for all
    future height estimates on this mirror.
    """
    px_per_cm = req.pixel_height / req.real_height_cm
    set_mirror_calibration(px_per_cm)
    return {"px_per_cm": px_per_cm, "status": "calibrated"}


@router.post("/presence")
async def presence(frame: UploadFile = File(...)):
    """
    Lightweight presence check for always-listening mode -- deliberately does
    NOT run the full scan pipeline (no skin tone, no glasses classifier, no
    Storage upload). Just: is a person standing in frame right now? Runs pose
    detection only, which is cheap enough to poll every 1-2 seconds from the
    frontend without meaningfully loading the server.

    Used to GATE the microphone: the frontend should only activate VAD/mic
    listening while this returns person_present: true, and end the
    conversation session a few seconds after it goes false. This is the
    practical mitigation for "always listening" without a wake word -- see
    the Always-Listening addendum for the honest limitations of this approach.
    """
    frame_bytes = await frame.read()
    image = decode_image(frame_bytes, max_dimension=320)  # even smaller than scan -- speed over precision here
    pose_landmarks = extract_pose_landmarks(image)
    return {"person_present": pose_landmarks is not None}
