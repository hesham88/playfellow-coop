"""What the last attempts learned, in a form the next attempt can read (Algorithm Distillation in spirit, research R3 section 6.4).

Algorithm Distillation trains a model on whole learning histories so that it picks up the policy-improvement step itself. Without training, the same idea at the prompt level is: keep a
SHORT summary of each earlier episode (what was tried, what happened, the score), ordered by improvement, and show the newest ones with the best at hand, so the model can continue the
trend instead of starting over. The window is bounded by an estimated token budget; the oldest and the least informative go first.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EpisodeSummary:
    episode: int
    score: float
    tried: list[str] = field(default_factory=list)  # the approaches, in words
    learned: list[str] = field(default_factory=list)  # rules or lessons with their evidence
    failure: str = ""  # how it ended, if it did not win

    def text(self) -> str:
        parts = [f"Episode {self.episode}: score {self.score:.2f}."]
        if self.tried:
            parts.append("Tried: " + "; ".join(self.tried) + ".")
        if self.learned:
            parts.append("Learned: " + "; ".join(self.learned) + ".")
        if self.failure:
            parts.append("Ended: " + self.failure + ".")
        return " ".join(parts)


def tokens(text: str) -> int:
    """A cheap token estimate (about four characters a token)."""
    return max(1, len(text) // 4)


class ContextWindow:
    def __init__(self, max_tokens: int = 600, keep_best: int = 1):
        self.max_tokens, self.keep_best = max_tokens, keep_best
        self.history: list[EpisodeSummary] = []

    def add(self, summary: EpisodeSummary) -> None:
        self.history.append(summary)

    def trend(self) -> float:
        """Average change in score per episode over the history (positive = improving)."""
        if len(self.history) < 2:
            return 0.0
        scores = [s.score for s in self.history]
        return (scores[-1] - scores[0]) / (len(scores) - 1)

    def render(self) -> str:
        """The summaries that fit the token budget: the best episode so far (for what worked), then the most recent ones, oldest of those first so the story reads in order."""
        if not self.history:
            return ""
        best = max(self.history, key=lambda s: s.score)
        chosen = [best] if self.keep_best else []
        used = tokens(best.text()) if chosen else 0
        for summary in reversed(self.history):
            if summary in chosen:
                continue
            cost = tokens(summary.text())
            if used + cost > self.max_tokens:
                break
            chosen.append(summary)
            used += cost
        chosen.sort(key=lambda s: s.episode)
        header = f"Earlier attempts (trend {self.trend():+.2f} per episode; best was episode {best.episode}):"
        return header + "\n" + "\n".join(s.text() for s in chosen)
