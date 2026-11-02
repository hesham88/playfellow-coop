"""Update the F1 (SkillSmith, model-written skills) rows in README.md and JUDGES.md from the committed live files.

One command, no hand edits:

    python tools/update_f1_rows.py           # rewrite both files from results/skillsmith/skillsmith-*.json
    python tools/update_f1_rows.py --check   # exit 1 if either file is out of date (writes nothing)

Only live files count (`skillsmith-muse-*.json`, `skillsmith-open-*.json` written by `bench/skillsmith_run.py`
with a real brain). The sandbox proof and any fake-brain file are ignored. While no live file is committed the
rows say "pending: run after the owner's yes"; the moment one lands, the same command replaces them with the
file's own held-out wins, progress and writing cost. Rows are matched by their line prefix, so the command is
idempotent and never touches any other line.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAMES = ("maze_chase", "key_caves", "action_quest", "osg_2048")  # osg_2048: the open-source 2048, which nobody wrote a skill for
BRAINS = {"muse": "Muse Spark 1.3 writes", "open": "Muse Spark Open writes"}
PENDING_RUNG = "| 3 Model-written skills (SkillSmith, F1) | pending: run after the owner's yes | — | harness `bench/skillsmith_run.py`; offline fake round only |"
JUDGES_HEADING = "## 5. Watch a model-written skill play, no key"


def live_files(root: Path) -> dict[str, dict[str, Path]]:
    """For each brain, the newest live file that ran each game ({brain: {game: file}}), or {} while none is committed.

    Newest is by the file's own "written" time (the file name breaks ties and covers files without one), per game: a later run on one
    game never hides an earlier run on the others, and a name that sorts last is never taken for the newest."""
    folder = root / "results" / "skillsmith"
    found: dict[str, dict[str, Path]] = {}
    for brain in BRAINS:
        files = sorted(folder.glob(f"skillsmith-{brain}-*.json")) if folder.is_dir() else []
        dated = []
        for path in files:
            doc = json.loads(path.read_text(encoding="utf-8"))
            dated.append((str(doc.get("written") or ""), path.name, path, doc))
        for _written, _name, path, doc in sorted(dated, key=lambda item: (item[0], item[1])):
            for game in doc.get("games", {}):
                found.setdefault(brain, {})[game] = path  # later in time order replaces earlier
    return found


def _game_state(row: dict) -> str:
    held = row.get("held_out") or {}
    if not row.get("supported"):
        return f"not scored: {row.get('reason', 'unsupported')}"
    if not row.get("promoted"):
        return f"no skill promoted ({held.get('reason', 'refused')}); writing ${float((row.get('writing') or {}).get('cost_usd', 0)):.3f}"
    episodes = held.get("episodes") or []
    return (f"promoted; held-out {held.get('wins')} of {len(episodes)} wins, progress IQM {held.get('progress_iqm')}, "
            f"play $0; writing ${float((row.get('writing') or {}).get('cost_usd', 0)):.3f}")


def f1_rows(root: Path) -> tuple[list[str], list[str], list[str]]:
    """(README rung rows, README per-game rows, JUDGES table rows), generated only from the live files."""
    files = live_files(root)
    if not files:
        games = [f"| {g} | pending: run after the owner's yes | no file yet |" for g in GAMES]
        games[GAMES.index("action_quest")] = "| action_quest | the gym has no progress score for it yet, so it cannot be scored | no file yet |"
        return [PENDING_RUNG], games, ["| — | pending: run after the owner's yes | no live file yet |"]
    rung, games_by_name, judges = [], {}, []
    docs: dict[Path, dict] = {}
    for brain, by_game in files.items():
        rows = []
        for name, path in by_game.items():
            doc = docs.setdefault(path, json.loads(path.read_text(encoding="utf-8")))
            rows.append((name, doc["games"][name], f"results/skillsmith/{path.name}"))
        played = [row for _, row, _ in rows if (row.get("held_out") or {}).get("played")]
        episodes = [e for row in played for e in row["held_out"]["episodes"]]
        wins = sum(1 for e in episodes if e["won"])
        iqms = [row["held_out"]["progress_iqm"] for row in played if row["held_out"].get("progress_iqm") is not None]
        mean = round(sum(iqms) / len(iqms), 3) if iqms else "—"
        rels = ", ".join(f"`{rel}`" for rel in dict.fromkeys(rel for _, _, rel in rows))
        rung.append(f"| 3 Model-written skills (SkillSmith, F1), {BRAINS[brain]} | {wins} of {len(episodes)} | {mean} | {rels} |")
        for name, row, rel in rows:
            games_by_name.setdefault(name, []).append(f"{brain}: {_game_state(row)}")
            held = row.get("held_out") or {}
            saved = f"{held.get('wins')} wins, IQM {held.get('progress_iqm')}" if held.get("played") else "not played (nothing promoted)"
            judges.append(f"| {name} ({brain}) | {saved} | `{rel}` |")
    # per-game file cell: name each brain's file for that game
    games = []
    for g in GAMES:
        names = ", ".join(dict.fromkeys(f"`results/skillsmith/{by_game[g].name}`" for by_game in files.values() if g in by_game))
        games.append(f"| {g} | {'; '.join(games_by_name.get(g, ['no live run yet']))} | {names or 'no file yet'} |")
    return rung, games, judges


def update_readme(text: str, rung: list[str], games: list[str]) -> str:
    lines = text.splitlines()
    out, rung_done, games_done = [], False, set()
    for line in lines:
        if line.startswith("| 3 Model-written skills (SkillSmith, F1)"):
            if not rung_done:
                out += rung
                rung_done = True
            continue
        game = next((g for g in GAMES if line.startswith(f"| {g} |")), None)
        if game is not None and game not in games_done:
            out.append(next(r for r in games if r.startswith(f"| {game} |")))
            games_done.add(game)
            continue
        out.append(line)
    for game in GAMES:  # a game added later (osg_2048) gets its row once, right after the last game row already there
        if game not in games_done:
            last = max((i for i, line in enumerate(out) if any(line.startswith(f"| {g} |") for g in GAMES)), default=None)
            if last is not None:
                out.insert(last + 1, next(r for r in games if r.startswith(f"| {game} |")))
                games_done.add(game)
    return "\n".join(out) + "\n"


def update_judges(text: str, rows: list[str]) -> str:
    block = [JUDGES_HEADING, "",
             "One command replays the newest committed live SkillSmith file: it reloads the skill source saved inside "
             "that file, checks its fingerprint, puts it through the same static gate and sandbox, and plays it again on "
             "the file's held-out seeds. No key and no network are needed; play after writing is local.",
             "", "```", "python -m bench.skillsmith_run --replay latest", "```", "",
             "| Game (brain) | Saved held-out result | File |", "|---|---|---|", *rows, ""]
    if JUDGES_HEADING not in text:
        return text.rstrip("\n") + "\n\n" + "\n".join(block)
    head, rest = text.split(JUDGES_HEADING, 1)
    tail = rest.split("\n## ", 1)
    return head + "\n".join(block) + ("\n## " + tail[1] if len(tail) > 1 else "")


def render(root: Path) -> tuple[str, str]:
    rung, games, judges = f1_rows(root)
    readme = update_readme((root / "README.md").read_text(encoding="utf-8"), rung, games)
    judges_text = update_judges((root / "JUDGES.md").read_text(encoding="utf-8"), judges)
    return readme, judges_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 if a row is out of date")
    args = parser.parse_args(argv)
    readme, judges_text = render(ROOT)
    stale = []
    for name, new in (("README.md", readme), ("JUDGES.md", judges_text)):
        if (ROOT / name).read_text(encoding="utf-8") != new:
            stale.append(name)
            if not args.check:
                (ROOT / name).write_text(new, encoding="utf-8", newline="\n")
    if stale:
        print(("out of date: " if args.check else "updated: ") + ", ".join(stale))
        return 1 if args.check else 0
    print("F1 rows already match the committed live files" if live_files(ROOT) else "no live F1 file committed yet; rows stay pending")
    return 0


if __name__ == "__main__":
    sys.exit(main())
