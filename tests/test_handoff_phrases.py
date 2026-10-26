"""The hand-off phrases in English and Arabic: both languages, never mixed, and the numbers in them are counted ones."""
from __future__ import annotations

import pytest

from messages import set_language
from meta_playfellow.handover import summary, taken_line


@pytest.fixture(autouse=True)
def _back_to_english():
    yield
    set_language("english")


def _latin(text: str) -> bool:
    return any("a" <= c.lower() <= "z" for c in text)


def test_the_take_over_line_in_english_and_arabic():
    set_language("english")
    english = taken_line()
    set_language("arabic")
    arabic = taken_line()
    assert english == "It's yours. I'm letting go of every key and I'll wait."
    assert arabic != english and not _latin(arabic) and any("؀" <= c <= "ۿ" for c in arabic)


@pytest.mark.parametrize("seconds,skipped,calls", [(12.4, 7, 0), (0.4, 0, 0), (95.0, 40, 2)])
def test_the_give_back_line_carries_exactly_the_counted_numbers(seconds, skipped, calls):
    set_language("english")
    english = summary(seconds, skipped, calls)
    set_language("arabic")
    arabic = summary(seconds, skipped, calls)
    for number in (round(seconds), skipped, calls):
        assert str(number) in english and str(number) in arabic
    assert english != arabic and not _latin(arabic)


def test_the_english_line_never_contains_arabic_and_the_other_way_round():
    set_language("english")
    assert not any("؀" <= c <= "ۿ" for c in summary(3, 1, 0) + taken_line())
    set_language("arabic")
    assert not _latin(summary(3, 1, 0) + taken_line())
