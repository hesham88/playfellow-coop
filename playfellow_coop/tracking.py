"""Follow what SAM found between SAM calls: fast, free, and honest about when to ask SAM again.

SAM finds objects accurately but costs a request each time. Most game pictures differ from the last one only by a small move. So after every SAM answer the tracker keeps a small picture
(a template) of each object, and on each new picture it looks for that template near where the object was (normalised cross-correlation). When every track still matches well, the marks
come from the tracker, with no request and no cost. When any track is lost, matches badly, or has gone a while without SAM confirming it, `needs_sam()` says so and SAM is asked again.

Identity: object ids in a SAM answer are stable inside ONE response only (docs: "key by object id; don't rely on it across entry, exit or occlusion"). Across two separate answers the
tracker keeps a track's id by matching boxes of the same kind by overlap, and gives a new id to a box that matches nothing. Nothing here knows any game.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

Box = tuple[float, float, float, float]  # left, top, right, bottom (half-open), in pixels of the picture given


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _grey(frame) -> np.ndarray:
    array = np.asarray(frame.convert("L") if hasattr(frame, "convert") else frame, dtype=np.float32)
    return array if array.ndim == 2 else array.mean(axis=2)


@dataclass
class Track:
    id: int
    kind: str
    box: Box
    template: np.ndarray = field(repr=False)
    score: float = 1.0  # the last correlation, 0 to 1
    since_sam: int = 0  # local updates since SAM last confirmed this track
    missed: int = 0  # updates in a row that matched badly


class Tracker:
    def __init__(self, min_score: float = 0.7, max_missed: int = 1, refresh_every: int = 12, min_side: int = 4, margin: float = 1.6):
        self.min_score, self.max_missed, self.refresh_every, self.min_side, self.margin = min_score, max_missed, refresh_every, min_side, margin
        self.tracks: list[Track] = []
        self._next = 0
        self.local_updates = 0  # how many pictures were handled without asking SAM (the saving, in requests)

    # ---- SAM answered: confirm, re-identify, and refresh the templates
    def anchor(self, frame, found: list[tuple[str, Box]]) -> None:
        grey = _grey(frame)
        old, new = self.tracks, []
        free = list(old)
        for kind, box in found:
            best, best_iou = None, 0.25
            for track in free:
                if track.kind == kind and iou(track.box, box) > best_iou:
                    best, best_iou = track, iou(track.box, box)
            template = self._crop(grey, box)
            if template is None:
                continue
            if best is not None:
                free.remove(best)
                track_id = best.id
            else:
                track_id, self._next = self._next, self._next + 1
            new.append(Track(track_id, kind, box, template))
        self.tracks = new

    @staticmethod
    def _crop(grey: np.ndarray, box: Box) -> np.ndarray | None:
        h, w = grey.shape
        l, t, r, b = int(max(0, box[0])), int(max(0, box[1])), int(min(w, np.ceil(box[2]))), int(min(h, np.ceil(box[3])))
        if r - l < 2 or b - t < 2:
            return None
        return grey[t:b, l:r].copy()

    # ---- a new picture, no SAM: move every track to where its template matches best
    def update(self, frame) -> list[Track]:
        grey = _grey(frame)
        for track in self.tracks:
            track.since_sam += 1
            box, score = self._match(grey, track)
            track.score = score
            if score >= self.min_score:
                track.box, track.missed = box, 0
            else:
                track.missed += 1
        self.local_updates += 1
        return list(self.tracks)

    def _match(self, grey: np.ndarray, track: Track) -> tuple[Box, float]:
        h, w = grey.shape
        th, tw = track.template.shape
        pad_x, pad_y = int(tw * self.margin) + 2, int(th * self.margin) + 2
        l, t = int(track.box[0]), int(track.box[1])
        x0, y0 = max(0, l - pad_x), max(0, t - pad_y)
        x1, y1 = min(w, l + tw + pad_x), min(h, t + th + pad_y)
        window = grey[y0:y1, x0:x1]
        if window.shape[0] < th or window.shape[1] < tw:
            return track.box, 0.0
        view = np.lib.stride_tricks.sliding_window_view(window, (th, tw))  # (rows, cols, th, tw)
        patches = view.reshape(-1, th * tw)
        tpl = track.template.reshape(-1)
        tpl0 = tpl - tpl.mean()
        patches0 = patches - patches.mean(axis=1, keepdims=True)
        denom = np.sqrt((patches0 ** 2).sum(axis=1) * (tpl0 ** 2).sum())
        flat_tpl = float((tpl0 ** 2).sum()) < 1e-6  # a flat template (one colour) is matched by plain difference instead
        if flat_tpl:
            diff = np.abs(patches - tpl.mean()).mean(axis=1)
            ncc = 1.0 - diff / 255.0
            ncc = np.where(ncc > 0.97, 1.0, ncc)
        else:
            with np.errstate(divide="ignore", invalid="ignore"):
                ncc = np.where(denom > 1e-6, (patches0 * tpl0).sum(axis=1) / denom, -1.0)
        best = int(np.argmax(ncc))
        row, col = divmod(best, view.shape[1])
        left, top = x0 + col, y0 + row
        return (float(left), float(top), float(left + tw), float(top + th)), float(max(0.0, min(1.0, ncc[best])))

    # ---- the honest question
    def needs_sam(self) -> bool:
        """True when there is nothing tracked, a track is lost or matching badly, or a track has gone `refresh_every` updates without SAM confirming it."""
        if not self.tracks:
            return True
        return any(t.missed > self.max_missed or t.score < self.min_score or t.since_sam >= self.refresh_every for t in self.tracks)

    def boxes(self, kind: str | None = None) -> list[tuple[str, Box]]:
        return [(t.kind, t.box) for t in self.tracks if kind is None or t.kind == kind]
