"""One widget, however it was started: the main command's widget (`--window ... --overlay`) follows the same small files as the game
packs' widget, so Meta's Muse Code (or any MCP agent) drives it the same way. Fake hands, safety and widget; files in a temp folder."""
from __future__ import annotations

from playfellow_coop.games.stk import widget
from playfellow_coop.handover import HandOver
from playfellow_coop.overlay.bridge import WidgetBridge
from playfellow_coop.voice import CommandQueue


class Hands:
    def __init__(self):
        self.stops = self.resumes = 0

    def on_stop(self):
        self.stops += 1

    def resume(self):
        self.resumes += 1


class Safety:
    def __init__(self):
        self.stopped, self.calls, self.reason = False, 0, None

    def stop(self, reason):
        self.stopped, self.reason = True, reason


def make(tmp_path):
    files = widget.game_files("My Game", home=tmp_path / "stk")
    hands, safety, events, queue = Hands(), Safety(), [], CommandQueue()
    handover = HandOver(hands, safety)
    bridge = WidgetBridge(files, events.append, handover, safety, queue, pid=4242)
    bridge.start_files()
    return bridge, files, handover, safety, events, queue


def test_the_files_are_the_same_ones_the_mcp_server_uses(tmp_path):
    files = widget.game_files("My Game", home=tmp_path / "stk")
    assert files["dir"] == tmp_path / "my-game" and files["stop"].name == "STOP" and files["feed"].name == "live-feed.txt"
    assert widget.game_files("SuperTuxKart", home=tmp_path / "stk")["dir"] == tmp_path / "stk"


def test_the_main_widget_says_it_is_running(tmp_path):
    bridge, files, *_ = make(tmp_path)
    assert files["lock"].read_text(encoding="utf-8") == "4242"
    bridge.close()
    assert not files["lock"].exists()


def test_an_agents_stop_stops_the_session(tmp_path):
    bridge, files, handover, safety, events, _ = make(tmp_path)
    files["stop"].write_text("stop", encoding="utf-8")
    bridge.poll()
    assert safety.stopped and safety.reason == "stopped_button"


def test_an_agents_hand_over_and_take_back_drive_the_session(tmp_path):
    bridge, files, handover, safety, events, _ = make(tmp_path)
    files["handover"].write_text("agent", encoding="utf-8")
    bridge.poll()
    assert handover.human_has_controls
    files["handover"].unlink()
    bridge.poll()
    assert not handover.human_has_controls


def test_the_players_f9_is_written_so_an_agent_cannot_undo_it(tmp_path):
    bridge, files, handover, *_ = make(tmp_path)
    handover.toggle()  # the player pressed F9
    bridge.poll()
    assert files["handover"].read_text(encoding="utf-8") == "you"
    handover.toggle()  # and F9 again
    bridge.poll()
    assert not files["handover"].exists()


def test_feed_lines_reach_the_widget_and_controls_are_applied(tmp_path):
    bridge, files, handover, safety, events, queue = make(tmp_path)
    widget.say_line("Nice jump!", files["feed"])
    widget.say_line("!opacity 0.6", files["feed"])
    widget.say_line("~happy", files["feed"])
    widget.say_line("!type grab the coins on the left", files["feed"])
    bridge.poll()
    assert ("say", "Nice jump!") in events and ("control", ("opacity", 0.6)) in events
    assert not any(kind == "say" and "happy" in str(data) for kind, data in events)
    assert queue.drain() == ["grab the coins on the left"]


def test_an_agents_words_wait_while_the_player_holds_the_controls(tmp_path):
    bridge, files, handover, safety, events, queue = make(tmp_path)
    handover.toggle()
    bridge.poll()
    widget.say_line("!type take the controls back", files["feed"])
    bridge.poll()
    assert queue.drain() == [] and any(kind == "say" and "you have the controls" in str(data) for kind, data in events)


def test_lines_from_before_the_start_are_not_replayed(tmp_path):
    files = widget.game_files("My Game", home=tmp_path / "stk")
    widget.say_line("old line", files["feed"])
    hands, safety, events = Hands(), Safety(), []
    bridge = WidgetBridge(files, events.append, HandOver(hands, safety), safety, CommandQueue(), pid=1)
    bridge.start_files()
    bridge.poll()
    assert events == []


def test_the_main_command_starts_and_closes_the_bridge_with_its_widget():
    import settings

    from playfellow_coop import __main__ as entry
    from tests.test_main import Parts

    parts, seen = Parts(), {}

    def build(argv):
        parts.overlay, parts.summon_key = True, "ctrl+alt+p"
        return parts, settings.Settings()

    class Runner:
        def event(self, kind, data):
            seen.setdefault("events", []).append((kind, data))

        def finish(self):
            pass

        def run(self):
            pass

    class Bridge:
        def __init__(self, on_event):
            self.on_event = on_event

        def start(self):
            seen["started"] = True
            self.on_event(("control", ("open", None)))

        def close(self):
            seen["closed"] = True

    entry.main([], build_fn=build, listen_key=lambda n, cb: None, listen_stop=lambda cb: None, say=lambda s: None,
               run=lambda *a, **k: "round_done", overlay_builder=lambda *a: Runner(), bridge_factory=Bridge)
    assert seen.get("started") and seen.get("closed") and ("control", ("open", None)) in seen["events"]


def test_the_runner_applies_an_agents_widget_controls():
    from playfellow_coop.overlay.panel import PanelModel
    from playfellow_coop.overlay.runner import OverlayRunner

    class View:
        class root:
            @staticmethod
            def after(ms, fn):
                pass

    model = PanelModel(CommandQueue())
    runner = OverlayRunner(model, View())
    runner.event("control", ("open", None))
    runner.event("control", ("opacity", 0.6))
    runner.tick()
    assert model.visible and abs(model.opacity - 0.6) < 1e-6
