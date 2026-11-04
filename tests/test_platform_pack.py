"""The platformer pack on made-up scrolling pictures: no game, no window. These prove the logic, not play in a real game."""
import numpy as np
import pytest

pytest.importorskip("cv2")

import cv2  # noqa: E402

from playfellow_coop.games.platform.bosses import BossBook, cue_of  # noqa: E402
from playfellow_coop.games.platform.runner import Keys, Runner  # noqa: E402
from playfellow_coop.games.platform.sight import camera_shift, collectibles, read_cut, small_grey  # noqa: E402
from playfellow_coop.games.platform.world import WorldMap  # noqa: E402

rng = np.random.default_rng(3)
LEVEL = cv2.GaussianBlur(rng.integers(0, 255, (360, 6400, 3), dtype=np.uint8), (9, 9), 0)


def view(x: int) -> np.ndarray:
    return LEVEL[:, x:x + 640].copy()


def test_the_cameras_motion_is_measured():
    dx, dy, conf = camera_shift(small_grey(view(100)), small_grey(view(132)))
    assert dx == pytest.approx(32 / 640, abs=0.01) and abs(dy) < 0.02 and conf > 0.1


def test_a_stopped_camera_reads_as_still():
    frame = small_grey(view(500))
    assert abs(camera_shift(frame, frame)[0]) < 0.003


def test_measuring_leaves_the_pictures_as_they_were():
    frame = small_grey(view(500))
    keep = frame.copy()
    camera_shift(frame, frame)
    assert np.array_equal(frame, keep)  # OpenCV writes its window into what it is given


def test_fade_and_new_scene_are_told_apart():
    a = small_grey(view(0))
    other = a.copy()
    other[:, :80] += 90
    other[:, 80:] -= 60
    assert read_cut(a, a, tracked=1.0).kind == "none"
    assert read_cut(a, np.zeros_like(a)).kind == "fade"
    assert read_cut(a, other, tracked=0.05).kind == "new_scene"
    assert read_cut(a, other, tracked=0.9).kind == "none"  # the camera followed it: scrolling


def test_yellow_pickups_are_found_nearest_the_middle_first():
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.circle(frame, (340, 170), 7, (0, 230, 255), -1)
    cv2.circle(frame, (60, 40), 7, (0, 230, 255), -1)
    found = collectibles(frame)
    assert len(found) == 2 and found[0][0] == pytest.approx(0.53, abs=0.02)


def drive(runner, frames):
    return [runner.step(f) for f in frames]


def test_it_runs_forward_and_tracks_how_far():
    runner = Runner(Keys(sprint="a"))
    held = drive(runner, [view(x) for x in range(0, 900, 30)])
    assert all("right" in k or not k for k in held[1:]) and any("a" in k for k in held)
    assert runner.world.furthest > 1.0
    assert sum("space" in k for k in held) == 0 or runner.log


def test_blocked_it_jumps_then_jumps_higher_then_backs_off_and_remembers_the_wall():
    runner = Runner(Keys())
    wall = view(800)
    held = drive(runner, [wall] * 40)
    assert any("space" in k for k in held)
    assert any("left" in k for k in held)
    assert runner.world.blocked and runner.world.blocked[0].reason == "too_high"


def test_a_fade_lets_go_of_everything_and_counts_one_death():
    runner = Runner(Keys())
    drive(runner, [view(x) for x in range(0, 200, 30)])
    black = np.zeros((360, 640, 3), dtype=np.uint8)
    held = drive(runner, [black] * 5)
    assert all(k == set() for k in held) and runner.deaths == 1


def test_the_map_keeps_rooms_and_finds_the_way_back():
    w = WorldMap()
    w.move(1.0, 0)
    first = w.room
    w.note_blocked("too_high")
    second = w.new_room()
    third = w.new_room()
    assert w.route(third, first) == [third, second, first]


def test_a_new_ability_offers_the_walls_it_may_open():
    w = WorldMap()
    w.move(1.0, 0)
    w.note_blocked("too_high")
    w.new_room()
    w.move(1.0, 0)
    w.note_blocked("door")
    assert [b.reason for b in w.learn_ability("double_jump")] == ["too_high"]
    assert {b.reason for b in w.learn_ability("key")} == {"too_high", "door"}


def test_a_boss_is_learned_across_attempts():
    book = BossBook()
    cue = (3, 4)
    for dodge in ("jump", "back", "forward"):
        assert book.choose(cue) == dodge
        book.record(cue, dodge, was_hit=dodge != "back")
    assert book.choose(cue) == "stay"  # still untried
    book.record(cue, "stay", was_hit=True)
    assert book.choose(cue) == "back"


def test_an_opening_is_one_that_was_not_punished():
    book = BossBook()
    assert book.attack_now((1,)) is False
    book.record_opening((1,), punished=False)
    assert book.attack_now((1,)) is True
    book.record_opening((1,), punished=True)
    assert book.attack_now((1,)) is False


def test_the_same_change_gives_the_same_cue():
    a, b = np.zeros((90, 160), np.float32), np.zeros((90, 160), np.float32)
    b[10:30, 100:140] = 200
    assert cue_of(a, b) == cue_of(a, b) and cue_of(a, b) != cue_of(a, np.flipud(b))


def test_every_built_skill_names_real_code():
    from pathlib import Path

    from playfellow_coop.games.platform.catalogue import SKILLS, WIRING

    pack = Path(__file__).resolve().parents[1] / "playfellow_coop" / "games" / "platform"
    assert {n for n, _, _, s in SKILLS if s.startswith("built")} - set(WIRING) == set()
    assert [n for n, (f, w) in WIRING.items() if w not in (pack / f).read_text(encoding="utf-8")] == []
