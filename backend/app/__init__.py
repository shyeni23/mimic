import os, types, sys, socket
import importlib.machinery

# Fail fast instead of hanging forever on a stalled connection (this dev
# machine's network occasionally stalls mid-download for HF/GitHub model
# weights). Individual downloads still resume/retry at the caller level;
# this only bounds how long a single stalled socket read can block.
socket.setdefaulttimeout(20)

# ctranslate2 (used by faster-whisper) and numpy/torch both statically link
# their own OpenMP runtime on Windows, which crashes on load with
# "OMP: Error #15: Initializing libiomp5md.dll, but found libiomp5md.dll
# already initialized." Safe to allow duplicates here since we don't run
# competing OpenMP workloads concurrently on the same data.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# DeepFace (gender detection, Module 1) needs legacy Keras (tf_keras) under
# TensorFlow >= 2.16 and sets this itself on import -- but TensorFlow only
# reads it the FIRST time `tensorflow` is imported, and in the scan pipeline
# MediaPipe/face_shape_ml import TensorFlow before DeepFace ever loads. The
# result was DeepFace building its model on Keras 3 and failing every call
# with "The layer sequential has never been called and thus has no defined
# input", so every scan silently returned gender='unknown' and the whole
# men's/women's recommendation filter never activated. Must be set here,
# before any app module can import TensorFlow.
os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

if "annoy" not in sys.modules:
    _m = types.ModuleType("annoy")
    _m.__spec__ = importlib.machinery.ModuleSpec("annoy", None)
    _m.AnnoyIndex = type("AnnoyIndex", (), {"__init__": lambda *a, **k: None})
    sys.modules["annoy"] = _m

if "datasets" not in sys.modules:
    _m = types.ModuleType("datasets")
    _m.__spec__ = importlib.machinery.ModuleSpec("datasets", None)
    _m.__version__ = "2.10.0"
    _m.Dataset = type("Dataset", (), {})
    _m.Image = type("Image", (), {})
    sys.modules["datasets"] = _m
