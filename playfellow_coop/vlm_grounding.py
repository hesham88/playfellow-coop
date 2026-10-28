"""Perception grounding by the language model itself (docs: image understanding, "Localize objects with perception grounding").

Muse Spark can say where things are, as boxes, points or counts, on a normalised 0 to 1000 grid over the picture it was sent: (0, 0) top-left, (1000, 1000) bottom-right, x first, y downward,
independent of resolution. It may say 1001 for an object touching the edge, so values are clamped. Anything it cannot find it leaves out. This is the no-SAM way of marking a picture:
one call, no extra request, accurate enough for large things. SAM stays the accurate one for small or crowded things.

The prompts follow the docs: one output shape per request, the objects listed, the system prompt kept minimal, and for boxes the line "You are an object grounding expert" (it measurably improves recall).
Our own code; nothing here calls the service.
"""
from __future__ import annotations

import json
import re

GRID = 1000

BOX_PROMPT = ('You are an object grounding expert. Provide the bounding box coordinates of the objects in the image: {names}. Ensure the objects accurately match the request and do not miss any objects. '
              'For each object, answer in the format {{"object_name": "<name>", "bbox": [{{"x_min": <int>, "y_min": <int>, "x_max": <int>, "y_max": <int>}}]}}. '
              'The coordinates should be in the 0-1000 range. Return a JSON array of results. If you cannot find an object, omit it from the results.')
POINT_PROMPT = ('Point to each of the following objects in the image: {names}. For each object, answer in the format {{"object_name": "<name>", "x": <int>, "y": <int>}}. '
                'The coordinates should be in the 0-1000 range. Return a JSON array of results. If you cannot find an object, omit it from the results.')
COUNT_PROMPT = ('Point to every instance of each of the following objects in the image and count them: {names}. For each object, answer in the format '
                '{{"object_name": "<name>", "points": [{{"x": <int>, "y": <int>}}, ...], "count": <int>}}. The coordinates should be in the 0-1000 range. Return a JSON array of results. '
                'If you cannot find any instances of an object, omit it from the results.')

# a strict JSON schema for the box answer, so the reply parses on the first try (structured output)
BOX_SCHEMA = {"type": "json_schema", "json_schema": {"name": "boxes", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["objects"], "properties": {"objects": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["object_name", "bbox"], "properties": {
            "object_name": {"type": "string"},
            "bbox": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["x_min", "y_min", "x_max", "y_max"], "properties": {
                k: {"type": "integer"} for k in ("x_min", "y_min", "x_max", "y_max")}}}}}}}}}}


def _names(objects: list[str]) -> str:
    clean = [re.sub(r"[^\w \-']", "", o).strip()[:40] for o in objects if o.strip()]
    if not clean:
        raise ValueError("name at least one object")
    return ", ".join(f'"{o}"' for o in clean[:12])


def box_prompt(objects: list[str]) -> str:
    return BOX_PROMPT.format(names=_names(objects))


def point_prompt(objects: list[str]) -> str:
    return POINT_PROMPT.format(names=_names(objects))


def count_prompt(objects: list[str]) -> str:
    return COUNT_PROMPT.format(names=_names(objects))


def clamp(value) -> int:
    return max(0, min(GRID, int(round(float(value)))))


def to_pixels(x: float, y: float, width: int, height: int) -> tuple[int, int]:
    """Normalised 0 to 1000 to pixels of the exact picture that was sent."""
    return round(clamp(x) * width / GRID), round(clamp(y) * height / GRID)


def _json_list(text: str):
    cleaned = re.sub(r"```(?:json)?", "", text or "").strip()
    for candidate in (cleaned, cleaned[cleaned.find("["): cleaned.rfind("]") + 1], cleaned[cleaned.find("{"): cleaned.rfind("}") + 1]):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            data = data.get("objects", [data])
        if isinstance(data, list):
            return data
    return []


def parse_boxes(text: str, width: int, height: int) -> list[dict]:
    """[{name, box: (left, top, right, bottom) in pixels}] from a box answer. A malformed entry is skipped; a missing object is simply absent."""
    out = []
    for item in _json_list(text):
        if not isinstance(item, dict):
            continue
        boxes = item.get("bbox")
        for b in boxes if isinstance(boxes, list) else []:
            try:
                x0, y0 = to_pixels(b["x_min"], b["y_min"], width, height)
                x1, y1 = to_pixels(b["x_max"], b["y_max"], width, height)
            except (KeyError, TypeError, ValueError):
                continue
            if x1 > x0 and y1 > y0:
                out.append({"name": str(item.get("object_name", ""))[:40], "box": (x0, y0, x1, y1)})
    return out


def parse_points(text: str, width: int, height: int) -> list[dict]:
    """[{name, point: (x, y)}] from a point answer, or from a count answer (every instance becomes one entry)."""
    out = []
    for item in _json_list(text):
        if not isinstance(item, dict):
            continue
        name = str(item.get("object_name", ""))[:40]
        points = item.get("points") if isinstance(item.get("points"), list) else [item]
        for p in points:
            try:
                out.append({"name": name, "point": to_pixels(p["x"], p["y"], width, height)})
            except (KeyError, TypeError, ValueError):
                continue
    return out
