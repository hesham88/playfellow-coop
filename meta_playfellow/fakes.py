"""A fake SAM server for offline demos and tests. It NEVER talks to Meta: it answers on 127.0.0.1 from the Practice Arena's own
truth, in the box-token format of the SAM 3.1 docs, so the marker, the marks and the harness can be exercised without credits.
Anything made with it must say so."""
from __future__ import annotations

import http.server
import json
import threading

from meta_playfellow.sam_eval import arena_truth_boxes


class FakeSam:
    def __init__(self, game, prompts: dict[str, str], extra: dict[str, list] | None = None):
        self.game, self.prompts = game, prompts
        self.requests: list[dict] = []
        self.extra = extra or {}  # kind -> extra pixel boxes to answer with (false alarms), for tests
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                owner.requests.append({"path": self.path, "body": body})
                phrase = body["input"][0]["content"][0]["text"]
                kind = next((k for k, p in owner.prompts.items() if p == phrase), None)
                width, height = owner.game.pixel_size
                boxes = list(arena_truth_boxes(owner.game).get(kind, [])) + list(owner.extra.get(kind, []))
                tokens = "".join(f"<1f>{n}<|box;x1={b[0]};y1={b[1]};x2={b[2]};y2={b[3]};w={width};h={height}|><|mask;lossless|>"
                                 for n, b in enumerate(boxes, start=1))
                data = json.dumps({"output": [{"content": [{"type": "output_text", "text": tokens}]}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
