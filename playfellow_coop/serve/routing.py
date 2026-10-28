"""Which model for which job (research R1 section 1.1): five models, each with a different latency, price and privacy profile, and a router that picks by role and constraints.

The table is data (October 2026 figures from the research) and the router is a pure function, so a price or a model change is one line and a test. Two rules are fixed by our own terms: the
Contributor tier (cheaper, because the provider trains on what is sent) is never used for play data, and a request that needs zero data retention or open-weight auditability goes to an
open-weight model on our own deployment.
"""
from __future__ import annotations

from dataclasses import dataclass

ROLES = ("strategic", "tactical", "verifier", "segmentation", "voice")


@dataclass(frozen=True)
class Model:
    id: str
    roles: tuple[str, ...]
    input_usd_per_m: float
    cached_usd_per_m: float
    output_usd_per_m: float
    first_token_ms: float  # typical time to first token
    open_weights: bool
    trains_on_data: bool = False
    hosted_on: str = "meta"
    notes: str = ""
    flat_call_usd: float | None = None  # models billed per GPU minute or per image: a modelled price per call

    def call_usd(self, prefix_tokens: int = 4000, dynamic_tokens: int = 1500, output_tokens: int = 120, cached: bool = True) -> float:
        if self.flat_call_usd is not None:
            return self.flat_call_usd
        prefix_rate = self.cached_usd_per_m if cached else self.input_usd_per_m
        return (prefix_tokens * prefix_rate + dynamic_tokens * self.input_usd_per_m + output_tokens * self.output_usd_per_m) / 1e6


MODELS = (
    Model("muse-wonder-1.0", ("strategic",), 4.00, 0.20, 20.00, 1940.0, False, notes="strongest reasoning and computer use; writes and repairs skills offline"),
    Model("muse-spark-1.3", ("strategic", "tactical", "verifier"), 1.25, 0.15, 4.25, 600.0, False, notes="the default Standard-mode model; adjustable reasoning effort"),
    Model("muse-spark-1.3-contributor", ("tactical",), 0.10, 0.002, 0.20, 600.0, False, trains_on_data=True, notes="REFUSED for play data: the provider trains on it"),
    Model("muse-spark-open-816b", ("strategic", "tactical"), 1.25, 0.15, 4.25, 350.0, True, hosted_on="partner_gpu", notes="open weights on our own dedicated GPUs: zero retention, auditable"),
    Model("muse-glimmer-30b", ("tactical", "verifier"), 0.0, 0.0, 0.0, 45.0, True, hosted_on="partner_gpu", flat_call_usd=0.00019, notes="small and fast; priced per GPU minute, modelled at about $0.00019 per call"),
    Model("sam-3.1", ("segmentation",), 0.0, 0.0, 0.0, 11.0, False, flat_call_usd=0.0025, notes="billed per image ($2.50 per 1,000) or per video frame ($0.20 per 1,000), not per token"),
)
BY_ID = {m.id: m for m in MODELS}


class NoModel(Exception):
    pass


def route(role: str, *, need_open_weights: bool = False, zero_retention: bool = False, max_first_token_ms: float | None = None, max_call_usd: float | None = None,
          prefer: str | None = None) -> Model:
    """The model for a role under constraints. Never a model that trains on play data. `zero_retention` and `need_open_weights` both mean an open-weight model on our own deployment.
    Candidates that break a limit are dropped; of the rest the cheapest per call wins unless `prefer` names an allowed one."""
    if role not in ROLES:
        raise ValueError(f"role is one of {ROLES}")
    candidates = [m for m in MODELS if role in m.roles and not m.trains_on_data]
    if need_open_weights or zero_retention:
        candidates = [m for m in candidates if m.open_weights and m.hosted_on == "partner_gpu"]
    if max_first_token_ms is not None:
        candidates = [m for m in candidates if m.first_token_ms <= max_first_token_ms]
    if max_call_usd is not None:
        candidates = [m for m in candidates if m.call_usd() <= max_call_usd]
    if not candidates:
        raise NoModel(f"no allowed model for role {role!r} with those limits")
    if prefer:
        for m in candidates:
            if m.id == prefer:
                return m
    return min(candidates, key=lambda m: (m.call_usd(), m.hosted_on != "meta", m.first_token_ms))  # same price: the provider's own hosted model before our own deployment


def plan_for(zero_retention: bool = False) -> dict[str, str]:
    """The default model per role for a session."""
    out = {}
    for role in ROLES:
        try:
            out[role] = route(role, zero_retention=zero_retention).id
        except NoModel:
            out[role] = "none"
    return out
