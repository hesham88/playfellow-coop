"""Layer 2: run a verified skill in a separate process that cannot see our secrets, with a hard time limit per step and a safe fallback.

The generated code never runs in this process. It runs in `_worker.py` under `python -I` with an environment holding only what the interpreter needs to start (no API keys, no proxy, no
tokens), in an empty temporary folder, talking over pipes. Each step has a time limit; a worker that is late, dead or returns nonsense is killed and replaced by the fallback action
(neutral: press nothing) from then on, and the skill is marked faulted so the session can hand the turn back to the model. The pipe round trip has a floor of a few milliseconds; the limit
is a parameter (the research's 4 ms needs shared memory, which a later step can add behind the same interface).
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from playfellow_coop.skillsmith import ast_gate, osjail

WORKER = Path(__file__).with_name("_worker.py")
NEUTRAL: dict = {"move": [0.0, 0.0], "buttons": [], "hold_ms": 0}
START_TIMEOUT = 20.0  # numpy takes a moment to import the first time


def scrubbed_environment() -> dict[str, str]:
    """Only what Python needs to start. Windows needs SYSTEMROOT; nothing else from our environment (keys, proxies, tokens) is passed on."""
    env = {"PATH": ""}
    for name in ("SYSTEMROOT", "SYSTEMDRIVE"):
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def numpy_location() -> list[str]:
    """Where numpy lives for the worker. `python -I` ignores the user site-packages, so a numpy installed there is invisible; the folder is appended (never prepended) to the worker's path."""
    try:
        import importlib.util
        spec = importlib.util.find_spec("numpy")
        if spec and spec.submodule_search_locations:
            return [str(Path(next(iter(spec.submodule_search_locations))).parent)]
    except (ImportError, ValueError):
        pass
    return []


def worker_python() -> str:
    """The interpreter the worker runs on: a real python.exe, never a venv launcher. In a venv on Windows `sys.executable` is a launcher that starts the real interpreter as a child; the
    job allows one process, so that child is refused when the job lands first ("Not enough quota", exit 101) and runs outside the job when it does not. The base interpreter is used when
    it is a python*.exe file outside any venv, otherwise `sys.executable` as before. The worker runs with -I and is handed numpy's folder, so it needs nothing else from the venv."""
    base = Path(getattr(sys, "_base_executable", "") or "")
    name = base.name.lower()
    if name.startswith("python") and name.endswith(".exe") and base.is_file() and not any((folder / "pyvenv.cfg").is_file() for folder in (base.parent, base.parent.parent)):
        return str(base)
    return sys.executable


class SandboxedProgram:
    """Any model-written class run in the isolated worker: `call(method, *args)` returns the method's JSON-able result, or None when the program is late, dead or faulted. A skill is the
    special case `SandboxedSkill`; a world model (init_state, transition, render) is another."""

    def __init__(self, code: str, class_name: str = "GeneratedArenaSkill", methods: tuple[str, ...] = ("compute_action",), step_timeout_ms: float = 50.0, python: str | None = None, require_containment: bool = False):
        ok, why = ast_gate.check(code, class_name, methods)
        if not ok:
            raise ast_gate.SkillRejected(why)
        self.class_name = class_name
        self.code, self.step_timeout = code, step_timeout_ms / 1000.0
        self._python = python or worker_python()
        self.faulted = False
        self.fault = ""
        self.containment = "none"
        self.require_containment = require_containment
        self.steps = 0
        self.latencies_ms: list[float] = []
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._folder = tempfile.TemporaryDirectory(prefix="pf-skill-")
        self._start()

    # ---- process handling ----------------------------------------------------------------------------------------------------------
    def _start(self) -> None:
        env = scrubbed_environment()
        env["TEMP"] = env["TMP"] = self._folder.name
        self._proc = subprocess.Popen([self._python, "-I", str(WORKER), *numpy_location()], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
                                      env=env, cwd=self._folder.name)
        threading.Thread(target=self._pump, args=(self._proc,), daemon=True).start()  # the one reader of the worker's output, from its start to its end
        self.containment = osjail.contain(self._proc)  # before the code is sent: the worker is still waiting for its first message
        if self.require_containment and self.containment == "none":
            self.close()
            self._fail("the operating-system containment could not be applied and it was required")
            return
        reply = self._ask({"code": self.code, "class": self.class_name}, START_TIMEOUT)
        if reply is None or not reply.get("ready"):
            self._fail(reply.get("error", "the skill did not start") if isinstance(reply, dict) else "the skill did not start in time")

    def _pump(self, proc: subprocess.Popen) -> None:
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                self._lines.put(line)
        except (OSError, ValueError):
            pass
        self._lines.put("")  # end of stream
        try:
            proc.stdout.close()  # type: ignore[union-attr]  # closed by its only reader, so close() never waits on a read in progress
        except OSError:
            pass

    def _ask(self, message: dict, timeout: float) -> dict | None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return None
        try:
            proc.stdin.write(json.dumps(message) + "\n")  # type: ignore[union-attr]
            proc.stdin.flush()  # type: ignore[union-attr]
        except (OSError, ValueError):
            return None
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            return None
        if not line:
            return None
        try:
            data = json.loads(line)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def _fail(self, why: str) -> None:
        self.faulted, self.fault = True, why
        self.close()

    def close(self) -> None:
        """Stop the worker and release everything the program holds: the process, its input pipe (the reader thread closes the output pipe) and the temporary folder."""
        proc, self._proc = self._proc, None
        if proc is not None:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:  # pragma: no cover
                    pass
            try:
                proc.stdin.close()  # type: ignore[union-attr]  # also when the worker had died: an open pipe outlives the process object otherwise
            except OSError:
                pass
        try:
            self._folder.cleanup()
        except OSError:  # the worker may still hold the folder for a moment on Windows
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def call(self, method: str, *args: Any) -> Any:
        """Call a method of the program. None (and the program is marked faulted) when it did not answer in time or raised."""
        if self.faulted:
            return None
        started = time.perf_counter()
        reply = self._ask({"call": method, "args": list(args)}, self.step_timeout)
        self.latencies_ms.append((time.perf_counter() - started) * 1000.0)
        self.steps += 1
        if reply is None:
            self._fail(f"no answer within {self.step_timeout * 1000:.0f} ms")
            return None
        if "error" in reply:
            self._fail(str(reply["error"]))
            return None
        return reply.get("result")

    def percentile_ms(self, q: float = 99.0) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        return ordered[min(len(ordered) - 1, int(round(q / 100.0 * (len(ordered) - 1))))]


class SandboxedSkill(SandboxedProgram):
    """A model-written controller: `step(obs)` returns a valid action or the neutral fallback."""

    def __init__(self, code: str, step_timeout_ms: float = 50.0, python: str | None = None):
        super().__init__(code, "GeneratedArenaSkill", ("compute_action",), step_timeout_ms, python)

    # ---- one step ------------------------------------------------------------------------------------------------------------------
    def step(self, obs: dict[str, Any]) -> dict:
        """The skill's action for this observation, or the neutral fallback when the skill is late, faulted or returned something that is not an action."""
        if self.faulted:
            return dict(NEUTRAL)
        started = time.perf_counter()
        reply = self._ask({"obs": obs}, self.step_timeout)
        self.latencies_ms.append((time.perf_counter() - started) * 1000.0)
        self.steps += 1
        if reply is None:
            self._fail(f"no answer within {self.step_timeout * 1000:.0f} ms")
            return dict(NEUTRAL)
        if "error" in reply:
            self._fail(str(reply["error"]))
            return dict(NEUTRAL)
        action = clean_action(reply.get("action"))
        if action is None:
            self._fail("the skill returned something that is not an action")
            return dict(NEUTRAL)
        return action


BUTTONS = frozenset({"jump", "attack", "use", "guard", "dash", "item", "confirm", "cancel", "fire", "special"})


def clean_action(raw: Any) -> dict | None:
    """The action schema: {"move": [dx, dy] in -1..1, "buttons": [names], "hold_ms": 0..3000}. Anything else is not an action."""
    if not isinstance(raw, dict):
        return None
    move = raw.get("move", [0.0, 0.0])
    if not (isinstance(move, (list, tuple)) and len(move) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in move)):
        return None
    dx, dy = float(move[0]), float(move[1])
    if not all(-1.0 <= v <= 1.0 for v in (dx, dy)):
        return None
    buttons = raw.get("buttons", [])
    if not (isinstance(buttons, (list, tuple)) and all(isinstance(b, str) and b in BUTTONS for b in buttons)) or len(buttons) > 4:
        return None
    hold = raw.get("hold_ms", 0)
    if isinstance(hold, bool) or not isinstance(hold, (int, float)) or not 0 <= hold <= 3000:
        return None
    return {"move": [dx, dy], "buttons": list(buttons), "hold_ms": int(hold)}


def action_to_tokens(action: dict, dead_zone: float = 0.3) -> str:
    """An action as the universal interface's tokens (see universal/actions.py): the dominant directions held, the buttons tapped."""
    parts = []
    dx, dy = action["move"]
    hold = action.get("hold_ms") or 0
    arg = f"({hold})" if hold else ""
    if dx > dead_zone:
        parts.append(f"[MOVE_RIGHT{arg}]")
    elif dx < -dead_zone:
        parts.append(f"[MOVE_LEFT{arg}]")
    if dy > dead_zone:
        parts.append(f"[MOVE_BACK{arg}]")
    elif dy < -dead_zone:
        parts.append(f"[MOVE_FORWARD{arg}]")
    names = {"jump": "JUMP", "attack": "ATTACK", "use": "USE", "guard": "CROUCH", "dash": "SPRINT", "item": "INVENTORY", "confirm": "USE", "cancel": "PAUSE", "fire": "ATTACK",
             "special": "RELOAD"}
    parts.extend(f"[{names[b]}]" for b in action.get("buttons", []))
    return "&".join(parts)
