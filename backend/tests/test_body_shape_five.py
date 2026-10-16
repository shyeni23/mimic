"""All five body shapes, via the segmentation silhouette.

Pose has no waist landmark, so hourglass and apple used to be unreachable --
only 3 of the 5 shapes could ever be returned. The waist now comes from the
body outline (MediaPipe's segmentation mask).

Synthetic silhouettes are used deliberately: they are the only way to assert
"this IS an hourglass" without labelled photographs of real people.
"""
import numpy as np
import pytest

from app.services.vision.body_shape import classify_body_shape

H, W = 600, 400
SHOULDER_Y, HIP_Y = 150, 450
WAIST_T = 0.55          # waist sits 55% of the way down the torso


def silhouette(shoulder, waist, hip):
    """Body outline tapering shoulder -> waist -> hip (half-widths, px)."""
    m = np.zeros((H, W), dtype=np.float32)
    for y in range(SHOULDER_Y, HIP_Y + 1):
        t = (y - SHOULDER_Y) / (HIP_Y - SHOULDER_Y)
        if t <= WAIST_T:
            w = shoulder + (waist - shoulder) * (t / WAIST_T)
        else:
            w = waist + (hip - waist) * ((t - WAIST_T) / (1 - WAIST_T))
        m[y, int(W // 2 - w):int(W // 2 + w)] = 1.0
    return m


def landmarks(shoulder, hip):
    lm = [{"x": 0, "y": 0, "z": 0, "visibility": 1.0} for _ in range(33)]
    cx = W // 2
    lm[11] = {"x": cx - shoulder, "y": SHOULDER_Y, "z": 0, "visibility": 1.0}
    lm[12] = {"x": cx + shoulder, "y": SHOULDER_Y, "z": 0, "visibility": 1.0}
    lm[23] = {"x": cx - hip, "y": HIP_Y, "z": 0, "visibility": 1.0}
    lm[24] = {"x": cx + hip, "y": HIP_Y, "z": 0, "visibility": 1.0}
    lm[27] = {"x": cx - 20, "y": 580, "z": 0, "visibility": 1.0}
    lm[28] = {"x": cx + 20, "y": 580, "z": 0, "visibility": 1.0}
    lm[2] = {"x": cx - 15, "y": 100, "z": 0, "visibility": 1.0}
    lm[5] = {"x": cx + 15, "y": 100, "z": 0, "visibility": 1.0}
    return lm


@pytest.mark.parametrize("expected, shoulder, waist, hip", [
    ("hourglass", 90, 55, 92),            # balanced ends, nipped waist
    ("apple", 85, 100, 88),               # midsection is the widest part
    ("pear", 70, 72, 105),                # hips widest
    ("inverted_triangle", 110, 80, 70),   # shoulders widest
    ("rectangle", 90, 84, 90),            # all similar, no real nip
])
def test_all_five_shapes(expected, shoulder, waist, hip):
    result = classify_body_shape(landmarks(shoulder, hip), silhouette(shoulder, waist, hip))
    assert result["body_shape"] == expected, result["metrics"]
    assert result["metrics"]["ratio_source"] == "silhouette"


def test_falls_back_to_landmarks_without_a_mask():
    """No mask (older frames, segmentation unavailable) must still classify,
    just without hourglass/apple -- and must say so rather than guessing."""
    result = classify_body_shape(landmarks(110, 70), None)
    assert result["body_shape"] in ("inverted_triangle", "pear", "rectangle")
    assert result["metrics"]["ratio_source"] == "landmarks"
    assert result["metrics"]["waist_to_widest_ratio"] is None


def test_outstretched_arm_does_not_become_waist_width():
    """A row where the person's pixels are sparse across the span is an arm
    held away from the body, not torso width."""
    m = silhouette(90, 55, 92)
    waist_row = int(SHOULDER_Y + (HIP_Y - SHOULDER_Y) * WAIST_T)
    m[waist_row - 1:waist_row + 2, 10:20] = 1.0      # detached arm pixels
    result = classify_body_shape(landmarks(90, 92), m)
    assert result["body_shape"] == "hourglass", result["metrics"]
