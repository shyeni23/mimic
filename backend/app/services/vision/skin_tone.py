"""
Skin tone extraction for clothing color-matching purposes only.

We deliberately classify by DEPTH (how light/dark) and UNDERTONE (warm/cool/neutral)
-- both are directly useful for recommending flattering clothing colors -- and never
attempt any demographic/ethnicity inference.

Sampling strategy: small patches on both cheeks and two forehead points (using
FaceMesh landmarks), which avoids eyes/lips/hair/shadow regions.

CALIBRATION IMPROVEMENTS (per the Module 1 research brief's own conclusion: skin
tone was its LOWEST-priority item, explicitly recommending "keep the heuristic,
don't add ML" -- the dermatology skin-tone datasets it surveyed, e.g. Fitzpatrick17k
and SCIN, were flagged as a domain mismatch for a fashion webcam and reference-only.
These are the calibration upgrades it did recommend):
1. Gray-world white-balance correction (computed from the WHOLE frame, not the
   patches themselves -- gray-world assumes a full natural scene averages to
   neutral gray, which holds reasonably for a room+person frame but not for a
   small non-gray skin patch) so ambient light color temperature (warm bulbs,
   cool daylight, etc.) doesn't get misread as the person's actual undertone.
2. CIELAB instead of raw RGB math for classification -- LAB separates lightness
   (L) from color (a/b) by design, unlike the old luminance-formula/RGB-math
   approach where brightness and color were entangled.
3. A fourth sample point (added forehead-top, landmark 10 -- already validated
   elsewhere in this codebase, see face_shape.py/height_estimate.py) and a
   trimmed mean per patch, so a stray hair/shadow/highlight pixel within one
   patch can't skew that patch's read.
4. A real inter-patch consistency check: if the cheek/forehead patches disagree
   with each other beyond a threshold (uneven lighting across the face, partial
   occlusion, motion blur), the result now genuinely degrades toward "unknown"
   instead of confidently averaging over conflicting data.
"""
import cv2
import numpy as np

LEFT_CHEEK, RIGHT_CHEEK, FOREHEAD, FOREHEAD_TOP = 50, 280, 151, 10
SAMPLE_POINTS = (LEFT_CHEEK, RIGHT_CHEEK, FOREHEAD, FOREHEAD_TOP)
PATCH_RADIUS = 6
TRIM_FRACTION = 0.15  # drop the darkest/lightest 15% of pixels per patch before averaging


def _sample_patch(image_bgr: np.ndarray, cx: int, cy: int, r: int = PATCH_RADIUS) -> np.ndarray:
    h, w = image_bgr.shape[:2]
    x0, x1 = max(cx - r, 0), min(cx + r, w)
    y0, y1 = max(cy - r, 0), min(cy + r, h)
    patch = image_bgr[y0:y1, x0:x1]
    return patch.reshape(-1, 3).astype(np.float32) if patch.size else np.zeros((0, 3), dtype=np.float32)


def _gray_world_gains(image_bgr: np.ndarray) -> np.ndarray:
    """Per-channel (B,G,R) correction gains from the gray-world assumption,
    estimated from the WHOLE frame -- see module docstring point 1."""
    avg = image_bgr.reshape(-1, 3).astype(np.float32).mean(axis=0)
    avg = np.clip(avg, 1.0, None)  # avoid divide-by-zero on a degenerate all-black frame
    gray = float(avg.mean())
    return gray / avg


def _trimmed_mean(pixels: np.ndarray, trim_fraction: float = TRIM_FRACTION) -> np.ndarray | None:
    """Per-channel trimmed mean -- drops the extreme high/low tail of each
    channel independently before averaging, so a handful of shadow/highlight/
    hair pixels inside a patch can't dominate the read. Returns None if the
    patch has no usable pixels at all."""
    if pixels.shape[0] == 0:
        return None
    n = pixels.shape[0]
    k = int(n * trim_fraction)
    result = np.empty(3, dtype=np.float32)
    for c in range(3):
        sorted_channel = np.sort(pixels[:, c])
        trimmed = sorted_channel[k: n - k] if n - 2 * k > 0 else sorted_channel
        result[c] = trimmed.mean()
    return result


def _bgr_to_lab(bgr: np.ndarray) -> np.ndarray:
    """Single BGR pixel (0-255 float) -> LAB (OpenCV's 8-bit convention: L in
    0-255, a/b centered at 128) via a real color-space conversion."""
    pixel = np.clip(bgr, 0, 255).astype(np.uint8).reshape(1, 1, 3)
    lab = cv2.cvtColor(pixel, cv2.COLOR_BGR2LAB).reshape(3).astype(np.float32)
    return lab


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _classify_depth(lightness: float) -> str:
    # L in OpenCV's 8-bit LAB convention (0-255) -- same scale/boundaries the
    # project already calibrated for its old luminance formula, which L is a
    # more perceptually-correct version of (design intent, not a coincidence:
    # both approximate "how bright", LAB's L is just built for exactly that).
    if lightness >= 200:
        return "fair"
    if lightness >= 170:
        return "light"
    if lightness >= 130:
        return "medium"
    if lightness >= 95:
        return "tan"
    return "deep"


def _classify_undertone(b_channel: float) -> str:
    # LAB's b axis is blue(-)/yellow(+) -- "warm" (golden/yellow) vs "cool"
    # (pink/blue) undertone in fashion/cosmetics terminology maps directly
    # onto this axis, more directly than the old (R+G)-2B RGB approximation.
    warm_score = b_channel - 128.0
    if warm_score > 6:
        return "warm"
    if warm_score < -6:
        return "cool"
    return "neutral"


def extract_skin_tone(image_bgr: np.ndarray, face_landmarks: list[dict]) -> dict:
    if not face_landmarks or len(face_landmarks) < 468:
        return {"skin_tone_hex": None, "depth": "unknown", "undertone": "unknown", "confidence": 0.0}

    gains = _gray_world_gains(image_bgr)

    patch_labs = []  # one LAB triple per sample point, after white-balance + trimming
    total_pixels = 0
    usable_pixels = 0
    for idx in SAMPLE_POINTS:
        p = face_landmarks[idx]
        raw = _sample_patch(image_bgr, int(p["x"]), int(p["y"]))
        total_pixels += raw.shape[0]
        if raw.shape[0] == 0:
            continue
        # Drop near-black/near-white outliers (shadows, specular highlights) before trimming
        mask = (raw.sum(axis=1) > 30) & (raw.sum(axis=1) < 740)
        filtered = raw[mask] if mask.any() else raw
        usable_pixels += filtered.shape[0]
        corrected = filtered * gains  # gray-world white balance
        trimmed = _trimmed_mean(corrected)
        if trimmed is not None:
            patch_labs.append(_bgr_to_lab(trimmed))

    if not patch_labs:
        return {"skin_tone_hex": None, "depth": "unknown", "undertone": "unknown", "confidence": 0.0}

    patch_labs = np.array(patch_labs)  # shape (num_patches, 3) -- [L, a, b] per patch

    # Inter-patch consistency: how much do the cheek/forehead reads disagree
    # with each other? High spread means uneven lighting across the face,
    # partial occlusion, or motion blur -- a genuine reliability signal, not
    # just noise to average away.
    patch_spread = float(patch_labs.std(axis=0).mean())

    l_mean, a_mean, b_mean = patch_labs.mean(axis=0)

    # Reconstruct an approximate display RGB from the mean LAB for the hex
    # swatch (Lab->BGR round-trip via OpenCV, single-pixel conversion).
    lab_pixel = np.clip(np.array([l_mean, a_mean, b_mean]), 0, 255).astype(np.uint8).reshape(1, 1, 3)
    bgr_pixel = cv2.cvtColor(lab_pixel, cv2.COLOR_LAB2BGR).reshape(3)
    b, g, r = [int(v) for v in bgr_pixel]

    depth = _classify_depth(l_mean)
    undertone = _classify_undertone(b_mean)
    hex_color = _rgb_to_hex((r, g, b))

    # Confidence combines: (a) how many sampled pixels survived outlier
    # rejection, (b) how consistent the independent patches were with each
    # other (the new, real reliability signal from point 4 above), and (c)
    # how far depth/undertone sit from their nearest bucket boundary.
    valid_ratio = (usable_pixels / total_pixels) if total_pixels else 0.0
    consistency = max(0.0, 1.0 - patch_spread / 25.0)  # tighter cross-patch agreement -> higher confidence
    depth_bounds = [200, 170, 130, 95]
    depth_margin = min(abs(l_mean - bnd) for bnd in depth_bounds)
    undertone_margin = abs(abs(b_mean - 128.0) - 6)
    boundary_confidence = min(1.0, (depth_margin / 40.0 + undertone_margin / 15.0) / 2)

    confidence = round(min(0.3 + valid_ratio * 0.2 + consistency * 0.25 + boundary_confidence * 0.25, 0.9), 2)

    # A patch disagreement this large means the four readings couldn't agree
    # on even a rough skin tone -- honest "unknown" beats confidently
    # averaging over data that doesn't actually agree.
    if patch_spread > 30:
        print(
            f"[vision:skin_tone] patch_spread={patch_spread:.1f} too high (patches disagree) -- returning unknown"
        )
        return {"skin_tone_hex": hex_color, "depth": "unknown", "undertone": "unknown", "confidence": 0.15}

    print(
        f"[vision:skin_tone] lab=({l_mean:.1f},{a_mean:.1f},{b_mean:.1f}) patch_spread={patch_spread:.1f} "
        f"valid_ratio={valid_ratio:.2f} -> depth={depth} undertone={undertone} hex={hex_color} confidence={confidence}"
    )

    return {
        "skin_tone_hex": hex_color,
        "depth": depth,
        "undertone": undertone,
        "confidence": confidence,
    }


# Simple color-recommendation lookup consumed by the recommendation engine (Module 1/3)
FLATTERING_PALETTES = {
    ("warm", "fair"): ["coral", "peach", "warm beige", "olive green", "gold"],
    ("warm", "light"): ["camel", "terracotta", "mustard", "warm red", "olive"],
    ("warm", "medium"): ["burnt orange", "warm brown", "gold", "tomato red"],
    ("warm", "tan"): ["rust", "chocolate brown", "amber", "warm green"],
    ("warm", "deep"): ["deep orange", "bronze", "warm burgundy", "gold"],
    ("cool", "fair"): ["soft blue", "lavender", "rose pink", "emerald"],
    ("cool", "light"): ["cobalt blue", "berry", "cool gray", "jewel tones"],
    ("cool", "medium"): ["sapphire", "plum", "true red", "cool teal"],
    ("cool", "tan"): ["fuchsia", "royal blue", "deep purple", "icy pastels"],
    ("cool", "deep"): ["bright white", "cobalt", "magenta", "jewel tones"],
    ("neutral", "fair"): ["soft pink", "navy", "dusty rose", "sage"],
    ("neutral", "light"): ["navy", "soft teal", "mauve", "gray"],
    ("neutral", "medium"): ["teal", "burgundy", "charcoal", "dusty blue"],
    ("neutral", "tan"): ["olive", "rust", "navy", "cream"],
    ("neutral", "deep"): ["white", "cobalt", "emerald", "warm gray"],
}


def recommended_palette(depth: str, undertone: str) -> list[str]:
    return FLATTERING_PALETTES.get((undertone, depth), ["navy", "white", "gray", "black"])
