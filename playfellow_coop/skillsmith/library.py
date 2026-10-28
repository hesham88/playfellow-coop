"""Where verified skills live: `<root>/.agents/skills/<game>/<name>.py`, each with a receipt, plus one `EXPERIENCE.md` of evidence-backed lessons (research R2 section 1.2).

Write-scope governance: this is the ONLY place the skill pipeline writes, and it refuses any path that would leave the skills folder (a name with a slash, a dot-dot, an absolute path). A
candidate that fails is never written. Every stored skill carries the SHA-256 of its code and of the gates it passed, and `folder_hash` hashes the whole folder, so a benchmark receipt can
say exactly which skills were present.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from playfellow_coop.skillsmith import ast_gate

NAME = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


class ScopeViolation(Exception):
    """A write outside the skills folder was refused."""


@dataclass
class Receipt:
    game: str
    name: str
    sha256: str
    gates: dict
    path: str
    created: float


class SkillLibrary:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.base = (self.root / ".agents" / "skills").resolve()

    def _path(self, game: str, name: str, suffix: str) -> Path:
        if not NAME.match(game) or not NAME.match(name):
            raise ScopeViolation(f"game and skill names are lower-case words with digits and underscores (got {game!r}, {name!r})")
        path = (self.base / game / f"{name}{suffix}").resolve()
        if self.base not in path.parents:
            raise ScopeViolation("the path leaves the skills folder")
        return path

    def add(self, game: str, name: str, code: str, verification=None) -> Receipt:
        """Store a skill. The code is checked by the AST gate again here, so nothing unchecked can enter the library by another door."""
        ok, why = ast_gate.check(code)
        if not ok:
            raise ast_gate.SkillRejected(why)
        if verification is not None and not verification.passed:
            raise ValueError("a skill that failed verification is never stored")
        target = self._path(game, name, ".py")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, encoding="utf-8", newline="\n")
        gates = {k: {"passed": g.passed, "detail": g.detail} for k, g in (verification.gates.items() if verification else [])}
        receipt = Receipt(game, name, hashlib.sha256(code.encode("utf-8")).hexdigest(), gates, str(target.relative_to(self.root)).replace("\\", "/"), time.time())
        self._path(game, name, ".json").write_text(json.dumps(receipt.__dict__, indent=1), encoding="utf-8", newline="\n")
        return receipt

    def get(self, game: str, name: str) -> str | None:
        path = self._path(game, name, ".py")
        if not path.is_file():
            return None
        code = path.read_text(encoding="utf-8")
        meta = self._path(game, name, ".json")
        if meta.is_file() and json.loads(meta.read_text(encoding="utf-8")).get("sha256") != hashlib.sha256(code.encode("utf-8")).hexdigest():
            return None  # the file changed after it was verified: it is no longer the skill that passed
        return code

    def names(self, game: str) -> list[str]:
        folder = self.base / game
        return sorted(p.stem for p in folder.glob("*.py")) if folder.is_dir() and NAME.match(game) else []

    def remove(self, game: str, name: str) -> bool:
        """Roll back: delete a skill and its receipt."""
        removed = False
        for suffix in (".py", ".json"):
            path = self._path(game, name, suffix)
            if path.is_file():
                path.unlink()
                removed = True
        return removed

    def note(self, game: str, lesson: str, evidence: str) -> None:
        """Append one lesson with the evidence behind it to EXPERIENCE.md (a lesson without evidence is not written)."""
        if not lesson.strip() or not evidence.strip():
            raise ValueError("a lesson needs its evidence")
        target = self.base / "EXPERIENCE.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"- [{game}] {lesson.strip()} (evidence: {evidence.strip()})\n")

    def experience(self, game: str | None = None) -> list[str]:
        target = self.base / "EXPERIENCE.md"
        if not target.is_file():
            return []
        lines = [l for l in target.read_text(encoding="utf-8").splitlines() if l.startswith("- [")]
        return [l for l in lines if game is None or l.startswith(f"- [{game}]")]

    def folder_hash(self) -> str:
        """SHA-256 over every file under the skills folder (names and bytes, in order): the receipt a benchmark records."""
        digest = hashlib.sha256()
        if self.base.is_dir():
            for path in sorted(self.base.rglob("*")):
                if path.is_file():
                    digest.update(str(path.relative_to(self.base)).replace("\\", "/").encode("utf-8"))
                    digest.update(path.read_bytes())
        return digest.hexdigest()
