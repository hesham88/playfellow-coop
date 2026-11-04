"""The one-line installers and launchers: they fetch only this repository and the engine at its pinned tag, change no machine-wide
policy, never touch a key, and the launchers need no activated virtual environment. Static checks: nothing is run or downloaded."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = "https://raw.githubusercontent.com/hesham88/playfellow-coop/main/"


def text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_the_one_liners_point_at_this_repository():
    assert f"irm {RAW}install.ps1 | iex" in text("install.ps1")
    assert f"curl -fsSL {RAW}install.sh | sh" in text("install.sh")
    for name in ("install.ps1", "install.sh"):
        urls = set(re.findall(r"https://[^\s\"'`]+", text(name)))
        assert urls <= {RAW + "install.ps1", RAW + "install.sh", "https://github.com/hesham88/playfellow-coop.git"}, urls


def test_the_engine_comes_only_at_its_pinned_tag():
    for name in ("bootstrap.ps1", "bootstrap.sh"):
        body = text(name)
        assert "--branch pre-hackathon https://github.com/hesham88/playfellow.git" in body


def test_no_installer_changes_machine_policy_or_touches_a_key():
    for name in ("install.ps1", "install.sh", "bootstrap.ps1", "bootstrap.sh", "playfellow.cmd", "playfellow"):
        body = text(name).lower()
        assert "set-executionpolicy" not in body and "model_api_key" not in body and "keyring" not in body, name
    assert "-ExecutionPolicy Bypass -File" in text("install.ps1")  # a process-only bypass for the bootstrap


def test_the_launchers_use_the_folders_own_environment():
    assert r'"%~dp0.venv\Scripts\python.exe" -m playfellow_coop %*' in text("playfellow.cmd")
    assert '"$here/.venv/bin/python" -m playfellow_coop "$@"' in text("playfellow")


def test_the_readme_shows_both_one_liners():
    readme = text("README.md")
    assert f"irm {RAW}install.ps1 | iex" in readme and f"curl -fsSL {RAW}install.sh | sh" in readme
