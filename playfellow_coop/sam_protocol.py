"""The SAM 3.1 wire format, read and written exactly as the published docs describe it (dev.meta.ai/docs/sam: segmenting, reading segmentation output, client libraries).

Our own code, written from the documented grammar; no code from the vendor's packages is used. What it covers:

  * output text: one line per frame, `<Nf>` then comma-separated records; a record is an object id, one box token, one mask token (box first); optional `c` confidence
    on both tokens; frame indices may skip and need not ascend; object ids are stable inside ONE response only and are not dense; zero matches is an empty text;
  * boxes in source pixels with x2 and y2 INCLUSIVE (the half-open edges are x2+1 and y2+1); w and h repeat the source size on every token;
  * masks: `data=<H>,<W>,<enc><payload>`, H rows then W columns; `~` lossless and `!` one_bit are read from the first character after `H,W,` only; the payload is
    base85 and may itself contain `~` or `!`, so it is never searched for them;
  * prompts: `<Nf>id<|box;...|>,id<|point;...|>-<|point;...|>`: right and bottom are half-open in our API and written as x2=right-1, y2=bottom-1; every token carries the same
    w and h; an id appears once per frame; at most one box per object per frame; at most 16 objects; an image prompt lives on frame 0; a noun phrase and object prompts are never mixed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_OBJECTS = 16
MAX_VIDEO_FRAMES = 15000
MIN_BILLED_VIDEO_FRAMES = 50  # video is billed per frame with this minimum per request
DIRECTIONS = ("both", "forward", "backward")
MASK_ENCODINGS = ("lossless", "one_bit")
ENC_MARKERS = {"~": "lossless", "!": "one_bit"}

FRAME = re.compile(r"<(\d+)f>")
RECORD = re.compile(r"(?:(?:^|,)(\d+))?<\|box;([^|]*?)\|>(?:<\|mask;([^|]*?)\|>)?", re.S)  # id (optional), box, mask (optional); a token ends at the first |>
_FIELD_INT = re.compile(r"-?\d+")


@dataclass(frozen=True)
class Box:
    left: int
    top: int
    right: int  # half-open: x2 + 1
    bottom: int  # half-open: y2 + 1
    width: int  # source frame size, repeated on the token
    height: int


@dataclass(frozen=True)
class MaskInfo:
    rows: int  # H
    cols: int  # W
    encoding: str  # "lossless", "one_bit" or "unknown"
    payload_chars: int
    confidence: float | None = None


@dataclass(frozen=True)
class Record:
    frame: int
    object_id: int
    box: Box
    mask: MaskInfo | None
    confidence: float | None  # from the box token, None when the request did not ask for it (absence is not zero)


@dataclass
class Parsed:
    records: list[Record] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)  # recoverable format problems; parsing goes on after each

    def frames(self) -> list[int]:
        return sorted({r.frame for r in self.records})

    def by_object(self) -> dict[int, list[Record]]:
        """Records keyed by object id (never by position in the line), each list in frame order of arrival."""
        out: dict[int, list[Record]] = {}
        for r in self.records:
            out.setdefault(r.object_id, []).append(r)
        return out

    def on_frame(self, frame: int) -> list[Record]:
        return [r for r in self.records if r.frame == frame]


def _fields(raw: str) -> dict[str, str]:
    """Fields found by NAME after splitting on ';' (a mask payload may hold '=' and letters, so nothing is searched for by pattern in the text)."""
    out = {}
    for part in raw.split(";"):
        key, sep, value = part.partition("=")
        if sep and key.strip():
            out[key.strip()] = value.strip()
    return out


def _conf(fields: dict) -> float | None:
    try:
        value = float(fields["c"]) if "c" in fields else None
    except ValueError:
        return None
    return value if value is None or 0.0 <= value <= 1.0 else None


def _box(fields: dict) -> Box | None:
    try:
        x1, y1, x2, y2, w, h = (int(fields[k]) for k in ("x1", "y1", "x2", "y2", "w", "h"))
    except (KeyError, ValueError):
        return None
    if w <= 0 or h <= 0 or not (0 <= x1 <= x2 < w and 0 <= y1 <= y2 < h):
        return None
    return Box(x1, y1, x2 + 1, y2 + 1, w, h)


def _mask(raw: str, fields: dict) -> MaskInfo | None:
    data = fields.get("data")
    if data is None:
        return None
    head = re.match(r"(\d+),(\d+),(.?)", data, re.S)
    if not head:
        return None
    marker = head.group(3)
    return MaskInfo(int(head.group(1)), int(head.group(2)), ENC_MARKERS.get(marker, "unknown"), len(data) - head.end(), _conf(fields))


def parse(text: str) -> Parsed:
    """Read a whole answer (any number of lines). Records are keyed by the explicit `<Nf>` marker, never by the line number."""
    result = Parsed()
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        marker = FRAME.match(line)
        if not marker:
            result.diagnostics.append(f"line without a frame marker: {line[:40]!r}")
            continue
        frame, body = int(marker.group(1)), line[marker.end():]
        # a record is `<id><|box...|><|mask...|>`; the id is the integer right before the box. An answer without ids (older fakes and some tools omit them) is still read:
        # such records take the next free ordinal and a diagnostic says so, because the id is then not a stable identity.
        ordinal = 0
        for m in RECORD.finditer(body):
            box = _box(_fields(m.group(2)))
            if box is None:
                result.diagnostics.append(f"frame {frame}: malformed box")
                continue
            if m.group(1) is None:
                object_id = ordinal
                result.diagnostics.append(f"frame {frame}: a box without an object id (read as {object_id})")
            else:
                object_id = int(m.group(1))
            ordinal = max(ordinal, object_id) + 1
            mask = _mask(m.group(3), _fields(m.group(3))) if m.group(3) is not None else None
            result.records.append(Record(frame, object_id, box, mask, _conf(_fields(m.group(2)))))
    return result


# ------------------------------------------------------------------ prompts
class ObjectPromptError(ValueError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


@dataclass(frozen=True)
class PromptBox:
    left: int
    top: int
    right: int  # half-open
    bottom: int


@dataclass(frozen=True)
class PromptPoint:
    x: int
    y: int
    negative: bool = False


@dataclass(frozen=True)
class FramePrompt:
    frame: int = 0
    box: PromptBox | None = None
    points: tuple[PromptPoint, ...] = ()


@dataclass(frozen=True)
class PromptObject:
    id: int
    prompts: tuple[FramePrompt, ...]


def build_object_prompt(size: tuple[int, int], objects: list[PromptObject]) -> str:
    """The input_text for box and point prompts. `size` is the media's displayed pixel size (width, height). Mirrors the documented builder: x2 = right - 1, y2 = bottom - 1,
    frames ascending, objects in input order inside a frame, each object's box before its points, a negative point written with a leading '-'."""
    width, height = size
    if width <= 0 or height <= 0:
        raise ObjectPromptError("invalid_size", f"{width}x{height}")
    if not objects:
        raise ObjectPromptError("no_objects")
    ids = set()
    by_frame: dict[int, list[tuple[int, FramePrompt]]] = {}
    for obj in objects:
        if not isinstance(obj.id, int) or obj.id < 0:
            raise ObjectPromptError("invalid_object_id", str(obj.id))
        if obj.id in ids:
            raise ObjectPromptError("duplicate_object_id", str(obj.id))
        ids.add(obj.id)
        if not obj.prompts:
            raise ObjectPromptError("empty_object", str(obj.id))
        seen = set()
        for prompt in obj.prompts:
            if prompt.frame < 0:
                raise ObjectPromptError("invalid_frame", str(prompt.frame))
            if prompt.frame in seen:
                raise ObjectPromptError("duplicate_frame", f"object {obj.id} frame {prompt.frame}")
            seen.add(prompt.frame)
            if prompt.box is None and not prompt.points:
                raise ObjectPromptError("empty_prompt", f"object {obj.id} frame {prompt.frame}")
            b = prompt.box
            if b is not None and not (0 <= b.left < b.right <= width and 0 <= b.top < b.bottom <= height):
                raise ObjectPromptError("invalid_box", f"{b}")
            for p in prompt.points:
                if not (0 <= p.x < width and 0 <= p.y < height):
                    raise ObjectPromptError("invalid_point", f"({p.x}, {p.y})")
            by_frame.setdefault(prompt.frame, []).append((obj.id, prompt))
    out = []
    for frame in sorted(by_frame):
        records = []
        for obj_id, prompt in by_frame[frame]:
            parts = [str(obj_id)]
            if prompt.box is not None:
                b = prompt.box
                parts.append(f"<|box;x1={b.left};y1={b.top};x2={b.right - 1};y2={b.bottom - 1};w={width};h={height}|>")
            for p in prompt.points:
                parts.append(("-" if p.negative else "") + f"<|point;x={p.x};y={p.y};w={width};h={height}|>")
            records.append("".join(parts))
        out.append(f"<{frame}f>" + ",".join(records))
    return "".join(out)


def request_metadata(*, mask_encoding: str | None = "one_bit", confidence: bool = True, direction: str | None = None) -> dict:
    """The top-level `metadata` of a segmentation request. Every value is a STRING ("true", not a JSON boolean). `one_bit` masks are several times smaller than lossless ones."""
    meta: dict[str, str] = {}
    if mask_encoding is not None:
        if mask_encoding not in MASK_ENCODINGS:
            raise ValueError(f"mask_encoding is one of {MASK_ENCODINGS}")
        meta["mask_encoding"] = mask_encoding
    if confidence:
        meta["include_confidence"] = "true"
    if direction is not None:
        if direction not in DIRECTIONS:
            raise ValueError(f"propagation_direction is one of {DIRECTIONS}")
        meta["propagation_direction"] = direction
    return meta


def classify_status(status: int, body_text: str = "") -> str:
    """How a failed request should be treated, from the docs' error rules: a 400 is permanent for that request (never retry it unchanged); a 404 or code
    model_not_found means the model id or access is wrong; 429 and 5xx may be retried with backoff; 401 is the key."""
    if status == 400:
        return "permanent"
    if status == 404 or "model_not_found" in body_text:
        return "model_not_found"
    if status == 401:
        return "bad_key"
    if status == 429 or 500 <= status < 600:
        return "retry"
    return "other"


IMAGE_USD = 2.50 / 1000
VIDEO_FRAME_USD = 0.20 / 1000


def sam_cost(frames: int, mode: str) -> float:
    """What SAM bills (docs: pricing). An image request is $2.50 per 1,000 images; a video request is $0.20 per 1,000 frames with a minimum of 50 frames per request
    (a shorter clip or tracking range is billed as 50). The same prices apply streamed or not."""
    if mode == "image":
        return max(1, frames) * IMAGE_USD
    if mode == "video":
        return max(MIN_BILLED_VIDEO_FRAMES, frames) * VIDEO_FRAME_USD
    raise ValueError("mode is image or video")


def cheaper_mode(frames: int) -> str:
    """For `frames` pictures of the same scene: one video request or that many image requests, whichever costs less (four images cost the same $0.01 as the 50-frame minimum of one clip, so from five pictures on a clip is cheaper)."""
    return "video" if sam_cost(frames, "video") < sam_cost(frames, "image") else "image"
