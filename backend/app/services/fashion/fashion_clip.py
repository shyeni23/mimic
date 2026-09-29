"""
Fashion CLIP wrapper -- Marqo-FashionCLIP by default.

Model choice: `Marqo/marqo-fashionCLIP` (Apache-2.0, ViT-B-16, 512-dim,
maintained by Marqo, ~+57% eval-metric gain over patrickjohncyh's original
fashion-clip on the same benchmarks). Both output 512-dim vectors so the
existing pgvector column stays the same size; changing the model name in
config swaps between them without a schema migration.

Load path: `open_clip.create_model_and_transforms('hf-hub:<model>')`. This
replaces the earlier `fashion-clip` PyPI package, which hard-pinned
torch==1.11.0 and was incompatible with any modern transformers install.
open_clip is the same library Marqo used to train these weights and is a
maintained mainstream dep.

Same public API as before:
- embed_image_bytes(bytes) -> list[float]
- embed_text(str) -> list[float]
- embed_texts(list[str]) -> list[list[float]]

Used two ways:
1. Offline: embed every inventory image once, store vector in Supabase
   (inventory.embedding, pgvector). See scripts/embed_inventory.py.
2. Online: embed a text query or item image, then call match_inventory()
   (pgvector cosine search) to retrieve compatible pieces.

Embedding-space compatibility: switching model NAMES invalidates any
previously-stored vectors -- cosine similarity across two different
embedding spaces is meaningless. If you swap models, re-run embed_inventory.py
against the full catalog before serving queries.
"""
import threading
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import torch
from PIL import Image

from app.config import settings

_MIN_WEIGHT_BYTES = 100_000_000  # real weights are ~600MB; reject partial/incomplete blobs


def _repo_id_from_setting(name: str) -> str:
    """Strip the `hf-hub:` prefix if the user included it in config.
    open_clip accepts both `hf-hub:Marqo/marqo-fashionCLIP` and just
    `Marqo/marqo-fashionCLIP` when passed via `hf-hub:`; this normalizes."""
    return name.removeprefix("hf-hub:")


def _is_fully_cached(repo_id: str) -> bool:
    """Filesystem-only check (zero network calls) for whether repo_id's
    weights are fully in the local HF cache. Lets callers fall back to a
    non-ML search instead of blocking on a slow/stalled download."""
    cache_root = Path.home() / ".cache" / "huggingface" / "hub"
    repo_dir = cache_root / ("models--" + repo_id.replace("/", "--"))
    snapshots_dir = repo_dir / "snapshots"
    if not snapshots_dir.exists():
        return False
    for snapshot in snapshots_dir.iterdir():
        weight_files = (
            list(snapshot.glob("*.safetensors"))
            + list(snapshot.glob("pytorch_model.bin"))
            + list(snapshot.glob("open_clip_pytorch_model.bin"))
        )
        if not weight_files:
            continue
        for w in weight_files:
            resolved = w.resolve() if w.is_symlink() else w
            if resolved.exists() and resolved.stat().st_size > _MIN_WEIGHT_BYTES:
                return True
    return False


_LOAD_LOCK = threading.Lock()
_ENCODE_LOCK = threading.Lock()


def _load():
    """Load Marqo-FashionCLIP via open_clip once, cache the tuple. Model runs
    on CPU by default -- CUDA switch is a torch.cuda.is_available() one-liner
    if a GPU is ever available.

    Serialised with a lock: @lru_cache alone is NOT thread-safe for a slow
    first call -- the grouped-look builders fan out 8 worker threads, and
    eight of them racing into open_clip's model construction at once
    segfaulted the process (reproduced 2026-09-19). With the lock, the
    first thread loads and the rest wait for the cached result."""
    with _LOAD_LOCK:
        return _load_uncached()


@lru_cache
def _load_uncached():
    import open_clip  # heavy import; keep inside the loader so import-time is free

    repo_id = _repo_id_from_setting(settings.fashion_clip_model)
    if not _is_fully_cached(repo_id):
        raise RuntimeError(
            f"Fashion-CLIP weights for '{repo_id}' not fully downloaded yet"
        )
    hub_name = f"hf-hub:{repo_id}"
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(hub_name)
    tokenizer = open_clip.get_tokenizer(hub_name)
    model = model.to(device).eval()
    return model, preprocess, tokenizer, device


def embed_image_bytes(image_bytes: bytes) -> list[float]:
    model, preprocess, _, device = _load()
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    tensor = preprocess(image).unsqueeze(0).to(device)
    with _ENCODE_LOCK, torch.no_grad():
        features = model.encode_image(tensor)
        features = features / features.norm(dim=-1, keepdim=True)
    return features[0].cpu().tolist()


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def embed_texts(texts: list[str]) -> list[list[float]]:
    model, _, tokenizer, device = _load()
    tokens = tokenizer(texts).to(device)
    with _ENCODE_LOCK, torch.no_grad():
        features = model.encode_text(tokens)
        features = features / features.norm(dim=-1, keepdim=True)
    return [f.tolist() for f in features.cpu()]
