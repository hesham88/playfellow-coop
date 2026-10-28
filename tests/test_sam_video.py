"""SAM on a recorded clip: encoding, the upload (expiry first, file last), the streamed answer read frame by frame, billing from the service's own count, and the clip file always deleted."""
from __future__ import annotations

import http.server
import json
import re
import threading

import numpy as np
import pytest

from brain import BrainError
from playfellow_coop import sam_video
from playfellow_coop.sam_protocol import FramePrompt, PromptBox, PromptObject
from playfellow_coop.sam_video import FrameBuffer, NoEncoder, SamVideo, StreamReader, read_stream, video_request

SECRET = "sam-video-test-key"
FRAME0 = "<0f>1<|box;x1=1;y1=2;x2=9;y2=9;w=64;h=48;conf=0.91|><|mask;enc=!;w=64;h=48;data=AAAA|>\n"
FRAME1 = "<1f>1<|box;x1=2;y1=2;x2=10;y2=9;w=64;h=48;conf=0.90|>\n"


def sse(*deltas, billed=50, kind="response.completed"):
    lines = [f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': d})}\n\n" for d in deltas]
    lines.append(f"data: {json.dumps({'type': kind, 'response': {'usage': {'video_frames_processed': billed}}})}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines)


class Handler(http.server.BaseHTTPRequestHandler):
    def _reply(self, status, payload, content_type="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        record = {"path": self.path, "auth": self.headers.get("Authorization"), "ctype": self.headers.get("Content-Type", ""), "body": body}
        self.server.hits.append(record)
        if self.path.endswith("/files"):
            self._reply(*self.server.upload_answer)
        else:
            self._reply(200, self.server.stream.encode("utf-8"), "text/event-stream")

    def do_DELETE(self):  # noqa: N802
        self.server.hits.append({"path": self.path, "auth": self.headers.get("Authorization"), "method": "DELETE"})
        self._reply(200, {"deleted": True})

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.hits, srv.upload_answer, srv.stream = [], (200, {"id": "file-842549258569145", "object": "file", "status": "uploaded"}), sse(FRAME0, FRAME1)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def sam(server, monkeypatch):
    monkeypatch.setattr(sam_video, "encode_mp4", lambda frames, path, fps=10.0: (path.write_bytes(b"fake-mp4-bytes"), path)[1])  # the network path is tested without an encoder
    video = SamVideo(SECRET, base=f"http://127.0.0.1:{server.server_address[1]}/v1")
    yield video
    video.close()


OBJECTS = [PromptObject(1, (FramePrompt(0, PromptBox(1, 2, 10, 10)),))]
FRAMES = [np.zeros((48, 64, 3), np.uint8)] * 6


def test_a_clip_is_uploaded_with_its_expiry_first_and_the_file_last_streamed_parsed_billed_and_deleted(sam, server):
    result = sam.track(FRAMES, OBJECTS, direction="forward")
    upload, ask, delete = server.hits
    assert upload["path"] == "/v1/files" and upload["auth"] == f"Bearer {SECRET}" and upload["ctype"].startswith("multipart/form-data")
    names = re.findall(rb'form-data; name="([^"]+)"', upload["body"])
    assert names == [b"purpose", b"expires_after[anchor]", b"expires_after[seconds]", b"file"] and b"user_data" in upload["body"] and b"fake-mp4-bytes" in upload["body"]
    request = json.loads(ask["body"])
    assert ask["path"] == "/v1/responses" and request["model"] == "sam-3.1" and request["stream"] is True
    assert request["metadata"] == {"mask_encoding": "one_bit", "include_confidence": "true", "propagation_direction": "forward"}
    parts = request["input"][0]["content"]
    assert parts[0]["text"].startswith("<0f>1<|box;x1=1;y1=2;x2=9;y2=9;w=64;h=48|>") and parts[1] == {"type": "input_video", "file_id": "file-842549258569145"}
    assert delete["method"] == "DELETE" and delete["path"] == "/v1/files/file-842549258569145" and result.file_deleted
    frames = sorted({r.frame for r in result.parsed.records})
    assert frames == [0, 1] and all(r.object_id == 1 for r in result.parsed.records)
    assert result.frames_billed == 50 and result.cost_usd == pytest.approx(0.01)
    assert SECRET not in repr(sam)


def test_the_file_is_deleted_even_when_the_answer_fails_and_a_failed_stream_is_an_error(sam, server):
    server.stream = sse(FRAME0, billed=0, kind="response.failed")
    with pytest.raises(BrainError):
        sam.track(FRAMES, OBJECTS)
    assert [h.get("method") for h in server.hits][-1] == "DELETE"


def test_an_unusable_upload_answer_stops_before_anything_is_asked(sam, server):
    server.upload_answer = (200, {"id": "../etc/passwd"})
    with pytest.raises(BrainError):
        sam.track(FRAMES, OBJECTS)
    assert len(server.hits) == 1  # nothing was asked and no delete was tried on a bad id
    server.upload_answer = (400, {"error": "storage full"})
    with pytest.raises(BrainError):
        sam.track(FRAMES, OBJECTS)


def test_without_a_service_count_the_minimum_billing_applies(sam, server):
    server.stream = sse(FRAME0, billed=None).replace('"video_frames_processed": null', '"x": 1')
    assert sam.track(FRAMES, OBJECTS).cost_usd == pytest.approx(50 * 0.20 / 1000)


# ---- pure pieces ---------------------------------------------------------------------------------------------------------------------
def test_the_stream_reader_hands_out_each_frame_as_its_line_ends_even_when_lines_are_split_across_events():
    reader = StreamReader()
    split = sse("<0f>1<|box;x1=1;y1=2;x2=9;y2=9;w=64;h=48|>", "\n<1f>1<|box;x1=2;y1=2;x2=9;y2=9;w=64;h=48|>")
    got = []
    for line in split.splitlines():
        got.extend(reader.feed(line))
    assert [p.records[0].frame for p in got] == [0, 1] and reader.status == "completed" and reader.frames_billed == 50  # the last line is flushed by the completion event
    reader2, frames = read_stream(["garbage", "data: not json", "data: [DONE]", ""])
    assert frames == [] and reader2.status == "in_progress"


def test_the_buffer_keeps_only_the_newest_frames_and_the_request_has_the_documented_shape():
    buffer = FrameBuffer(3)
    for n in range(5):
        buffer.push(n)
    assert buffer.frames() == [2, 3, 4] and len(buffer) == 3
    body = video_request("p", "file-1")
    assert body["input"][0]["content"][1] == {"type": "input_video", "file_id": "file-1"} and "propagation_direction" not in body["metadata"]
    with pytest.raises(ValueError):
        sam_video.upload(None, "k", __file__, expires_seconds=10)


def test_mp4_encoding_writes_a_readable_clip_or_says_what_is_missing(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    frames = [np.full((32, 48, 3), (n * 20, 100, 50), np.uint8) for n in range(8)]
    path = sam_video.encode_mp4(frames, tmp_path / "c.mp4", fps=8)
    capture = cv2.VideoCapture(str(path))
    count = 0
    while capture.read()[0]:
        count += 1
    capture.release()
    assert count == 8
    with pytest.raises(ValueError):
        sam_video.encode_mp4([np.zeros((4, 4, 3), np.uint8), np.zeros((5, 5, 3), np.uint8)], tmp_path / "d.mp4")
    monkeypatch.setitem(__import__("sys").modules, "cv2", None)  # OpenCV missing
    with pytest.raises(NoEncoder):
        sam_video.encode_mp4(frames, tmp_path / "e.mp4")
