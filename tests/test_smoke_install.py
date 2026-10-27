"""Smoke test: clone the engine at the pre-hackathon tag, install it and this package editable, and in a FRESH Python run one turn
through the engine's own building blocks with the Muse brain pointed at a fake server on 127.0.0.1. No key, no screen, no real API."""
from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE_REPO = ROOT.parent / "playfellow"  # the engine checkout beside this repo (cloned locally: no network)

PROBE = '''
import json, site, sys
before = list(sys.path)
for folder in sys.argv[1:3]:
    site.addsitedir(folder)
# addsitedir appends; put the fresh install FIRST so an engine already installed editable in this environment (the README's own
# route) cannot shadow the tagged clone this test just made
sys.path[:] = [p for p in sys.path if p not in before] + before
from pathlib import Path
from PIL import Image
import play, controls, settings
from eyes import WindowBox
from memory import Memory
from reply import parse_reply
from safety import Safety
from playfellow_coop import muse_brain
from playfellow_coop.budget import DailyBudget
from playfellow_coop.muse_brain import MuseBrain

muse_brain.ENDPOINTS["muse"] = sys.argv[3]
root = Path(play.SOFTWARE)
card = controls.load_card(root / "controls" / "practice_arena.yaml")
loaded = settings.load_settings(root / "settings.yaml")
move = sorted(card.actions)[0]

class Screen:
    def find(self, title): return WindowBox(0, 0, 320, 240)
    def in_front(self, title): return True
    def grab(self, box): return Image.new("RGB", (box.width, box.height), (30, 60, 90))

class Hands:
    def __init__(self): self.done = []
    def do(self, step, box): self.done.append(step.action)

screen, hands, memory = Screen(), Hands(), Memory(2)
safety = Safety(5, 5)
safety.start()
brain = MuseBrain("muse-spark", "smoke-test-key", budget=DailyBudget(Path(sys.argv[4]) / "budget.json", cap_usd=1, max_calls=5))
box = screen.find(loaded.game_window)
image = play.shrink(screen.grab(box), loaded.image_width)
safety.count_ai_call()
raw = brain.ask(play.system_for(play.Parts(brain, card, screen, hands, safety, memory), loaded),
                play.turn_text(loaded.goal, memory.as_text(), [], None), [image])
reply = parse_reply(raw, card, loaded.max_actions_per_step)
for step in reply.steps:
    hands.do(step, box)
brain.close()
print(json.dumps({"engine": play.__file__, "plugin": muse_brain.__file__, "move": move, "pressed": hands.done}))
'''


class _Fake(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.paths.append(self.path)
        move = self.server.move
        data = json.dumps({"choices": [{"message": {"content": json.dumps({"thought": "go", "say": "", "actions": [move]})}}],
                           "usage": {"prompt_tokens": 50, "completion_tokens": 10}}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.mark.skipif(not (ENGINE_REPO / "software" / "play.py").is_file(), reason="the engine checkout is not beside this repo")
def test_the_engine_at_the_tag_and_this_package_install_and_take_one_turn_with_the_muse_brain(tmp_path):
    tag = subprocess.run(["git", "-C", str(ENGINE_REPO), "rev-parse", "--verify", "refs/tags/pre-hackathon"],
                         capture_output=True, text=True)
    assert tag.returncode == 0, "the pre-hackathon tag is missing from the engine checkout"
    clone = tmp_path / "engine"
    cloned = subprocess.run(["git", "clone", "--quiet", "--branch", "pre-hackathon", str(ENGINE_REPO), str(clone)],
                            capture_output=True, text=True, timeout=300)
    assert cloned.returncode == 0, cloned.stderr[-600:]
    site_dir = tmp_path / "site"
    for target in (clone, ROOT):
        built = subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(target), "--no-deps", "--no-build-isolation",
                                "--no-cache-dir", "--disable-pip-version-check", "--target", str(site_dir)],
                               capture_output=True, text=True, timeout=600, cwd=tmp_path)
        assert built.returncode == 0, built.stdout[-600:] + built.stderr[-600:]
    # the first card action is the move the fake server will answer with
    card_move = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import controls; "
                                "print(sorted(controls.load_card(sys.argv[1] + '/controls/practice_arena.yaml').actions)[0])",
                                str(clone / "software")], capture_output=True, text=True, timeout=120, cwd=tmp_path)
    assert card_move.returncode == 0, card_move.stderr[-600:]
    move = card_move.stdout.strip()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    server.paths, server.move = [], move
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        done = subprocess.run([sys.executable, "-c", PROBE, str(site_dir), str(site_dir),
                               f"http://127.0.0.1:{server.server_address[1]}/v1", str(tmp_path)],
                              capture_output=True, text=True, timeout=300, cwd=elsewhere)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert done.returncode == 0, done.stderr[-1500:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert Path(result["engine"]).resolve().is_relative_to(clone.resolve())  # the engine is the tagged clone
    assert Path(result["plugin"]).resolve().is_relative_to(ROOT.resolve())  # the plugin is this repo
    assert server.paths == ["/v1/chat/completions"] and result["pressed"] == [move]
