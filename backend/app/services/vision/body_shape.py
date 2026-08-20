"""
Heuristic body-shape classification from MediaPipe Pose landmarks.

MediaPipe Pose landmark indices used:
  11 = left shoulder     12 = right shoulder
  23 = left hip          24 = right hip
  25 = left knee          (used only for height reference)

This is a geometric heuristic (industry-standard shoulder/waist/hip ratio
approach), not a trained classifier. It's intentionally simple and
explainable -- good enough for a mirror demo, and easy to swap for a
trained model later without touching the API contract.
"""
import math

LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_HIP, RIGHT_HIP = 23, 24
NOSE = 0
LEFT_EYE, RIGHT_EYE = 2, 5
LEFT_ANKLE, RIGHT_ANKLE = 27, 28

# MediaPipe reports a per-landmark visibility score (0-1). Below this, the
# landmark is an extrapolated guess (e.g. hips out of frame at typical webcam
# distance/framing) rather than something actually seen -- trusting it anyway
# produces a confidently-wrong, systematically-biased shape for most users.
MIN_VISIBILITY = 0.5


def _dist(p1: dict, p2: dict) -> float:
    return math.hypot(p1["x"] - p2["x"], p1["y"] - p2["y"])


def classify_body_shape(pose_landmarks: list[dict]) -> dict:
    if not pose_landmarks or len(pose_landmarks) < 29:
        return {"body_shape": "unknown", "confidence": 0.0, "reason": "insufficient landmarks"}

    ls, rs = pose_landmarks[LEFT_SHOULDER], pose_landmarks[RIGHT_SHOULDER]
    lh, rh = pose_landmarks[LEFT_HIP], pose_landmarks[RIGHT_HIP]

    low_vis = [
        name for name, lm in (("left shoulder", ls), ("right shoulder", rs), ("left hip", lh), ("right hip", rh))
        if lm.get("visibility", 1.0) < MIN_VISIBILITY
    ]
    if low_vis:
        return {
            "body_shape": "unknown",
            "confidence": 0.0,
            "reason": f"low camera confidence on {', '.join(low_vis)} -- step back so your shoulders and hips are both clearly visible",
        }

    shoulder_width = _dist(ls, rs)
    hip_width = _dist(lh, rh)
    if shoulder_width <= 0 or hip_width <= 0:
        return {"body_shape": "unknown", "confidence": 0.0, "reason": "degenerate measurements"}

    mid_shoulder = {"x": (ls["x"] + rs["x"]) / 2, "y": (ls["y"] + rs["y"]) / 2}
    mid_hip = {"x": (lh["x"] + rh["x"]) / 2, "y": (lh["y"] + rh["y"]) / 2}
    torso_height = _dist(mid_shoulder, mid_hip)

    # MediaPipe's hip landmarks (23/24) mark the HIP JOINTS (bi-trochanteric
    # width), which sit anatomically narrower than the visible/outer hip width
    # "body shape" terminology actually refers to -- shoulder landmarks, by
    # contrast, track close to the real visible shoulder width. Left
    # uncorrected this asymmetry inflates shoulder/hip ratio for nearly
    # everyone regardless of true shape (that's what caused different real
    # people to keep converging on "inverted_triangle"). NEUTRAL_RATIO
    # approximates the typical joint-based ratio for someone who would
    # visually read as balanced/rectangle -- classification compares against
    # this calibrated baseline instead of the naive geometric 1.0.
    NEUTRAL_RATIO = 1.15
    ratio = (shoulder_width / hip_width) / NEUTRAL_RATIO

    # Confidence scales with how far the ratio sits from the nearest decision
    # boundary -- a ratio just barely past the cutoff is a much shakier call
    # than one clearly past it, so this replaces the old fixed-per-branch
    # confidence constants (which never reflected genuine uncertainty).
    def _confidence(margin: float) -> float:
        # Multiplier lowered (3.0 -> 1.2) and cap raised (0.85 -> 0.9): the
        # old formula saturated at its cap for any margin past ~0.17, which
        # is well within normal human variation -- meaning two genuinely
        # different people could both hit the SAME capped confidence, making
        # them look like duplicated results even though the underlying ratio
        # differed. This keeps differentiating across a much wider range.
        return round(min(0.3 + margin * 1.2, 0.9), 2)

    BROAD_SHOULDER, BROAD_HIP = 1.08, 0.93
    reasons = []
    if ratio >= BROAD_SHOULDER:
        shape = "inverted_triangle"
        conf = _confidence(ratio - BROAD_SHOULDER)
        reasons.append("shoulders are noticeably wider than hips")
    elif ratio <= BROAD_HIP:
        shape = "pear"
        conf = _confidence(BROAD_HIP - ratio)
        reasons.append("hips are noticeably wider than shoulders")
    else:
        shape = "rectangle"
        conf = _confidence(min(BROAD_SHOULDER - ratio, ratio - BROAD_HIP))
        reasons.append("shoulders and hips are close in width")

    # Distinguishing hourglass/apple from rectangle needs an actual waist
    # measurement -- MediaPipe Pose has no waist landmark, so rather than
    # fabricate one (the previous fixed-multiplier "waist_width" made
    # hourglass mathematically unreachable -- see git history), "rectangle"
    # is the honest result for balanced proportions.
    if conf < 0.4:
        reasons.append("close to a category boundary -- treat this reading as approximate")

    print(
        f"[vision:body_shape] shoulder_px={shoulder_width:.1f} hip_px={hip_width:.1f} "
        f"raw_ratio={shoulder_width / hip_width:.3f} calibrated_ratio={ratio:.3f} "
        f"-> {shape} (confidence={conf})"
    )

    return {
        "body_shape": shape,
        "confidence": conf,
        "reason": "; ".join(reasons),
        "metrics": {
            "shoulder_width_px": round(shoulder_width, 1),
            "hip_width_px": round(hip_width, 1),
            "torso_height_px": round(torso_height, 1),
            "shoulder_to_hip_ratio_calibrated": round(ratio, 3),
        },
    }


def estimate_body_size(pose_landmarks: list[dict], image_height: int, px_per_cm: float | None = None) -> dict:
    """
    Very rough size bucket (XS/S/M/L/XL) from visible landmark proportions.
    This is NOT a substitute for real measurements -- it's a coarse estimate
    to bias inventory filtering, and should say so to the user.

    Two tiers -- both give a REAL real-world measurement, not a frame-relative
    guess. A shoulder-width-vs-frame-width fallback was tried and removed: it
    conflates "close to the camera" with "actually broad", so someone sitting
    close to a laptop webcam always reads as bigger than they are regardless
    of true size -- systematically wrong, not just imprecise, so it's worse
    than admitting uncertainty.
      1. Full body (nose to ankles) visible -- shoulder-width/height-in-frame
         ratio. Self-normalizing (both measured at the same distance), so
         this works without calibration.
      2. Only shoulders visible, but this mirror HAS been calibrated (see
         /api/vision/calibrate) -- px_per_cm converts shoulder width to an
         actual centimeter measurement, which is distance-corrected by
         construction since calibration is done once at the mirror's fixed
         standing spot.
    Neither available -> honest "unknown" rather than a biased guess.
    """
    if not pose_landmarks or len(pose_landmarks) < 29:
        return {"size_estimate": "unknown", "confidence": 0.0}

    ls, rs = pose_landmarks[LEFT_SHOULDER], pose_landmarks[RIGHT_SHOULDER]
    if any(lm.get("visibility", 1.0) < MIN_VISIBILITY for lm in (ls, rs)):
        return {"size_estimate": "unknown", "confidence": 0.0, "note": "shoulders not clearly visible"}

    shoulder_width_px = _dist(ls, rs)

    la, ra = pose_landmarks[LEFT_ANKLE], pose_landmarks[RIGHT_ANKLE]
    nose = pose_landmarks[NOSE]
    le, re = pose_landmarks[LEFT_EYE], pose_landmarks[RIGHT_EYE]
    full_body_visible = all(lm.get("visibility", 1.0) >= MIN_VISIBILITY for lm in (la, ra, nose, le, re))

    if full_body_visible:
        ankle_y = (la["y"] + ra["y"]) / 2
        # Nose sits well below the actual crown of the head -- measuring
        # nose-to-ankle as "full height" understates true height by roughly
        # 12-15% (forehead + crown), which systematically INFLATES
        # shoulder-width/height for every person, biasing everyone toward
        # larger sizes and masking real differences between people. Correct
        # for this the same way height_estimate.py already does: estimate the
        # crown position from eye-to-nose spacing.
        eye_y = (pose_landmarks[LEFT_EYE]["y"] + pose_landmarks[RIGHT_EYE]["y"]) / 2
        crown_offset = abs(nose["y"] - eye_y) * 3.2
        top_of_head_y = nose["y"] - crown_offset
        full_height_px = ankle_y - top_of_head_y
        if full_height_px > 0:
            build_ratio = shoulder_width_px / full_height_px  # broader build -> larger ratio
            bounds = [0.14, 0.16, 0.19, 0.22, 0.25]
            labels = ["XS", "S", "M", "L", "XL", "XXL"]
            size = next((labels[i] for i, b in enumerate(bounds) if build_ratio < b), labels[-1])
            # Genuine confidence: how far the measured ratio sits from the
            # NEAREST bucket edge -- replaces the old fixed 0.4 constant,
            # which gave every scan the same confidence regardless of how
            # borderline or clear-cut the actual measurement was.
            margin = min(abs(build_ratio - b) for b in bounds)
            confidence = round(min(0.3 + margin * 8.0, 0.75), 2)
            print(
                f"[vision:body_size] shoulder_px={shoulder_width_px:.1f} "
                f"height_px={full_height_px:.1f} (crown-corrected) build_ratio={build_ratio:.4f} "
                f"-> {size} (confidence={confidence})"
            )
            return {
                "size_estimate": size,
                "confidence": confidence,
                "note": "Estimated from full-body camera proportions, not exact measurements.",
            }

    if px_per_cm:
        shoulder_width_cm = shoulder_width_px / px_per_cm
        if shoulder_width_cm < 36:
            size = "XS"
        elif shoulder_width_cm < 40:
            size = "S"
        elif shoulder_width_cm < 44:
            size = "M"
        elif shoulder_width_cm < 48:
            size = "L"
        elif shoulder_width_cm < 52:
            size = "XL"
        else:
            size = "XXL"
        print(
            f"[vision:body_size] shoulder_px={shoulder_width_px:.1f} px_per_cm={px_per_cm:.3f} "
            f"shoulder_cm={shoulder_width_cm:.1f} -> {size}"
        )
        return {
            "size_estimate": size,
            "confidence": 0.35,
            "note": "Estimated from this mirror's calibrated shoulder-width measurement.",
        }

    return {
        "size_estimate": "unknown",
        "confidence": 0.0,
        "note": (
            "Full body not visible and this mirror isn't calibrated yet -- either step back "
            "so your whole body is in frame, or run /api/vision/calibrate once for reliable "
            "sizing at any distance."
        ),
    }
