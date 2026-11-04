"""The widget docks at the top centre of the game the player chose, not of the screen: the main command hands the overlay a
`follow` function built from the engine's own window finder. No window is opened and no desktop is touched here."""
from __future__ import annotations

import threading
from dataclasses import dataclass

from playfellow_coop import __main__ as entry
from playfellow_coop.overlay.runner import game_follow
from tests.test_main import Parts


@dataclass(frozen=True)
class Box:  # the engine's WindowBox shape: the game's client area in screen pixels
    left: int
    top: int
    width: int
    height: int


class FakeScreen:
    def __init__(self, boxes):
        self.boxes, self.asked = dict(boxes), []

    def find(self, title):
        self.asked.append(title)
        return self.boxes.get(title)


def test_follow_turns_the_game_window_into_the_widgets_rectangle():
    follow = game_follow(FakeScreen({"SuperTuxKart": Box(100, 50, 1280, 720)}), "SuperTuxKart")
    assert follow() == (100, 50, 1380, 770)


def test_follow_says_none_when_the_game_is_gone_so_the_widget_keeps_its_place():
    assert game_follow(FakeScreen({}), "SuperTuxKart")() is None


def test_follow_never_raises_when_the_window_finder_fails():
    class Broken:
        def find(self, title):
            raise OSError("desktop went away")

    assert game_follow(Broken(), "x")() is None


def test_main_hands_the_overlay_a_follow_function_for_the_chosen_game():
    import settings

    parts, seen = Parts(), {}
    parts.screen = FakeScreen({"My Game": Box(10, 20, 800, 600)})

    def build(argv):
        parts.overlay, parts.summon_key = True, "ctrl+alt+p"
        return parts, settings.Settings(game_window="My Game")

    class Runner:
        closes = True

        def event(self, kind, data):
            pass

        def finish(self):
            pass

        def run(self):
            pass

    def builder(p, commands, handover, key, talk_down, talk_up):
        seen["follow"] = getattr(p, "follow", None)
        return Runner()

    def run(p, cfg, system, timer, handover, on_event, commands=None, latency=None):
        return "round_done"

    entry.main([], build_fn=build, listen_key=lambda n, cb: None, listen_stop=lambda cb: None, run=run, say=lambda s: None,
               overlay_builder=builder)
    assert seen["follow"] is not None and seen["follow"]() == (10, 20, 810, 620)
    assert threading.active_count() >= 1
