"""Control-loop hooks (watchdog, completion gate) and the clean-evaluation helpers (no network, prompt budget, cost ledger)."""
from __future__ import annotations

import socket

import pytest

from playfellow_coop.evalkit.isolation import CostLedger, NetworkBlocked, NoNetwork, prompt_budget
from playfellow_coop.harness.hooks import CONTINUE, FORCE_FINISH, Check, CompletionGate, ControlHooks, Watchdog, from_spec


def test_the_watchdog_forces_a_finish_on_steps_time_or_spend_and_stays_quiet_before():
    now = [0.0]
    hooks = ControlHooks(Watchdog(max_steps=10, max_seconds=5, max_usd=0.2, clock=lambda: now[0]))
    assert hooks.before_step({"step": 3, "spent_usd": 0.05}) == CONTINUE
    assert hooks.before_step({"step": 10}) == FORCE_FINISH and "step limit" in hooks.forced
    hooks = ControlHooks(Watchdog(max_seconds=5, clock=lambda: now[0]))
    assert hooks.before_step({"step": 1}) == CONTINUE
    now[0] = 6.0
    assert hooks.before_step({"step": 2}) == FORCE_FINISH and "time limit" in hooks.forced
    hooks = ControlHooks(Watchdog(max_usd=0.2))
    assert hooks.before_step({"spent_usd": 0.25}) == FORCE_FINISH and "spend limit" in hooks.forced


def test_the_gate_refuses_a_finish_until_every_check_passes_and_a_crashing_check_refuses():
    gate = CompletionGate([Check("won", lambda s: s["won"], "the game is not won"), Check("boom", lambda s: s["missing"], "never reached")])
    ok, why = gate.allow({"won": True})
    assert not ok and len(why) == 1 and why[0].startswith("boom")  # the KeyError counted as a refusal, not a pass
    assert gate.allow({"won": True, "missing": True}) == (True, [])
    hooks = ControlHooks(gate=gate)
    assert hooks.before_finish({"won": False, "missing": True})[0] is False and hooks.blocked == 1


def test_a_forced_finish_may_always_stop_even_when_the_gate_would_refuse():
    hooks = ControlHooks(Watchdog(max_steps=1), CompletionGate([Check("won", lambda s: s.get("won"))]))
    assert hooks.before_step({"step": 5}) == FORCE_FINISH
    assert hooks.before_finish({"won": False}) == (True, []) and hooks.blocked == 0


def test_hooks_come_from_plain_data_and_a_typo_is_an_error_not_an_open_door():
    hooks = from_spec({"watchdog": {"max_steps": 600}, "gate": [{"check": "won"}, {"check": "progress_at_least", "value": 0.9}]})
    assert hooks.before_finish({"won": True, "progress": 0.5})[0] is False
    assert hooks.before_finish({"won": True, "progress": 0.95}) == (True, [])
    assert from_spec({}).before_finish({}) == (True, [])
    with pytest.raises(ValueError):
        from_spec({"gate": [{"check": "wonn"}]})
    with pytest.raises(ValueError):
        from_spec({"gate": [{"check": "progress_at_least_"}]})


def test_no_network_blocks_connections_and_lookups_and_puts_everything_back():
    before = (socket.create_connection, socket.getaddrinfo)
    with NoNetwork():
        with pytest.raises(NetworkBlocked):
            socket.create_connection(("example.com", 80), timeout=1)
        with pytest.raises(NetworkBlocked):
            socket.getaddrinfo("example.com", 80)
        with pytest.raises(NetworkBlocked), socket.socket() as blocked:  # closed either way: -W error turns an open socket into a failure
            blocked.connect(("127.0.0.1", 9))
    assert (socket.create_connection, socket.getaddrinfo) == before
    with pytest.raises(OSError) as err, socket.socket() as plain:  # reachable code again: the refusal is the OS's, not ours
        plain.connect(("127.0.0.1", 9))
    assert not isinstance(err.value, NetworkBlocked)


def test_the_always_on_prompt_has_a_size_limit_that_names_the_parts():
    ok, sizes = prompt_budget({"system": "x" * 400, "skills": "y" * 400}, limit_tokens=250)
    assert ok and sizes == {"system": 100, "skills": 100}
    ok, _ = prompt_budget({"system": "x" * 4000}, limit_tokens=250)
    assert not ok


def test_the_cost_ledger_adds_up_by_kind_and_shows_how_much_the_search_cost_against_the_final_run():
    ledger = CostLedger()
    assert ledger.overhead_vs_final() == float("inf")
    ledger.add("reference_run", 0.10)
    ledger.add("probe", 0.30, calls=6)
    ledger.add("editing", 0.05)
    ledger.add("final_run", 0.05)
    assert ledger.total() == pytest.approx(0.50) and ledger.by_kind()["probe"] == pytest.approx(0.30)
    assert ledger.overhead_vs_final() == pytest.approx(10.0)
    with pytest.raises(ValueError):
        ledger.add("lunch", 1.0)


def test_gate_b_cannot_pass_a_trace_that_never_asked_the_question():
    from playfellow_coop.skillsmith.verify import gate_b
    calm = [{"danger": 0.0} for _ in range(10)]
    actions = [{"move": [0.0, 0.0]} for _ in range(10)]
    assert gate_b(actions, calm).passed is False
    risky = [{"danger": 0.9, "escape": [1.0, 0.0]} for _ in range(10)]
    assert gate_b([{"move": [1.0, 0.0]}] * 5 + [{"move": [0.5, 0.5]}] * 5, risky).passed is True


def test_hooks_reset_between_rounds_a_missing_state_key_is_not_a_pass_a_finished_match_may_stop_and_bad_specs_are_errors():
    hooks = from_spec({"watchdog": {"max_steps": 2}, "gate": [{"check": "no_blank_fields"}]})
    assert hooks.before_step({"step": 5}) == FORCE_FINISH and hooks.before_finish({})[0] is True
    hooks.reset()
    assert hooks.forced is None and hooks.before_step({"step": 1}) == CONTINUE
    assert hooks.before_finish({"won": True})[0] is False  # the state never said whether fields are blank: refused
    assert hooks.before_finish({"blank_fields": []})[0] is True
    assert hooks.before_finish({"match_over": True})[0] is True  # a lost or won match the game reports as over can always stop
    for bad in ({"watchdog": {"max_steps": -1}}, {"watchdog": {"max_usd": "five"}}, {"gate": [{"check": "progress_at_least"}]}, {"gate": ["won"]}):
        with pytest.raises(ValueError):
            from_spec(bad)
    boom = CompletionGate([Check("x", lambda s: s["nope"])])
    assert "KeyError" in boom.allow({})[1][0]


def test_no_network_also_blocks_sends_and_extra_lookups():
    with NoNetwork():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            with pytest.raises(NetworkBlocked):
                sock.sendto(b"x", ("127.0.0.1", 9))
            with pytest.raises(NetworkBlocked):
                socket.gethostbyaddr("127.0.0.1")
        finally:
            sock.close()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(b"x", ("127.0.0.1", 9))  # allowed again outside the block
    finally:
        sock.close()
