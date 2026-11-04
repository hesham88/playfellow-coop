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


def test_a_refused_capture_setting_does_not_kill_a_widget_meant_to_be_recorded():
    """Owner 4 Nov: moving the opacity slider re-applied the style, Windows refused the display affinity and the widget died. When
    the widget is shown in recordings nothing has to be hidden, so a refusal is harmless; hiding from capture must still raise."""
    import pytest

    from playfellow_coop.overlay import winstyle

    class Refusing:
        def GetWindowLongPtrW(self, hwnd, index):
            return 0

        def SetWindowLongPtrW(self, hwnd, index, value):
            return 0

        def SetWindowPos(self, *args):
            return 1

        def SetWindowDisplayAffinity(self, hwnd, affinity):
            return 0

    assert winstyle.apply_overlay_style(1, show_in_recordings=True, user32=Refusing()).excluded_from_capture is False
    with pytest.raises(OSError):
        winstyle.apply_overlay_style(1, show_in_recordings=False, user32=Refusing())


def test_a_doubled_word_from_a_clipped_start_is_said_once():
    """Real lines heard on 3 and 4 Nov."""
    from playfellow_coop.games.stk.widget import clean_heard

    assert clean_heard("dodo a new mission.") == "do a new mission."
    assert clean_heard("Wewe are uh in the menu") == "We are uh in the menu"
    assert clean_heard("openopen single player.") == "open single player."
    assert clean_heard("collectcollect the blue nitro also.") == "collect the blue nitro also."


def test_real_words_are_left_alone():
    from playfellow_coop.games.stk.widget import clean_heard

    assert clean_heard("haha restart the mission with the banana") == "haha restart the mission with the banana"
    assert clean_heard("stop") == "stop"


def test_a_quiet_recording_is_lifted_without_clipping_and_silence_stays():
    import numpy as np

    from playfellow_coop.games.stk.widget import level_up

    quiet = (np.sin(np.linspace(0, 50, 2400)) * 2000).astype(np.int16)
    loud = np.frombuffer(level_up(quiet.tobytes()), dtype=np.int16)
    assert 15000 < np.abs(loud.astype(int)).max() <= 20001
    hush = np.full(100, 5, dtype=np.int16).tobytes()
    assert level_up(hush) == hush


def test_every_game_gives_the_recogniser_its_own_words():
    from playfellow_coop.games.stk.widget import GAME_WORDS

    assert "bounty" in GAME_WORDS["Endless Sky"] and "nitro" in GAME_WORDS["SuperTuxKart"]


def test_the_mic_says_ready_only_once_audio_flows():
    from playfellow_coop.microphone import Microphone

    class Stream:
        def __init__(self, **kw):
            self.callback = kw["callback"]

        def start(self):
            self.callback(b"12", 1, None, None)

        def stop(self):
            pass

        def close(self):
            pass

    class Device:
        RawInputStream = Stream

    mic = Microphone(Device)
    mic.start()
    assert not mic._frames.empty()
    mic.stop()


def test_each_game_has_its_own_keys_for_the_chat_brain():
    """4 Nov: on a game whose start screen says 'Press SPACE' the widget offered only arrows, enter and esc, the SuperTuxKart list."""
    from playfellow_coop.games.stk.widget import GAME_KEYS

    assert "space" in GAME_KEYS["Endless Sky"] and "j" in GAME_KEYS["Endless Sky"]
    assert "Xonotic" not in GAME_KEYS  # not part of the public submission
    assert "space" not in GAME_KEYS["SuperTuxKart"]


def test_the_model_cannot_press_a_key_off_the_list():
    from playfellow_coop.games.stk.widget import allowed_presses

    assert allowed_presses(["Enter", "up", "delete", "f4"]) == ["enter", "up"]
    assert allowed_presses(None) == []
