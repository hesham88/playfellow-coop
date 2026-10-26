"""Rules for what may be in this repo: no banned wording, no personal paths or keys, no copy of an engine file, and no import of
anything the public engine does not ship."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The organisers' banned-topic wording, kept as data so a scan can look for it (this file is the only place it may appear).
BANNED = ("coach", "analyz", "analys", "sports", "football", "soccer", "basketball", "war game", "warfare", "military")
ENGINE_MODULES = {"play.py", "settings.py", "safety.py", "hands.py", "eyes.py", "reply.py", "grounding.py", "controls.py"}


def _files():
    for path in ROOT.rglob("*"):
        parts = set(path.relative_to(ROOT).parts)
        if path.is_file() and not parts & {".git", "__pycache__", ".pytest_cache", "results"} and path.suffix in (".py", ".md", ".toml", ".txt", ".yaml"):
            yield path


def test_no_banned_wording_anywhere_but_this_file():
    hits = []
    for path in _files():
        if path.name == "test_repo_rules.py":
            continue
        text = path.read_text(encoding="utf-8").lower()
        hits += [f"{path.relative_to(ROOT)}: {word}" for word in BANNED if word in text]
    assert hits == []


def test_no_personal_path_or_key_shape():
    pattern = re.compile(r"[A-Za-z]:[\\/]+(Users|PlayFellow)\b|AIza[0-9A-Za-z_\-]{30,}|\bsk-[A-Za-z0-9_\-]{20,}|pdl_(live|sdbx)_", re.I)
    hits = [str(p.relative_to(ROOT)) for p in _files() if p.name != "test_repo_rules.py" and pattern.search(p.read_text(encoding="utf-8"))]
    assert hits == []


def test_no_engine_file_is_copied_here():
    names = {p.name for p in ROOT.rglob("*.py") if ".git" not in p.parts}
    assert not names & ENGINE_MODULES


def test_the_package_imports_only_public_engine_names():
    private = {"loop", "captain", "coach", "builder", "diary", "licence", "auth", "mind"}  # private-engine modules (names only)
    bad = []
    for path in (ROOT / "meta_playfellow").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else []
            bad += [f"{path.name}: {n}" for n in names if n.split(".")[0] in private]
    assert bad == []


def test_the_licence_is_the_engines_text_word_for_word():
    here = (ROOT / "LICENSE").read_bytes()
    assert here and b"OpenRAIL-S" in here
    engine = ROOT.parent / "playfellow" / "LICENSE"
    if engine.is_file():
        assert here == engine.read_bytes()
    assert "LICENSE" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_key_is_named_model_api_key_and_the_key_code_reads_no_file():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "MODEL_API_KEY" in readme
    for name in ("muse_brain.py", "__main__.py"):
        tree = ast.parse((ROOT / "meta_playfellow" / name).read_text(encoding="utf-8"))
        functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and ("key" in n.name.lower() or n.name == "__init__")]
        for function in functions:
            for call in (n for n in ast.walk(function) if isinstance(n, ast.Call)):
                called = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
                assert called not in {"open", "read_text", "read_bytes"}, f"{name}:{function.name} reads a file"


def test_the_bench_script_is_valid_python():
    ast.parse((ROOT / "bench" / "speed_bench.py").read_text(encoding="utf-8"))


def test_the_readme_opens_with_the_disclosure():
    first = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[:4]
    text = " ".join(first)
    assert "Built on the PlayFellow engine" in text and "pre-hackathon" in text and "Everything in this repo was built during the event" in text
