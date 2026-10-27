"""Rules for what may be in this repo: no banned wording, no personal paths or keys, no copy of an engine file, and no import of
anything the public engine does not ship."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The organisers' banned-topic wording, kept as data so a scan can look for it (this file is the only place it may appear).
BANNED = ("coach", "analyz", "analys", "sports", "football", "soccer", "basketball", "war game", "warfare", "military",
          "dashboard", "streamlit")  # the last two: banned project types (kickoff slides); bench results are README tables
# folders that are not our code: a virtual environment, a build, installed packages, a scratch result
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "results", ".venv", "venv", "build", "node_modules"}
# test files that hold the banned words AS DATA, in order to scan for them (they are the scanners, not the offenders)
RULE_FILES = {"test_repo_rules.py", "test_web_arena_parity.py"}
ENGINE_MODULES = {"play.py", "settings.py", "safety.py", "hands.py", "eyes.py", "reply.py", "grounding.py", "controls.py"}


def _walk(pattern: str = "*"):
    """Every path under the repo that is our own: no virtual environment, build output, installed package metadata or caches."""
    for path in ROOT.rglob(pattern):
        parts = path.relative_to(ROOT).parts
        if set(parts) & SKIP_DIRS or any(part.endswith(".egg-info") for part in parts):
            continue
        yield path


def _files():
    for path in ROOT.rglob("*"):
        parts = set(path.relative_to(ROOT).parts)
        if path.is_file() and not parts & SKIP_DIRS and not any(p.endswith(".egg-info") for p in parts) and path.suffix in (".py", ".md", ".toml", ".txt", ".yaml", ".yml", ".mjs", ".html", ".json", ".rs", ".ps1", ".sql", ".css", ".js"):
            yield path


def test_no_banned_wording_anywhere_but_this_file():
    hits = []
    for path in _files():
        if path.name in RULE_FILES:
            continue
        text = path.read_text(encoding="utf-8").lower()
        hits += [f"{path.relative_to(ROOT)}: {word}" for word in BANNED if word in text]
    assert hits == []


def test_no_web_dashboard_framework_is_imported_anywhere():
    banned = {"streamlit", "gradio", "dash", "panel", "flask", "fastapi"}
    bad = []
    for path in _walk("*.py"):
        if path.name == "test_repo_rules.py":
            continue
        text = path.read_text(encoding="utf-8")
        try:
            names = []
            for node in ast.walk(ast.parse(text)):
                names += [a.name for a in node.names] if isinstance(node, ast.Import) else                     [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else []
        except SyntaxError:  # a file that does not even parse is somebody else's failure; still look for the imports in its text
            names = re.findall(r"^\s*(?:import|from)\s+([A-Za-z_][\w]*)", text, flags=re.MULTILINE)
        bad += [f"{path.relative_to(ROOT)}: {n}" for n in names if n.split(".")[0] in banned]
    assert bad == []


def test_the_old_repo_name_is_nowhere_in_the_repo():
    """The project was renamed (Meta's API terms bar another party's name inside ours). The old names are built from pieces here
    so this file does not contain them either. Every text file, tracked or not, is scanned; a folder name counts too."""
    old = ("meta" + "-playfellow", "meta" + "_playfellow")
    hits = []
    for path in _walk("*"):
        relative = str(path.relative_to(ROOT)).lower()
        hits += [f"{relative}: in the name" for word in old if word in relative]
        if path.is_file() and path.suffix in (".py", ".md", ".toml", ".txt", ".yaml", ".yml", ".json", ".cfg", ".ini"):
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            hits += [f"{relative}: {word}" for word in old if word in text]
    assert hits == []


def test_every_package_folder_is_listed_for_install():
    """A package folder missing from pyproject.toml is dropped from a normal (non-editable) install: the overlay once was."""
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["name"] == "playfellow-coop"
    found = set()
    for top in ("playfellow_coop", "train"):
        for init in (ROOT / top).rglob("__init__.py"):
            if "__pycache__" not in init.parts:
                found.add(".".join(init.parent.relative_to(ROOT).parts))
    assert found == set(config["tool"]["setuptools"]["packages"])
    assert "pynput" in " ".join(config["project"]["dependencies"])  # imported by the push-to-talk key listener


def test_no_judge_pass_link_or_code_is_in_any_file():
    """The judge pass goes ONLY in the submission form's private notes. The patterns are built from pieces so this file is not a hit."""
    patterns = [re.compile("pa" + r"ss\s*=\s*[A-Za-z0-9_\-]{6,}", re.I),
                re.compile(r"judge[ _-]?(?:pa" + r"ss|code|link|token)\s*[:=]\s*\S{6,}", re.I),
                re.compile(r"[?&](?:judge|jp|token|access)=[A-Za-z0-9_\-]{8,}", re.I)]
    hits = []
    for path in _walk("*"):
        if path.is_file() and path.name != "test_repo_rules.py" and path.suffix in (".py", ".md", ".toml", ".txt", ".yaml", ".yml", ".json", ".html", ".js"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            hits += [f"{path.relative_to(ROOT)}: {p.pattern[:20]}" for p in patterns if p.search(text)]
    assert hits == []


def test_the_readme_points_judges_to_the_submission_note_and_names_no_code():
    text = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "judges" not in text or "access note in the submission" in text


def test_nothing_routes_traffic_to_a_partner_gpu_service():
    """Partner credits are for the owner's own recorded runs, the bench and partner verification only: no code here may send
    public or judge traffic to Baseten or Modal. Mentioning the names in a doc is fine; importing or calling them is not."""
    code = [p for p in _walk("*.py") if p.name != "test_repo_rules.py"]
    hits = []
    for path in code:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        hits += [f"{path.relative_to(ROOT)}: {word}" for word in ("baseten", "import modal", "from modal", "modal.com") if word in text]
    assert hits == []


def test_no_personal_path_or_key_shape():
    pattern = re.compile(r"[A-Za-z]:[\\/]+(Users|PlayFellow)\b|AIza[0-9A-Za-z_\-]{30,}|\bsk-[A-Za-z0-9_\-]{20,}|pdl_(live|sdbx)_", re.I)
    hits = [str(p.relative_to(ROOT)) for p in _files() if p.name != "test_repo_rules.py" and pattern.search(p.read_text(encoding="utf-8"))]
    assert hits == []


def test_no_engine_file_is_copied_here():
    names = {p.name for p in _walk("*.py")}
    assert not names & ENGINE_MODULES


def test_the_package_imports_only_public_engine_names():
    private = {"loop", "captain", "coach", "builder", "diary", "licence", "auth", "mind"}  # private-engine modules (names only)
    bad = []
    for path in (ROOT / "playfellow_coop").rglob("*.py"):
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
        tree = ast.parse((ROOT / "playfellow_coop" / name).read_text(encoding="utf-8"))
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

def test_the_readme_and_the_video_script_open_with_the_two_tag_disclosure():
    """The organisers asked for one line, first: what was pre-existing and what was built. Both tags and their commits are named."""
    for name in ("README.md", "docs/video-script.md"):
        top = " ".join((ROOT / name).read_text(encoding="utf-8").splitlines()[:6])
        assert "before-kickoff" in top and "b7b72a8" in top and "pre-hackathon" in top and "d63c1b4" in top, name
        assert "no new features" not in top.lower(), name

def test_every_commit_is_by_the_noreply_identity():
    """A repo-local git setting once held the literal text "user.name" as the e-mail: every author and committer must be the noreply address."""
    import subprocess

    out = subprocess.run(["git", "log", "--format=%ae|%ce"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:  # not a git checkout (an exported tarball): nothing to check
        return
    for line in out.stdout.split():
        for address in line.split("|"):
            assert address.endswith("@users.noreply.github.com"), address


def test_no_commit_message_names_an_ai_assistant_or_carries_its_trailer():
    """Owner, 2026-10-27: the public history uses only our own neutral role names (architect, supervisor, builder 1, builder 2)."""
    import subprocess

    out = subprocess.run(["git", "log", "--format=%B%x00"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60)
    if out.returncode != 0:  # not a git checkout (an exported tarball): nothing to check
        return
    banned = re.compile(r"claude|anthropic|sonnet|\bopus\b|chatgpt|copilot|antigravity|\bgemini\b|co-authored-by|claude-session", re.I)
    for message in out.stdout.split("\x00"):
        assert not banned.search(message), message.strip().splitlines()[0] if message.strip() else message
