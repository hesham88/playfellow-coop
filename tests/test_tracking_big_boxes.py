"""A segmentation box that covers much of the picture (a background, a big platform) is never tracked by template matching: matching it
would need gigabytes of memory on a full-HD frame. Such a box is left to SAM, and the picture is asked again when needed."""
from __future__ import annotations

import numpy as np

from playfellow_coop.tracking import Tracker


def test_a_box_over_a_large_share_of_the_frame_is_not_tracked_and_small_ones_still_are():
    frame = np.random.default_rng(0).integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
    tracker = Tracker()
    tracker.anchor(frame, [("hazard", (0, 0, 1700, 900)), ("me", (900, 500, 960, 580))])
    assert [t.kind for t in tracker.tracks] == ["me"]
    tracker.update(frame)  # must not try to allocate a huge array
    assert tracker.tracks[0].kind == "me"


def test_when_only_big_boxes_were_found_the_next_picture_goes_back_to_sam():
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    tracker = Tracker()
    tracker.anchor(frame, [("door", (100, 100, 1500, 1000))])
    assert tracker.tracks == [] and tracker.needs_sam()
