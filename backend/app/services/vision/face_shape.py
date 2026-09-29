"""
Face-shape classification: a trained model first, a geometric heuristic as
the fallback.

PRIMARY PATH: a real classifier trained on labeled data (Diksha-cmd's
FaceNet-based model, vendored in face_shape_ml/ -- see that module's
docstring for full attribution/license). This replaced the pure hand-tuned
heuristic per the Module 1 research brief's recommendation ("the current
hand-tuned face-shape rules should be replaced or supplemented by a learned
classifier") -- face shape was one of the brief's two top-priority items,
and this was the one with a genuinely usable released model (MIT-licensed
weights, reports ~100ms/image on CPU) rather than requiring us to train
from scratch.

FALLBACK PATH (_classify_face_shape_heuristic, unchanged from before): used
whenever the trained model isn't available (weights not set up yet) or
declines to answer (no clean face detected, side profile, multiple faces) --
this project's existing "never crash, degrade gracefully" pattern, same as
detect_glasses()/DeepFace's gender path. A scan should never fail outright
just because the ML model had a bad frame; the geometric heuristic still
gives a real (if less accurate) answer from the SAME FaceMesh landmarks
already being extracted every scan.

CLASS-NAME MAPPING: the trained model's 5 classes are Oblong/Heart/Square/
Oval/Round (the standard schema for this problem, per the research brief and
the dataset it's trained on). This project's existing internal keyword for
"oblong" is "long" (see mapBackendValues.js's FACE_SHAPE_MAP on the frontend)
-- translated at the boundary below so nothing downstream needs to change.
The old heuristic's 6th category, "diamond", isn't part of the trained
model's label schema (per the brief: "only add another class if the
project's label schema requires it") -- the heuristic fallback can still
return it, but the ML path never will.

Landmark indices used by the fallback heuristic (standard MediaPipe FaceMesh
topology):
  10  = top of forehead        152 = chin (bottom of face)
  234 = left cheekbone/temple  454 = right cheekbone/temple
  127 = left forehead edge     356 = right forehead edge
  172 = left jaw               397 = right jaw
"""
import math
from functools import lru_cache

import numpy as np

FOREHEAD_TOP, CHIN = 10, 152
CHEEK_LEFT, CHEEK_RIGHT = 234, 454
FOREHEAD_LEFT, FOREHEAD_RIGHT = 127, 356
JAW_LEFT, JAW_RIGHT = 172, 397

_MODEL_CLASS_TO_INTERNAL = {
    "oblong": "long",
    "heart": "heart",
    "square": "square",
    "oval": "oval",
    "round": "round",
}


@lru_cache
def _get_face_shape_model():
    """Lazy singleton, same pattern as detect_glasses()/DeepFace's gender
    model -- raises on first call if weights aren't set up yet; callers
    catch that and fall back to the heuristic rather than failing the scan."""
    from app.services.vision.face_shape_ml.predictor import FaceShapePredictor
    return FaceShapePredictor()


def _dist(p1: dict, p2: dict) -> float:
    return math.hypot(p1["x"] - p2["x"], p1["y"] - p2["y"])


def _classify_face_shape_heuristic(face_landmarks: list[dict]) -> dict:
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
        f"[vision:face_shape] (heuristic fallback) length_px={face_length:.1f} cheek_px={cheekbone_width:.1f} "
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


def classify_face_shape(face_landmarks: list[dict], image_bgr: "np.ndarray | None" = None) -> dict:
    """
    Tries the trained model first (needs the actual frame, not just
    landmarks -- it runs its own internal face detection/alignment). Falls
    back to the geometric heuristic (landmarks-only) whenever the model
    isn't available, or declines to answer for this frame.
    """
    if image_bgr is not None:
        try:
            model = _get_face_shape_model()
            rgb = image_bgr[:, :, ::-1]  # BGR (this project's convention) -> RGB (predictor's)
            result = model.predict(rgb)
            if result["status"] == "ok":
                shape = _MODEL_CLASS_TO_INTERNAL.get(result["face_shape"], result["face_shape"])
                confidence = round(float(result["scores"][result["face_shape"]]), 2)
                print(
                    f"[vision:face_shape] (trained model) scores={result['scores']} -> {shape} "
                    f"(confidence={confidence})"
                )
                return {
                    "face_shape": shape,
                    "confidence": confidence,
                    "reason": "predicted by a trained classifier (FaceNet-based, fine-tuned on labeled face-shape data)",
                    "metrics": {"model_scores": result["scores"]},
                }
            print(f"[vision:face_shape] trained model declined ({result['status']}) -- falling back to heuristic")
        except Exception as e:
            print(f"[vision:face_shape] trained model unavailable ({e}) -- falling back to heuristic")

    return _classify_face_shape_heuristic(face_landmarks)
