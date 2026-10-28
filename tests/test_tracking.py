"""The tracker keeps SAM's objects between SAM calls, says when it must ask again, and keeps ids across answers by overlap."""
from __future__ import annotations

import numpy as np

from playfellow_coop.tracking import Tracker, iou


def scene(x, y, size=14, w=160, h=120, seed=0, extra=()):
    rng = np.random.default_rng(seed)
    frame = rng.integers(20, 50, (h, w)).astype(np.uint8)  # noisy floor
    frame[y:y + size, x:x + size] = np.add.outer(np.arange(size), np.arange(size)).clip(0, 255).astype(np.uint8) * 6 + 90  # a textured block
    for ex, ey in extra:
        frame[ey:ey + 10, ex:ex + 10] = 240
    return np.stack([frame] * 3, axis=2)


def test_iou_is_one_for_the_same_box_and_zero_for_apart():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0 and iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert 0.0 < iou((0, 0, 10, 10), (5, 5, 15, 15)) < 0.2


def test_a_tracked_block_is_followed_through_small_moves_without_asking_sam():
    t = Tracker()
    t.anchor(scene(40, 40), [("me", (40.0, 40.0, 54.0, 54.0))])
    assert t.needs_sam() is False
    for step in range(1, 7):
        t.update(scene(40 + step * 4, 40 + step * 2, seed=step))
        assert t.needs_sam() is False and t.tracks[0].score > 0.9
    left, top, right, bottom = t.tracks[0].box
    assert abs(left - 64) <= 1 and abs(top - 52) <= 1 and (right - left, bottom - top) == (14, 14)
    assert t.local_updates == 6


def test_a_vanished_object_makes_the_tracker_ask_sam_again():
    t = Tracker()
    t.anchor(scene(40, 40), [("me", (40.0, 40.0, 54.0, 54.0))])
    blank = scene(0, 0, size=2, seed=9)
    t.update(blank)
    t.update(blank)
    assert t.needs_sam() is True


def test_nothing_tracked_means_ask_and_an_old_track_is_refreshed_after_a_while():
    assert Tracker().needs_sam() is True
    t = Tracker(refresh_every=3)
    t.anchor(scene(40, 40), [("me", (40.0, 40.0, 54.0, 54.0))])
    for i in range(3):
        t.update(scene(40, 40, seed=i + 1))
    assert t.needs_sam() is True  # three updates without SAM confirming it


def test_ids_stay_the_same_across_separate_answers_by_overlap_and_new_things_get_new_ids():
    t = Tracker()
    t.anchor(scene(40, 40, extra=[(100, 80)]), [("me", (40.0, 40.0, 54.0, 54.0)), ("reward", (100.0, 80.0, 110.0, 90.0))])
    ids = {tr.kind: tr.id for tr in t.tracks}
    t.anchor(scene(46, 42, extra=[(100, 80)]), [("me", (46.0, 42.0, 60.0, 56.0)), ("reward", (100.0, 80.0, 110.0, 90.0)), ("reward", (10.0, 10.0, 20.0, 20.0))])
    now = [(tr.kind, tr.id) for tr in t.tracks]
    assert ("me", ids["me"]) in now and ("reward", ids["reward"]) in now
    assert len({i for _, i in now}) == 3  # the third box matched nothing and got its own id
    assert len(t.boxes("reward")) == 2 and len(t.boxes()) == 3


def test_a_flat_coloured_object_is_tracked_too():
    frame = np.full((100, 100, 3), 30, np.uint8)
    frame[40:52, 40:52] = 220
    t = Tracker()
    t.anchor(frame, [("reward", (40.0, 40.0, 52.0, 52.0))])
    moved = np.full((100, 100, 3), 30, np.uint8)
    moved[44:56, 47:59] = 220
    t.update(moved)
    assert abs(t.tracks[0].box[0] - 47) <= 1 and abs(t.tracks[0].box[1] - 44) <= 1 and t.needs_sam() is False
