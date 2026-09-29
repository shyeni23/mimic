"""
Gender detection for Module 1's full-body scan.

Per the project's Technology & GitHub Repository Reference doc, DeepFace
(https://github.com/serengil/deepface) is the recommended repo for face
analysis capabilities -- it ships a pretrained gender classifier, so this
follows the same "reuse a real trained model" pattern as accessory_detect.py's
glasses-detector rather than a hand-built heuristic (there is no reliable
geometric proxy for gender the way there is for face/body shape ratios).

Used only to bias clothing-category recommendations (menswear/womenswear
inventory filtering) -- not stored or exposed for any other purpose.
"""
import numpy as np
from functools import lru_cache

FOREHEAD_TOP = 10


@lru_cache
def _get_gender_backend():
    from deepface import DeepFace
    return DeepFace


import cv2

# Minimum face crop side (pixels) DeepFace's gender classifier gives reliable
# scores at. Below this the classifier averages ~50/50 and flips between
# scans on the same person. Upscale smaller crops via bicubic before inference.
MIN_CROP_SIDE = 128
# Confidence floor: below this the model's own softmax says "I'm guessing".
# Better to return unknown than an unreliable label the recommender then
# filters inventory on.
MIN_CONFIDENCE = 0.55


def _detect_gender_deepface(image_bgr: np.ndarray, face_landmarks: list[dict]) -> dict:
    """Runs DeepFace's pretrained gender classifier on a face crop.

    Fixes for the "always unknown" complaint:
      1. Was requiring len(face_landmarks) == 468. Some scans return 478
         (with irises); anything != 468 was silently returning unknown even
         when the face was clearly detected. Now accepts >= 400.
      2. Small face crops (full-body shots, distant users) fed DeepFace
         classifier gibberish -- upscale via bicubic to MIN_CROP_SIDE before
         inference so the model sees enough pixels to make a real call.
      3. Low-confidence predictions (< MIN_CONFIDENCE) return unknown rather
         than a coin-flip label that then biases inventory filtering wrong.

    Falls back to "unknown" (rather than raising) if pretrained weights
    can't be loaded -- e.g. still downloading -- so a slow/failed model
    fetch never blocks the core scan response.
    """
    if not face_landmarks or len(face_landmarks) < 400:
        return {"gender": "unknown", "confidence": 0.0, "reason": "no face landmarks"}

    h, w = image_bgr.shape[:2]
    xs = [p["x"] for p in face_landmarks]
    ys = [p["y"] for p in face_landmarks]
    # Generous padding: DeepFace prefers to see the full face including hair
    # and jawline, not a tight landmark-hull crop.
    pad_x = max(int((max(xs) - min(xs)) * 0.2), 10)
    pad_y = max(int((max(ys) - min(ys)) * 0.2), 10)
    x0, x1 = max(int(min(xs)) - pad_x, 0), min(int(max(xs)) + pad_x, w)
    y0, y1 = max(int(min(ys)) - pad_y, 0), min(int(max(ys)) + pad_y, h)
    face_crop = image_bgr[y0:y1, x0:x1]
    if face_crop.size == 0:
        return {"gender": "unknown", "confidence": 0.0, "reason": "empty crop"}

    # Upscale small crops -- DeepFace's gender classifier is trained on
    # ~224px inputs and gives ~50/50 gibberish on 40-60px full-body-shot faces.
    ch, cw = face_crop.shape[:2]
    if min(ch, cw) < MIN_CROP_SIDE:
        scale = MIN_CROP_SIDE / min(ch, cw)
        face_crop = cv2.resize(
            face_crop, (int(cw * scale), int(ch * scale)),
            interpolation=cv2.INTER_CUBIC,
        )

    try:
        DeepFace = _get_gender_backend()
        result = DeepFace.analyze(
            img_path=face_crop,
            actions=["gender"],
            enforce_detection=False,  # we already cropped to a MediaPipe-detected face
            silent=True,
        )
        analysis = result[0] if isinstance(result, list) else result
        dominant = analysis["dominant_gender"]  # "Man" | "Woman"
        gender_scores = analysis["gender"]      # {"Man": 0-100, "Woman": 0-100}
    except Exception as e:
        return {"gender": "unknown", "confidence": 0.0, "model": f"unavailable ({e})"}

    confidence = round(float(gender_scores[dominant]) / 100.0, 2)
    if confidence < MIN_CONFIDENCE:
        print(f"[vision:gender] scores={gender_scores} -- confidence {confidence} below floor, returning unknown")
        return {
            "gender": "unknown",
            "confidence": confidence,
            "reason": "confidence below reliability floor",
        }

    gender = "male" if dominant == "Man" else "female"
    print(
        f"[vision:gender] crop={face_crop.shape[:2]} scores={gender_scores} "
        f"dominant={dominant} -> {gender} (confidence={confidence})"
    )
    return {
        "gender": gender,
        "confidence": confidence,
        "model": "serengil/deepface (dominant gender classifier)",
    }


# ---------------------------------------------------------------------------
# Ensemble (the actual entry point used by /api/vision/scan)
# ---------------------------------------------------------------------------
# DeepFace's gender classifier alone was the wrong tool for a MIRROR: it
# only ever sees the face crop, has a documented male bias, and on a badly
# lit frame it called a woman "male" at 0.77 -- then at 0.93 after low-light
# normalisation (tried and rejected). The CLIP model this app already loads
# for recommendations (Marqo-FashionCLIP) sees the whole frame -- hair,
# clothing, build -- which is exactly the presentation the men's/women's
# department decision should follow. Measured 95% zero-shot accuracy on 80
# labelled 80x60 catalog product shots (misses were flat garment images with
# no person at all); on the two real frames where DeepFace said "male" it
# said "woman" at 0.98 and 1.00.
#
# Votes (p_female, weight):
#   CLIP full frame      weight 2.0   -- primary signal
#   CLIP face crop       weight 1.0   -- halved when the crop is dark
#   DeepFace face crop   weight 1.0   -- halved when the crop is dark
# Decision: weighted mean >= FEMALE_THRESHOLD -> female, <= MALE_THRESHOLD
# -> male, in between -> unknown (recommendations then show both
# departments and the customer picks -- never a coin-flip filter).

_CLIP_MALE_PROMPTS = ["a photo of a man", "a man wearing clothes", "male person"]
_CLIP_FEMALE_PROMPTS = ["a photo of a woman", "a woman wearing clothes", "female person"]
_CLIP_TEXT_CACHE: dict = {}

FEMALE_THRESHOLD = 0.62
MALE_THRESHOLD = 0.38
DARK_CROP_MEAN = 70        # gray mean below this = face-based votes are unreliable
W_CLIP_FULL, W_CLIP_FACE, W_DEEPFACE = 2.0, 1.0, 1.0


def _clip_text_matrix():
    """Prompt embeddings, computed once per process."""
    if "T" not in _CLIP_TEXT_CACHE:
        from app.services.fashion.fashion_clip import embed_texts
        t = np.array(embed_texts(_CLIP_MALE_PROMPTS + _CLIP_FEMALE_PROMPTS), dtype=np.float32)
        t /= np.linalg.norm(t, axis=1, keepdims=True)
        _CLIP_TEXT_CACHE["T"] = t
    return _CLIP_TEXT_CACHE["T"]


def _clip_p_female(image_bgr: np.ndarray) -> float:
    """Zero-shot P(woman) for an image via FashionCLIP prompt similarity."""
    from app.services.fashion.fashion_clip import embed_image_bytes
    ok, buf = cv2.imencode(".jpg", image_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise ValueError("could not encode frame")
    v = np.array(embed_image_bytes(buf.tobytes()), dtype=np.float32)
    v /= np.linalg.norm(v)
    t = _clip_text_matrix()
    logits = 100.0 * (t @ v)
    p = np.exp(logits - logits.max())
    p /= p.sum()
    return float(p[len(_CLIP_MALE_PROMPTS):].sum())


def _face_crop(image_bgr: np.ndarray, face_landmarks: list[dict], pad: float = 0.5) -> np.ndarray | None:
    if not face_landmarks:
        return None
    h, w = image_bgr.shape[:2]
    xs = [p["x"] for p in face_landmarks]
    ys = [p["y"] for p in face_landmarks]
    px = max(int((max(xs) - min(xs)) * pad), 10)
    py = max(int((max(ys) - min(ys)) * pad), 10)
    crop = image_bgr[max(int(min(ys)) - py, 0):min(int(max(ys)) + py, h),
                     max(int(min(xs)) - px, 0):min(int(max(xs)) + px, w)]
    return crop if crop.size else None


def detect_gender(image_bgr: np.ndarray, face_landmarks: list[dict]) -> dict:
    """Ensemble gender estimate for the department (men's/women's) filter.
    Never raises: any voter that fails is simply left out, and with no
    voters at all the answer is 'unknown'."""
    votes: list[tuple[str, float, float]] = []   # (name, p_female, weight)

    crop = _face_crop(image_bgr, face_landmarks)
    crop_mean = float(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).mean()) if crop is not None else 0.0
    dark = crop is None or crop_mean < DARK_CROP_MEAN
    face_w = 0.5 if dark else 1.0

    # ORDER MATTERS: DeepFace (TensorFlow) must run BEFORE the CLIP votes
    # (PyTorch). Importing TensorFlow into a process that already has
    # PyTorch loaded segfaults on this machine (reproduced: torch->tf dies,
    # tf->torch is fine). The server's startup warm-up loads a TF model
    # first anyway (see main.py), but scripts/tests reach this function
    # cold, so the ordering is enforced here too.
    df = _detect_gender_deepface(image_bgr, face_landmarks)
    if df.get("gender") in ("male", "female"):
        p_f = df["confidence"] if df["gender"] == "female" else 1.0 - df["confidence"]
        votes.append(("deepface", p_f, W_DEEPFACE * face_w))

    try:
        votes.append(("clip_full", _clip_p_female(image_bgr), W_CLIP_FULL))
    except Exception as e:
        print(f"[vision:gender] CLIP full-frame vote unavailable: {e}")

    if crop is not None:
        try:
            votes.append(("clip_face", _clip_p_female(crop), W_CLIP_FACE * face_w))
        except Exception as e:
            print(f"[vision:gender] CLIP face vote unavailable: {e}")

    if not votes:
        return {"gender": "unknown", "confidence": 0.0, "reason": "no gender signal available", "votes": []}

    total_w = sum(w for _, _, w in votes)
    p_female = sum(p * w for _, p, w in votes) / total_w
    if p_female >= FEMALE_THRESHOLD:
        gender, confidence = "female", p_female
    elif p_female <= MALE_THRESHOLD:
        gender, confidence = "male", 1.0 - p_female
    else:
        gender, confidence = "unknown", max(p_female, 1.0 - p_female)

    vote_str = ", ".join(f"{n}={p:.2f}(w{w:g})" for n, p, w in votes)
    print(
        f"[vision:gender] ensemble p_female={p_female:.2f} [{vote_str}] "
        f"crop_mean={crop_mean:.0f}{' DARK' if dark else ''} -> {gender} (confidence={confidence:.2f})"
    )
    return {
        "gender": gender,
        "confidence": round(confidence, 2),
        "model": "ensemble: FashionCLIP zero-shot (full frame + face) + DeepFace",
        "p_female": round(p_female, 3),
        "votes": [{"name": n, "p_female": round(p, 3), "weight": w} for n, p, w in votes],
    }
