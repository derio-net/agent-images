"""Put `scripts/` on sys.path so `tests/` can import the modules it guards.

The per-image suites in this repo only read Dockerfiles, so none of them needed
an importable module before. `version_audit` is real code, so its tests import it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
