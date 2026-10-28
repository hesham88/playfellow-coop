"""The reproducibility receipt every evaluation log carries (research R2 section 6.2): enough to repeat the run and to see exactly what help was present."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Receipt:
    game: str
    game_version: str
    seed: int
    opponents: str  # "house bots", "human", "none" ...
    model: str  # the model id as served
    effort: str  # reasoning effort
    rung: str  # the evaluation rung (evalkit.ladder)
    clock: str  # "live" or "paused"
    skills_sha256: str = ""  # SkillLibrary.folder_hash(): which local skills were present
    replay_url: str = ""
    harness_commit: str = ""
    budget_usd: float | None = None
    notes: list[str] = field(default_factory=list)

    def digest(self) -> str:
        """A stable hash of the receipt itself."""
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(receipt: Receipt) -> list[str]:
    """What a receipt is missing that makes the run unrepeatable."""
    missing = []
    if receipt.seed is None:
        missing.append("seed")
    for name in ("game", "game_version", "model", "effort", "rung", "clock"):
        if not getattr(receipt, name):
            missing.append(name)
    if receipt.rung in ("model_skills", "human_skills") and not receipt.skills_sha256:
        missing.append("skills_sha256 (a skill rung without the hash of its skills)")
    return missing
