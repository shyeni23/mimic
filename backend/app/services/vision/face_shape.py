"""
Heuristic face-shape classification from MediaPipe FaceMesh landmarks (468/478 pts).

Landmark indices (standard MediaPipe FaceMesh topology):
  10  = top of forehead        152 = chin (bottom of face)
  234 = left cheekbone/temple  454 = right cheekbone/temple
  127 = left forehead edge     356 = right forehead edge
  172 = left jaw               397 = right jaw
"""
import math

FOREHEAD_TOP, CHIN = 10, 152
CHEEK_LEFT, CHEEK_RIGHT = 234, 454
FOREHEAD_LEFT, FOREHEAD_RIGHT = 127, 356
JAW_LEFT, JAW_RIGHT = 172, 397


def _dist(p1: dict, p2: dict) -> float:
    return math.hypot(p1["x"] - p2["x"], p1["y"] - p2["y"])


def classify_face_shape(face_landmarks: list[dict]) -> dict:
    if not face_landmarks or len(face_landmarks) < 468:
        return {"face_shape": "unknown", "confidence": 0.0, "reason": "insufficient landmarks"}

    face_length = _dist(face_landmarks[FOREHEAD_TOP], face_landmarks[CHIN])
    cheekbone_width = _dist(face_landmarks[CHEEK_LEFT], face_landmarks[CHEEK_RIGHT])
    forehead_width = _dist(face_landmarks[FOREHEAD_LEFT], face_landmarks[FOREHEAD_RIGHT])
    jaw_width = _dist(face_landmarks[JAW_LEFT], face_landmarks[JAW_RIGHT])

    if cheekbone_width == 0:
        return {"face_shape": "unknown", "confidence": 0.0, "reason": "degenerate landmarks"}

    length_to_width = face_length / cheekbone_width
    jaw_to_cheek = jaw_width / cheekbone_width
    forehead_to_cheek = forehead_width / cheekbone_width
    forehead_to_jaw = forehead_width / jaw_width if jaw_width else 1.0

    # Confidence scales with how far past each ratio threshold the measurement
    # falls -- a face just barely over 1.5 length/width is a much shakier
    # "long" call than one clearly past it. Replaces the old fixed-per-branch
    # constants, which never reflected genuine uncertainty.
    def _confidence(margin: float, base: float = 0.35) -> float:
        # Multiplier lowered (2.5 -> 1.0) and cap raised (0.85 -> 0.9): the
        # old formula saturated at its cap too easily, which could make two
        # different real faces show the identical confidence percentage even
        # though their actual measurements differed.
        return round(min(base + max(margin, 0) * 1.0, 0.9), 2)

    reasons = []
    if length_to_width >= 1.5:
        shape = "long"
        conf = _confidence(length_to_width - 1.5)
        reasons.append("face length is notably greater than its width")
    elif jaw_to_cheek >= 0.95 and forehead_to_cheek >= 0.95 and length_to_width < 1.3:
        shape = "square"
        conf = _confidence(min(jaw_to_cheek - 0.95, forehead_to_cheek - 0.95))
        reasons.append("forehead, cheekbones, and jaw are all similarly wide")
    elif forehead_to_jaw >= 1.15:
        shape = "heart"
        conf = _confidence(forehead_to_jaw - 1.15)
        reasons.append("forehead is noticeably wider than the jaw")
    elif jaw_to_cheek <= 0.85 and forehead_to_cheek <= 0.9:
        shape = "diamond"
        conf = _confidence(min(0.85 - jaw_to_cheek, 0.9 - forehead_to_cheek), base=0.35)
        reasons.append("cheekbones are the widest point, narrowing at forehead and jaw")
    elif 1.3 <= length_to_width < 1.5 and jaw_to_cheek < 0.9:
        shape = "oval"
        conf = _confidence(min(length_to_width - 1.3, 0.9 - jaw_to_cheek), base=0.45)
        reasons.append("face is longer than wide with a gently narrowing jaw")
    else:
        shape = "round"
        conf = 0.4  # genuine catch-all -- didn't clearly match a more specific shape
        reasons.append("face width and length are close, with a softer jawline")

    if conf < 0.4:
        reasons.append("close to a category boundary -- treat this reading as approximate")

    print(
        f"[vision:face_shape] length_px={face_length:.1f} cheek_px={cheekbone_width:.1f} "
        f"forehead_px={forehead_width:.1f} jaw_px={jaw_width:.1f} "
        f"length/width={length_to_width:.3f} jaw/cheek={jaw_to_cheek:.3f} "
        f"forehead/cheek={forehead_to_cheek:.3f} forehead/jaw={forehead_to_jaw:.3f} "
        f"-> {shape} (confidence={conf})"
    )

    return {
        "face_shape": shape,
        "confidence": conf,
        "reason": "; ".join(reasons),
        "metrics": {
            "face_length_px": round(face_length, 1),
            "cheekbone_width_px": round(cheekbone_width, 1),
            "forehead_width_px": round(forehead_width, 1),
            "jaw_width_px": round(jaw_width, 1),
        },
    }
