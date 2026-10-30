"""AD1: ADK has its own environment, pinned, outside the repository, never the app's. These checks need no ADK."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("adk_env", ROOT / "tools" / "adk_env.py")
adk_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adk_env)


def test_adk_is_pinned_to_one_exact_version_and_the_lock_agrees():
    pins = adk_env.pinned()
    assert pins["google-adk"] == "2.13.0"
    assert "pytest" not in pins  # a range is not a pin
    lock = adk_env.pinned(adk_env.LOCK)
    assert lock["google-adk"] == pins["google-adk"] and len(lock) > 20  # the full resolved set, not just the top line


def test_the_environment_must_not_be_the_running_one_or_inside_the_repository(tmp_path):
    assert "running this script" in adk_env.refusal(Path(sys.prefix))
    assert "outside this repository" in adk_env.refusal(ROOT / ".adk-venv")
    assert "outside this repository" in adk_env.refusal(ROOT)
    assert adk_env.refusal(tmp_path / "adk-venv", root=ROOT, running_prefix=sys.prefix) == ""


def test_a_folder_without_an_environment_is_reported_not_crashed(tmp_path):
    assert adk_env.check(tmp_path / "nothing-here") == [f"no python at {adk_env.python_of(tmp_path / 'nothing-here')}"]
    assert adk_env.install(Path(sys.prefix)) == 2  # refused before anything is installed
