"""The open-weights bench brain: the same harness, schema and safety as the Muse brain, pointed at an open-weights Muse Spark served by a partner GPU service.

This file is the narrow exception to the repo rule "no code routes traffic to a partner GPU service": it lives in bench/, it is used only by the owner's recorded benchmark
runs, nothing in playfellow_coop imports it, and the demo and the app never reach it (a test pins all three). The key comes from the environment (BASETEN_API_KEY) only.
Cost: the partner's per-token prices were not published to us when this was written, so cost is the Muse Spark Standard price as a provisional upper bound and every
result file says so; replace the two numbers from the partner's price page before quoting a dollar figure.
"""
from __future__ import annotations

from playfellow_coop.muse_brain import MuseBrain

OPEN_BASE = "https://inference.baseten.co/v1"  # pinned
OPEN_MODEL = "meta-models/muse-spark-open-1026"
OPEN_MAX_TOKENS = 3000  # measured: this model always reasons and the budget includes the thinking; at 1000 some answers came back empty
COST_NOTE = "provisional: priced like muse-spark Standard until the partner's own prices are filled in"


class OpenWeightsBrain(MuseBrain):
    name = "open-weights"

    def __init__(self, api_key: str, model: str = OPEN_MODEL, **kw):
        # no prompt_cache_key: the partner caches by prefix on its own (measured: 128 of 220 prompt tokens cached on a repeated prompt)
        super().__init__(model, api_key, base_url=OPEN_BASE, auth_scheme="Api-Key", cache_key=None, **kw)
        self.max_tokens = OPEN_MAX_TOKENS

    def __repr__(self) -> str:
        return f"<OpenWeightsBrain model={self.model!r}>"
