"""The plugin imports the PlayFellow engine as an installed package. While developing, point PLAYFELLOW_ENGINE at a checkout's
software folder (default: the engine checkout beside this repo); tests never press keys, grab the screen or call the network."""
import os
import sys
from pathlib import Path

ENGINE = Path(os.environ.get("PLAYFELLOW_ENGINE") or Path(__file__).resolve().parents[2] / "playfellow" / "software")
if ENGINE.is_dir() and str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))
os.environ["PLAYFELLOW_ENGINE"] = str(ENGINE)  # tests read the engine folder from here (the engine has its own "tests" package)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_circuit_breaker():
    """The circuit breaker is process-wide state (one circuit per host). This fixture imports nothing: after each test, if the HTTP module
    was loaded at all, every circuit is closed again, so one test's failures never open a circuit for the next."""
    yield
    module = sys.modules.get("playfellow_coop._http")
    if module is not None:
        module.BREAKER.reset()
