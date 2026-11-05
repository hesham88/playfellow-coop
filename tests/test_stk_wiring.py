"""Every skill the catalogue calls built must point at real code, and the race loop must really call the new parts."""
from pathlib import Path

import pytest

pytest.importorskip("cv2")

from playfellow_coop.games.stk.catalogue import SKILLS, WIRING  # noqa: E402

PACK = Path(__file__).resolve().parents[1] / "playfellow_coop" / "games" / "stk"


def test_every_skill_marked_built_names_its_code():
    built = {name for name, _, _, _, status in SKILLS if status.startswith("built")}
    assert built - set(WIRING) == set()


def test_the_named_code_exists():
    missing = [name for name, (file, word) in WIRING.items() if word not in (PACK / file).read_text(encoding="utf-8")]
    assert missing == []


def test_the_race_loop_calls_the_readers_and_the_rules():
    loop = (PACK / "live.py").read_text(encoding="utf-8")
    # 5 Nov: the power and place are read by PowerWatch on its own thread (inside the loop it cost 39% of the loop's time)
    for call in ("reader.read(", "read_place(", "PowerWatch(", "decide(Moment(", "dodge(bananas(", "driver.kick(", "hands.clear()",
                 "driver.begin_race(", "learn_lap"):
        assert call in loop, call


def test_marks_are_honest_about_what_a_race_has_not_proven():
    unproven = {name for name, _, _, _, status in SKILLS if "not yet proven" in status}
    assert {"predictive drift", "power rules per item", "nitro tapping on a fading boost"} - unproven <= {"predictive drift"}
