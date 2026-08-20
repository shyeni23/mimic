"""
Accessory / hair detection for Module 1's full-body scan.

GLASSES: uses mantasu/glasses-detector (GitHub, pip-installable, pretrained) --
a real trained classifier, not a heuristic. This replaced an earlier edge-density
heuristic once a proper pretrained repo was confirmed to exist and fit cleanly.

HAIR LENGTH: honest limitation -- there is no equivalent clean pip-installable
pretrained repo for hair segmentation/length. Every option found (e.g.
thangtran480/hair-segmentation, marvin521/hair-segmentation-pytorch) is a
research repo requiring manual checkpoint downloads or training from scratch --
the same situation as Module 5's virtual try-on models (IDM-VTON/CatVTON), not
a simple pip install. Until one of those is deliberately integrated (same
clone + checkpoint pattern as Module 5), we use a lightweight color-region
heuristic here, clearly flagged as low-confidence.
"""
import cv2
import numpy as np
from functools import lru_cache

FOREHEAD_TOP = 10
LEFT_SHOULDER_APPROX, RIGHT_SHOULDER_APPROX = 234, 454


@lru_cache
def _get_glasses_classifier():
    from glasses_detector import AnyglassesClassifier
    return AnyglassesClassifier(base_model="small", pretrained=True).eval()


def detect_glasses(image_bgr: np.ndarray, face_landmarks: list[dict]) -> dict:
    """Runs the pretrained glasses-detector model on a face crop.

    Falls back to an "unknown" result (rather than raising) if the pretrained
    weights can't be loaded -- e.g. still downloading / network unavailable --
    so a slow/failed model fetch never blocks the core scan response."""
    if not face_landmarks or len(face_landmarks) < 468:
        return {"glasses_detected": False, "confidence": 0.0}

    h, w = image_bgr.shape[:2]
    xs = [p["x"] for p in face_landmarks]
    ys = [p["y"] for p in face_landmarks]
    x0, x1 = max(int(min(xs)) - 10, 0), min(int(max(xs)) + 10, w)
    y0, y1 = max(int(min(ys)) - 10, 0), min(int(max(ys)) + 10, h)
    face_crop = image_bgr[y0:y1, x0:x1]
    if face_crop.size == 0:
        return {"glasses_detected": False, "confidence": 0.0}

    try:
        classifier = _get_glasses_classifier()
    except Exception as e:
        return {"glasses_detected": False, "confidence": 0.0, "model": f"unavailable ({e})"}

    from PIL import Image
    rgb_crop = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(rgb_crop)

    prediction = classifier(pil_image, format="proba")  # returns probability of "has glasses"

    return {
        "glasses_detected": bool(prediction > 0.5),
        "confidence": round(float(prediction if prediction > 0.5 else 1 - prediction), 2),
        "model": "mantasu/glasses-detector (AnyglassesClassifier, small)",
    }


def detect_hair_length(image_bgr: np.ndarray, face_landmarks: list[dict]) -> dict:
    """
    Heuristic: sample the hair-colored region above the forehead landmark and
    measure how far down (relative to face height) similarly-colored pixels
    extend at the sides of the head -- a rough proxy for hair length.
    """
    if not face_landmarks or len(face_landmarks) < 468:
        return {"hair_length": "unknown", "confidence": 0.0}

    forehead = face_landmarks[FOREHEAD_TOP]
    left_edge = face_landmarks[LEFT_SHOULDER_APPROX]
    right_edge = face_landmarks[RIGHT_SHOULDER_APPROX]
    face_height = abs(face_landmarks[152]["y"] - forehead["y"]) if len(face_landmarks) > 152 else 100

    h, w = image_bgr.shape[:2]
    sample_y = max(int(forehead["y"] - 15), 0)
    sample_x = int(forehead["x"])
    if sample_y >= h or sample_x >= w:
        return {"hair_length": "unknown", "confidence": 0.0}

    hair_color = image_bgr[sample_y, sample_x].astype(np.int16)

    # Walk down both sides of the head looking for hair-colored pixels;
    # the lower they extend past the shoulders, the longer the hair bucket.
    def hair_extent(x: int) -> int:
        x = min(max(x, 0), w - 1)
        extent = 0
        for y in range(sample_y, min(sample_y + int(face_height * 3), h)):
            pixel = image_bgr[y, x].astype(np.int16)
            if np.abs(pixel - hair_color).sum() < 60:
                extent = y - sample_y
        return extent

    left_extent = hair_extent(int(left_edge["x"]))
    right_extent = hair_extent(int(right_edge["x"]))
    max_extent = max(left_extent, right_extent)

    ratio = max_extent / face_height if face_height else 0
    if ratio < 0.6:
        length = "short"
    elif ratio < 1.4:
        length = "medium"
    else:
        length = "long"

    return {"hair_length": length, "confidence": 0.4, "note": "coarse heuristic, not a trained hairstyle classifier"}
