"""The widget's commands: typed or spoken words do what they say, and the bar always has a status (never a black box)."""
import pytest

from playfellow_coop.games.stk import widget


@pytest.fixture()
def files(tmp_path, monkeypatch):
    for name in ("STOP", "HANDOVER", "STATUS", "COMMANDS"):
        monkeypatch.setattr(widget, name, tmp_path / name)
    return tmp_path


def test_stop_and_go(files):
    assert "stopping everything" in widget.command("stop")
    assert widget.STOP.exists()
    assert "I have the controls again" in widget.command("go")
    assert not widget.STOP.exists()


def test_wait_hands_over_and_go_takes_back(files):
    assert "You have the controls" in widget.command("wait")
    assert widget.HANDOVER.exists()
    assert "waiting for F9" in widget.status_text()
    widget.command("take it back")
    assert not widget.HANDOVER.exists()


def test_arabic_hand_over_words(files):
    widget.command("خدها")
    assert widget.HANDOVER.exists()


def test_anything_else_is_noted_with_the_current_status(files):
    widget.set_status("waiting for the race to load")
    reply = widget.command("go faster on the straights")
    assert "Noted" in reply and "waiting for the race to load" in reply
    assert "go faster" in widget.COMMANDS.read_text(encoding="utf-8")


def test_never_silent(files):
    assert widget.status_text()  # even with no status written there is something to say


def test_short_racing_commands_go_straight_to_the_driver(files, tmp_path, monkeypatch):
    monkeypatch.setattr(widget, "NUDGE", tmp_path / "nudge.txt")
    assert "steering left" in widget.command("left!")
    assert "nitro now" in widget.command("nitro")
    assert "firing" in widget.command("shoot now")
    assert "drifting" in widget.command("drift")
    lines = widget.NUDGE.read_text(encoding="utf-8").split()
    assert lines[1::2] == ["left", "nitro", "fire", "drift"]
    assert widget.driving_command("please take the left side when the road gets narrow ahead") is None  # a sentence: brain
