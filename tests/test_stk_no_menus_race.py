"""A hand-started race (--no-menus) must not need the model key: the player starts the race, the minimap driver drives it."""
from pathlib import Path

import pytest

pytest.importorskip("cv2")

from playfellow_coop.games.stk import catalogue, mission  # noqa: E402


class _FakeSession:
    def __init__(self, tmp_path: Path):
        import threading

        self.difficulty = "intermediate"
        self.no_menus = True
        self.nav = None  # no model key: menu reading is impossible
        self.out = tmp_path
        self.results: list[dict] = []
        self.lines: list[str] = []
        self.stop = threading.Event()
        self.sam_marker = None
        self.kart = "tux"

    def say(self, text: str) -> None:
        self.lines.append(text)


def test_no_menus_race_runs_without_a_model_key(tmp_path, monkeypatch):
    session = _FakeSession(tmp_path)
    monkeypatch.setattr(mission, "load_preskills", lambda: {})
    monkeypatch.setattr(catalogue, "build", lambda *a, **k: [])
    monkeypatch.setattr(catalogue, "load_notes", lambda *a, **k: {})
    monkeypatch.setattr(catalogue, "note_race", lambda *a, **k: {"spots": []})
    monkeypatch.setattr(mission, "race_seen", lambda s, track_id, icon: lambda: True)
    monkeypatch.setattr(mission, "finish_and_read", lambda s, track_id: None)
    driven = {}

    def fake_run(track_id, out, **kwargs):
        driven["track"] = track_id
        return {"results_screen": {"player_position": 3}}

    monkeypatch.setattr(mission.live, "run", fake_run)
    mission.mission_race(session, reader=None, guard=None, icon=tmp_path / "icon.png")
    assert driven.get("track") == "abyss"
    assert not any("needs the model key" in line for line in session.lines)


def test_choose_kart_walks_even_for_tux(monkeypatch):
    """The profile's last kart is not necessarily Tux: the picker must walk the cursor for Tux too, not just press Enter."""
    walked = []
    tapped = []

    class _KartSession:
        kart = "tux"

        def say(self, text):
            pass

        def tap(self, key):
            tapped.append(key)
            return True

    monkeypatch.setattr(mission, "kart_info", lambda kart: {"name": "Tux"})
    monkeypatch.setattr(mission, "kart_name_label", lambda s: "tux")

    def fake_walk(read, tap, want, say=None):
        walked.append(want)
        return True

    monkeypatch.setattr(mission, "kart_walk", fake_walk)
    assert mission.choose_kart(_KartSession()) is True
    assert walked == ["Tux"]
    assert tapped == ["enter"]


def test_menus_race_still_stops_without_a_model_key(tmp_path, monkeypatch):
    session = _FakeSession(tmp_path)
    session.no_menus = False
    monkeypatch.setattr(mission, "load_preskills", lambda: {})
    monkeypatch.setattr(catalogue, "build", lambda *a, **k: [])
    monkeypatch.setattr(mission, "race_seen", lambda s, track_id, icon: lambda: False)
    mission.mission_race(session, reader=None, guard=None, icon=tmp_path / "icon.png")
    assert any("needs the model key" in line for line in session.lines)
