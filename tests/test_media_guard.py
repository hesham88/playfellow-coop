"""No media from three named outside games may sit anywhere in this repo, in any folder, at any depth.

The names are matched in the file name only, case-insensitively, across image, video and audio files.
A hit fails the suite; the planted-file test below proves the scan really catches one.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANNED_NAMES = ("rayman", "xonotic", "unvanquished")
MEDIA_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico", ".tif", ".tiff", ".avif",
                            ".mp4", ".mov", ".webm", ".avi", ".mkv", ".wmv", ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"})


def banned_media_files(root: Path) -> list[str]:
    """Every image, video or audio file under `root` whose file name carries a banned name (the .git store is not repo content)."""
    found = []
    for path in Path(root).rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        name = path.name.lower()
        if path.suffix.lower() in MEDIA_SUFFIXES and any(banned in name for banned in BANNED_NAMES):
            found.append(str(path))
    return sorted(found)


def test_no_named_game_media_anywhere_in_the_repo():
    assert banned_media_files(ROOT) == []


def test_a_planted_file_is_caught_wherever_it_hides(tmp_path):
    keep = tmp_path / "art" / "fello-smile.jpg"
    keep.parent.mkdir()
    keep.write_bytes(b"plain")
    planted = tmp_path / "deep" / "nested" / "Rayman-planted.PNG"
    (tmp_path / "deep").mkdir()
    planted.parent.mkdir()
    planted.write_bytes(b"planted")
    clip = tmp_path / "clip" / "xonotic-clip.webm"
    clip.parent.mkdir()
    clip.write_bytes(b"planted")
    song = tmp_path / "unvanquished-theme.ogg"
    song.write_bytes(b"planted")
    found = banned_media_files(tmp_path)
    assert found == sorted([str(planted), str(clip), str(song)])
