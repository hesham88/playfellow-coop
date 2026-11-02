"""The sandbox proof for the judges ($0, no key): planted hostile skills through the real 3-layer path on this PC.

  python -m bench.sandbox_proof --out results/skillsmith/sandbox-proof-<date>.json

Each hostile row names which layer stopped it: the static gate (the code is refused before anything runs), the worker
namespace (the separate worker's proxied modules, scrubbed environment and per-step time limit), or the OS job object
(low integrity plus the Windows job that caps memory and forbids child processes). Three harmless skills must pass.
Any hostile row that gets through fails the run and is printed as NOT STOPPED: that row goes to the architect at once.
Read-only on `skillsmith/**`: a hole found here is reported, never patched from this file.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCHEMA = "pf-sandbox-proof/1"
LAYERS = ("static gate", "worker namespace", "OS job object")
OBS = {"self": [0.5, 0.5], "items": [[0.9, 0.5, 0, 0]], "enemies": [], "hud": {}, "t": 0, "danger": 0.0, "escape": None}

_HEAD = "class GeneratedArenaSkill:\n    def compute_action(self, obs):\n"
HOSTILE: dict[str, str] = {
    "open a socket": "import socket\n" + _HEAD + "        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n",
    "write a file outside the folder": _HEAD + "        open('outside.txt', 'w')\n        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n",
    "start a child process": "import subprocess\n" + _HEAD + "        subprocess.run(['python', '-c', '1'])\n        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n",
    "import os": "import os\n" + _HEAD + "        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n",
    "import subprocess": "import subprocess\n" + _HEAD + "        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n",
    "import ctypes": "import ctypes\n" + _HEAD + "        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n",
    "read an environment variable": "import math\n" + _HEAD + "        return {'move': [float(math.environ), 0.0], 'buttons': [], 'hold_ms': 0}\n",
    "loop forever": _HEAD + "        total = 0\n        for i in range(100000000):\n            total += i\n        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n",
    "allocate past the memory cap": "BIG = [0.0] * 300000000\n" + _HEAD + "        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n",
    "call eval": _HEAD + "        return eval('1')\n",
    "call exec": _HEAD + "        exec('x = 1')\n        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n",
    "walk frames to escape": _HEAD + "        g = (1 for _ in range(1))\n        h = g.gi_frame.f_back.f_globals\n        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n",
}
HARMLESS: dict[str, str] = {
    "chase the nearest item": "import math\n\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        items = obs.get('items') or []\n        if items:\n            sx, sy = obs['self']\n            dx, dy = items[0][0] - sx, items[0][1] - sy\n            n = math.hypot(dx, dy) or 1.0\n            return {'move': [dx / n, dy / n], 'buttons': [], 'hold_ms': 0}\n        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n",
    "stay still": _HEAD + "        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n",
    "use numpy to steer": "import numpy as np\n\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        items = obs.get('items') or []\n        if items:\n            move = np.clip(np.array([items[0][0] - obs['self'][0], items[0][1] - obs['self'][1]]), -1, 1)\n            return {'move': [float(move[0]), float(move[1])], 'buttons': [], 'hold_ms': 0}\n        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n",
}


def probe_hostile(code: str, step_timeout_ms: float = 1500.0) -> dict:
    """One hostile skill through the three layers in order. Stopped, and by which layer, is measured, never assumed."""
    from playfellow_coop.skillsmith import ast_gate
    from playfellow_coop.skillsmith.sandbox import SandboxedSkill

    started = time.perf_counter()
    ok, why = ast_gate.check(code)
    if not ok:
        return {"stopped": True, "layer": "static gate", "detail": why, "ms": round((time.perf_counter() - started) * 1000.0, 1)}
    with SandboxedSkill(code, step_timeout_ms=step_timeout_ms) as skill:
        containment = skill.containment
        faulted_at_start = skill.faulted
        if not faulted_at_start:
            skill.step(dict(OBS))
        ms = round((time.perf_counter() - started) * 1000.0, 1)
        if not skill.faulted:
            return {"stopped": False, "layer": None, "detail": "the skill ran and answered: nothing stopped it", "ms": ms}
        if faulted_at_start:
            layer = "OS job object" if "job" in containment else "worker namespace"
            return {"stopped": True, "layer": layer, "detail": f"the worker died or was refused at start ({skill.fault}); containment {containment}", "ms": ms}
        return {"stopped": True, "layer": "worker namespace", "detail": skill.fault, "ms": ms}


_OS_RUNNER = (
    "import json, sys\n"
    "for line in sys.stdin:\n"
    "    try:\n"
    "        message = json.loads(line)\n"
    "        scope = {'__name__': 'skill'}\n"
    "        exec(compile(message['code'], '<skill>', 'exec'), scope)\n"
    "        instance = scope[message.get('class', 'GeneratedArenaSkill')]()\n"
    "        reply = {'result': instance.compute_action(message['obs'])}\n"
    "    except BaseException as error:\n"
    "        reply = {'error': type(error).__name__ + ': ' + str(error)[:200]}\n"
    "    sys.stdout.write(json.dumps(reply) + '\\n')\n"
    "    sys.stdout.flush()\n"
)


def probe_gate_off(code: str, step_timeout_ms: float = 1000.0) -> dict:
    """Proof only: the same hostile skill with the static gate bypassed, so the worker namespace and the OS job object must stop it alone.

    The bypass is a temporary patch inside this proof process. No product module imports this file, so the product path cannot reach it
    (a test checks exactly that)."""
    from playfellow_coop.skillsmith import ast_gate
    from playfellow_coop.skillsmith.sandbox import SandboxedSkill

    started = time.perf_counter()
    original = ast_gate.check
    ast_gate.check = lambda *args, **kwargs: (True, "ok (proof only: static gate off)")  # noqa: E731
    try:
        with SandboxedSkill(code, step_timeout_ms=step_timeout_ms) as skill:
            containment = skill.containment
            faulted_at_start = skill.faulted
            if not faulted_at_start:
                skill.step(dict(OBS))
            ms = round((time.perf_counter() - started) * 1000.0, 1)
            if not skill.faulted:
                return {"stopped": False, "layer": None, "detail": "the skill ran and answered with the gate off: the deeper layers did not refuse it", "ms": ms}
            if faulted_at_start:
                layer = "OS job object" if ("MemoryError" in skill.fault or "quota" in skill.fault.lower()) else "worker namespace"
                return {"stopped": True, "layer": layer, "detail": f"the worker died or was refused at start ({skill.fault}); containment {containment}", "ms": ms}
            return {"stopped": True, "layer": "worker namespace", "detail": skill.fault, "ms": ms}
    finally:
        ast_gate.check = original


def probe_os_only(code: str, timeout_s: float = 2.5) -> dict:
    """Proof only: the same hostile skill with the gate and the worker namespace both off (full builtins, full imports, full environment), so only the OS job object (low integrity, memory and single-process limits) can stop it.

    A valid action back, a file created, a non-action return, or a skill that only the proof watchdog could time out all count as not stopped
    by the OS limits alone: the table must not credit the OS layer with the gate's or the worker's refusals."""
    import os
    import queue
    import shutil
    import subprocess
    import tempfile
    import threading

    from playfellow_coop.skillsmith import osjail
    from playfellow_coop.skillsmith.sandbox import clean_action, worker_python

    started = time.perf_counter()
    folder = tempfile.mkdtemp(prefix="pf-proof-os-")
    proc = None
    try:
        runner = Path(folder) / "runner.py"
        runner.write_text(_OS_RUNNER, encoding="utf-8")
        proc = subprocess.Popen([worker_python(), "-I", str(runner)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, bufsize=1, env=dict(os.environ), cwd=folder)
        containment = osjail.contain(proc)
        lines: queue.Queue = queue.Queue()

        def _pump():
            try:
                for line in proc.stdout:  # type: ignore[union-attr]
                    lines.put(line)
            except (OSError, ValueError):
                pass
            lines.put("")

        threading.Thread(target=_pump, daemon=True).start()
        try:
            proc.stdin.write(json.dumps({"code": code, "class": "GeneratedArenaSkill", "obs": dict(OBS)}) + "\n")  # type: ignore[union-attr]
            proc.stdin.flush()  # type: ignore[union-attr]
        except (OSError, ValueError):
            pass
        try:
            line = lines.get(timeout=timeout_s)
            timed_out = False
        except queue.Empty:
            line, timed_out = "", True
        ms = round((time.perf_counter() - started) * 1000.0, 1)
        file_created = (Path(folder) / "outside.txt").exists()
        if file_created:
            return {"stopped": False, "layer": None, "detail": f"the skill wrote outside.txt with only the OS limits on (containment {containment})", "ms": ms, "containment": containment}
        if timed_out:
            return {"stopped": False, "layer": None, "detail": f"still running after {timeout_s:.1f} s: the OS limits alone did not stop it (the proof watchdog ended it; containment {containment})", "ms": ms, "containment": containment}
        if not line:
            return {"stopped": True, "layer": "OS job object", "detail": f"the worker died with no answer (containment {containment})", "ms": ms, "containment": containment}
        try:
            reply = json.loads(line)
        except ValueError:
            return {"stopped": True, "layer": "OS job object", "detail": f"the worker answered nonsense and was ended (containment {containment})", "ms": ms, "containment": containment}
        if "error" in reply:
            os_caused = reply["error"].startswith(("PermissionError", "MemoryError")) or "quota" in reply["error"].lower() or "permission" in reply["error"].lower()
            if os_caused:
                return {"stopped": True, "layer": "OS job object", "detail": f"{reply['error']} (containment {containment})", "ms": ms, "containment": containment}
            return {"stopped": False, "layer": None, "detail": f"the skill failed on its own ({reply['error']}); no OS limit acted (containment {containment})", "ms": ms, "containment": containment}
        if clean_action(reply.get("result")) is not None:
            return {"stopped": False, "layer": None, "detail": f"the skill ran and answered with only the OS limits on (containment {containment})", "ms": ms, "containment": containment}
        return {"stopped": False, "layer": None, "detail": f"the skill returned a non-action with only the OS limits on; no OS limit acted (containment {containment})", "ms": ms, "containment": containment}
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001 (cleanup only)
                    pass
            for stream in (proc.stdin, proc.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass
        shutil.rmtree(folder, ignore_errors=True)


def probe_harmless(code: str) -> dict:
    from playfellow_coop.skillsmith import ast_gate
    from playfellow_coop.skillsmith.sandbox import SandboxedSkill

    started = time.perf_counter()
    ok, why = ast_gate.check(code)
    if not ok:
        return {"passed": False, "detail": f"refused by the static gate: {why}", "ms": round((time.perf_counter() - started) * 1000.0, 1)}
    with SandboxedSkill(code, step_timeout_ms=2000.0) as skill:
        action = skill.step(dict(OBS))
        ms = round((time.perf_counter() - started) * 1000.0, 1)
        return {"passed": not skill.faulted and action is not None, "detail": skill.fault or "answered inside the sandbox",
                "containment": skill.containment, "ms": ms}


def run_proof() -> dict:
    rows = [{"name": name, **probe_hostile(code)} for name, code in HOSTILE.items()]
    harmless = [{"name": name, **probe_harmless(code)} for name, code in HARMLESS.items()]
    full = {row["name"]: row for row in rows}
    defence = [{"name": name, "full": {"stopped": full[name]["stopped"], "layer": full[name]["layer"]},
                "gate_off": probe_gate_off(code), "os_only": probe_os_only(code)} for name, code in HOSTILE.items()]
    return {"schema": SCHEMA, "written": datetime.now().astimezone().isoformat(timespec="seconds"),
            "platform": sys.platform, "layers": list(LAYERS), "rows": rows, "harmless": harmless,
            "defence_in_depth": defence,
            "all_stopped": all(row["stopped"] for row in rows) and all(row["passed"] for row in harmless)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    out = args.out if args.out is not None else ROOT / "results" / "skillsmith" / f"sandbox-proof-{datetime.now().strftime('%Y%m%d')}.json"
    document = run_proof()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=1), encoding="utf-8", newline="\n")
    for row in document["rows"]:
        state = f"stopped by {row['layer']}" if row["stopped"] else "NOT STOPPED: report this row at once"
        print(f"{row['name']:34} {state:44} {row['ms']:.0f} ms  {row['detail'][:90]}")
    for row in document["harmless"]:
        print(f"{row['name']:34} {'passed' if row['passed'] else 'FAILED (harmless)':44} {row['ms']:.0f} ms  {row['detail'][:90]}")
    print("defence in depth (proof only: each deeper layer alone):")
    for row in document["defence_in_depth"]:
        gate_off = "stopped" if row["gate_off"]["stopped"] else "NOT stopped"
        os_only = "stopped" if row["os_only"]["stopped"] else "NOT stopped"
        print(f"{row['name']:34} gate off: {gate_off:12} OS only: {os_only:12} ({row['os_only']['detail'][:70]})")
    print(f"wrote {out}")
    return 0 if document["all_stopped"] else 1


if __name__ == "__main__":
    sys.exit(main())
