"""Pillar 2, reading the screen's own furniture: bars, timers and text, with no knowledge of the game's code.

* `bar_fraction`: how full a health, energy or progress bar is (the share of its length that has the bar's colour), horizontal or vertical.
* `find_bars`: bars nobody told us about: long thin single-colour rectangles.
* `cooldown_fraction`: how much of an icon is dimmed (a cooldown sweep darkens the icon until it is ready again).
* `text_regions`: where the small, high-contrast things that look like text are.
* `GlyphReader`: reads text from letter shapes learned from examples (`fit`), or from a font Pillow can draw (`from_font`): it works on any stylised font you can show it a sample of.
* `ModelReader`: the fallback when the shapes are too odd: hands the crop to a vision model through a callable and returns what it says.
`Hud` ties them together: named regions in, a dict of values out.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

import numpy as np

from playfellow_coop.universal.motion import Box, components, grey

Colour = tuple[int, int, int]


def _crop(frame: np.ndarray, rect: Box) -> np.ndarray:
    left, top, width, height = rect
    return frame[max(top, 0):top + height, max(left, 0):left + width]


def bar_fraction(frame: np.ndarray, rect: Box, colour: Colour, tolerance: int = 40, vertical: bool = False) -> float:
    """0..1: how much of the bar in `rect` is filled. A column (or row, when vertical) counts as filled when at least half of its pixels are near `colour`."""
    area = _crop(frame, rect)
    if area.size == 0:
        return 0.0
    near = (np.abs(area.astype(np.int16) - np.array(colour, dtype=np.int16)) <= tolerance).all(axis=2)
    lines = near.mean(axis=1 if vertical else 0) >= 0.5
    if vertical:
        lines = lines[::-1]  # a vertical bar fills from the bottom
    if not lines.any():
        return 0.0
    # a bar is a filled run from its start: count the run, so a coloured speck at the far end does not read as full
    run = np.argmin(lines) if not lines.all() else len(lines)
    return float(run) / len(lines)


def cooldown_fraction(frame: np.ndarray, rect: Box, ready_frame: np.ndarray) -> float:
    """0..1: how dim the icon in `rect` is compared with the same icon when it was ready (`ready_frame`). 0 = ready, 1 = fully dark."""
    now, ready = _crop(frame, rect), _crop(ready_frame, rect)
    if now.size == 0 or now.shape != ready.shape:
        return 0.0
    base = max(float(grey(ready).mean()), 1.0)
    return float(min(1.0, max(0.0, 1.0 - float(grey(now).mean()) / base)))


def find_bars(frame: np.ndarray, min_length: int = 24, max_thickness: int = 14, min_aspect: float = 4.0, levels: int = 8) -> list[tuple[Box, Colour]]:
    """Long thin one-colour rectangles (health bars and the like) with their colour. Colours are grouped into `levels` steps per channel; grey and black are skipped."""
    small = (frame // (256 // levels)).astype(np.int32)
    keys = small[:, :, 0] * levels * levels + small[:, :, 1] * levels + small[:, :, 2]
    spread = frame.max(axis=2).astype(int) - frame.min(axis=2).astype(int)
    found: list[tuple[Box, Colour]] = []
    for key in np.unique(keys):
        mask = (keys == key) & (spread > 60)
        if mask.sum() < min_length * 2:
            continue
        for blob in components(mask, min_area=min_length * 2):
            left, top, width, height = blob.box
            long_side, short_side = max(width, height), min(width, height)
            if long_side >= min_length and short_side <= max_thickness and long_side / max(short_side, 1) >= min_aspect and blob.area >= 0.7 * width * height:
                colour = tuple(int(v) for v in frame[top + height // 2, left + width // 2])
                found.append((blob.box, colour))
    return sorted(found, key=lambda item: (item[0][1], item[0][0]))


def text_regions(frame: np.ndarray, min_height: int = 6, max_height: int = 40, gap: int = 6) -> list[Box]:
    """Places that look like lines of text: dense small edges, joined sideways across letter gaps, thin enough to be a line, not a bar."""
    g = grey(frame)
    edges = np.zeros(g.shape, dtype=bool)
    edges[:, 1:] |= np.abs(np.diff(g, axis=1)) > 60
    edges[1:, :] |= np.abs(np.diff(g, axis=0)) > 60
    wide = edges.copy()
    for step in range(1, gap + 1):  # smear sideways so the letters of one word join
        wide[:, step:] |= edges[:, :-step]
    boxes = []
    for blob in components(wide, min_area=12):
        left, top, width, height = blob.box
        if not (min_height <= height <= max_height and width >= height // 2):
            continue
        density = edges[top:top + height, left:left + width].mean()
        if 0.08 <= density <= 0.6:
            boxes.append((left, top, width, height))
    return boxes


class Reader(Protocol):
    def read(self, crop: np.ndarray) -> str: ...


def _binarise(crop: np.ndarray) -> np.ndarray:
    """Letters as True: the side of the middle grey that is the minority (text is the rarer colour)."""
    g = grey(crop)
    low, high = float(g.min()), float(g.max())
    if high - low < 30:
        return np.zeros(g.shape, dtype=bool)
    ink = g > (low + high) / 2
    return ink if ink.mean() <= 0.5 else ~ink


def _glyph_columns(ink: np.ndarray) -> list[tuple[int, int]]:
    """Column spans of single letters: gaps between letters split the line; two letters that touch (a span wider than a letter is tall) are cut where the ink is thinnest."""
    columns = ink.any(axis=0)
    spans, start = [], None
    for x, on in enumerate(np.append(columns, False)):
        if on and start is None:
            start = x
        elif not on and start is not None:
            spans.append((start, x))
            start = None
    rows = np.flatnonzero(ink.any(axis=1))
    height = int(rows[-1] - rows[0] + 1) if len(rows) else 0
    out: list[tuple[int, int]] = []
    pending = list(spans)
    while pending:
        start, end = pending.pop(0)
        width = end - start
        if height and width > 1.15 * height and width >= 8:
            low, high = start + int(0.4 * height), end - int(0.4 * height)
            if high > low:
                ink_per_column = ink[:, low:high].sum(axis=0)
                cut = low + int(np.argmin(ink_per_column))
                pending[0:0] = [(start, cut), (cut, end)]
                continue
        out.append((start, end))
    return out


def _squash(ink: np.ndarray, size: tuple[int, int] = (14, 20)) -> np.ndarray:
    ys, xs = np.nonzero(ink)
    if len(xs) == 0:
        return np.zeros(size[::-1], dtype=np.float32)
    ink = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32)
    from playfellow_coop.universal.frames import resize
    return resize(np.repeat(ink[:, :, None] * 255, 3, axis=2).astype(np.uint8), size[0], size[1])[:, :, 0].astype(np.float32) / 255.0


class GlyphReader:
    """Reads text by matching each letter's shape to learned examples. Learn from your own samples (`fit`) or from a font Pillow can draw (`from_font`)."""

    def __init__(self):
        self.templates: list[tuple[str, np.ndarray]] = []

    def fit(self, samples: dict[str, list[np.ndarray]]) -> "GlyphReader":
        """`samples`: character -> pictures of that character (one letter each)."""
        for char, crops in samples.items():
            for crop in crops:
                self.templates.append((char, _squash(_binarise(crop))))
        return self

    @classmethod
    def from_font(cls, characters: str = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz:/%+-.", font=None, scales: tuple[int, ...] = (1, 2, 3)) -> "GlyphReader":
        from PIL import Image, ImageDraw, ImageFont
        font = font or ImageFont.load_default()
        samples: dict[str, list[np.ndarray]] = {}
        for char in characters:
            for scale in scales:
                image = Image.new("RGB", (24, 24), (0, 0, 0))
                ImageDraw.Draw(image).text((4, 4), char, fill=(255, 255, 255), font=font)
                if scale > 1:
                    image = image.resize((24 * scale, 24 * scale), Image.NEAREST)
                samples.setdefault(char, []).append(np.asarray(image))
        return cls().fit(samples)

    def read(self, crop: np.ndarray) -> str:
        ink = _binarise(crop)
        spans = _glyph_columns(ink)
        if not spans or not self.templates:
            return ""
        widths = [e - s for s, e in spans]
        typical = float(np.median(widths))
        text, previous_end = "", None
        for (start, end) in spans:
            if previous_end is not None and start - previous_end > max(typical * 1.6, 3):
                text += " "
            previous_end = end
            glyph = _squash(ink[:, start:end])
            best = min(self.templates, key=lambda item: float(np.abs(item[1] - glyph).mean()))
            text += best[0]
        return text


class ModelReader:
    """The fallback: a vision model reads the crop. `ask(crop) -> str` is any callable (a brain's image question, or a fake in tests)."""

    def __init__(self, ask: Callable[[np.ndarray], str]):
        self.ask = ask

    def read(self, crop: np.ndarray) -> str:
        return str(self.ask(crop)).strip()


def read_number(text: str) -> float | None:
    """A number from text such as "HP 87/100" (87), "1,250" (1250), "x3" (3); None when there are no digits. Common look-alikes (O, l, I) next to digits are repaired."""
    cleaned = "".join("0" if c in "Oo" else "1" if c in "lI" else c for c in text) if any(c.isdigit() for c in text) else text
    digits, number = [], ""
    for char in cleaned + " ":
        if char.isdigit() or (char in ".," and number and char):
            number += char
        else:
            if number:
                digits.append(number)
            number = ""
    if not digits:
        return None
    first = digits[0].replace(",", "")
    try:
        return float(first)
    except ValueError:
        return None


@dataclass
class Region:
    rect: Box
    kind: str = "text"  # "bar", "vbar", "number", "text", "cooldown"
    colour: Colour = (200, 40, 40)
    tolerance: int = 40


@dataclass
class Hud:
    """Named screen regions in, values out. Bars give 0..1, numbers give a float, text gives a string, cooldowns give 0..1 (0 = ready)."""
    regions: dict[str, Region] = field(default_factory=dict)
    reader: Reader | None = None
    ready: dict[str, np.ndarray] = field(default_factory=dict)  # the picture when each cooldown was ready

    def read(self, frame: np.ndarray) -> dict[str, float | str | None]:
        values: dict[str, float | str | None] = {}
        for name, region in self.regions.items():
            if region.kind in ("bar", "vbar"):
                values[name] = bar_fraction(frame, region.rect, region.colour, region.tolerance, vertical=region.kind == "vbar")
            elif region.kind == "cooldown":
                ready = self.ready.setdefault(name, frame)
                values[name] = cooldown_fraction(frame, region.rect, ready)
            elif self.reader is None:
                values[name] = None
            else:
                text = self.reader.read(_crop(frame, region.rect))
                values[name] = read_number(text) if region.kind == "number" else text
        return values
