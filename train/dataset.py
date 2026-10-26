"""T-1: the training data for the small helper model, made only from our own game's exact state and hand-written phrases.

  python -m train.dataset --out DIR [--train 5000] [--heldout 500] [--images]

Each row is one marked frame of the Practice Arena, one spoken or typed command (English or Arabic), and the one correct plan: a short JSON
reply that names only keys on the controls card. The correct plan is the scripted baseline, a search over the game's OWN state. It is a
teacher for training labels ONLY and is never shown as the buddy playing.

The data rule (checked on every row, and again on the finished file): no row holds the output of any model, from Meta or from anyone else.
Every row names where each part came from: the frame and its marks from the game's state, the plan from the scripted baseline, the command
from phrases we wrote ourselves. The Arabic phrases are ours and are marked NOT yet checked by a native speaker until the owner has checked
them. A held-out part (other levels AND other phrases) is never trained on; it is frozen by a hash in the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import deque
from pathlib import Path

from grounding import label_marks, legend, mark_from_box
from practice_arena.game import MOVES, ArenaGame

from playfellow_coop.sam_eval import arena_truth, tile_box

SCHEMA = "pf-train/1"
ALLOWED = ("UP", "DOWN", "LEFT", "RIGHT", "WAIT")  # the Practice Arena's controls card; a test compares this with the card itself
MAX_STEPS = 3  # keys in one plan: short enough to be checked step by step
INTENTS = ("coins", "key", "door")
KEYS = {"UP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right"}
DELTAS = {name: MOVES[key] for name, key in KEYS.items()}

# Where each part of a row comes from: the ONLY values a row may carry. Anything else (a model, an outside file) is refused.
PROVENANCE = {"frame": "game state", "plan": "scripted baseline (teacher for labels only)", "command": "hand-written templates"}
ALLOWED_SOURCES = {"frame": {"game state"}, "plan": {PROVENANCE["plan"]}, "command": {"hand-written templates", "owner's own words"}}
# Names that must never appear anywhere in a row: the sign that a model wrote it or was quoted in it.
VENDOR_NAMES = re.compile(r"\b(muse|meta|gemini|claude|anthropic|openai|chatgpt|gpt|llama|glimmer|qwen|mistral|deepseek|copilot|bard)\b", re.I)
PERSONAL_PATH = re.compile(r"[A-Za-z]:[\\/]|/Users/|/home/")

# Phrases we wrote. Every fourth one (index 3, 7) is held out: never in the training part.
PHRASES = {
    "en": {
        "coins": ["take the coins", "collect the coins", "grab all the coins", "go and get the coins", "pick up the coins", "get me the coins",
                  "I want the coins", "start with the coins"],
        "key": ["get the key", "take the key", "go to the key", "grab the key", "pick up the key", "fetch the key", "find the key",
                "I need the key"],
        "door": ["open the door", "go to the door", "take me to the door", "head for the door", "go through the door", "reach the door",
                 "get to the door", "I want the door"],
    },
    "ar": {
        "coins": ["اجمع العملات", "خذ العملات", "التقط كل العملات", "هات العملات"],
        "key": ["خذ المفتاح", "أحضر المفتاح", "اذهب إلى المفتاح", "التقط المفتاح"],
        "door": ["افتح الباب", "اذهب إلى الباب", "اخرج من الباب", "وصّلني إلى الباب"],
    },
}
FILLERS = {"en": ["", "", "please ", "ok buddy, ", "hey, ", "quick, "], "ar": ["", "", "من فضلك ", "يا صديقي ", "بسرعة "]}
SAY = {
    "en": {"go": "Going for the nearest {thing}.", "locked": "The door is locked. I need the key first.", "have_key": "I already have the key.",
           "none": "There is nothing to go to.", "thing": {"coins": "coin", "key": "key", "door": "door"}},
    "ar": {"go": "أتجه إلى أقرب {thing}.", "locked": "الباب مغلق. أحتاج المفتاح أولًا.", "have_key": "المفتاح معي بالفعل.",
           "none": "لا يوجد شيء أذهب إليه.", "thing": {"coins": "عملة", "key": "مفتاح", "door": "باب"}},
}
THOUGHT = {"en": "The command names a target; I move toward it one square at a time.", "ar": "الأمر يحدد هدفًا؛ أتحرك نحوه مربعًا واحدًا في كل مرة."}


def is_heldout_phrase(index: int) -> bool:
    return index % 4 == 3


def is_heldout_seed(seed: int) -> bool:
    return seed % 5 == 0


# ---------------------------------------------------------------------------------------------------- the game side
def _passable(game: ArenaGame, tile: tuple[int, int]) -> bool:
    x, y = tile
    return 0 <= y < len(game.level) and 0 <= x < len(game.level[0]) and tile not in game.walls and (tile != game.door or game.has_key)


def route(game: ArenaGame, goals: set, avoid: frozenset = frozenset()):
    """(the shortest keys from ME to the nearest goal, the goal reached), ties broken by key order so it is the same every time; None if
    unreachable. Standing on a goal gives ([], that goal)."""
    start = game.player
    if start in goals:
        return [], start
    seen, queue = {start: None}, deque([start])
    while queue:
        here = queue.popleft()
        for name, (dx, dy) in DELTAS.items():
            nxt = (here[0] + dx, here[1] + dy)
            if nxt in seen or nxt in avoid or not _passable(game, nxt):
                continue
            seen[nxt] = (here, name)
            if nxt in goals:
                path, tile = [], nxt
                while seen[tile] is not None:
                    tile, step = seen[tile]
                    path.append(step)
                return path[::-1], nxt
            queue.append(nxt)
    return None


def _goals(game: ArenaGame, intent: str) -> set:
    if intent == "coins":
        return set(game.coins)
    if intent == "key":
        return {game.key} if game.key is not None else set()
    return {game.door}


def make_state(seed: int) -> tuple[ArenaGame, list[str]]:
    """A fresh Practice Arena after a seeded walk (two walks in three mostly head for a target, so keys and doors are reached too). Never a finished game."""
    rng = random.Random(seed)
    game, walk = ArenaGame(), []
    guided = seed % 3 != 0
    for _ in range(rng.randrange(0, 120)):
        goals = set(game.coins) | ({game.key} if game.key else set()) | ({game.door} if game.has_key else set())
        found = route(game, goals) if guided and rng.random() < 0.85 else None
        key = found[0][0].lower() if found and found[0] else rng.choice(list(KEYS.values()))
        game.press(key)
        if game.won:
            game = ArenaGame()
            for earlier in walk:
                game.press(earlier)
            break
        walk.append(key)
    return game, walk


def plan_for(game: ArenaGame, intent: str, language: str):
    """(the correct short reply in the command's language, the tile of the target it heads for). A locked door, a key already held or nothing to
    reach gives a plain sentence and NO keys: the honest answer to a command that cannot be done."""
    words = SAY[language]
    empty = {"thought": THOUGHT[language], "actions": []}
    if intent == "door" and not game.has_key:
        return {**empty, "say": words["locked"]}, None
    if intent == "key" and game.key is None:
        return {**empty, "say": words["have_key"]}, None
    goals = _goals(game, intent)
    found = route(game, goals, avoid=frozenset({game.key} if game.key and intent != "key" else ())) if goals else None  # the key would be taken on the way
    found = found or (route(game, goals) if goals else None)
    if found is None:
        return {**empty, "say": words["none"]}, None
    path, tile = found
    return {"thought": THOUGHT[language], "say": words["go"].format(thing=words["thing"][intent]), "actions": path[:MAX_STEPS]}, tile


# ---------------------------------------------------------------------------------------------------- the rows
def vary(text: str, language: str, rng: random.Random) -> str:
    """Filler words and, now and then, a slip like a speech-to-text typo (a dropped or a doubled letter)."""
    text = rng.choice(FILLERS[language]) + text
    if rng.random() < 0.25 and len(text) > 6:
        i = rng.randrange(2, len(text) - 2)
        if text[i] != " ":
            text = text[:i] + text[i + 1:] if rng.random() < 0.5 else text[:i] + text[i] + text[i:]
    return text.strip()


def build_row(seed: int, intent: str, language: str, phrase_index: int, split: str = "train") -> dict:
    game, walk = make_state(seed)
    command = vary(PHRASES[language][intent][phrase_index], language, random.Random(f"{seed}-{intent}-{language}-{phrase_index}"))
    truth = arena_truth(game)
    marks = label_marks([m for kind in ("reward", "hazard", "door") for m in truth[kind]], me=truth["me"][0])
    reply, tile = plan_for(game, intent, language)
    kind, tag = ("door" if intent == "door" else "reward"), None
    if tile is not None:
        want = mark_from_box(kind, tile_box(tile), game.pixel_size)
        tag = next((m.tag for m in marks if m.kind == kind and (m.x, m.y) == (want.x, want.y)), None)
    allowed = list(ALLOWED)
    return {
        "schema": SCHEMA, "id": f"{language}-{intent}-s{seed:05d}-p{phrase_index}", "split": split,
        "language": language, "intent": intent, "command": command,
        "frame": {"game": "practice_arena", "seed": seed, "walk": walk},
        "marks": [{"tag": m.tag, "kind": m.kind, "x": m.x, "y": m.y} for m in marks],
        "allowed": allowed, "prompt": legend(marks) + "\nAllowed keys: " + ", ".join(allowed) + "\nCommand: " + command,
        "completion": json.dumps(reply, ensure_ascii=False), "target_tag": tag,
        "provenance": {"frame": PROVENANCE["frame"], "plan": PROVENANCE["plan"], "command": PROVENANCE["command"],
                       "model_output": False, "models": [], "arabic_checked_by_native_speaker": False if language == "ar" else None},
    }


# ---------------------------------------------------------------------------------------------------- checking
class BadRow(ValueError):
    """A row that breaks the data rule or the format: nothing is written when one exists."""


def validate_row(row: dict) -> None:
    if not isinstance(row, dict) or row.get("schema") != SCHEMA:
        raise BadRow("not a pf-train/1 row")
    name = row.get("id", "?")
    for field in ("id", "split", "language", "intent", "command", "frame", "marks", "allowed", "prompt", "completion", "provenance"):
        if field not in row:
            raise BadRow(f"{name}: missing {field}")
    prov = row["provenance"]
    if not isinstance(prov, dict):
        raise BadRow(f"{name}: provenance is not a record")
    for part, allowed in ALLOWED_SOURCES.items():
        if prov.get(part) not in allowed:
            raise BadRow(f"{name}: provenance.{part} is {prov.get(part)!r}, not one of {sorted(allowed)}")
    if prov.get("model_output") is not False or prov.get("models") != []:
        raise BadRow(f"{name}: a row may not hold any model's output")
    if row["split"] not in ("train", "heldout") or row["language"] not in ("en", "ar") or row["intent"] not in INTENTS:
        raise BadRow(f"{name}: split, language or intent is not a known value")
    blob = json.dumps(row, ensure_ascii=False)
    if VENDOR_NAMES.search(blob):
        raise BadRow(f"{name}: names a model or a vendor")
    if PERSONAL_PATH.search(blob):
        raise BadRow(f"{name}: holds a file path")
    try:
        reply = json.loads(row["completion"])
    except ValueError:
        raise BadRow(f"{name}: the completion is not JSON") from None
    if not isinstance(reply, dict) or set(reply) != {"thought", "say", "actions"} or not isinstance(reply["actions"], list):
        raise BadRow(f"{name}: the completion is not a valid reply")
    if any(action not in ALLOWED for action in reply["actions"]) or len(reply["actions"]) > MAX_STEPS:
        raise BadRow(f"{name}: the completion uses a key off the card or too many keys")


def validate_file(path: Path | str) -> int:
    count, seen = 0, set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        validate_row(row)
        if row["id"] in seen:
            raise BadRow(f"{row['id']}: appears twice")
        seen.add(row["id"])
        count += 1
    return count


# ---------------------------------------------------------------------------------------------------- the generator
def heldout_hash(rows: list[dict]) -> str:
    """One hash over the held-out ids AND phrases, written into the manifest before any training so the set cannot be changed afterwards."""
    ids = sorted(r["id"] for r in rows if r["split"] == "heldout")
    phrases = {lang: {intent: [p for i, p in enumerate(items) if is_heldout_phrase(i)] for intent, items in by.items()} for lang, by in PHRASES.items()}
    return hashlib.sha256(json.dumps({"ids": ids, "phrases": phrases}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def generate(train: int = 5000, heldout: int = 500) -> list[dict]:
    """`train` training rows and `heldout` held-out rows, the same every time. The two parts share NOTHING: training rows use levels whose seed is
    not a multiple of 5 and phrases that are not every fourth; held-out rows use only levels that are multiples of 5 AND only the held-out phrases."""
    combos = [(language, intent) for language in ("en", "ar") for intent in INTENTS]
    rows = []
    for count, held in ((train, False), (heldout, True)):
        made, seed = 0, 0
        while made < count:
            seed += 1
            if is_heldout_seed(seed) != held:
                continue
            language, intent = combos[made % len(combos)]
            pool = [i for i in range(len(PHRASES[language][intent])) if is_heldout_phrase(i) == held]
            rows.append(build_row(seed, intent, language, pool[(seed // 5 + made) % len(pool)], "heldout" if held else "train"))
            made += 1
    return rows


def write_dataset(out: Path | str, train: int = 5000, heldout: int = 500, images: bool = False) -> dict:
    """Write train.jsonl, heldout.jsonl and manifest.json; every row is checked first and nothing is written if one fails."""
    out = Path(out)
    rows = generate(train, heldout)
    for row in rows:
        validate_row(row)
    out.mkdir(parents=True, exist_ok=True)
    for split in ("train", "heldout"):
        (out / f"{split}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows if r["split"] == split), encoding="utf-8")
    if images:
        folder = out / "frames"
        folder.mkdir(exist_ok=True)
        for row in rows:
            name = folder / f"practice_arena_s{row['frame']['seed']:05d}.png"
            if not name.exists():
                game = ArenaGame()
                for key in row["frame"]["walk"]:
                    game.press(key)
                game.render().convert("RGB").save(name)
    manifest = {
        "schema": SCHEMA, "rows": {"train": sum(r["split"] == "train" for r in rows), "heldout": sum(r["split"] == "heldout" for r in rows)},
        "heldout_sha256": heldout_hash(rows), "provenance": PROVENANCE, "model_output_rows": 0,
        "languages": sorted({r["language"] for r in rows}), "arabic_checked_by_native_speaker": False,
        "note": "The plan labels come from a scripted search over the game's own state (a teacher for labels, never the buddy's play). "
                "No row holds any model's output.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--train", type=int, default=5000)
    parser.add_argument("--heldout", type=int, default=500)
    parser.add_argument("--images", action="store_true")
    args = parser.parse_args(argv)
    manifest = write_dataset(args.out, args.train, args.heldout, args.images)
    print(f"{manifest['rows']['train']} training rows, {manifest['rows']['heldout']} held-out rows, hash {manifest['heldout_sha256'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
