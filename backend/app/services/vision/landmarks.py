"""
MediaPipe-based landmark extraction.

Camera frame -> face landmarks + pose landmarks.
Everything downstream (body_shape, face_shape, skin_tone) consumes these
landmark arrays instead of re-running detection.
"""
import math
import numpy as np
import cv2
import mediapipe as mp

mp_face_mesh = mp.solutions.face_mesh
mp_pose = mp.solutions.pose

_face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=True,
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
)

_pose = mp_pose.Pose(
    static_image_mode=True,
    model_complexity=1,
    min_detection_confidence=0.5,
)

# MediaPipe Pose landmark indices used to locate the head for the face-crop
# retry below (see extract_all's docstring for why this exists).
POSE_NOSE, POSE_LEFT_EAR, POSE_RIGHT_EAR = 0, 7, 8


def decode_image(file_bytes: bytes, max_dimension: int = 960) -> np.ndarray:
    """
    Downscale before inference. MediaPipe/glasses-detector accuracy is unaffected
    by this at typical webcam resolutions, but inference time scales with pixel
    count -- capping the longest side keeps the whole scan pipeline well under
    the 1-second budget regardless of the camera's native resolution.

    Raised from 640 -> 960: at 640, a person standing far enough back for a
    full-body shot (needed for accurate size estimation) left too few pixels
    on their face for FaceMesh to detect reliably even before the crop-retry
    below kicks in.
    """
    arr = np.frombuffer(file_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image bytes")

    h, w = img.shape[:2]
    longest_side = max(h, w)
    if longest_side > max_dimension:
        scale = max_dimension / longest_side
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    return img


def extract_face_landmarks(image_bgr: np.ndarray) -> list[dict] | None:
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    result = _face_mesh.process(rgb)
    if not result.multi_face_landmarks:
        return None
    h, w = image_bgr.shape[:2]
    landmarks = result.multi_face_landmarks[0].landmark
    return [{"x": lm.x * w, "y": lm.y * h, "z": lm.z} for lm in landmarks]


def extract_pose_landmarks(image_bgr: np.ndarray) -> list[dict] | None:
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    result = _pose.process(rgb)
    if not result.pose_landmarks:
        return None
    h, w = image_bgr.shape[:2]
    landmarks = result.pose_landmarks.landmark
    return [
        {"x": lm.x * w, "y": lm.y * h, "z": lm.z, "visibility": lm.visibility}
        for lm in landmarks
    ]


def _crop_head_region(image_bgr: np.ndarray, pose_landmarks: list[dict], target_size: int = 480) -> np.ndarray | None:
    """
    Locate the head using pose landmarks (nose + ears) and return a
    cropped-and-upscaled sub-image centered on it.

    Why this exists: a full-body shot (needed for accurate size estimation)
    puts the face far from the camera, so it occupies very few pixels in the
    frame -- often too few for FaceMesh's face detector, which is tuned for
    closer, larger faces (portrait/selfie distance). Since Pose reliably
    detects the whole body at that same distance, we use ITS head-region
    landmarks to find and zoom into just the face, then hand FaceMesh a
    properly-sized crop instead of the tiny face-in-a-wide-shot it was
    failing on.
    """
    if not pose_landmarks or len(pose_landmarks) <= POSE_RIGHT_EAR:
        return None

    nose = pose_landmarks[POSE_NOSE]
    left_ear = pose_landmarks[POSE_LEFT_EAR]
    right_ear = pose_landmarks[POSE_RIGHT_EAR]
    if any(lm.get("visibility", 1.0) < 0.3 for lm in (nose, left_ear, right_ear)):
        return None

    ear_dist = math.hypot(left_ear["x"] - right_ear["x"], left_ear["y"] - right_ear["y"])
    if ear_dist <= 1:
        return None

    # Generous padding: ears mark head WIDTH, not its full extent, and we
    # need room above (hair/crown) and below (chin/neck) the nose too.
    half_width = ear_dist * 1.6
    half_height = ear_dist * 2.0
    cx = nose["x"]
    cy = nose["y"] - ear_dist * 0.2  # nose sits slightly below head center

    h, w = image_bgr.shape[:2]
    x0, x1 = max(int(cx - half_width), 0), min(int(cx + half_width), w)
    y0, y1 = max(int(cy - half_height), 0), min(int(cy + half_height), h)
    if x1 - x0 < 10 or y1 - y0 < 10:
        return None

    crop = image_bgr[y0:y1, x0:x1]
    longest_side = max(crop.shape[:2])
    if longest_side <= 0:
        return None
    scale = target_size / longest_side
    if scale <= 1.0:
        return crop  # already large enough
    new_w, new_h = int(crop.shape[1] * scale), int(crop.shape[0] * scale)
    return cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_CUBIC)


def extract_all(file_bytes: bytes) -> dict:
    """
    Single entry point used by the /vision/scan endpoint and the agent tool.

    Runs face detection on the main frame first. If that fails AND pose
    landmarks are available, retries on a cropped/upscaled head region located
    via pose (see _crop_head_region) -- this is what makes face shape/skin
    tone/glasses/hair detection work even when the user is standing back far
    enough for a full-body size estimate, instead of only working up close.

    `_image` is returned matching whichever frame face_landmarks came from
    (main frame, or the head crop) since skin_tone/glasses/hair all sample
    pixels using face_landmarks' coordinates -- they must stay in the same
    coordinate space as the landmarks passed alongside them.
    """
    image = decode_image(file_bytes)
    pose = extract_pose_landmarks(image)
    face = extract_face_landmarks(image)
    face_image = image

    if face is None and pose is not None:
        crop = _crop_head_region(image, pose)
        if crop is not None:
            retry_face = extract_face_landmarks(crop)
            if retry_face is not None:
                face = retry_face
                face_image = crop

    return {
        "image_shape": {"height": image.shape[0], "width": image.shape[1]},
        "face_landmarks": face,
        "pose_landmarks": pose,
        "_image": face_image,  # kept in-process only, stripped before returning to client
    }
