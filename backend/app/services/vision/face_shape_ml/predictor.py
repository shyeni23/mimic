"""
Face-shape prediction: MediaPipe face validation + a FaceNet-based classifier.

ATTRIBUTION: vendored (with minor path/comment adaptations only -- the
model-loading, alignment, and prediction logic below is otherwise
unmodified) from Diksha-cmd/face-shape-prediction
(github.com/Diksha-cmd/face-shape-prediction) -- MIT License, Copyright (c)
2026 Diksha Tiwari. Adopted per the Module 1 research brief's own
recommendation (real released weights, MIT license, reports ~100ms/image CPU
inference, and already uses MediaPipe for alignment -- the same perception
layer this project already uses). See LICENSE in this directory for the full
license text.

    MIT License permission notice (reproduced per license terms):
    "Permission is hereby granted, free of charge, to any person obtaining
    a copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction..."
    Full text: this directory's LICENSE file.

WHY VENDORED RATHER THAN REIMPLEMENTED: the original module docstring says
"the preprocessing here must mirror training exactly" -- reimplementing the
alignment/crop math from a paraphrased description (rather than the real
code) risks a silent accuracy regression that would be very hard to detect
before a demo. This project's OWN FaceMesh landmarks (landmarks.py) are
NOT reused here on purpose, for the same reason: this predictor's alignment
was trained against MediaPipe's Tasks-API FaceLandmarker output specifically
(normalized coordinates, its own detector), not this project's Solutions-API
FaceMesh (pixel coordinates) -- splicing the two risks a coordinate-space/
detector mismatch the model was never trained to handle. Running a second,
separate MediaPipe detector here is redundant compute but the safe choice.

VERIFIED COMPATIBLE with this project's existing mediapipe==0.10.14 pin (the
upstream repo's own requirements.txt asks for >=0.10.30, but that's untested
lower-bound drift, not a real compatibility requirement -- confirmed live,
no MediaPipe version bump was needed here).

The model is an InceptionResNet FaceNet backbone (via keras-facenet) fine-tuned
on the Kaggle face-shape dataset (niten19/face-shape-dataset, CC0) to classify
five face shapes: Oblong, Heart, Square, Oval, Round.

The preprocessing here must mirror training exactly:
1. detect the face and its landmarks (MediaPipe FaceLandmarker),
2. rotate the image so the eye line is horizontal,
3. crop a fixed window around the eye midpoint,
4. resize to 160x160 RGB in [0, 1].

Photos are validated first -- no face, multiple faces, or a strongly turned
head are rejected with a status instead of a wrong prediction.
"""

import threading
import urllib.request
from pathlib import Path

import numpy as np

CLASSES = ["Oblong", "Heart", "Square", "Oval", "Round"]

# backend/data/models/face_shape/ -- this project's existing convention for
# locally-cached model artifacts (see requirements.txt / README for the
# equivalent pattern used by faster-whisper, DeepFace, glasses-detector).
_MODELS_DIR = Path(__file__).resolve().parents[4] / "data" / "models" / "face_shape"
DEFAULT_MODEL_PATH = _MODELS_DIR / "faceshape_facenet_v3.keras"
DEFAULT_LANDMARKER_PATH = _MODELS_DIR / "face_landmarker.task"
_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)

# Face-mesh landmark indices
_LEFT_EYE = (33, 133)
_RIGHT_EYE = (362, 263)
_NOSE_TIP = 1
_LEFT_CHEEK = 234
_RIGHT_CHEEK = 454


class FaceShapePredictor:
    """Loads the model once; ``predict`` is safe to call from multiple threads.

    >>> predictor = FaceShapePredictor()
    >>> predictor.predict("photo.jpg")
    {'status': 'ok', 'face_shape': 'round', 'scores': {...}}
    """

    def __init__(self, model_path=None, landmarker_path=None):
        import cv2
        import mediapipe as mp
        import tensorflow as tf
        import tensorflow_hub as hub
        from mediapipe.tasks import python as mp_tasks
        from mediapipe.tasks.python import vision as mp_vision
        # Keras 3 DIRECTLY, not `tensorflow.keras`: this .keras file is saved
        # in Keras 3 format, while the process runs with TF_USE_LEGACY_KERAS=1
        # (set in app/__init__.py -- DeepFace's gender model only works on
        # legacy tf_keras). Under that flag `tensorflow.keras` resolves to
        # tf_keras, which can't deserialize a Keras 3 model ("parent module
        # tf_keras.src.models.functional cannot be imported"). Importing
        # `keras` by name sidesteps the alias; both libraries coexist fine.
        import keras
        from keras.layers import Rescaling

        model_path = Path(model_path or DEFAULT_MODEL_PATH)
        landmarker_path = Path(landmarker_path or DEFAULT_LANDMARKER_PATH)
        if not model_path.exists():
            raise FileNotFoundError(
                f"face-shape model weights not found at {model_path} -- this is a "
                f"142MB file distributed via Git LFS on the upstream repo, not "
                f"auto-downloadable; see this directory's README for the one-time "
                f"setup step."
            )
        if not landmarker_path.exists():
            landmarker_path.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(_LANDMARKER_URL, landmarker_path)

        # Custom objects referenced by the saved model (from keras-facenet).
        def scaling(x, *args, scale=1.0, **kwargs):
            if args:
                scale = args[0]
            return x * scale

        def l2_normalize(x, axis=-1, *_, **kwargs):
            return tf.math.l2_normalize(x, axis=axis)

        self._cv2 = cv2
        self._model = keras.models.load_model(
            model_path,
            compile=False,
            custom_objects={
                "scaling": scaling,
                "l2_normalize": l2_normalize,
                "Rescaling": Rescaling,
                "KerasLayer": hub.KerasLayer,
            },
        )
        # model_asset_buffer (raw bytes), not model_asset_path -- MediaPipe's
        # C++ resource resolver mishandles a Windows absolute path here (it
        # doesn't recognize "E:\..." -- or even "E:/..." -- as already-
        # absolute, so it silently prepends its own base directory instead:
        # confirmed live, repeatedly, with "Unable to open file at
        # .../site-packages/E:\...\face_landmarker.task"). Reading the bytes
        # ourselves and handing them over directly sidesteps that resolver
        # entirely instead of fighting its path-format assumptions.
        self._landmarker = mp_vision.FaceLandmarker.create_from_options(
            mp_vision.FaceLandmarkerOptions(
                base_options=mp_tasks.BaseOptions(model_asset_buffer=landmarker_path.read_bytes()),
                running_mode=mp_vision.RunningMode.IMAGE,
                num_faces=2,
            )
        )
        self._mp_image = lambda rgb: mp.Image(
            image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)
        )
        self._lock = threading.Lock()
        # Warm up so the first real prediction doesn't pay graph-tracing cost.
        self._model.predict(np.zeros((1, 160, 160, 3), dtype="float32"), verbose=0)

    # -- geometry helpers ------------------------------------------------------

    @staticmethod
    def _eye_center(landmarks, idxs):
        pts = np.array([[landmarks[i].x, landmarks[i].y] for i in idxs])
        return pts.mean(axis=0)

    def _align(self, bgr, landmarks):
        """Rotate the image so the eye line is horizontal (no scaling)."""
        cv2 = self._cv2
        h, w = bgr.shape[:2]
        l = self._eye_center(landmarks, _LEFT_EYE)
        r = self._eye_center(landmarks, _RIGHT_EYE)
        dx, dy = r - l
        angle = np.degrees(np.arctan2(dy, dx))
        mid = ((l + r) / 2) * np.array([w, h])
        M = cv2.getRotationMatrix2D(tuple(mid), angle, 1.0)
        rot = cv2.warpAffine(
            bgr, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
        )
        return rot, tuple(mid.astype(int))

    @staticmethod
    def _is_side_face(landmarks) -> bool:
        nose = landmarks[_NOSE_TIP].x
        d_left = abs(nose - landmarks[_LEFT_CHEEK].x)
        d_right = abs(landmarks[_RIGHT_CHEEK].x - nose)
        if min(d_left, d_right) < 1e-6:
            return True
        return max(d_left, d_right) / min(d_left, d_right) > 2.2

    # -- input handling --------------------------------------------------------

    @staticmethod
    def _to_rgb_array(image) -> np.ndarray:
        """Accepts a file path, an RGB numpy array, or a PIL image."""
        if isinstance(image, (str, Path)):
            from PIL import Image, ImageOps

            img = ImageOps.exif_transpose(Image.open(image)).convert("RGB")
            img.thumbnail((1000, 1000))
            return np.asarray(img)
        if isinstance(image, np.ndarray):
            if image.ndim != 3 or image.shape[2] != 3:
                raise ValueError("expected an HxWx3 RGB array")
            return image.astype(np.uint8)
        # PIL image (avoid importing PIL just for the isinstance check)
        if hasattr(image, "convert"):
            return np.asarray(image.convert("RGB"))
        raise TypeError(f"unsupported image type: {type(image)!r}")

    # -- prediction ------------------------------------------------------------

    def predict(self, image) -> dict:
        """Classify the face shape in a photo.

        Returns ``{"status": "ok", "face_shape": ..., "scores": {...}}`` or a
        rejection: ``{"status": "no_face" | "multiple_faces" | "side_face"}``.
        """
        rgb = self._to_rgb_array(image)
        cv2 = self._cv2
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

        with self._lock:
            res = self._landmarker.detect(self._mp_image(rgb))
            if not res.face_landmarks:
                return {"status": "no_face"}
            if len(res.face_landmarks) > 1:
                return {"status": "multiple_faces"}
            lm = res.face_landmarks[0]
            if self._is_side_face(lm):
                return {"status": "side_face"}

            rot, mid = self._align(bgr, lm)
            res2 = self._landmarker.detect(
                self._mp_image(cv2.cvtColor(rot, cv2.COLOR_BGR2RGB))
            )
            if not res2.face_landmarks:
                return {"status": "no_face"}

            h, w = rot.shape[:2]
            ew = int(min(w, h) * 0.8)
            eh = int(ew * 1.2)
            x0 = max(0, mid[0] - ew // 2)
            y0 = max(0, mid[1] - int(eh * 0.4))
            crop = rot[y0 : y0 + eh, x0 : x0 + ew]
            if crop.size == 0:
                return {"status": "no_face"}

            crop160 = (
                cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB), (160, 160)).astype(
                    "float32"
                )
                / 255.0
            )
            probs = self._model.predict(crop160[None, ...], verbose=0)[0]

        return {
            "status": "ok",
            "face_shape": CLASSES[int(np.argmax(probs))].lower(),
            "scores": {
                cls.lower(): round(float(p), 4) for cls, p in zip(CLASSES, probs)
            },
        }
