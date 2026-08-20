"""
FashionCLIP wrapper.

Used two ways:
1. Offline: embed every inventory image once, store the vector in Supabase
   (inventory.embedding, pgvector). See scripts/embed_inventory.py.
2. Online: embed the user's text query ("something for a wedding") or a
   selected item's image, then call match_inventory() (pgvector cosine
   search) to retrieve visually/semantically compatible pieces.
"""
import os
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image
from fashion_clip.fashion_clip import FashionCLIP

from app.config import settings

_MIN_WEIGHT_BYTES = 100_000_000  # real CLIP weights are ~600MB; reject partial/incomplete blobs


def _is_fully_cached(repo_id: str) -> bool:
    """
    Filesystem-only check (zero network calls) for whether repo_id's weights
    are fully downloaded to the local HF cache. Needed because fashion-clip's
    own loader calls a raw `requests.get` HF-repo-existence check before ever
    touching HF_HUB_OFFLINE, so that env var alone doesn't prevent a hang on a
    stalled connection -- this check lets us skip calling FashionCLIP()
    entirely (and therefore skip that hang) until the weights are really there.
    """
    cache_root = Path.home() / ".cache" / "huggingface" / "hub"
    repo_dir = cache_root / ("models--" + repo_id.replace("/", "--"))
    snapshots_dir = repo_dir / "snapshots"
    if not snapshots_dir.exists():
        return False
    for snapshot in snapshots_dir.iterdir():
        weight_files = list(snapshot.glob("*.safetensors")) + list(snapshot.glob("pytorch_model.bin"))
        if not weight_files or not (snapshot / "config.json").exists():
            continue
        for w in weight_files:
            resolved = w.resolve() if w.is_symlink() else w
            if resolved.exists() and resolved.stat().st_size > _MIN_WEIGHT_BYTES:
                return True
    return False


@lru_cache
def get_model() -> FashionCLIP:
    """
    Only instantiates FashionCLIP once its weights are fully present locally.
    Raises immediately (no network call at all) otherwise, so callers can fall
    back to a non-ML search instead of hanging on a slow/stalled download.
    """
    if not _is_fully_cached(settings.fashion_clip_model):
        raise RuntimeError(f"FashionCLIP weights for '{settings.fashion_clip_model}' not fully downloaded yet")

    prev = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        return FashionCLIP(settings.fashion_clip_model)
    finally:
        if prev is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = prev


def embed_image_bytes(image_bytes: bytes) -> list[float]:
    model = get_model()
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    embedding = model.encode_images([image], batch_size=1)[0]
    return embedding.tolist()


def embed_text(text: str) -> list[float]:
    model = get_model()
    embedding = model.encode_text([text], batch_size=1)[0]
    return embedding.tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = get_model()
    embeddings = model.encode_text(texts, batch_size=min(32, len(texts)))
    return [e.tolist() for e in embeddings]
