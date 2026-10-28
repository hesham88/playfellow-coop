"""The tactical loop over one persistent WebSocket (research R1 section 1.3 and 4.1): frames in, action chunks out, one connection pinned to one replica so the prompt prefix stays cached.

A plain HTTP call pays a connection set-up every time, lands on a random replica (so the cached prefix is lost) and waits for the whole answer. A persistent socket keeps the replica, so the
stable prefix (system prompt, game contract, skill library, rolling history) is a cache hit, and the first action chunk can be sent the moment it has been generated instead of after the
trailing words. `TacticalSession` is the logic of one connection with the model call injected, so it is tested here without a GPU; `deploy/partner_gpu/playfellow_tactical` wraps it for Truss.

Messages (JSON):  client -> {"type": "frame", "id": n, "jpeg": base64, "hud": {...}, "goal": "..."} | {"type": "reset"}
                  server -> {"type": "chunk", "id": n, "text": "<|action_start|>...<|action_end|>", "first_ms": ..., "total_ms": ...} | {"type": "error", "code": "...", "id": n}
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import time
from collections import deque
from typing import AsyncIterator, Callable

START, END = "<|action_start|>", "<|action_end|>"
MAX_FRAME_BYTES = 1_500_000
MAX_GOAL_CHARS = 400
HISTORY = 4  # earlier frames kept as small reminders; the newest frame is always the last picture

SYSTEM = ("You are the tactical controller of a game-playing agent. Each turn you see the newest screen and a short history. Answer with exactly one action block: "
          f"{START}dx dy dz; K1; K2; K3; K4; K5; K6{END} where dx dy dz is one mouse movement and each K is the keys held for 33 ms. Keep keys that should stay down in every chunk. "
          "Never invent keys that are not on the game's controls. Be brief: no words outside the block.")


class StreamingBlocks:
    """Pulls complete action blocks out of text that arrives in pieces, so the first block can be acted on before the model has finished talking."""

    def __init__(self) -> None:
        self._text = ""

    def feed(self, piece: str) -> list[str]:
        self._text += piece
        found = []
        while True:
            start = self._text.find(START)
            if start < 0:
                self._text = self._text[-len(START):]  # keep a possible half-written tag
                return found
            end = self._text.find(END, start)
            if end < 0:
                self._text = self._text[start:]
                return found
            found.append(self._text[start:end + len(END)])
            self._text = self._text[end + len(END):]


Generate = Callable[[str, list[bytes]], AsyncIterator[str]]


class TacticalSession:
    """One connection. `generate(prompt, images)` is an async generator of text pieces from the model (a Glimmer or Spark call behind the partner GPU service's runtime in production, a fake in tests)."""

    def __init__(self, generate: Generate, clock: Callable[[], float] = time.perf_counter):
        self.generate, self.clock = generate, clock
        self.frames: deque[bytes] = deque(maxlen=HISTORY + 1)
        self.sent = 0

    async def handle(self, raw: str) -> list[dict]:
        """Process one message from the client and return the messages to send back (usually one chunk). Never raises for a bad client message: it answers with an error."""
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            return [{"type": "error", "code": "bad_json"}]
        if not isinstance(message, dict):
            return [{"type": "error", "code": "bad_message"}]
        kind = message.get("type")
        if kind == "reset":
            self.frames.clear()
            return [{"type": "reset_ok"}]
        if kind != "frame":
            return [{"type": "error", "code": "unknown_type", "id": message.get("id")}]
        ident = message.get("id")
        try:
            jpeg = base64.b64decode(message.get("jpeg", ""), validate=True)
        except (binascii.Error, ValueError, TypeError):
            return [{"type": "error", "code": "bad_image", "id": ident}]
        if not jpeg or len(jpeg) > MAX_FRAME_BYTES:
            return [{"type": "error", "code": "bad_image_size", "id": ident}]
        goal = re.sub(r"[\x00-\x1f]", " ", str(message.get("goal", "")))[:MAX_GOAL_CHARS]
        hud = message.get("hud") if isinstance(message.get("hud"), dict) else {}
        self.frames.append(jpeg)
        prompt = self.prompt(goal, hud)
        blocks, started = StreamingBlocks(), self.clock()
        stream = self.generate(prompt, list(self.frames))
        try:
            async for piece in stream:
                for block in blocks.feed(piece):
                    # the first complete block goes back at once: the socket sends it while the model could still be talking, and the rest of the generation is dropped
                    return [{"type": "chunk", "id": ident, "text": block, "first_ms": (self.clock() - started) * 1000.0}]
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
        return [{"type": "error", "code": "no_action_block", "id": ident}]

    def prompt(self, goal: str, hud: dict) -> str:
        """The stable part first, the changing part last: that order is what lets the server's prefix cache hit on every turn."""
        hud_text = ", ".join(f"{k}={v}" for k, v in sorted(hud.items()))[:300]
        return f"{SYSTEM}\n\nGoal: {goal or 'play well'}\n\nHUD: {hud_text or 'none'}"
