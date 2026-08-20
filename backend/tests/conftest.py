import sys
from pathlib import Path

# Makes `from app...` importable regardless of the directory pytest is
# invoked from -- this backend has no package/setup.py, so nothing else
# puts backend/ on sys.path automatically.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
