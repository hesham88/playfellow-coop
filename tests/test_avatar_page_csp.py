"""The 3D companion's web page may read the local model file, so it must not be able to send anything out: a Content Security
Policy allows scripts only from the pinned three.js path and lets the page fetch local files only (no host to send data to)."""
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "playfellow_coop" / "overlay" / "avatar3d.html"


def policy() -> dict[str, str]:
    html = PAGE.read_text(encoding="utf-8")
    found = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', html)
    assert found, "the page has no Content Security Policy"
    return {part.split()[0]: part.strip() for part in found.group(1).split(";") if part.strip()}


def test_the_page_has_a_default_deny_policy():
    assert policy()["default-src"] == "default-src 'none'"


def test_scripts_come_only_from_the_pinned_three_js_path():
    script = policy()["script-src"]
    remote = [s for s in script.split()[1:] if s.startswith("http")]
    assert remote == ["https://cdn.jsdelivr.net/npm/three@0.169.0/"]


def test_the_page_cannot_send_data_to_any_host():
    rules = policy()
    for name in ("connect-src", "img-src", "form-action", "frame-src"):
        rule = rules.get(name, f"{name} 'none'")
        assert "http" not in rule and "*" not in rule, rule
    assert "connect-src" in rules  # the model file and the three.js modules are the only fetches


def test_the_policy_sits_before_any_script():
    html = PAGE.read_text(encoding="utf-8")
    assert html.index("Content-Security-Policy") < html.index("<script")
