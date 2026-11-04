"""Typing in the widget from the main command: the open panel may take the keyboard for typing, folded it never does, and after a
command is sent the chosen game gets the front back. The Qt and Windows calls are replaced by recorders; no window is opened."""
from __future__ import annotations

from playfellow_coop.overlay.panel import PanelModel
from playfellow_coop.overlay.runner import panel_focus_listener
from playfellow_coop.voice import CommandQueue


def test_the_panel_takes_the_keyboard_only_while_open_and_only_on_a_change():
    model, calls = PanelModel(CommandQueue()), []
    model.subscribe(panel_focus_listener(model, calls.append))
    model.show()
    model.show()  # no change, no call
    model.lines.clear()
    model.hide()
    assert calls == [True, False]


def test_a_sent_command_gives_the_game_the_front_back():
    queue, backs = CommandQueue(), []
    model = PanelModel(queue)
    model.on_submitted = lambda: backs.append("game")
    assert model.submit("grab the coins on the left")
    assert backs == ["game"] and queue.drain() == ["grab the coins on the left"]
    assert not model.submit("   ") and backs == ["game"]  # nothing sent, nothing moved


def test_a_failing_give_back_never_breaks_the_command():
    queue = CommandQueue()
    model = PanelModel(queue)

    def broken():
        raise OSError("desktop went away")

    model.on_submitted = broken
    assert model.submit("wait") and queue.drain() == ["wait"]
