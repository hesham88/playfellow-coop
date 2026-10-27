"""--log: the session can write a raw log (pf-session-log/1) for the replay recorder. Off by default; it holds only the named fields.

Three things are tested: the session's new events change nothing about play; the log holds no key, header, picture, path, user name or
player's words; and a log written here is what the recorder accepts (real only when the run was real)."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

from playfellow_coop import __main__ as entry
from playfellow_coop import muse_brain, sam_marks, session_log
from playfellow_coop.budget import DailyBudget
from playfellow_coop.fakes import FakeSam
from playfellow_coop.sam_marks import DEFAULT_PROMPTS, SamMarker
from playfellow_coop.stage_timer import StageTimer
from playfellow_coop.voice import CommandQueue
from practice_arena.game import ArenaGame
from tests.test_session_and_handover import MOVE, Brain, make, session
from tests.test_main import Parts

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import record_replay as rr  # noqa: E402

SAYING = json.dumps({"thought": "THOUGHT-SECRET", "say": "On my way.", "actions": [MOVE]})


class Talker(Brain):
    def ask(self, system, text, images):
        self.calls += 1
        return SAYING


def one_turn_events(parts, cfg, logging=True):
    parts.session_log_on = logging  # what main sets when --log is given
    seen = []
    parts.safety.start()
    timer = StageTimer()
    timer.begin_turn()
    session.take_turn(parts, cfg, "system", timer, on_event=lambda kind, data: seen.append((kind, data)))
    timer.end_turn()
    return seen


def with_sam(parts, tmp_path, monkeypatch, fake):
    game = ArenaGame()
    monkeypatch.setitem(sam_marks.ENDPOINTS, "sam", fake.url)
    parts.marker = SamMarker("k", budget=DailyBudget(tmp_path / "b.json", cap_usd=5, max_calls=100))
    parts.screen.grab = lambda box: game.render()


# ---- the session's events --------------------------------------------------------------------------------------------
def test_a_marked_turn_tells_on_event_the_marks_and_the_buddys_line_before_the_actions(tmp_path, monkeypatch):
    with FakeSam(ArenaGame(), DEFAULT_PROMPTS) as fake:
        parts, cfg = make(Talker())
        with_sam(parts, tmp_path, monkeypatch, fake)
        seen = one_turn_events(parts, cfg)
        parts.marker.close()
    kinds = [kind for kind, _ in seen]
    assert kinds.index("marks") < kinds.index("buddy_line") < kinds.index("actions")
    marks = dict(seen)["marks"]
    assert marks and all(set(m) == {"tag", "kind", "x", "y"} for m in marks)
    assert dict(seen)["buddy_line"] == "On my way." and dict(seen)["actions"] == [MOVE]


def test_without_marks_there_is_no_marks_event_and_play_is_the_same():
    parts, cfg = make(Talker())
    seen = one_turn_events(parts, cfg, logging=True)
    assert "marks" not in [kind for kind, _ in seen]
    assert parts.hands.pressed == [MOVE]
    assert [kind for kind, _ in seen if kind not in ("buddy_line",)] == ["thought", "actions"]  # exactly the events it had before


def test_without_the_log_on_event_never_receives_the_two_new_kinds_even_with_marks(tmp_path, monkeypatch):
    with FakeSam(ArenaGame(), DEFAULT_PROMPTS) as fake:
        parts, cfg = make(Talker())
        with_sam(parts, tmp_path, monkeypatch, fake)
        seen = one_turn_events(parts, cfg, logging=False)
        parts.marker.close()
    assert [kind for kind, _ in seen] == ["thought", "actions"]  # exactly the events it had before
    plain, plain_cfg = make(Talker())
    assert [kind for kind, _ in one_turn_events(plain, plain_cfg, logging=False)] == ["thought", "actions"]
    assert not hasattr(make(Talker())[0], "session_log_on")  # nothing sets the flag by itself


def test_a_session_without_a_log_presses_the_same_keys_and_writes_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    parts, cfg = make(Talker())
    session.play_session(parts, cfg, "system", StageTimer(), max_turns=2, wait=lambda s: False)
    assert parts.hands.pressed == [MOVE, MOVE] and list(tmp_path.iterdir()) == []


# ---- the writer -----------------------------------------------------------------------------------------------------
def head(**changes):
    base = {"brain": "muse", "model": "muse-spark", "marks": "sam", "marks_endpoint": rr.PINNED_MARKS_ENDPOINT, "fake_server": False,
            "commit": "abcdef0123", "recorded": "2026-10-28", "level": "garden"}
    base.update(changes)
    return base


def lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def test_the_log_is_a_header_then_one_line_per_turn_with_only_the_named_fields(tmp_path):
    path = tmp_path / "s.jsonl"
    log = session_log.SessionLog(path, head())
    log("marks", [{"tag": "R1", "kind": "reward", "x": 10, "y": 20}])
    log("thought", "THOUGHT-SECRET")
    log("buddy_line", "On my way.")
    log("actions", ["up"])
    log("status", "STATUS-SECRET")
    log("actions", ["down"])  # a turn with no marks and no line
    log.close()
    got = lines(path)
    assert got[0] == {"type": "header", "schema": "pf-session-log/1", **head()}
    assert got[1] == {"type": "turn", "say": "On my way.", "marks": [{"tag": "R1", "kind": "reward", "x": 10, "y": 20}], "actions": ["up"]}
    assert got[2] == {"type": "turn", "say": "", "marks": [], "actions": ["down"]}  # nothing carries over from the turn before
    assert "SECRET" not in path.read_text(encoding="utf-8")


def test_the_log_never_overwrites_a_file_and_closes_cleanly(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("mine", encoding="utf-8")
    with pytest.raises(FileExistsError):
        session_log.SessionLog(path, head())
    assert path.read_text(encoding="utf-8") == "mine"


def test_a_spoken_line_with_a_path_an_address_or_the_user_name_is_not_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(session_log.getpass, "getuser", lambda: "Quentin")
    path = tmp_path / "s.jsonl"
    log = session_log.SessionLog(path, head())
    for text in ("see " + "C:" + "\\Users\\q\\x", "mail a" + "@b.com", "Quentin is here", "sk-" + "a1" * 15, "Going up."):
        log("buddy_line", text)
        log("actions", ["up"])
    log.close()
    assert [t["say"] for t in lines(path)[1:]] == ["", "", "", "", "Going up."]


def test_a_whole_session_logs_no_player_words_no_key_no_picture_and_no_path(tmp_path, monkeypatch):
    monkeypatch.setattr(session_log.getpass, "getuser", lambda: "Quentin")
    secret = "my mail is q" + "@example.com and my key is sk-" + "z9" * 15
    q = CommandQueue()
    q.put(secret)
    path = tmp_path / "private-folder" / "s.jsonl"
    path.parent.mkdir()
    parts, cfg = make(Talker())
    parts.session_log_on = True
    log = session_log.SessionLog(path, head())
    session.play_session(parts, cfg, "system", StageTimer(), on_event=log, commands=q, max_turns=2, wait=lambda s: False)
    log.close()
    text = path.read_text(encoding="utf-8")
    for needle in ("example", "sk-", "my mail", "private-folder", str(tmp_path), "THOUGHT", "Quentin", "PNG", "base64", "Authorization"):
        assert needle not in text
    assert len(lines(path)) == 3 and lines(path)[1]["say"] == "On my way."


# ---- the header -----------------------------------------------------------------------------------------------------
def plan(**changes):
    base = {"path": "unused", "brain": "muse", "model": "muse-spark", "level": "garden"}
    base.update(changes)
    return base


def parts_with(marks="sam"):
    parts = Parts()
    parts.marks_source = marks
    return parts


def test_a_real_looking_setup_makes_a_header_the_recorder_accepts_as_real(monkeypatch):
    monkeypatch.setattr(session_log, "git_commit", lambda: "abcdef0123")
    header = session_log.make_header(parts_with(), plan())
    assert header["fake_server"] is False and header["marks_endpoint"] == rr.PINNED_MARKS_ENDPOINT
    assert header["recorded"] == date.today().isoformat() and header["commit"] == "abcdef0123" and header["level"] == "garden"
    recording = rr.build(({"type": "header", "schema": "pf-session-log/1", **header}, [{"type": "turn", "say": "", "marks": [], "actions": ["up"]}]))
    assert recording["source"]["kind"] == "real"


@pytest.mark.parametrize("how", ["sam_endpoint", "muse_endpoint", "fake_sam"])
def test_any_address_that_is_not_the_pinned_one_makes_fake_server_true(monkeypatch, how):
    monkeypatch.setattr(session_log, "git_commit", lambda: "abcdef0123")
    parts = parts_with()
    if how == "sam_endpoint":
        monkeypatch.setitem(sam_marks.ENDPOINTS, "sam", "http://127.0.0.1:9999")
    elif how == "muse_endpoint":
        monkeypatch.setitem(muse_brain.ENDPOINTS, "muse", "http://127.0.0.1:9999")
    else:
        parts.fake_sam = object()  # the --marks fake server
    header = session_log.make_header(parts, plan())
    assert header["fake_server"] is True
    with pytest.raises(rr.Refused):
        rr.build(({"type": "header", "schema": "pf-session-log/1", **header}, [{"type": "turn", "say": "", "marks": [], "actions": ["up"]}]))


def test_the_builtin_brain_and_fake_marks_are_logged_as_what_they_are(monkeypatch):
    monkeypatch.setattr(session_log, "git_commit", lambda: "abcdef0123")
    header = session_log.make_header(parts_with("fake"), plan(brain="builtin", model=None))
    assert header["brain"] == "builtin" and header["marks"] == "fake"
    with pytest.raises(rr.Refused):
        rr.build(({"type": "header", "schema": "pf-session-log/1", **header}, [{"type": "turn", "say": "", "marks": [], "actions": ["up"]}]))


def test_a_model_that_looks_like_a_path_and_a_missing_commit_are_left_out_not_guessed(monkeypatch):
    monkeypatch.setattr(session_log, "git_commit", lambda: None)
    header = session_log.make_header(parts_with(), plan(brain="local-open", model="C:" + "\\models\\m.gguf", level=None))
    assert "model" not in header and "commit" not in header and "level" not in header
    assert "models" not in json.dumps(header)


# ---- --log on the command line ---------------------------------------------------------------------------------------
def _builder(cfg):
    return Parts()


def test_the_log_is_off_unless_asked_for(tmp_path):
    parts, _ = entry.build([], build_parts=_builder, key_loader=lambda: None)
    assert getattr(parts, "session_log_plan", None) is None
    parts, _ = entry.build(["--log", str(tmp_path / "s.jsonl"), "--log-level", "garden"], build_parts=_builder, key_loader=lambda: None)
    assert parts.session_log_plan == {"path": tmp_path / "s.jsonl", "brain": "builtin", "model": "builtin", "level": "garden"}


def test_main_writes_the_log_only_when_there_is_a_plan_and_closes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(session_log, "git_commit", lambda: "abcdef0123")
    path = tmp_path / "s.jsonl"

    def build(argv):
        import settings

        parts = Parts()
        parts.marks_source = "off"
        parts.session_log_plan = plan(path=path, brain="builtin", model="builtin")
        return parts, settings.Settings()

    def run(p, cfg, system, timer, handover, on_event, commands=None, latency=None):
        on_event("buddy_line", "Hi.")
        on_event("actions", ["up"])
        return "round_done"

    assert entry.main([], build_fn=build, listen_key=lambda *a: None, listen_stop=lambda cb: None, run=run, say=lambda *a: None) == 0
    got = lines(path)
    assert got[0]["brain"] == "builtin" and got[1]["actions"] == ["up"] and got[1]["say"] == "Hi."


def test_main_refuses_to_overwrite_an_existing_log_and_says_so(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("mine", encoding="utf-8")
    said = []

    def build(argv):
        import settings

        parts = Parts()
        parts.marks_source = "off"
        parts.session_log_plan = plan(path=path)
        return parts, settings.Settings()

    def run(*a, **k):
        raise AssertionError("the session must not start")

    assert entry.main([], build_fn=build, listen_key=lambda *a: None, listen_stop=lambda cb: None, run=run, say=said.append) == 2
    assert path.read_text(encoding="utf-8") == "mine" and any("already exists" in line for line in said)


# ---- where the log goes ------------------------------------------------------------------------------------------------
def test_a_bare_file_name_goes_under_session_logs_and_a_path_is_kept(tmp_path):
    assert session_log.resolve_log_path("s.jsonl") == Path("session-logs") / "s.jsonl"
    assert session_log.resolve_log_path(Path("s.jsonl")) == Path("session-logs") / "s.jsonl"
    assert session_log.resolve_log_path(tmp_path / "s.jsonl") == tmp_path / "s.jsonl"
    assert session_log.resolve_log_path("mine/s.jsonl") == Path("mine") / "s.jsonl"


def test_the_default_folder_is_created_when_missing_and_no_other_folder_is(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session_log.SessionLog(session_log.resolve_log_path("s.jsonl"), head()).close()
    assert (tmp_path / "session-logs" / "s.jsonl").exists()
    with pytest.raises(FileNotFoundError):
        session_log.SessionLog(tmp_path / "nowhere" / "s.jsonl", head())  # only the default folder is made for you


def test_build_puts_a_bare_log_name_under_session_logs():
    parts, _ = entry.build(["--log", "run1.jsonl"], build_parts=_builder, key_loader=lambda: None)
    assert parts.session_log_plan["path"] == Path("session-logs") / "run1.jsonl"


def test_a_session_log_is_never_committed():
    root = Path(__file__).resolve().parents[1]
    assert "session-logs/" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    import subprocess

    done = subprocess.run(["git", "check-ignore", "-q", "session-logs/run1.jsonl"], cwd=root)
    assert done.returncode == 0


def test_main_turns_the_events_on_only_when_there_is_a_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(session_log, "git_commit", lambda: "abcdef0123")
    flags = []

    def make_build(with_plan):
        def build(argv):
            import settings

            parts = Parts()
            parts.marks_source = "off"
            if with_plan:
                parts.session_log_plan = plan(path=tmp_path / "s.jsonl", brain="builtin", model="builtin")
            return parts, settings.Settings()

        return build

    def run(p, cfg, system, timer, handover, on_event, commands=None, latency=None):
        flags.append(getattr(p, "session_log_on", False))
        return "round_done"

    for with_plan in (False, True):
        entry.main([], build_fn=make_build(with_plan), listen_key=lambda *a: None, listen_stop=lambda cb: None, run=run, say=lambda *a: None)
    assert flags == [False, True]


# ---- the owner's checklist ---------------------------------------------------------------------------------------------
def test_the_owner_checklist_says_who_looks_at_a_real_recording_before_it_ships_and_gives_the_two_commands():
    text = (Path(__file__).resolve().parents[1] / "docs" / "owner-live-checks.md").read_text(encoding="utf-8")
    assert "ONLY after the architect has looked at the file" in text
    assert "--brain muse --log run1.jsonl --log-level garden" in text
    assert "python demo/record_replay.py session-logs/run1.jsonl" in text


# ---- the PC's own name ---------------------------------------------------------------------------------------------------
def test_a_line_with_this_pcs_host_name_is_dropped(monkeypatch):
    monkeypatch.setattr(session_log.socket, "gethostname", lambda: "ZED-PC")  # a made-up name: the real one is never in the repo
    words = session_log.private_words()
    assert "zed-pc" in words
    assert session_log.clean_line("Heading for the door at Zed-PC now", words) == ""
    assert session_log.clean_line("Heading for the door now.", words) == "Heading for the door now."
