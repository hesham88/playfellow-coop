"""--overlay is a real switch: the session's events reach the panel through a queue (never from the session's thread), the summon key opens
and closes it, the panel follows the hand-over, and the window closes exactly once when the session ends. No window is ever opened here."""
from __future__ import annotations

import threading
from pathlib import Path

from playfellow_coop import __main__ as entry
from playfellow_coop.overlay.panel import PanelModel
from playfellow_coop.overlay.runner import POLL_MS, OverlayRunner
from playfellow_coop.voice import CommandQueue
from tests.test_main import Parts


class FakeRoot:
    def __init__(self):
        self.scheduled = []

    def after(self, ms, fn):
        self.scheduled.append((ms, fn))


class FakeView:
    def __init__(self):
        self.root, self.started, self.closed, self.looped = FakeRoot(), 0, 0, 0

    def start(self):
        self.started += 1

    def mainloop(self):
        self.looped += 1  # the real one blocks until closed; here the test drives ticks itself

    def close(self):
        self.closed += 1


class FakePump:
    def __init__(self):
        self.started = self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


class Hand:
    human_has_controls = False


def make(handover=None, safety=None):
    model = PanelModel(CommandQueue(), language=lambda: "english")
    view, pump = FakeView(), FakePump()
    return OverlayRunner(model, view, handover=handover, safety=safety, pump=pump), model, view, pump


def test_events_from_another_thread_reach_the_panel_only_when_the_main_thread_ticks():
    runner, model, view, _ = make()
    worker = threading.Thread(target=lambda: (runner.event("say", "I've got it."), runner.event("thought", "private"), runner.event("say", "")))
    worker.start()
    worker.join()
    assert list(model.lines) == []  # nothing is drawn from the session's thread
    runner.tick()
    assert [line.text for line in model.lines] == ["I've got it."] and view.root.scheduled[-1][0] == POLL_MS


def test_the_summon_key_opens_and_closes_the_panel():
    runner, model, _, _ = make()
    runner.summon()
    runner.tick()
    assert model.visible
    runner.summon()
    runner.tick()
    assert not model.visible


def test_the_panel_follows_the_hand_over_and_the_stop():
    hand, safety = Hand(), type("S", (), {"stopped": False})()
    runner, model, _, _ = make(handover=hand, safety=safety)
    runner.tick()
    assert model.state == "ready"
    hand.human_has_controls = True
    runner.tick()
    assert model.state == "player"
    hand.human_has_controls = False
    runner.tick()
    assert model.state == "ready"
    safety.stopped = True
    runner.tick()
    assert model.state == "stopped"


def test_finish_closes_the_window_and_the_hotkey_once_and_stops_the_polling():
    runner, _, view, pump = make()
    runner.finish()
    runner.finish()
    runner.tick()
    assert view.closed == 1 and pump.stopped == 1 and runner.closes == 1
    scheduled = len(view.root.scheduled)
    runner.tick()
    assert len(view.root.scheduled) == scheduled  # no further polling once closed


def test_run_starts_the_view_and_the_hotkey_then_the_loop():
    runner, _, view, pump = make()
    runner.run()
    assert view.started == 1 and pump.started == 1 and view.looped == 1 and view.root.scheduled


def test_main_with_the_overlay_runs_the_session_on_another_thread_and_closes_the_window_when_it_ends():
    parts, said, seen = Parts(), [], {}
    runner, model, view, _ = make()

    def build(argv):
        import settings

        parts.overlay, parts.summon_key = True, "ctrl+alt+p"
        return parts, settings.Settings()

    def builder(p, commands, handover, key, talk_down, talk_up):
        seen["key"] = key
        return runner

    def run(p, cfg, system, timer, handover, on_event, commands=None, latency=None):
        seen["thread"] = threading.current_thread().name
        on_event("say", "Back with me.")
        return "round_done"

    def loop():  # stands in for the window loop: collect what the session posted until it finishes
        for _ in range(200):
            runner.tick()
            if runner.closes:
                break
            threading.Event().wait(0.01)

    view.mainloop = loop
    code = entry.main([], build_fn=build, listen_key=lambda n, cb: None, listen_stop=lambda cb: None, run=run, say=said.append,
                      overlay_builder=builder)
    assert code == 0 and seen["thread"] == "session" and seen["key"] == "ctrl+alt+p"
    assert "Back with me." in said and [line.text for line in model.lines] == ["Back with me."] and view.closed == 1


def test_a_summon_key_the_game_uses_is_a_friendly_stop_not_a_crash():
    from playfellow_coop.overlay.hotkey import HotkeyError

    parts, said = Parts(), []

    def build(argv):
        import settings

        parts.overlay, parts.summon_key = True, "w"
        return parts, settings.Settings()

    def builder(*args):
        raise HotkeyError("that key is used by the game's controls card")

    assert entry.main([], build_fn=build, listen_key=lambda n, cb: None, listen_stop=lambda cb: None, say=said.append,
                      overlay_builder=builder) == 2
    assert any("controls card" in line for line in said)


def test_a_missing_qt_is_a_friendly_stop_with_its_message_and_no_old_window_opens_instead():
    """Owner order 27 Oct: no old window is ever the fallback."""
    from playfellow_coop.overlay.runner import OverlayUnavailableError

    parts, said = Parts(), []

    def build(argv):
        import settings

        parts.overlay, parts.summon_key = True, "ctrl+alt+p"
        return parts, settings.Settings()

    def builder(*args):
        raise OverlayUnavailableError("The command center needs PySide6.")

    assert entry.main([], build_fn=build, listen_key=lambda n, cb: None, listen_stop=lambda cb: None, say=said.append,
                      overlay_builder=builder) == 2
    assert any("PySide6" in line for line in said)


def test_the_overlay_switch_is_off_by_default_and_read_from_the_command_line():
    parts, _ = entry.build([], build_parts=lambda cfg: Parts(), key_loader=lambda: None)
    assert parts.overlay is False and parts.summon_key == "ctrl+alt+p"
    parts, _ = entry.build(["--overlay", "--summon-key", "ctrl+alt+o"], build_parts=lambda cfg: Parts(), key_loader=lambda: None)
    assert parts.overlay is True and parts.summon_key == "ctrl+alt+o"
