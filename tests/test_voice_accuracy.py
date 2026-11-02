"""The voice accuracy harness scores what would reach the buddy, not only the word error rate. Fake transcriber: no network."""
from __future__ import annotations

import io
import shutil
import wave
from pathlib import Path

import pytest

from bench import voice_accuracy as va

CLIPS_MD = Path(r"F:\PlayFellow\data\voice-clips-2026-11-02\RECORD-THESE.md")


def test_the_recording_list_has_twenty_lines_in_three_groups():
    if not CLIPS_MD.exists():
        pytest.skip("the recording list lives outside the repository")
    lines = va.expected_lines(CLIPS_MD)
    assert len(lines) == 20
    groups = [g for _, g in lines.values()]
    assert groups.count("english") == 7 and groups.count("arabic") == 7 and groups.count("mixed") == 6


def test_word_error_rate():
    assert va.wer("grab the coins on the left", "grab the coins on the left") == 0.0
    assert va.wer("grab the coins on the left", "grab coins on the left") == round(1 / 6, 4)
    assert va.wer("خذ العملات على اليسار", "خذ عملات على اليسار") == 0.0  # the article "ال" is not a word error


def test_a_hand_over_phrase_must_be_heard_as_exactly_that_phrase():
    assert va.command_match("Stop.", "stop")
    assert va.command_match("I've got it.", "I have got it")
    assert not va.command_match("I've got it.", "I've got a bit")
    assert va.command_match("وقف.", "وقف")


def test_a_request_heard_as_stop_is_the_worst_mistake_and_never_counts():
    assert not va.command_match("Take me to the door.", "stop")


def test_a_request_must_keep_two_thirds_of_its_meaningful_words():
    assert va.command_match("Grab the coins on the left.", "grab coins left please")
    assert not va.command_match("Grab the coins on the left.", "grab the cones")
    assert va.command_match("خذ الـ coins اللي على الـ left.", "خذ ال coins على left")


def test_run_converts_any_clip_and_scores_each_group(tmp_path):
    if shutil.which("ffmpeg") is None:
        try:
            import imageio_ffmpeg  # noqa: F401
        except ImportError:
            pytest.skip("no ffmpeg")
    (tmp_path / "RECORD-THESE.md").write_text("## English\n01. Stop.\n02. Take me to the door.\n## Arabic\n03. وقف.\n", encoding="utf-8")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * 4410)
    for n in ("01", "02", "03"):
        (tmp_path / f"{n}.wav").write_bytes(buf.getvalue())

    class Fake:
        heard = {"english": iter(["stop", "take me to the floor"]), "arabic": iter(["وقف"])}

        def transcribe(self, wav, language="english", keywords=None):
            from playfellow_coop.voice import check_wav
            check_wav(wav)  # the converted clip is what Muse Voice accepts
            return next(self.heard[language])

    out = va.run(tmp_path, Fake())
    assert [r["command_ok"] for r in out["rows"]] == [True, False, True]
    assert out["summary"]["all"]["command_match"] == 2 and out["summary"]["arabic"]["command_match_rate"] == 1.0
