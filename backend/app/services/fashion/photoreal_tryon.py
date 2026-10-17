"""
Photorealistic virtual try-on (Module 5).

The live overlay in the browser positions a cut-out garment on the body: it
tracks, scales and rotates, but it is a flat sticker. It cannot drape, fold,
shade, or wrap around an arm, because none of that is solvable at 12fps on a
CPU.

This is the real thing. A diffusion try-on model (IDM-VTON) takes a photo of
the person and a photo of the garment and generates the person actually
wearing it -- correct drape, folds, shadows and fit. It costs one GPU
inference, roughly 10-20 seconds, which is why it is a "take a photo, see
the result" flow rather than a live mirror. Every commercial try-on works
this way for the same reason.

Runs on Replicate so no GPU is needed locally. Set REPLICATE_API_TOKEN in
backend/.env to enable; without it this degrades to "unavailable" and the
live overlay remains, matching how weather.py and the FashionCLIP/DeepFace
paths handle missing credentials.
"""
import base64
import time

import httpx

from app.config import settings

# IDM-VTON: the strongest open try-on model as of writing, and the one with
# the most reliable hosted endpoint. Pinned by version digest because
# Replicate models are mutable by tag.
REPLICATE_MODEL = (
    "cuuupid/idm-vton:"
    "c871bb9b046607b680449ecbae55fd8c6d945e0a1948644bf2361b3d021d3ff4"
)
REPLICATE_URL = "https://api.replicate.com/v1/predictions"
# Generation is 10-20s; the poll gives it real headroom before giving up.
POLL_TIMEOUT_S = 90
POLL_INTERVAL_S = 1.5


# FREE path: the same IDM-VTON model, running on Hugging Face's shared
# ZeroGPU. No card, no token needed. The trade-off is a public queue --
# minutes at busy times, and the Space can be down entirely -- so Replicate
# stays the paid option for when it has to work on demand.
HF_SPACE = "yisol/IDM-VTON"
HF_TIMEOUT_S = 300


def backend() -> str:
    """Which try-on backend is in use: 'replicate' (paid, reliable),
    'huggingface' (free, queued) or 'none'."""
    if settings.replicate_api_token:
        return "replicate"
    if settings.tryon_use_free_space:
        return "huggingface"
    return "none"


def is_available() -> bool:
    return backend() != "none"


def _generate_huggingface(person_jpeg: bytes, garment_url: str, description: str) -> dict:
    """Free Hugging Face Space. Slower and queue-dependent, same model."""
    import tempfile
    from pathlib import Path

    try:
        from gradio_client import Client, handle_file
    except ImportError:
        return {"error": "gradio_client isn't installed (pip install gradio_client)"}

    tmpdir = Path(tempfile.mkdtemp(prefix="tryon_"))
    try:
        person_path = tmpdir / "person.jpg"
        person_path.write_bytes(person_jpeg)
        client = Client(HF_SPACE, token=settings.hf_token or None)
        result = client.predict(
            dict={"background": handle_file(str(person_path)), "layers": [], "composite": None},
            garm_img=handle_file(garment_url),
            garment_des=description or "clothing item",
            is_checked=True,        # auto-generate the body mask
            is_checked_crop=True,   # auto-crop to the person
            denoise_steps=30,
            seed=42,
            api_name="/tryon",
        )
        # Returns (generated_image_path, masked_image_path).
        out = result[0] if isinstance(result, (list, tuple)) else result
        if not out:
            return {"error": "the free try-on service returned no image"}
        data = Path(out).read_bytes()
        return {"image_data": data, "mime": "image/png"}
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        # The Space is ZeroGPU: anonymous callers get little or no GPU quota,
        # and it reports that as a bare "upstream Gradio app has raised an
        # exception" with no detail. Verified live -- the API signature and
        # inputs were correct and it still failed, which is what pointed at
        # quota. A free HF account token is usually enough to fix it.
        if ("quota" in low or "gpu" in low or "exceeded" in low
                or "has raised an exception" in low):
            hint = ("" if settings.hf_token else
                    " Adding a free HF_TOKEN to backend/.env usually fixes this -- "
                    "the shared GPU gives anonymous callers almost no quota.")
            return {"error": f"The free try-on service turned the request away.{hint}"}
        return {"error": f"free try-on failed: {msg[:200]}"}
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def _data_url(image_bytes: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"


def generate_tryon(person_jpeg: bytes, garment_url: str, *,
                   category: str = "upper_body", description: str = "") -> dict:
    """Photo of the person + garment image -> photo of them wearing it.

    Returns {"image_url": ...} on success, or {"error": ...}. Never raises:
    a failed try-on must fall back to the live overlay, not break the page.

    category maps to what the model expects for garment placement:
    upper_body | lower_body | dresses.
    """
    which = backend()
    if which == "none":
        return {"error": "photorealistic try-on is not configured"}
    if which == "huggingface":
        return _generate_huggingface(person_jpeg, garment_url, description)

    headers = {
        "Authorization": f"Bearer {settings.replicate_api_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "version": REPLICATE_MODEL.split(":", 1)[1],
        "input": {
            "human_img": _data_url(person_jpeg),
            "garm_img": garment_url,
            "garment_des": description or "clothing item",
            "category": category,
            "crop": True,          # auto-crop to the person
            "force_dc": False,
            "steps": 30,           # quality/latency balance
        },
    }

    try:
        with httpx.Client(timeout=30) as client:
            created = client.post(REPLICATE_URL, headers=headers, json=payload)
            if created.status_code >= 400:
                return {"error": f"try-on service rejected the request: {created.text[:200]}"}
            prediction = created.json()
            poll_url = prediction.get("urls", {}).get("get")
            if not poll_url:
                return {"error": "try-on service did not return a result URL"}

            deadline = time.time() + POLL_TIMEOUT_S
            while time.time() < deadline:
                time.sleep(POLL_INTERVAL_S)
                res = client.get(poll_url, headers=headers)
                data = res.json()
                status = data.get("status")
                if status == "succeeded":
                    out = data.get("output")
                    # The model returns either a URL or a single-item list.
                    url = out[0] if isinstance(out, list) and out else out
                    if not url:
                        return {"error": "try-on finished but returned no image"}
                    return {"image_url": url, "seconds": round(POLL_TIMEOUT_S - (deadline - time.time()), 1)}
                if status in ("failed", "canceled"):
                    return {"error": f"try-on {status}: {str(data.get('error'))[:200]}"}
            return {"error": "try-on timed out -- the service is busy, try again"}
    except Exception as e:
        print(f"[photoreal_tryon] request failed (non-fatal): {e}")
        return {"error": f"could not reach the try-on service: {e}"}


# Catalog category -> what the model calls that garment slot.
CATEGORY_MAP = {
    "top": "upper_body",
    "dress": "dresses",
    "bottom": "lower_body",
}


def model_category(catalog_category: str | None) -> str | None:
    return CATEGORY_MAP.get((catalog_category or "").lower())
