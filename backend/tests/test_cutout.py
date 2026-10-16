"""Garment cutouts (app/services/fashion/cutout.py).

The browser flood-fill this replaces erased a white garment on a white
backdrop entirely -- measured 96% of pixels cleared, i.e. the product
vanished. White kurtas and cream sarees are common here, so that mattered.
"""
import numpy as np
import pytest

from app.services.fashion.cutout import has_plain_backdrop


def _studio_shot(garment_colour=(60, 60, 200), backdrop=255):
    """Product centred on a plain light backdrop, like the catalog."""
    img = np.full((512, 384, 3), backdrop, dtype=np.uint8)
    img[120:400, 110:280] = garment_colour
    return img


def test_plain_studio_backdrop_is_accepted():
    assert has_plain_backdrop(_studio_shot())


def test_white_garment_on_white_still_has_a_plain_backdrop():
    """The case that broke flood-fill: the garment itself is white, so
    colour-distance from the corner tells you nothing."""
    assert has_plain_backdrop(_studio_shot(garment_colour=(250, 250, 250)))


def test_busy_background_is_refused():
    """A lifestyle shot has no plain border, so GrabCut's assumption fails
    and carving it would ruin the image -- better to leave it alone."""
    rng = np.random.default_rng(0)
    busy = rng.integers(0, 255, (512, 384, 3), dtype=np.uint8)
    assert not has_plain_backdrop(busy)


def test_dark_backdrop_is_refused():
    """Uniform but dark: more likely a photo that happens to have dark
    edges than a studio cut-out shot."""
    assert not has_plain_backdrop(_studio_shot(backdrop=30))


@pytest.mark.parametrize("colour", [(250, 250, 250), (10, 10, 10), (200, 30, 30)])
def test_garment_colour_does_not_decide_suitability(colour):
    """Suitability is about the BACKDROP, not the product -- that was the
    flood-fill's fatal assumption."""
    assert has_plain_backdrop(_studio_shot(garment_colour=colour))
