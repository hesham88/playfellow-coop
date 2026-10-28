"""The calls-per-win and cost-per-win model (research R2 section 5.2, R1 section 3.4): which optimisation lever cuts what.

A failed episode still spends calls, so what matters is Calls per Win = calls per episode / win rate, and Cost per Win = cost per episode / win rate. The prices and token counts are inputs (the
research's October 2026 numbers are the defaults); every output is arithmetic you can check by hand. This module PREDICTS; a measured run replaces the prediction with a number.
"""
from __future__ import annotations

from dataclasses import dataclass

# October 2026 Muse Wonder API pricing quoted in the research, USD per million tokens
WONDER = {"input": 4.00, "cached_input": 0.20, "output": 20.00}
GLIMMER_CALL_USD = 0.00019  # modelled cost of one small-model call on a hosted GPU


@dataclass(frozen=True)
class Turn:
    prefix_tokens: int = 4000  # the stable part (system prompt, tools, skill library): cacheable
    dynamic_tokens: int = 1500  # frame tokens and HUD state: never cached
    output_tokens: int = 120


def call_cost(turn: Turn = Turn(), prices: dict = WONDER, cached: bool = False) -> float:
    """USD for one call. With a warm prefix cache the stable prefix is billed at the cached rate."""
    prefix_rate = prices["cached_input"] if cached else prices["input"]
    return (turn.prefix_tokens * prefix_rate + turn.dynamic_tokens * prices["input"] + turn.output_tokens * prices["output"]) / 1e6


@dataclass(frozen=True)
class Tier:
    name: str
    heavy_calls: float
    small_calls: float
    win_rate: float
    cached: bool = False

    def episode_cost(self, turn: Turn = Turn(), prices: dict = WONDER) -> float:
        return self.heavy_calls * call_cost(turn, prices, self.cached) + self.small_calls * GLIMMER_CALL_USD

    def per_win(self, value: float) -> float:
        return float("inf") if self.win_rate <= 0 else value / self.win_rate

    def heavy_calls_per_win(self) -> float:
        return self.per_win(self.heavy_calls)

    def total_calls_per_win(self) -> float:
        return self.per_win(self.heavy_calls + self.small_calls)

    def cost_per_win(self, turn: Turn = Turn(), prices: dict = WONDER) -> float:
        return self.per_win(self.episode_cost(turn, prices))


# the research's 60 s arena episode at 4 decisions per second (240 ticks), win rates as modelled there
TIERS = (
    Tier("0 baseline: uncached heavy model every tick", 240, 0, 0.12),
    Tier("1 streaming plan + prefix cache", 240, 0, 0.28, cached=True),
    Tier("2 semantic / action cache (68% hit)", 76, 0, 0.48, cached=True),
    Tier("3 macro-actions (chunks of 6)", 46, 0, 0.56, cached=True),
    Tier("4 speculative macro commit (small drafter + heavy actor)", 91, 240, 0.67, cached=True),
    Tier("5 hybrid: local skill + small model + sparse heavy planning", 6, 48, 0.81, cached=True),
)


def macro_calls(ticks: int, chunk: int, early_stop: float = 0.0) -> float:
    """Calls needed when one call yields `chunk` actions; `early_stop` is the average number of chunk steps lost to hazard interruptions per call."""
    per_call = max(1.0, chunk - early_stop)
    return ticks / per_call


def cache_hit_calls(calls: float, hit_rate: float) -> float:
    """Calls that still reach the model when a state-action cache answers `hit_rate` of them."""
    return calls * (1.0 - hit_rate)


def table(turn: Turn = Turn(), prices: dict = WONDER) -> str:
    lines = ["| tier | heavy calls/ep | small calls/ep | win rate | cost/episode | heavy calls/win | total calls/win | cost/win |", "|---|---|---|---|---|---|---|---|"]
    for t in TIERS:
        lines.append(f"| {t.name} | {t.heavy_calls:g} | {t.small_calls:g} | {t.win_rate:.0%} | ${t.episode_cost(turn, prices):.4f} | {t.heavy_calls_per_win():.1f} | "
                     f"{t.total_calls_per_win():.1f} | ${t.cost_per_win(turn, prices):.4f} |")
    return "\n".join(lines)
