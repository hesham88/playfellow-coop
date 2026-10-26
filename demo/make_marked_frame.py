"""Make the picture for the README and the video: one Practice Arena frame with numbered marks drawn on it.

OFFLINE: the marks come from a FAKE server that answers from the arena's own truth (meta_playfellow/fakes.py). The picture shows
the mark-and-label pipeline, not SAM's accuracy; the file name and the text beside it say so. When credits arrive, the same
function runs with the real marker and the file is replaced."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from practice_arena.game import ArenaGame  # noqa: E402

from meta_playfellow import sam_marks  # noqa: E402
from meta_playfellow.budget import DailyBudget  # noqa: E402
from meta_playfellow.fakes import FakeSam  # noqa: E402
from meta_playfellow.sam_marks import DEFAULT_PROMPTS, SamMarker, mark_image  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs" / "img"


def make(out: Path = OUT) -> tuple[Path, Path]:
    game = ArenaGame()
    out.mkdir(parents=True, exist_ok=True)
    with FakeSam(game, DEFAULT_PROMPTS) as fake, tempfile.TemporaryDirectory() as scratch:
        saved = dict(sam_marks.ENDPOINTS)
        sam_marks.ENDPOINTS["sam"] = fake.url
        try:
            marker = SamMarker("fake-key", budget=DailyBudget(Path(scratch) / "b.json", cap_usd=1, max_calls=100))
            marked, legend_text = mark_image(game.render(), marker)
            marker.close()
        finally:
            sam_marks.ENDPOINTS.update(saved)
    picture, words = out / "arena_marks_FAKE_SAM.png", out / "arena_marks_FAKE_SAM.txt"
    marked.save(picture)
    words.write_text("Marks drawn from a FAKE server that answers with the Practice Arena's own truth (no Meta call was made).\n"
                     "This shows the mark-and-label pipeline, not SAM's accuracy.\n\n" + legend_text + "\n", encoding="utf-8")
    return picture, words


if __name__ == "__main__":
    print(*make(), sep="\n")
