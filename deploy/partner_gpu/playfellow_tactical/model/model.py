"""Partner-GPU Truss handler for the tactical loop. One WebSocket connection = one game session = one TacticalSession (playfellow_coop/serve/protocol.py).

This file only adapts Truss to the session logic; the logic and its tests live in the package. The model call (`_generate`) is the one place a real deployment fills in: it streams text from the
loaded model (Muse Glimmer behind the partner GPU service's TensorRT-LLM or vLLM runtime with prefix caching and speculative decoding). Until it is filled in, the handler refuses to answer rather than
pretend: a deployment that has not loaded a model returns an error message on every frame.
"""
from __future__ import annotations

import os


class Model:
    def __init__(self, **kwargs):
        self._model = None
        self.name = os.environ.get("PLAYFELLOW_TACTICAL_MODEL", "muse-glimmer-30b")

    def load(self):
        # A real deployment loads the weights here (for example through the runtime the partner GPU service provides) and keeps the engine in self._model.
        self._model = None

    async def _generate(self, prompt: str, images: list[bytes]):
        if self._model is None:
            raise RuntimeError("no model is loaded in this deployment")
        async for piece in self._model.stream(prompt, images):  # pragma: no cover - needs a loaded model
            yield piece

    async def websocket(self, websocket):
        from playfellow_coop.serve.protocol import TacticalSession
        import json
        session = TacticalSession(self._generate)
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    replies = await session.handle(raw)
                except RuntimeError as error:
                    replies = [{"type": "error", "code": "model_unavailable", "detail": str(error)[:120]}]
                for reply in replies:
                    await websocket.send_text(json.dumps(reply))
        except Exception:  # the client went away: the connection simply ends
            return
