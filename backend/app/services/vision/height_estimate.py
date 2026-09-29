"""
Height estimation for a smart mirror.

A single webcam cannot know real-world scale on its own -- 2 meters away and
tall looks identical to 1 meter away and short. There are two ways to give it
a real-world reference:

1. CALIBRATION (pixels-per-cm, set once via /api/vision/calibrate) -- only
   correct for whoever stands at the EXACT distance the calibration was done
   at. Confirmed in practice: people don't reliably stand at one fixed spot,
   so this alone silently over/under-estimates everyone who stands even a
   little closer or farther than that one reference measurement.
2. FACE-LENGTH RATIO (this scan's OWN FaceMesh forehead-to-chin measurement
   as the reference) -- distance-INVARIANT by construction: your face and
   your body are photographed at the same distance, so both measurements
   grow or shrink by the same factor as you move: the ratio between them
   stays meaningful regardless of where you're standing. The trade-off is
   assuming an average adult face length (18.5cm) instead of your exact one,
   a smaller and non-systematic source of error than "stood at the wrong
   spot" is.

Given the choice, (2) is the DEFAULT here -- it's correct no matter where
someone stands, which matters more day to day than the small precision
calibration would add for someone who happens to stand at exactly the
calibrated spot. Calibration is kept only as a fallback for the rare case
a face wasn't detected alongside the body.

This is the CAMERA-GUESS path either way. The SPOKEN path (user just tells
the mirror their height in conversation) is the most reliable of all --
zero camera-model assumptions -- and takes priority over both when
available; see merge_height() below.
"""
import math

NOSE = 0
LEFT_ANKLE, RIGHT_ANKLE = 27, 28
LEFT_EYE, RIGHT_EYE = 2, 5

# FaceMesh forehead-top/chin landmarks -- see face_shape.py's FOREHEAD_TOP/CHIN.
FACE_FOREHEAD_TOP, FACE_CHIN = 10, 152
# Average adult forehead-to-chin (face) length, ~18.5cm -- a genuine, if
# rough, anthropometric constant (unlike the old formula, this is used as a
# real-world reference for an INDEPENDENTLY measured pixel quantity, not
# derived circularly from the thing it's rescaling -- see the long comment
# below for why that distinction actually matters here).
AVERAGE_FACE_LENGTH_CM = 18.5


def _dist(p1: dict, p2: dict) -> float:
    return math.hypot(p1["x"] - p2["x"], p1["y"] - p2["y"])


def estimate_height_from_camera(
    pose_landmarks: list[dict], px_per_cm: float | None, face_landmarks: list[dict] | None = None
) -> dict:
    """
    face_landmarks (preferred): this scan's own face gives a distance-
    invariant reference (see module docstring) -- tried FIRST regardless of
    whether this mirror has been calibrated, since it's correct no matter
    where the person is standing.
    px_per_cm: this mirror's fixed-position calibration constant (see
    /api/vision/calibrate) -- used only when face_landmarks isn't available,
    since it's only accurate for someone standing at the exact calibrated
    distance.
    """
    if not pose_landmarks or len(pose_landmarks) < 29:
        return {"height_cm": None, "confidence": 0.0, "source": "camera", "note": "insufficient landmarks"}

    nose = pose_landmarks[NOSE]
    la, ra = pose_landmarks[LEFT_ANKLE], pose_landmarks[RIGHT_ANKLE]
    ankle_y = (la["y"] + ra["y"]) / 2

    # top-of-head is above the nose landmark; approximate using eye-to-nose
    # spacing as a proxy for the extra distance to the head's crown
    eye_y = (pose_landmarks[LEFT_EYE]["y"] + pose_landmarks[RIGHT_EYE]["y"]) / 2
    crown_offset = abs(nose["y"] - eye_y) * 3.2  # empirical proxy for forehead+crown
    top_of_head_y = nose["y"] - crown_offset

    pixel_height = ankle_y - top_of_head_y
    if pixel_height <= 0:
        return {"height_cm": None, "confidence": 0.0, "source": "camera", "note": "person not fully in frame"}

    # PREFERRED: this scan's own face as the real-world reference. Breaks the
    # circularity an old formula had (deriving a fixed ratio from pixel_height
    # then using it to rescale pixel_height right back -- every uncalibrated
    # scan returned the same 172.5cm regardless of who stood there). FaceMesh
    # is a DIFFERENT landmark detector than the pose-based pixel_height above,
    # so face_length_px is a genuinely independent pixel measurement, not
    # derived from pixel_height itself. Both quantities scale together with
    # camera distance (stand closer and BOTH your face and body look bigger
    # by the same factor), so their ratio is meaningful regardless of
    # distance -- unlike px_per_cm below, this never breaks just because
    # someone stood closer or farther than a one-time reference measurement.
    if face_landmarks and len(face_landmarks) > FACE_CHIN:
        face_length_px = _dist(face_landmarks[FACE_FOREHEAD_TOP], face_landmarks[FACE_CHIN])
        if face_length_px > 0:
            assumed_px_per_cm = face_length_px / AVERAGE_FACE_LENGTH_CM
            height_cm = pixel_height / assumed_px_per_cm
            print(
                f"[vision:height] pixel_height={pixel_height:.1f} "
                f"face_length_px={face_length_px:.1f} (distance-invariant face reference) -> {height_cm:.1f}cm"
            )
            return {
                "height_cm": round(height_cm, 1),
                "confidence": 0.55,
                "source": "camera",
                "note": "estimated from your own face-to-body proportions -- accurate regardless of distance from the camera",
            }

    # FALLBACK: face wasn't detected alongside the body this scan (rare --
    # scan already needs a face for skin tone/face-shape). Only correct if
    # this person happens to be standing at the exact spot calibration was
    # done at -- see module docstring for why that's not assumed reliable.
    if px_per_cm:
        height_cm = pixel_height / px_per_cm
        note = "estimated using this mirror's saved calibration -- most accurate if you're standing at the usual spot"
        print(f"[vision:height] no face reference -- pixel_height={pixel_height:.1f} px_per_cm={px_per_cm:.3f} -> {height_cm:.1f}cm")
        return {"height_cm": round(height_cm, 1), "confidence": 0.45, "source": "camera", "note": note}

    print(f"[vision:height] no face reference and no calibration available -- pixel_height={pixel_height:.1f}, cannot estimate")
    return {
        "height_cm": None,
        "confidence": 0.0,
        "source": "camera",
        "note": (
            "cannot estimate height -- face wasn't detected alongside the body this scan. "
            "Run /api/vision/calibrate once, or tell the mirror your height in chat, for a reliable number."
        ),
    }


def merge_height(spoken_height_cm: float | None, camera_result: dict) -> dict:
    """Spoken height (explicitly told to the agent) always wins over the camera guess."""
    if spoken_height_cm:
        return {"height_cm": spoken_height_cm, "confidence": 0.95, "source": "spoken"}
    return camera_result
