"""
Garment cutouts for virtual try-on.

The first version did this in the browser: flood-fill inward from the image
edges, clearing pixels close to the corner colour. That is cheap but crude --
it stops at the first colour change, so it leaves the shadow under a
garment, eats a white shirt on a white backdrop entirely (measured 96% of
pixels cleared), and cannot follow a soft or frayed edge at all.

GrabCut is a real segmentation algorithm (iterative graph cut over a colour
model of foreground vs background). On a catalog product shot -- one centred
object, plain backdrop -- it is close to ideal: initialise with a rectangle
inset from the borders, let it refine the boundary, and the result follows
sleeves, drape and hems properly.

Cutouts are cached on disk because GrabCut costs ~0.3-1s per image and the
result never changes: the same product always cuts out the same way.
"""
import hashlib
from pathlib import Path

import cv2
import numpy as np

# Alongside the product photos themselves (backend/data/product_images).
CUTOUT_DIR = Path(__file__).resolve().parents[3] / "data" / "cutouts"
CUTOUT_DIR.mkdir(parents=True, exist_ok=True)

# How far in from each edge the "definitely background" border is. Catalog
# shots keep the product well clear of the frame, so 6% is safe; too large
# and a wide garment's sleeves fall outside the init rectangle and get cut.
BORDER_FRACTION = 0.06
GRABCUT_ITERATIONS = 5
# Below this the backdrop isn't plain and GrabCut's assumption breaks.
MIN_BACKDROP_BRIGHTNESS = 170


def _cache_path(image_path: Path) -> Path:
    key = hashlib.sha1(str(image_path).encode()).hexdigest()[:16]
    return CUTOUT_DIR / f"{key}.png"


def has_plain_backdrop(img: np.ndarray) -> bool:
    """GrabCut needs the border to really be background. A lifestyle shot
    (model outdoors, busy background) breaks that assumption, so it's better
    to leave those alone than to carve a hole in them."""
    h, w = img.shape[:2]
    b = max(2, int(min(h, w) * 0.02))
    border = np.concatenate([
        img[:b].reshape(-1, 3), img[-b:].reshape(-1, 3),
        img[:, :b].reshape(-1, 3), img[:, -b:].reshape(-1, 3),
    ])
    mean = border.mean(axis=0)
    # Plain AND light: a uniform dark backdrop would also be "plain" but
    # these catalog shots are white, and a dark one is more likely a photo
    # that happens to have dark edges.
    spread = float(border.std(axis=0).mean())
    return bool(mean.min() >= MIN_BACKDROP_BRIGHTNESS and spread < 42)


def make_cutout(image_path: Path, force: bool = False) -> Path | None:
    """Transparent PNG of the garment, or None when the image isn't suitable.

    Cached: the same product always cuts out identically, and GrabCut is far
    too slow to run per request.
    """
    image_path = Path(image_path)
    out = _cache_path(image_path)
    if out.exists() and not force:
        return out
    img = cv2.imread(str(image_path))
    if img is None:
        return None
    if not has_plain_backdrop(img):
        return None

    h, w = img.shape[:2]
    bx, by = int(w * BORDER_FRACTION), int(h * BORDER_FRACTION)
    rect = (bx, by, w - 2 * bx, h - 2 * by)

    mask = np.zeros((h, w), np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(img, mask, rect, bgd, fgd, GRABCUT_ITERATIONS, cv2.GC_INIT_WITH_RECT)
    except cv2.error as e:
        print(f"[cutout] grabCut failed for {image_path.name}: {e}")
        return None

    # GC_FGD / GC_PR_FGD are the keep classes.
    alpha = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)

    kept = float(alpha.mean()) / 255.0
    # Same guard the browser version needed: a white garment on white can
    # still collapse, and a result that kept almost everything means the
    # backdrop was never separated. Either way the original is better than
    # a hole or a rectangle.
    if not 0.04 <= kept <= 0.92:
        print(f"[cutout] implausible result for {image_path.name} (kept {kept:.0%}) -- skipped")
        return None

    # Feather the edge by a pixel so it doesn't look cut with scissors.
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
    rgba = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = alpha
    cv2.imwrite(str(out), rgba)
    return out
