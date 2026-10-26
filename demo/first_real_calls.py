"""Credit day: three tiny capped calls that save the real answers as fixtures. `python demo/first_real_calls.py`

Needs MODEL_API_KEY in the environment, asks for a typed YES before it spends anything, and caps the total at $10. It does not
run in the tests: they use fake servers (tests/test_smoke.py)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:  # the engine is normally pip-installed; without that, use PLAYFELLOW_ENGINE or the clone beside this repo
    import practice_arena  # noqa: F401
except ImportError:
    import os

    sys.path.insert(0, str(Path(os.environ.get("PLAYFELLOW_ENGINE") or Path(__file__).resolve().parents[2] / "playfellow" / "software")))

from playfellow_coop.smoke import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run())
