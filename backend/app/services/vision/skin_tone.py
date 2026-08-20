"""
Skin tone extraction for clothing color-matching purposes only.

We deliberately classify by DEPTH (how light/dark) and UNDERTONE (warm/cool/neutral)
-- both are directly useful for recommending flattering clothing colors -- and never
attempt any demographic/ethnicity inference.

Sampling strategy: average pixel color over small patches on both cheeks and the
forehead (using FaceMesh landmarks), which avoids eyes/lips/hair/shadow regions.
"""
import numpy as np

LEFT_CHEEK, RIGHT_CHEEK, FOREHEAD = 50, 280, 151
PATCH_RADIUS = 6


def _sample_patch(image_bgr: np.ndarray, cx: int, cy: int, r: int = PATCH_RADIUS) -> np.ndarray:
    h, w = image_bgr.shape[:2]
    x0, x1 = max(cx - r, 0), min(cx + r, w)
    y0, y1 = max(cy - r, 0), min(cy + r, h)
    patch = image_bgr[y0:y1, x0:x1]
    return patch.reshape(-1, 3) if patch.size else np.zeros((1, 3))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _classify_depth(luminance: float) -> str:
    # luminance in 0-255
    if luminance >= 200:
        return "fair"
    if luminance >= 170:
        return "light"
    if luminance >= 130:
        return "medium"
    if luminance >= 95:
        return "tan"
    return "deep"


def _classify_undertone(r: float, g: float, b: float) -> str:
    # Simple heuristic: compare red/yellow balance vs blue.
    warm_score = (r + g) - 2 * b
    if warm_score > 15:
        return "warm"
    if warm_score < -15:
        return "cool"
    return "neutral"


def extract_skin_tone(image_bgr: np.ndarray, face_landmarks: list[dict]) -> dict:
    if not face_landmarks or len(face_landmarks) < 468:
        return {"skin_tone_hex": None, "depth": "unknown", "undertone": "unknown", "confidence": 0.0}

    points = [face_landmarks[i] for i in (LEFT_CHEEK, RIGHT_CHEEK, FOREHEAD)]
    samples = []
    for p in points:
        patch = _sample_patch(image_bgr, int(p["x"]), int(p["y"]))
        samples.append(patch)
    all_pixels = np.vstack(samples).astype(np.float32)

    # Drop near-black/near-white outliers (shadows, specular highlights)
    mask = (all_pixels.sum(axis=1) > 30) & (all_pixels.sum(axis=1) < 740)
    filtered = all_pixels[mask] if mask.any() else all_pixels

    b, g, r = filtered.mean(axis=0)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    warm_score = (r + g) - 2 * b

    depth = _classify_depth(luminance)
    undertone = _classify_undertone(r, g, b)
    hex_color = _rgb_to_hex((int(r), int(g), int(b)))

    # Genuine confidence, not a fixed constant: combines (a) how many of the
    # sampled pixels were usable after dropping shadow/highlight outliers,
    # (b) how internally consistent the three patches were (low spread across
    # cheeks/forehead = a clean, well-lit read), and (c) how far the
    # luminance/warm-score sit from their nearest bucket boundary -- a
    # borderline warm_score of 16 is a much shakier "warm" call than one of 60.
    valid_ratio = float(mask.mean()) if mask.size else 0.0
    pixel_std = float(filtered.std(axis=0).mean()) if filtered.size else 255.0
    consistency = max(0.0, 1.0 - pixel_std / 60.0)  # tighter spread -> higher confidence
    depth_bounds = [200, 170, 130, 95]
    depth_margin = min(abs(luminance - b) for b in depth_bounds)
    undertone_margin = abs(abs(warm_score) - 15)
    boundary_confidence = min(1.0, (depth_margin / 40.0 + undertone_margin / 30.0) / 2)

    confidence = round(min(0.3 + valid_ratio * 0.2 + consistency * 0.25 + boundary_confidence * 0.25, 0.9), 2)

    print(
        f"[vision:skin_tone] sampled_rgb=({r:.1f},{g:.1f},{b:.1f}) luminance={luminance:.1f} "
        f"warm_score={warm_score:.1f} valid_ratio={valid_ratio:.2f} pixel_std={pixel_std:.1f} "
        f"-> depth={depth} undertone={undertone} hex={hex_color} confidence={confidence}"
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
