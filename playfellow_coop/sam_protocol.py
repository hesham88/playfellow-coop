"""The SAM 3.1 wire format, read and written exactly as the published docs describe it (dev.meta.ai/docs/sam: segmenting, reading segmentation output, client libraries).

Our own code, written from the documented grammar; no code from the vendor's packages is used. What it covers:

  * output text: one line per frame, `<Nf>` then comma-separated records; a record is an object id, one box token, one mask token (box first); optional `c` confidence
    on both tokens; frame indices may skip and need not ascend; object ids are stable inside ONE response only and are not dense; zero matches is an empty text;
  * boxes in source pixels with x2 and y2 INCLUSIVE (the half-open edges are x2+1 and y2+1); w and h repeat the source size on every token;
  * masks: `data=<H>,<W>,<enc><payload>`, H rows then W columns; `~` lossless and `!` one_bit are read from the first character after `H,W,` only; the payload is
    base85 and may itself contain `~` or `!`, so it is never searched for them;
  * prompts: `<Nf>id<|box;...|>,id<|point;...|>-<|point;...|>`: right and bottom are half-open in our API and written as x2=right-1, y2=bottom-1; every token carries the same
    w and h; an id appears once per frame; at most one box per object per frame; at most 16 objects; an image prompt lives on frame 0; a noun phrase and object prompts are never mixed.

Two readings: the default forgives what older fakes send (a box without its mask, a record without an id), each with a diagnostic; `parse(text, strict=True)`
(`StrictReader`) follows the protocol rule by rule, with coded diagnostics, prose lines and mask revisions, and is checked against the vendor's shared
conformance cases (`sam_conformance.py`, from a clone outside this repository).
"""
from __future__ import annotations

import math
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
    payload: str = ""  # the payload as sent (strict reading only): opaque, never decoded here
    revision: int = 1  # strict reading: 2 for the second complete mask of the same media, frame and object, and so on


@dataclass(frozen=True)
class Record:
    frame: int
    object_id: int
    box: Box
    mask: MaskInfo | None
    confidence: float | None  # from the box token, None when the request did not ask for it (absence is not zero)
    object_key: str = ""  # the object id exactly as written (strict reading keeps it as text, as the protocol says)


@dataclass(frozen=True)
class Issue:
    """One structured diagnostic of the strict reading. `error`: data was dropped; `warning`: the record was kept and part of the input ignored."""
    severity: str
    code: str  # malformed_record, invalid_box, invalid_mask_payload, unexpected_frame, ignored_field, ignored_token, ignored_confidence
    message: str
    line: int  # one-based line of the answer
    raw: str  # that line as received


@dataclass(frozen=True)
class Prose:
    """A line of plain text in the answer (not segmentation). Kept in order, never treated as data to act on."""
    text: str


@dataclass
class Parsed:
    records: list[Record] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)  # recoverable format problems; parsing goes on after each
    issues: list[Issue] = field(default_factory=list)  # strict reading: the same problems with a code, a severity and the line
    items: list = field(default_factory=list)  # strict reading: records and prose lines in the order they came

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


def parse(text: str, strict: bool = False, media: str | None = None) -> Parsed:
    """Read a whole answer (any number of lines). Records are keyed by the explicit `<Nf>` marker, never by the line number.

    The default reading is forgiving: older fakes and tools send boxes without masks or without ids, and those are still read (with a diagnostic). `strict=True` reads
    exactly as the published protocol says (`StrictReader`), the reading the vendor's shared conformance cases check; `media` ("image" or "video") applies the frame rule."""
    if strict:
        reader = StrictReader(media)
        reader.feed(text or "")
        return reader.finish()
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


# ------------------------------------------------------------------ strict reading (the published protocol, rule by rule)
API_LINE = re.compile(r"<\d+f")  # a line that starts like a frame header is segmentation; any other line is prose
HEADER = re.compile(r"<(\d+)f([^>]*)>")
TOKEN_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")
SIGNED = re.compile(r"-?\d+")
UNSIGNED = re.compile(r"\d+")
DECIMAL = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
MAX_SAFE = 2 ** 53 - 1
BOX_KEYS = ("x1", "y1", "x2", "y2", "w", "h")
MASK_KEYS = ("x", "y", "data")
B85 = "!#$%&'()*+-./0123456789:=?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`abcdefghijklmnopqrstuvwxyz{"  # the protocol's 85 digits, in order
B85_VALUE = {ch: i for i, ch in enumerate(B85)}
MESSAGES = {"malformed_record": "Malformed SAM API object record.", "invalid_box": "SAM API box coordinates are invalid.",
            "invalid_mask_payload": "SAM API mask payload is invalid.", "unexpected_frame": "Image segmentation records require frame zero."}


class _Malformed(Exception):
    """One object segment breaks the grammar: the whole line is diagnosed once."""

    def __init__(self, code: str = "malformed_record"):
        super().__init__(code)
        self.code = code


def _b85_bytes(digits: str) -> int | None:
    """How many bytes base85 `digits` pack into (four bytes per five digits, a short tail of n+1 digits for n bytes), or None when they cannot be a packing."""
    whole, tail = divmod(len(digits), 5)
    if tail == 1:
        return None
    for start in range(0, whole * 5, 5):
        value = 0
        for ch in digits[start:start + 5]:
            value = value * 85 + B85_VALUE[ch]
        if value > 0xFFFFFFFF:
            return None
    return whole * 4 + (tail - 1 if tail else 0)


def payload_envelope_ok(payload: str) -> bool:
    """The mask payload's envelope, as far as the protocol text defines it: a marker (`~` lossless, `!` one_bit), then base85 digits only, a five-digit length
    prefix, and a body that packs exactly that many bytes (a lossless body may carry trailing bytes). The arithmetic-coded body itself is NOT decoded here: the
    published text does not define that coder, and we never draw masks; a body that passes this envelope but would fail the vendor's decoder is still accepted."""
    if len(payload) < 6 or payload[0] not in "~!":
        return False
    digits = payload[1:]
    if any(ch not in B85_VALUE for ch in digits):
        return False
    declared = 0
    for ch in digits[:5]:
        declared = declared * 85 + B85_VALUE[ch]
    body = _b85_bytes(digits[5:])
    if body is None:
        return False
    return body == declared or (payload[0] == "~" and body > declared)


class StrictReader:
    """Reads SAM answer text line by line exactly as the protocol defines it, and keeps what it saw: records (a box and its mask, an id kept as text), prose lines,
    and diagnostics with a code and a line number. Warnings (ignored fields, tokens, confidence) are reported once per answer, on the first line of an ACCEPTED
    record they apply to. Feed text in any chunks; `finish` reads a last line that has no newline."""

    def __init__(self, media: str | None = None):
        if media not in (None, "image", "video"):
            raise ValueError("media is image or video")
        self.media = media
        self.parsed = Parsed()
        self.line_no = 0
        self._buffer = ""
        self._warned: set[tuple] = set()
        self._mask_revisions: dict[tuple, int] = {}

    def feed(self, chunk: str) -> list[Record]:
        """Add text; every line it completes is read now. Returns the records those lines added."""
        before = len(self.parsed.records)
        self._buffer += chunk
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._line(line)
        return self.parsed.records[before:]

    def finish(self) -> Parsed:
        if self._buffer:
            line, self._buffer = self._buffer, ""
            self._line(line)
        return self.parsed

    # ---- one line
    def _issue(self, severity: str, code: str, raw: str, message: str | None = None) -> None:
        issue = Issue(severity, code, message or MESSAGES.get(code, code), self.line_no, raw)
        self.parsed.issues.append(issue)
        self.parsed.diagnostics.append(f"line {self.line_no}: {code}")

    def _warn(self, raw: str, pending: list[tuple]) -> None:
        for key, code, message in pending:
            if key not in self._warned:
                self._warned.add(key)
                self._issue("warning", code, raw, message)

    def _line(self, raw: str) -> None:
        self.line_no += 1
        if not API_LINE.match(raw):
            if raw.strip():
                self.parsed.items.append(Prose(raw))
            return
        header = HEADER.match(raw)
        if not header or (header.group(2) and not header.group(2).startswith(";")) or int(header.group(1)) > MAX_SAFE:
            self._issue("error", "malformed_record", raw)
            return
        frame = int(header.group(1))
        header_warnings = [(("ignored_field", "frame header", name), "ignored_field", f'Ignored unknown frame header field "{name}".')
                           for name in self._names(header.group(2)[1:])] if header.group(2) else []
        if self.media == "image" and frame != 0:
            self._issue("error", "unexpected_frame", raw)
            return
        pos, end = header.end(), len(raw)
        if pos == end:
            self._issue("error", "malformed_record", raw)  # a bare frame header
            return
        accepted: list[tuple[Record, list[tuple]]] = []
        problem = None
        while pos < end and problem is None:
            if raw[pos] == ",":
                pos += 1
            ident = UNSIGNED.match(raw, pos)
            if not ident:
                problem = "malformed_record"
                break
            pos = ident.end()
            tokens = []
            while raw.startswith("<|", pos):
                close = raw.find("|>", pos + 2)
                if close < 0:
                    break
                name, has_fields, fields = raw[pos + 2:close].partition(";")
                tokens.append((name, fields if has_fields else ""))
                pos = close + 2
            if not tokens or (pos < end and raw[pos] != "," and not raw[pos].isdigit()):
                problem = "malformed_record"  # an id without tokens, an unclosed token, or text between tokens
                break
            try:
                record, pending, payload_bad = self._segment(frame, ident.group(), tokens)
            except _Malformed as error:
                problem = error.code
                if problem == "invalid_box":  # an impossible box drops this record only; the line goes on
                    self._issue("error", "invalid_box", raw)
                    problem = None
                continue
            accepted.append((record, pending))
            if payload_bad:
                self._issue("error", "invalid_mask_payload", raw)
        if problem:
            self._issue("error", problem, raw)
        if accepted:
            self._warn(raw, header_warnings)
        for record, pending in accepted:
            self._warn(raw, pending)
            self.parsed.records.append(record)
            self.parsed.items.append(record)

    @staticmethod
    def _names(fields: str) -> list[str]:
        names = []
        for part in fields.split(";"):
            if part.strip():
                key = part.partition("=")[0].strip()
                names.append(key or part.strip())
        return names

    def _fields(self, kind: str, raw: str, known: tuple[str, ...], pending: list[tuple]) -> tuple[dict[str, str], float | None]:
        """Known fields by name (a repeat or a missing value is malformed), the optional confidence, and warnings for everything else."""
        values: dict[str, str] = {}
        confidences: list[str | None] = []
        for part in raw.split(";"):
            if not part.strip():
                continue
            key, sep, value = part.partition("=")
            key, value = key.strip(), value.strip()
            if key == "c":
                confidences.append(value if sep else None)
            elif key in known:
                if key in values or not sep:
                    raise _Malformed()
                values[key] = value
            else:
                name = key or part.strip()
                pending.append((("ignored_field", kind, name), "ignored_field", f'Ignored unknown {kind} field "{name}".'))
        confidence = None
        if confidences:
            value = confidences[0]
            number = float(value) if len(confidences) == 1 and value is not None and DECIMAL.fullmatch(value) else math.nan
            if math.isfinite(number) and 0.0 <= number <= 1.0:  # -0 passes (it equals 0) and is written as 0
                confidence = 0.0 if number == 0.0 else number
            else:  # not a number, out of range, no value, or a second c: the record is kept without this token's confidence
                pending.append((("ignored_confidence",), "ignored_confidence", "Ignored a confidence value that is not a number from 0 through 1."))
        return values, confidence

    def _segment(self, frame: int, key: str, tokens: list[tuple[str, str]]) -> tuple[Record, list[tuple], bool]:
        pending: list[tuple] = []
        boxes = [fields for name, fields in tokens if name == "box"]
        masks = [fields for name, fields in tokens if name == "mask"]
        for name, _ in tokens:
            if not TOKEN_NAME.fullmatch(name):
                raise _Malformed()
            if name not in ("box", "mask"):
                pending.append((("ignored_token", name), "ignored_token", f'Ignored unknown token "{name}".'))
        if len(boxes) != 1 or len(masks) != 1:
            raise _Malformed()
        box_fields, box_conf = self._fields("box", boxes[0], BOX_KEYS + ("c",), pending)
        mask_fields, mask_conf = self._fields("mask", masks[0], MASK_KEYS + ("c",), pending)
        if any(k not in box_fields for k in BOX_KEYS) or any(k not in mask_fields for k in MASK_KEYS):
            raise _Malformed()
        if not all(SIGNED.fullmatch(box_fields[k]) for k in ("x1", "y1", "x2", "y2")) or not all(UNSIGNED.fullmatch(box_fields[k]) for k in ("w", "h")):
            raise _Malformed()
        x1, y1, x2, y2, w, h = (int(box_fields[k]) for k in BOX_KEYS)
        if max(abs(x1), abs(y1), abs(x2), abs(y2), w, h) > MAX_SAFE:
            raise _Malformed()
        if not (SIGNED.fullmatch(mask_fields["x"]) and SIGNED.fullmatch(mask_fields["y"])) or int(mask_fields["x"]) != 0 or int(mask_fields["y"]) != 0:
            raise _Malformed()  # the mask's origin must be 0,0
        rows, sep1, rest = mask_fields["data"].partition(",")
        cols, sep2, payload = rest.partition(",")
        if not (sep1 and sep2 and UNSIGNED.fullmatch(rows) and UNSIGNED.fullmatch(cols) and int(rows) > 0 and int(cols) > 0 and payload):
            raise _Malformed()
        if w <= 0 or h <= 0 or not (0 <= x1 <= x2 < w and 0 <= y1 <= y2 < h):
            raise _Malformed("invalid_box")
        box = Box(x1, y1, x2 + 1, y2 + 1, w, h)
        mask = None
        payload_bad = not payload_envelope_ok(payload)
        if not payload_bad:
            identity = (self.media, None if self.media == "image" else frame, key)
            revision = self._mask_revisions.get(identity, 0) + 1
            self._mask_revisions[identity] = revision
            mask = MaskInfo(int(rows), int(cols), ENC_MARKERS.get(payload[0], "unknown"), len(payload) - 1, mask_conf, payload, revision)
        return Record(frame, int(key), box, mask, box_conf, key), pending, payload_bad


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


CANONICAL_ID = re.compile(r"0|[1-9]\d*")


def _whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def build_object_prompt_from(spec: dict) -> str:
    """The documented builder's input shape, untyped (as JSON gives it): {"size": {"width", "height"}, "objects": [{"id", "prompts": [{"frame"?, "box"?: {left, top,
    right, bottom}, "points"?: [{"x", "y", "label"?}]}]}]}. Every number must be a whole number (a fraction is refused, never rounded); an id is a whole number or
    its canonical decimal text ("10", never "010"); a point's label is "positive" (the default) or "negative". Then `build_object_prompt` writes the text."""
    size = spec.get("size") if isinstance(spec, dict) else None
    width, height = (size.get("width"), size.get("height")) if isinstance(size, dict) else (None, None)
    if not (_whole(width) and _whole(height) and width > 0 and height > 0):
        raise ObjectPromptError("invalid_size", f"{width!r}x{height!r}")
    objects = []
    for obj in spec.get("objects") or []:
        ident = obj.get("id")
        if isinstance(ident, str) and CANONICAL_ID.fullmatch(ident):
            ident = int(ident)
        if not _whole(ident) or ident < 0:
            raise ObjectPromptError("invalid_object_id", repr(ident))
        prompts = []
        for prompt in obj.get("prompts") or []:
            frame = prompt.get("frame", 0)
            if not _whole(frame) or frame < 0:
                raise ObjectPromptError("invalid_frame", repr(frame))
            box = None
            if prompt.get("box") is not None:
                edges = [prompt["box"].get(k) for k in ("left", "top", "right", "bottom")]
                if not all(_whole(v) for v in edges):
                    raise ObjectPromptError("invalid_box", repr(edges))
                box = PromptBox(*edges)
            points = []
            for point in prompt.get("points") or []:
                label = point.get("label", "positive")
                if label not in ("positive", "negative"):
                    raise ObjectPromptError("invalid_point_label", repr(label))
                if not (_whole(point.get("x")) and _whole(point.get("y"))):
                    raise ObjectPromptError("invalid_point", repr((point.get("x"), point.get("y"))))
                points.append(PromptPoint(point["x"], point["y"], label == "negative"))
            prompts.append(FramePrompt(frame, box, tuple(points)))
        objects.append(PromptObject(ident, tuple(prompts)))
    return build_object_prompt((width, height), objects)


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
