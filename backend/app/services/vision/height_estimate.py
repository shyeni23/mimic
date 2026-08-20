"""
Height estimation for a smart mirror.

A single webcam cannot know real-world scale on its own -- 2 meters away and
tall looks identical to 1 meter away and short. Smart mirrors solve this
because the camera position is FIXED and the user always stands at
roughly the same spot to see themselves in the mirror. So we calibrate
ONCE (pixels-per-cm at that standing distance) and every scan afterward
converts pixel height -> real height using that constant.

Until calibration is done, we still return a rough estimate (flagged as
approximate) so the feature always returns something.

This is the CAMERA-GUESS path. The SPOKEN path (user just tells the mirror
their height in conversation) is handled separately in nlp_extract.py and
takes priority when available -- see merge_height() below.
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
    px_per_cm: calibration constant for this mirror's fixed camera position.
    Set it once via the /api/vision/calibrate endpoint (stand a person of
    known height at the mirror's standing spot, call that endpoint with
    their real height). None -> falls back to a rough anthropometric guess
    using FaceMesh's independently-measured face length (see below).
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

    if px_per_cm:
        height_cm = pixel_height / px_per_cm
        confidence = 0.75
        note = "estimated using this mirror's saved calibration"
        print(f"[vision:height] pixel_height={pixel_height:.1f} px_per_cm={px_per_cm:.3f} -> {height_cm:.1f}cm")
        return {"height_cm": round(height_cm, 1), "confidence": confidence, "source": "camera", "note": note}

    # No calibration yet. A single 2D camera can't determine absolute scale
    # without SOME independently-known real-world reference (same reason a
    # thumb held close to your eye can visually block out the moon -- the
    # camera can't tell "close" from "big"). The PREVIOUS approach tried to
    # derive one from `head_height_px = pixel_height / AVERAGE_HEAD_TO_HEIGHT_RATIO`
    # -- but that derived head height FROM pixel_height using a fixed ratio,
    # then used it to rescale pixel_height right back -- circular: substituting
    # shows height_cm always equalled 7.5 * 23.0 = 172.5, a constant, regardless
    # of the actual person. That's why every uncalibrated scan returned the
    # same 172.5cm no matter who stood in front of the camera.
    #
    # This version breaks the circularity by using FaceMesh's forehead-to-chin
    # measurement as the reference instead -- that comes from a DIFFERENT
    # landmark detector than the pose-based pixel_height above, so it's a
    # genuinely independent pixel measurement, not derived from pixel_height
    # itself. Both quantities scale together with camera distance (stand
    # closer and BOTH your face and body look bigger by the same factor), so
    # their ratio stays meaningful regardless of distance, while still
    # reflecting this specific person's actual face-to-height proportions --
    # a real, if rough, per-person estimate instead of a fabricated constant.
    if face_landmarks and len(face_landmarks) > FACE_CHIN:
        face_length_px = _dist(face_landmarks[FACE_FOREHEAD_TOP], face_landmarks[FACE_CHIN])
        if face_length_px > 0:
            assumed_px_per_cm = face_length_px / AVERAGE_FACE_LENGTH_CM
            height_cm = pixel_height / assumed_px_per_cm
            print(
                f"[vision:height] no calibration -- pixel_height={pixel_height:.1f} "
                f"face_length_px={face_length_px:.1f} (independent FaceMesh reference) -> {height_cm:.1f}cm (rough)"
            )
            return {
                "height_cm": round(height_cm, 1),
                "confidence": 0.3,
                "source": "camera",
                "note": "rough estimate from average face-to-body proportions -- speak your height or calibrate for a more reliable number",
            }

    print(f"[vision:height] no calibration and no face reference available -- pixel_height={pixel_height:.1f}, cannot estimate")
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
