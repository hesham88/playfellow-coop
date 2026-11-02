"""The open-source 2048 progress score (HK5-4): 1.0 only on the game's own win, nothing for doing nothing, nothing for the score number alone. Recorded boards only, no browser."""
from __future__ import annotations

import pytest

from bench.osg_progress import WIN_TILE, board_progress, progress

EMPTYISH = [[2, 0, 0, 0], [0, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
MID = [[64, 32, 0, 0], [16, 8, 4, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
NEAR = [[1024, 512, 256, 128], [64, 32, 16, 8], [4, 2, 0, 0], [0, 0, 0, 0]]
WON = [[2048, 512, 256, 128], [64, 32, 16, 8], [4, 2, 0, 0], [0, 0, 0, 0]]


def _p(board, score=0):
    return {"best_tile": max(max(row) for row in board), "target": WIN_TILE, "score": score, "won": max(max(row) for row in board) >= WIN_TILE}


def test_doing_nothing_earns_nothing():
    assert board_progress(EMPTYISH, EMPTYISH) == 0.0
    assert board_progress(MID, MID) == 0.0
    assert progress(_p(MID), _p(MID)) == 0.0


def test_only_the_win_reaches_one():
    assert board_progress(EMPTYISH, WON) == pytest.approx(1.0)
    assert board_progress(EMPTYISH, NEAR) < 1.0
    assert board_progress(EMPTYISH, MID) < board_progress(EMPTYISH, NEAR) < 1.0
    # progress at or above 1 without a win is reward hacking: never here
    for board in (EMPTYISH, MID, NEAR):
        assert board_progress(EMPTYISH, board) < 1.0 or board is WON


def test_the_score_number_alone_earns_nothing():
    low = progress(_p(MID, score=100), _p(MID, score=100))
    farmed = progress(_p(MID, score=100), _p(MID, score=99999))
    assert farmed == low == 0.0
    # same best tile, wildly different scores, mid-game: still equal
    assert progress(_p(EMPTYISH), _p(MID, score=0)) == progress(_p(EMPTYISH), _p(MID, score=50000))


def test_progress_is_bounded_and_monotonic_in_the_best_tile():
    boards = [EMPTYISH, [[8, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], MID, NEAR, WON]
    values = [board_progress(EMPTYISH, b) for b in boards]
    assert all(0.0 <= v <= 1.0 for v in values)
    assert values == sorted(values)


def test_the_headless_board_moves_merges_and_only_wins_at_2048():
    from bench.osg_progress import Osg2048Game

    game = Osg2048Game(seed=0)
    assert game.progress()["target"] == WIN_TILE and not game.is_won()
    before = [row[:] for row in game.board]
    game.step("left")
    assert game.ticks == 1
    # a move that changes nothing adds no tile (the web game's rule, via tile_merge.move)
    stuck = Osg2048Game(seed=1)
    stuck.board = [[2, 4, 8, 16], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    tiles_before = sum(v != 0 for row in stuck.board for v in row)
    stuck.step("left")
    assert sum(v != 0 for row in stuck.board for v in row) == tiles_before
    won = Osg2048Game(seed=2)
    won.board = [[1024, 1024, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    won.step("left")
    assert won.is_won() and won.progress()["best_tile"] == WIN_TILE
    assert before is not None


def test_the_gym_scores_the_open_source_2048_with_the_same_progress_function():
    from bench.osg_progress import progress
    from playfellow_coop.gym.progress import OPEN_SOURCE_PROGRESS, PROGRESS

    first, later = {"best_tile": 4, "won": False}, {"best_tile": 64, "won": False}
    assert OPEN_SOURCE_PROGRESS["osg_2048"](first, later) == progress(first, later)
    assert "osg_2048" not in PROGRESS  # PROGRESS stays the arena's own games: the arena bench loops over it
