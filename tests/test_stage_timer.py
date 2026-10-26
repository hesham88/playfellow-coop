"""The stage timer: real durations in the right stage, honest summaries, no invented numbers."""
import pytest

from meta_playfellow.stage_timer import NOT_MEASURED, STAGES, StageTimer


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_the_stage_list_is_the_one_list_and_has_no_change_test():
    assert STAGES == ("capture", "shrink", "mark", "encode", "request", "parse_and_check", "key_down")
    assert "change_test" not in STAGES and "first_byte" not in STAGES


def test_each_stage_records_the_time_that_passed_inside_it():
    clock = Clock()
    timer = StageTimer(clock)
    timer.begin_turn()
    with timer.stage("capture"):
        clock.now += 0.25
    with timer.stage("request"):
        clock.now += 0.75
    assert timer.end_turn() == {"capture": 0.25, "request": 0.75}


def test_an_unknown_stage_is_refused_so_a_typo_cannot_hide_a_number():
    timer = StageTimer()
    timer.begin_turn()
    with pytest.raises(ValueError):
        with timer.stage("capure"):
            pass
    with pytest.raises(ValueError):
        timer.add("first_byte", 0.1)


def test_a_duration_added_from_elsewhere_is_summed_into_its_stage():
    timer = StageTimer()
    timer.begin_turn()
    timer.add("encode", 0.1)
    timer.add("encode", 0.2)
    assert timer.end_turn() == {"encode": pytest.approx(0.3)}


def test_the_summary_uses_nearest_rank_percentiles_and_says_not_measured_for_the_rest():
    timer = StageTimer()
    for i in range(1, 101):  # 1..100 ms
        timer.begin_turn()
        timer.add("request", i / 1000)
        timer.end_turn()
    summary = timer.summary()
    assert summary["request"] == {"n": 100, "p50": 0.05, "p90": 0.09, "p95": 0.095}
    assert summary["encode"] == NOT_MEASURED and summary["capture"] == NOT_MEASURED


def test_a_stage_that_ran_in_only_some_turns_counts_only_those():
    timer = StageTimer()
    for seconds in (0.1, None, 0.3):
        timer.begin_turn()
        if seconds is not None:
            timer.add("key_down", seconds)
        timer.end_turn()
    assert timer.summary()["key_down"]["n"] == 2
