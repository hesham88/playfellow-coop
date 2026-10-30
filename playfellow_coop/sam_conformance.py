"""Conformance of our SAM reader with the vendor's shared cases (github.com/meta-models/meta-sam), read from a local clone kept outside this repository.

Nothing of the clone is copied here, and its code is never run: the cases (folder `conformance/`) are JSON data, read only.

  python -m playfellow_coop.sam_conformance --clone ../meta-sam          one line per case; exit 1 on any difference or on a case nobody classified

Every output case goes through OUR strict reading, the way a real answer arrives: its events become official Responses stream events and are fed to
`sam_video.read_stream_strict` (lanes, finalizers, terminal outcomes and source failures) over `sam_protocol.StrictReader` (records and diagnostics). Compared:
  * a case with a result: every record in order (prose text; box: id as text, frame, half-open edges, confidence; mask: encoding, size, payload, revision,
    bounds, confidence), every diagnostic (severity, code, line, raw line), and the outcome (completed, or incomplete with its reason and detail);
  * a case with an error: the code, the message where it comes from the source (failed, error, refusal), the lanes of a lane error, the source operation.
Not compared, by design, and said so: the cumulative snapshots (our reader hands out complete lines, not snapshots), diagnostic wording (each implementation
words its own messages; the code is the contract), and the decoded mask (raster, COCO RLE, SVG path: the arithmetic coder is not defined in the protocol text
and we never draw masks, so a payload is checked only as far as the text defines its envelope).
Every object-prompt case's input goes through `sam_protocol.build_object_prompt_from`; the text or the error code must match exactly.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from playfellow_coop.sam_protocol import ObjectPromptError, Prose, Record, build_object_prompt_from
from playfellow_coop.sam_video import read_stream_strict

NOT_COMPARED = "snapshots, diagnostic wording and decoded mask rasters are not compared (see the module note)"


@dataclass
class Verdict:
    name: str
    kind: str  # "output" or "object-prompt"
    same: bool
    detail: str = ""


def _sse(event: dict) -> str:
    return "data: " + json.dumps(event)


def stream_lines(case: dict) -> list[str]:
    """The case's normalized events as the official Responses stream events our reader receives from the service."""
    chunks = case.get("chunks") or []
    lines = []
    for event in case["events"]:
        kind, lane = event["type"], dict(event.get("lane") or {})
        if kind == "output_text_delta":
            lines.append(_sse({"type": "response.output_text.delta", **lane, "delta": chunks[event["chunk"]]}))
        elif kind == "output_text_done":
            lines.append(_sse({"type": "response.output_text.done", **lane, "text": event["text"]}))
        elif kind == "content_part_done":
            text_key = "refusal" if event["part_type"] == "refusal" else "text"
            lines.append(_sse({"type": "response.content_part.done", **lane, "part": {"type": event["part_type"], text_key: event["text"]}}))
        elif kind == "response_completed":
            lines.append(_sse({"type": "response.completed", "response": {"status": "completed"}}))
        elif kind == "response_incomplete":
            details = {"reason": event["detail"]} if "detail" in event else {}
            lines.append(_sse({"type": "response.incomplete", "response": {"status": "incomplete", "incomplete_details": details}}))
        elif kind == "response_failed":
            lines.append(_sse({"type": "response.failed", "response": {"status": "failed", "error": {"message": event["message"]}}}))
        elif kind == "error":
            lines.append(_sse({"type": "error", "message": event["message"]}))
        elif kind == "refusal_delta":
            lines.append(_sse({"type": "response.refusal.delta", **lane, "delta": event["text"]}))
        elif kind == "refusal_done":
            lines.append(_sse({"type": "response.refusal.done", **lane, "refusal": event["text"]}))
        else:
            raise ValueError(f"unknown event type {kind!r}")
    return lines


class FailingSource:
    """The case's `source` directive: fail while starting, after N events, or while cleaning up."""

    def __init__(self, lines: list[str], directive: dict | None):
        self.lines, self.directive, self.at = lines, directive or {}, 0

    def __iter__(self):
        if self.directive.get("operation") == "iterator":
            raise RuntimeError(self.directive["message"])
        return self

    def __next__(self) -> str:
        if self.directive.get("operation") == "next" and self.at == self.directive["after_events"]:
            raise RuntimeError(self.directive["message"])
        if self.at >= len(self.lines):
            raise StopIteration
        self.at += 1
        return self.lines[self.at - 1]

    def close(self) -> None:
        if self.directive.get("operation") == "close":
            raise RuntimeError(self.directive["message"])


def ours(case: dict) -> dict:
    """Our reading of a case, normalized like the case's own expectations."""
    media = case["media"]
    stream = read_stream_strict(FailingSource(stream_lines(case), case.get("source")), media=media)
    records = []
    for item in stream.parsed.items:
        if isinstance(item, Prose):
            records.append({"kind": "text", "text": item.text})
            continue
        assert isinstance(item, Record)
        frame = None if media == "image" else item.frame
        bounds = {"left": item.box.left, "top": item.box.top, "right": item.box.right, "bottom": item.box.bottom}
        box = {"kind": "box", "object_id": item.object_key, "frame_index": frame, **bounds}
        if item.confidence is not None:
            box["confidence"] = item.confidence
        records.append(box)
        if item.mask is not None:
            mask = {"kind": "mask", "object_id": item.object_key, "frame_index": frame, "revision": item.mask.revision, "bounds": bounds,
                    "mask": {"encoding": item.mask.encoding, "payload": item.mask.payload, "width": item.mask.cols, "height": item.mask.rows}}
            if item.mask.confidence is not None:
                mask["confidence"] = item.mask.confidence
            records.append(mask)
    diagnostics = [{"severity": i.severity, "code": i.code, "line": i.line, "raw": i.raw} for i in stream.parsed.issues]
    if stream.error is not None:
        return {"error": _error_view(stream.error)}
    return {"records": records, "diagnostics": diagnostics, "outcome": stream.outcome}


def _error_view(error: dict) -> dict:
    view = {"code": error["code"]}
    if error["code"] in ("response_failed", "response_error", "response_refusal"):
        view["message"] = error["message"]  # these words come from the source and must be kept as they were
    if error["code"] == "response_lane":
        view["expected_lane"], view["received_lane"] = error.get("expected_lane"), error.get("received_lane")
    if error["code"] == "source_error":
        view["source_operation"] = error["source_operation"]
    return view


def expected(case: dict) -> dict:
    """The case's final expectation, reduced to what we compare."""
    if "error" in case["expected"]:
        return {"error": _error_view(case["expected"]["error"])}
    result = case["expected"]["result"]
    records = []
    for record in result["records"]:
        if record["kind"] == "text":
            records.append({"kind": "text", "text": record["text"]})
        elif record["kind"] == "box":
            records.append({k: record[k] for k in ("kind", "object_id", "frame_index", "left", "top", "right", "bottom", "confidence") if k in record})
        else:
            mask = {k: record["mask"][k] for k in ("encoding", "payload", "width", "height")}
            view = {"kind": "mask", "object_id": record["object_id"], "frame_index": record["frame_index"], "revision": record["revision"],
                    "bounds": record["bounds"], "mask": mask}
            if "confidence" in record:
                view["confidence"] = record["confidence"]
            records.append(view)
    diagnostics = [{k: d[k] for k in ("severity", "code", "line", "raw")} for d in result["diagnostics"]]
    return {"records": records, "diagnostics": diagnostics, "outcome": result["outcome"]}


def _first_difference(a, b, path: str = "") -> str:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{path}.{key}: ours {a.get(key, '<missing>')!r} vs theirs {b.get(key, '<missing>')!r}"
            found = _first_difference(a[key], b[key], f"{path}.{key}")
            if found:
                return found
        return ""
    if isinstance(a, list) and isinstance(b, list):
        for index, (x, y) in enumerate(zip(a, b)):
            found = _first_difference(x, y, f"{path}[{index}]")
            if found:
                return found
        return f"{path}: ours has {len(a)} items, theirs {len(b)}" if len(a) != len(b) else ""
    return "" if a == b else f"{path}: ours {a!r} vs theirs {b!r}"


def check_output(case: dict) -> Verdict:
    mine, theirs = ours(case), expected(case)
    difference = _first_difference(mine, theirs)
    return Verdict(case["name"], "output", not difference, difference)


def check_prompt(case: dict) -> Verdict:
    want = case["expected"]
    try:
        got = {"text": build_object_prompt_from(case["input"])}
    except ObjectPromptError as error:
        got = {"error": error.code}
    return Verdict(case["name"], "object-prompt", got == want, "" if got == want else f"ours {got} vs theirs {want}")


def load_cases(folder: Path) -> list[dict]:
    """Every case file directly in `folder`; a stray file or folder is an error, never silently skipped (the corpus's own rule)."""
    cases = []
    for path in sorted(folder.iterdir()):
        if path.is_dir() or path.suffix != ".json":
            raise ValueError(f"unexpected entry in the case folder: {path.name}")
        case = json.loads(path.read_text(encoding="utf-8"))
        if case.get("schema_version") != 1 or case.get("name") != path.stem:
            raise ValueError(f"{path.name}: unsupported schema version or a name that is not the file name")
        cases.append(case)
    return cases


def run(clone: Path) -> list[Verdict]:
    root = Path(clone) / "conformance"
    verdicts = [check_output(case) for case in load_cases(root / "cases")]
    verdicts += [check_prompt(case) for case in load_cases(root / "object-prompts")]
    return verdicts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clone", type=Path, required=True, help="a local clone of github.com/meta-models/meta-sam (kept outside this repository)")
    args = parser.parse_args(argv)
    verdicts = run(args.clone)
    for v in verdicts:
        print(f"{'same   ' if v.same else 'DIFFERS'} {v.kind:13} {v.name}" + (f"  -> {v.detail}" if v.detail else ""))
    differing = [v for v in verdicts if not v.same]
    print(f"\n{len(verdicts) - len(differing)} of {len(verdicts)} cases the same; {NOT_COMPARED}.")
    return 1 if differing else 0


if __name__ == "__main__":
    sys.exit(main())
