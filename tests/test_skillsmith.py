"""Model-written skills: the static gate refuses what it must, the sandbox contains and times what runs, the gates separate good skills from unsafe ones, the library only writes inside its
folder, and promotion follows TORSI's rules."""
from __future__ import annotations

import json
import os

import pytest

from playfellow_coop.skillsmith import ast_gate, sandbox
from playfellow_coop.skillsmith.library import ScopeViolation, SkillLibrary
from playfellow_coop.skillsmith.promote import Budget, BudgetExceeded, HeldOutLeak, Selector, assert_disjoint
from playfellow_coop.skillsmith.sandbox import NEUTRAL, SandboxedSkill, action_to_tokens, clean_action, scrubbed_environment
from playfellow_coop.skillsmith.synth import Synthesizer, build_prompt, extract_code
from playfellow_coop.skillsmith.verify import guided_progress, verify

GOOD = '''
import math

class GeneratedArenaSkill:
    """Run away from danger, otherwise chase the nearest item."""
    def __init__(self):
        self.t = 0

    def compute_action(self, obs):
        self.t += 1
        if obs.get("danger", 0) >= 0.5 and obs.get("escape"):
            ex, ey = obs["escape"]
            return {"move": [max(-1.0, min(1.0, ex)), max(-1.0, min(1.0, ey))], "buttons": [], "hold_ms": 0}
        items = obs.get("items") or []
        if items:
            sx, sy = obs["self"]
            ix, iy = items[0][0], items[0][1]
            dx, dy = ix - sx, iy - sy
            n = math.hypot(dx, dy) or 1.0
            return {"move": [dx / n, dy / n], "buttons": [], "hold_ms": 0}
        return {"move": [1.0 if self.t % 2 else -1.0, 0.0], "buttons": [], "hold_ms": 0}
'''

ATTACKS = {
    "import os": "import os\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return {}\n",
    "from subprocess": "from subprocess import run\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return {}\n",
    "open": "class GeneratedArenaSkill:\n    def compute_action(self, obs):\n        open('x', 'w')\n        return {}\n",
    "eval": "class GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return eval('1')\n",
    "getattr": "class GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return getattr(obs, 'keys')\n",
    "dunder attribute": "class GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return ().__class__.__bases__[0].__subclasses__()\n",
    "dunder name": "class GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return __builtins__\n",
    "while": "class GeneratedArenaSkill:\n    def compute_action(self, obs):\n        while True:\n            pass\n",
    "global": "X = 1\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        global X\n        return {}\n",
    "numpy file io": "import numpy as np\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        np.load('x')\n        return {}\n",
    "numpy ctypes": "import numpy as np\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return np.ctypeslib\n",
    "runs at import": "print('hi')\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return {}\n",
    "call at top level": "x = 1\nx.real\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return {}\n",
    "relative import": "from . import x\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return {}\n",
    "no class": "def compute_action(obs):\n    return {}\n",
    "no method": "class GeneratedArenaSkill:\n    pass\n",
    "syntax": "class GeneratedArenaSkill(:\n",
    "async": "class GeneratedArenaSkill:\n    async def compute_action(self, obs):\n        return {}\n",
}


# ---- layer 1 ------------------------------------------------------------------------------------------------------------------------
def test_good_code_passes_and_every_attack_is_refused_with_a_reason():
    assert ast_gate.check(GOOD) == (True, "ok")
    for name, code in ATTACKS.items():
        ok, why = ast_gate.check(code)
        assert not ok and why, name


def test_a_huge_skill_is_refused():
    big = "class GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return [" + ",".join(["1"] * 900) + "]\n"
    ok, why = ast_gate.check(big)
    assert not ok and "too large" in why


# ---- layer 2 ------------------------------------------------------------------------------------------------------------------------
def test_a_good_skill_runs_in_a_separate_process_and_answers_within_the_limit():
    with SandboxedSkill(GOOD, step_timeout_ms=2000) as skill:
        a = skill.step({"self": [0.5, 0.5], "items": [[0.9, 0.5, 0, 0]], "danger": 0.0})
        b = skill.step({"self": [0.5, 0.5], "danger": 0.9, "escape": [-1.0, 0.0]})
        assert a["move"][0] > 0.9 and b["move"] == [-1.0, 0.0] and not skill.faulted and skill.steps == 2
        assert skill.percentile_ms() < 2000


def test_a_skill_that_is_too_slow_is_killed_and_the_fallback_is_neutral_from_then_on():
    slow = ("class GeneratedArenaSkill:\n    def compute_action(self, obs):\n        total = 0\n        for i in range(100000000):\n            total += i\n"
            "        return {'move': [1.0, 0.0], 'buttons': [], 'hold_ms': 0}\n")
    with SandboxedSkill(slow, step_timeout_ms=150) as skill:
        assert skill.step({}) == NEUTRAL and skill.faulted and "no answer within" in skill.fault
        assert skill.step({}) == NEUTRAL  # nothing runs any more


def test_a_skill_that_raises_or_returns_nonsense_is_faulted():
    raises = "class GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return 1 / 0\n"
    junk = "class GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return {'move': [5.0, 0.0]}\n"
    with SandboxedSkill(raises, step_timeout_ms=2000) as skill:
        assert skill.step({}) == NEUTRAL and skill.faulted and "ZeroDivisionError" in skill.fault
    with SandboxedSkill(junk, step_timeout_ms=2000) as skill:
        assert skill.step({}) == NEUTRAL and skill.faulted and "not an action" in skill.fault


def test_the_worker_alone_refuses_imports_even_if_the_static_gate_were_bypassed(monkeypatch):
    monkeypatch.setattr(ast_gate, "check", lambda code, *a, **k: (True, "ok"))
    code = "import os\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return {'move': [0.0, 0.0]}\n"
    with SandboxedSkill(code, step_timeout_ms=2000) as skill:
        assert skill.faulted and "ImportError" in skill.fault
    code2 = "class GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return open('x')\n"
    with SandboxedSkill(code2, step_timeout_ms=2000) as skill:  # open is not even a builtin inside the worker
        assert skill.step({}) == NEUTRAL and skill.faulted


def test_the_worker_environment_holds_no_secrets(monkeypatch):
    monkeypatch.setenv("PLAYFELLOW_SECRET_KEY", "super-secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid")
    env = scrubbed_environment()
    assert "PLAYFELLOW_SECRET_KEY" not in env and "HTTPS_PROXY" not in env and env["PATH"] == ""
    assert set(env) <= {"PATH", "SYSTEMROOT", "SYSTEMDRIVE"}


def test_action_schema_and_tokens():
    assert clean_action({"move": [0.5, -1], "buttons": ["jump"], "hold_ms": 120}) == {"move": [0.5, -1.0], "buttons": ["jump"], "hold_ms": 120}
    for bad in (None, {"move": [2, 0]}, {"move": [0, 0], "buttons": ["format_disk"]}, {"move": [0, 0], "hold_ms": 99999}, {"move": "up"}, {"move": [True, 0]}):
        assert clean_action(bad) is None
    assert action_to_tokens({"move": [1.0, -1.0], "buttons": ["jump"], "hold_ms": 100}) == "[MOVE_RIGHT(100)]&[MOVE_FORWARD(100)]&[JUMP]"
    assert action_to_tokens({"move": [0.1, 0.0], "buttons": []}) == ""


# ---- the gates ----------------------------------------------------------------------------------------------------------------------
def trace(n=40):
    rows = []
    for i in range(n):
        danger = 0.9 if i % 4 == 0 else 0.0
        rows.append({"self": [0.5, 0.5], "items": [[0.9, 0.5 + 0.01 * (i % 5), 0, 0]], "danger": danger, "escape": [-1.0, 0.0] if danger else None, "progress_dir": [1.0, 0.0], "t": i})
    return rows


def test_a_good_skill_passes_all_gates_and_reports_guided_progress():
    result = verify(GOOD, trace(), trial=lambda: (0.1, 0.4), limit_ms=2000, step_timeout_ms=2000)
    assert result.passed and set(result.gates) == {"A", "B", "C"} and result.progress is not None and result.progress >= 0.7
    assert "A: ok" in result.summary()


def test_gate_b_catches_a_skill_that_runs_into_danger_and_a_skill_that_locks_on_one_direction():
    suicidal = "class GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return {'move': [1.0, 0.0], 'buttons': [], 'hold_ms': 0}\n"
    result = verify(suicidal, trace(), limit_ms=2000, step_timeout_ms=2000)
    assert not result.passed and not result.gates["B"].passed and "moved away from danger" in result.gates["B"].detail
    calm = [dict(r, danger=0.0, escape=None) for r in trace()]
    lock = verify(suicidal, calm, limit_ms=2000, step_timeout_ms=2000)
    assert not lock.passed and "wall lock" in lock.gates["B"].detail


def test_gate_a_catches_a_skill_over_the_latency_limit_and_gate_c_a_trial_that_does_not_improve():
    result = verify(GOOD, trace(10), limit_ms=0.0001, step_timeout_ms=2000)
    assert not result.passed and not result.gates["A"].passed and "over the" in result.gates["A"].detail and "B" not in result.gates
    flat = verify(GOOD, trace(), trial=lambda: (0.5, 0.5), limit_ms=2000, step_timeout_ms=2000, min_gain=0.01)
    assert not flat.passed and not flat.gates["C"].passed
    assert guided_progress([{"move": [1, 0]}], [{}]) is None


# ---- the library --------------------------------------------------------------------------------------------------------------------
def test_the_library_writes_only_inside_its_folder_keeps_receipts_and_detects_tampering(tmp_path):
    lib = SkillLibrary(tmp_path)
    verification = verify(GOOD, trace(12), limit_ms=2000, step_timeout_ms=2000)
    receipt = lib.add("snake", "chaser", GOOD, verification)
    assert receipt.path == ".agents/skills/snake/chaser.py" and len(receipt.sha256) == 64 and lib.names("snake") == ["chaser"] and lib.get("snake", "chaser") == GOOD
    before = lib.folder_hash()
    (tmp_path / ".agents" / "skills" / "snake" / "chaser.py").write_text(GOOD + "\n# edited", encoding="utf-8")
    assert lib.get("snake", "chaser") is None and lib.folder_hash() != before  # no longer the skill that passed
    for game, name in (("../evil", "x"), ("snake", "../../x"), ("snake", "a/b"), ("Snake", "x"), ("snake", "C:x"), ("", "x")):
        with pytest.raises(ScopeViolation):
            lib.add(game, name, GOOD)
    with pytest.raises(ast_gate.SkillRejected):
        lib.add("snake", "bad", ATTACKS["import os"])
    failed = verify(GOOD, trace(12), trial=lambda: (1.0, 0.0), limit_ms=2000, step_timeout_ms=2000)
    with pytest.raises(ValueError):
        lib.add("snake", "failed", GOOD, failed)
    assert lib.remove("snake", "chaser") and lib.names("snake") == []
    lib.note("snake", "tail-chasing loops kill the snake", "seed 3 trace")
    with pytest.raises(ValueError):
        lib.note("snake", "a lesson with no evidence", "")
    assert lib.experience("snake") == ["- [snake] tail-chasing loops kill the snake (evidence: seed 3 trace)"] and lib.experience("kart") == []


# ---- promotion ----------------------------------------------------------------------------------------------------------------------
def test_promotion_needs_a_strict_validation_gain_and_never_touches_the_held_out_set():
    selector = Selector()
    scores = {"current": 0.50, "a": 0.50, "b": 0.62, "c": 0.58}
    decision = selector.choose("current", scores, [1, 2, 3], [100, 101])
    assert decision.promote and decision.chosen == "b"
    assert not selector.choose("current", scores, [1, 2, 3], [100]).promote  # the same validation tasks cannot be mined twice
    assert not Selector().choose("current", {"current": 0.5, "a": 0.5}, [4, 5]).promote  # a tie keeps the current skill
    with pytest.raises(HeldOutLeak):
        Selector().choose("current", scores, [1, 2, 100], [100])
    with pytest.raises(ValueError):
        Selector().choose("current", {"a": 1.0}, [9])
    assert_disjoint([1], [2])
    budget = Budget(max_usd=0.10, max_calls=3)
    budget.spend(0.04)
    budget.spend(0.04)
    with pytest.raises(BudgetExceeded):
        budget.spend(0.04)
    assert budget.calls == 2 and budget.left_usd == pytest.approx(0.02)
    with pytest.raises(BudgetExceeded):
        Budget(10.0, 1).spend(0.01, calls=2)


# ---- the synthesizer ----------------------------------------------------------------------------------------------------------------
def test_the_synthesizer_retries_once_with_the_reason_stores_only_verified_skills_and_writes_lessons(tmp_path):
    prompts = []
    answers = ["```python\n" + ATTACKS["import os"] + "```", "```python\n" + GOOD + "```"]

    def ask(prompt):
        prompts.append(prompt)
        return answers[len(prompts) - 1]

    lib = SkillLibrary(tmp_path)
    synth = Synthesizer(ask, lib, Budget(1.0, 10), cost_per_call_usd=0.05)
    attempt = synth.build("snake", "collect the food", "chaser", trace(16), trial=lambda: (0.0, 1.0), limit_ms=2000)
    assert attempt.receipt is not None and attempt.verification.passed and lib.names("snake") == ["chaser"]
    assert "import of 'os' is not allowed" in prompts[1] and "Recorded observations" in prompts[0] and "collect the food" in prompts[0]
    assert any("passed all gates" in line for line in lib.experience("snake")) and synth.budget.calls == 2


def test_two_refusals_end_the_attempt_and_a_failed_verification_is_recorded_not_stored(tmp_path):
    lib = SkillLibrary(tmp_path)
    synth = Synthesizer(lambda p: "no code here", lib, Budget(1.0, 10))
    attempt = synth.build("snake", "goal", "x", trace(8))
    assert attempt.code is None and len(attempt.reasons) == 2 and lib.names("snake") == [] and any("rejected twice" in l for l in lib.experience("snake"))
    synth = Synthesizer(lambda p: "```python\n" + GOOD + "```", lib, Budget(1.0, 10))
    failed = synth.build("snake", "goal", "y", trace(8), trial=lambda: (1.0, 0.0), limit_ms=2000)
    assert failed.receipt is None and not failed.verification.passed and lib.names("snake") == [] and any("failed verification" in l for l in lib.experience("snake"))
    tight = Synthesizer(lambda p: "x", lib, Budget(0.05, 5), cost_per_call_usd=0.05)
    with pytest.raises(BudgetExceeded):
        tight.propose("snake", "g", [])


def test_prompt_helpers():
    assert extract_code("here:\n```python\nclass A: pass\n```") == "class A: pass\n" and extract_code("class A: pass") == "class A: pass\n" and extract_code("hi") is None
    prompt = build_prompt("snake", "goal", trace(200), ["lesson one"], "bad import")
    assert "lesson one" in prompt and "bad import" in prompt and prompt.count('"self"') <= 61 and json.loads(prompt.split("Recorded observations (raw, in order):\n")[1].split("\n\n")[0])
    assert os.name  # keeps the import used


def test_numpy_is_an_allow_list_in_both_layers_so_file_touching_functions_are_absent():
    from playfellow_coop.skillsmith.ast_gate import check
    from playfellow_coop.skillsmith.sandbox import SandboxedSkill
    body = "import numpy as np\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return {}\n"
    for bad in ("np.memmap('x', mode='w+')", "np.loadtxt('x')", "np.genfromtxt('x')", "np.fromregex('x', 'a', float)", "np.DataSource()"):
        ok, why = check(body.replace("return {}", f"return {bad}"))
        assert not ok and "not allowed" in why, bad
    assert not check("from numpy import memmap\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return {}\n")[0]
    assert not check("import numpy.lib.format\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return {}\n")[0]
    assert check(body.replace("return {}", "return {'x': float(np.clip(np.mean(np.array([1.0, 2.0])), 0, 1))}"))[0]
    # the second layer: code that skipped the gate (a gate bug) still cannot reach the real module from inside the worker
    import json, subprocess, sys
    import pathlib, playfellow_coop.skillsmith as pkg
    NL = chr(10)
    code = NL.join(["import numpy as np", "class GeneratedArenaSkill:", "    def compute_action(self, obs):", "        try:", "            np.memmap",
                    "            return {'v': 'reached'}", "        except AttributeError:", "            return {'v': 'absent'}", ""])
    lines = json.dumps({"code": code}) + NL + json.dumps({"obs": {}}) + NL
    import numpy
    worker = str(pathlib.Path(pkg.__file__).parent / "_worker.py")
    boot = "import sys; sys.path.insert(0, %r); exec(compile(open(%r).read(), 'w', 'exec'))" % (str(pathlib.Path(numpy.__file__).parent.parent), worker)  # -I hides the user site where numpy may live
    out = subprocess.run([sys.executable, "-I", "-c", boot], input=lines, capture_output=True, text=True, timeout=60).stdout.splitlines()
    assert json.loads(out[0]) == {"ready": True} and json.loads(out[1]) == {"action": {"v": "absent"}}
