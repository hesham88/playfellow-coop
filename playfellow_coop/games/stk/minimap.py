"""Reading the race minimap: where the buddy's kart is, in the game's own world coordinates.

The game draws the minimap with one uniform scale, world X to the right and world Z upwards, anchored at the bottom-left
(src/tracks/graph.cpp mapPoint2MiniMap, src/states_screens/race_gui.cpp drawGlobalMiniMap in stk-code):
    size  = minimap_size (config, 180) * min(view height, view width) / 480
    scale = size / max(track width, track depth)          (the bounding box of every road quad)
    x_px  = left  + (X - min X) * scale
    y_px  = lower - (Z - min Z) * scale
`left` and `lower` are 10 px (scaled) in from the view's bottom-left corner. A local player's icon sits in a coloured frame
(red for player one), which is how the buddy finds itself among the AI karts' smaller, frameless icons.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from playfellow_coop.games.stk.track import Track


@dataclass
class MapGeometry:
    left: float
    lower: float
    scale: float
    bb_min: np.ndarray
    size: float
    view_w: int = 0
    view_h: int = 0
    origin: tuple[int, int] = (0, 0)

    @classmethod
    def for_view(cls, track: Track, view_w: int, view_h: int, minimap_size: float = 180.0, origin: tuple[int, int] = (0, 0)) -> "MapGeometry":
        unit = min(view_w, view_h) / 480.0
        size = minimap_size * unit
        dx, dz = track.bb_max - track.bb_min
        return cls(origin[0] + 10.0 * unit, origin[1] + view_h - 10.0 * unit, size / max(dx, dz), track.bb_min.copy(), size, view_w, view_h, origin)

    def to_pixel(self, xz: np.ndarray) -> np.ndarray:
        xz = np.asarray(xz, dtype=float)
        return np.stack([self.left + (xz[..., 0] - self.bb_min[0]) * self.scale, self.lower - (xz[..., 1] - self.bb_min[1]) * self.scale], -1)

    def to_world(self, px: np.ndarray) -> np.ndarray:
        px = np.asarray(px, dtype=float)
        return np.stack([(px[..., 0] - self.left) / self.scale + self.bb_min[0], (self.lower - px[..., 1]) / self.scale + self.bb_min[1]], -1)

    def box(self, pad: float = 24.0) -> tuple[int, int, int, int]:
        """The minimap's square on screen (x0, y0, x1, y1), padded for icons that hang over the edge."""
        return (int(self.left - pad), int(self.lower - self.size - pad), int(self.left + self.size + pad), int(self.lower + pad))


def frame_mask(bgr: np.ndarray, colour: str = "red") -> np.ndarray:
    b, g, r = (bgr[..., i].astype(np.int16) for i in range(3))
    if colour == "red":
        return (r > 160) & (g < 70) & (b < 70)
    if colour == "blue":
        return (b > 160) & (r < 70) & (g < 140)
    if colour == "green":
        return (g > 150) & (r < 90) & (b < 90)
    if colour == "yellow":
        return (r > 190) & (g > 170) & (b < 60)
    raise ValueError(colour)


def find_icon(bgr: np.ndarray, geo: MapGeometry, colour: str = "red", expect: float | None = None, track: Track | None = None,
              near: tuple[float, float] | None = None, radius: float = 80.0, cold: bool = True) -> tuple[float, float] | None:
    """Centre (screen-pixel x, y inside `bgr`) of the ring-shaped frame of a local player's icon on the minimap, or None.
    A ring: a blob about the icon's size, roughly square, hollow (thin: under 45% of its box is frame-coloured). With `track`,
    a ring must also sit on the road (within twice the road width of the driveline), which rules out red things in the 3D view
    behind the minimap, such as the kart's own paint."""
    def inside(ring):  # an icon's centre is always drawn on the map square itself; the pad only lets its edge hang over
        x, y = ring[0]
        return geo.left - 4 <= x <= geo.left + geo.size + 4 and geo.lower - geo.size - 4 <= y <= geo.lower + 4

    rings = [r for r in (find_rings(bgr, geo, colour, expect, threshold=0.30, near=near, radius=radius) if near is not None else []) if inside(r)]
    rings = [r for r in rings if np.hypot(r[0][0] - near[0], r[0][1] - near[1]) <= radius]
    if rings:
        return min(rings, key=lambda r: np.hypot(r[0][0] - near[0], r[0][1] - near[1]))[0]
    if near is not None and not cold:
        return None  # tracking: nothing where the kart can physically be; better lost than wrong
    rings = [r for r in find_rings(bgr, geo, colour, expect, threshold=0.32) if inside(r)]
    h, w = bgr.shape[:2]
    clear = [r for r in rings if not in_kart_zone(r[0], geo)]
    rings = clear or rings  # the kart model behind the map makes ring-like shapes; a cold search trusts them last
    if track is not None and len(rings) > 1:
        # several rings: the one on the road wins (a kart can leave the road, so a lone ring is never thrown away)
        def on_road(ring):
            xz = geo.to_world(np.array(ring[0]))
            d = np.linalg.norm(track.centre - xz, axis=1)
            i = int(np.argmin(d))
            return ring[1] - 0.02 * max(0.0, d[i] - track.width[i])
        rings = sorted(rings, key=on_road, reverse=True)[:1]
    return max(rings, key=lambda r: r[1])[0] if rings else None


ICON_FILE_SCALE = 0.95  # the icon file's size inside the map icon's circle (fitted on the 4 Nov Puffy race frames)
SHAPED_RMS = 48.0  # backdrop-free looks: 5 Nov, on the 3 Nov winning race video the learned look scored 26 typical / 45 worst on true sightings; icon-file look 34, menus 44-60
MATCH_RMS = 60.0  # mean colour distance (0-255) under which a patch IS the learned icon; measured: true icon 35-44, best wrong patch 82+


def without_backdrop(template: np.ndarray) -> np.ndarray:
    """A mask of the icon itself (the red ring and the kart's face), without the bit of map that was behind it when the look
    was learned. 5 Nov: a look learned on a teal stretch matched other teal stretches and the buddy thought it was across the
    track, steering into the right-hand wall; the backdrop is different at every place on the map, so it must not count."""
    size = template.shape[0]
    r = size // 2
    yy, xx = np.mgrid[:size, :size] - r
    dist = np.hypot(xx, yy)
    disc = dist <= r - 1.0
    ring_band = (dist > r - 4.5) & disc
    inner = dist <= r - 4.5
    t = template.astype(np.int32)
    redness = t[:, :, 2] - np.maximum(t[:, :, 0], t[:, :, 1])
    ring = ring_band & (redness > 60)
    edge = inner & (dist > r - 7.5)  # just inside the ring: mostly backdrop
    backdrop = np.median(template[edge], axis=0) if edge.any() else np.zeros(3)
    face = inner & (np.abs(t - backdrop.astype(np.int32)).sum(axis=2) > 60)
    keep = (ring | face).astype(np.uint8)
    if keep.sum() < 30:  # not enough left to be sure: fall back to the whole disc
        keep = disc.astype(np.uint8)
    return cv2.merge([keep, keep, keep])


@dataclass
class IconModel:
    """What the buddy's own minimap icon looks like, learned once from a confident sighting (the icon is drawn opaque over the
    map, so its pixels do not depend on what is behind it). Finding it again is masked template matching, which a red patch
    of the kart's paint or chrome cannot pass."""

    template: np.ndarray  # BGR, (2r+1, 2r+1)
    mask: np.ndarray  # uint8 BGR mask, the disc inside the frame (or the icon's own opaque pixels when `shaped`)
    shaped: bool = False

    @classmethod
    def learn(cls, bgr: np.ndarray, centre: tuple[float, float], unit: float) -> "IconModel | None":
        r = int(round(9.0 * unit))
        cx, cy = int(round(centre[0])), int(round(centre[1]))
        if cy - r < 0 or cx - r < 0 or cy + r + 1 > bgr.shape[0] or cx + r + 1 > bgr.shape[1]:
            return None
        crop = bgr[cy - r:cy + r + 1, cx - r:cx + r + 1].copy()
        return cls(crop, without_backdrop(crop), shaped=True)

    @classmethod
    def load(cls, path) -> "IconModel | None":
        data = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if data is None:
            return None
        return cls(data, without_backdrop(data), shaped=True)

    @classmethod
    def from_game_icon(cls, icon_file, r: int = 18, scale: float = ICON_FILE_SCALE) -> "IconModel | None":
        """The look of any kart's minimap icon, made from the game's own icon file (kart.xml minimap-icon-file). Only the
        icon's own opaque pixels are compared: what is around it on the map differs (4 Nov: Tux's learned look had a red
        disc, Puffy in a race had a green ring and the map showing through, so a look with a backdrop never matched)."""
        data = cv2.imread(str(icon_file), cv2.IMREAD_UNCHANGED)
        if data is None:
            return None
        size = 2 * r + 1
        s = max(3, min(size, int(round(size * scale))))
        icon = cv2.resize(data, (s, s), interpolation=cv2.INTER_AREA)
        out = np.zeros((size, size, 3), np.uint8)
        mask = np.zeros((size, size), np.uint8)
        o = (size - s) // 2
        out[o:o + s, o:o + s] = icon[:, :, :3]
        opaque = (icon[:, :, 3] > 200) if icon.shape[2] == 4 else np.ones((s, s), bool)
        mask[o:o + s, o:o + s] = cv2.erode(opaque.astype(np.uint8), np.ones((3, 3), np.uint8))  # edges blend with the map
        return cls(out, cv2.merge([mask, mask, mask]), shaped=True)

    def save(self, path) -> None:
        cv2.imwrite(str(path), self.template)

    def at_unit(self, unit: float) -> "IconModel":
        """This look at another map scale (itself when the size already fits)."""
        r = int(round(9.0 * unit))
        if r == self.template.shape[0] // 2:
            return self
        cache = self.__dict__.setdefault("_scaled", {})
        if r not in cache:
            size = 2 * r + 1
            template = cv2.resize(self.template, (size, size), interpolation=cv2.INTER_AREA)
            if self.shaped:  # a look made from the game's icon file: keep its own outline, not a full disc
                mask = (cv2.resize(self.mask, (size, size), interpolation=cv2.INTER_NEAREST) > 0).astype(np.uint8)
                cache[r] = IconModel(template, mask, shaped=True)
            else:
                yy, xx = np.mgrid[:size, :size] - r
                disc = (np.hypot(xx, yy) <= r - 1.0).astype(np.uint8)
                cache[r] = IconModel(template, cv2.merge([disc, disc, disc]))
        return cache[r]

    def match(self, bgr: np.ndarray, geo: MapGeometry, near: tuple[float, float] | None = None, radius: float = 40.0,
              max_rms: float = MATCH_RMS) -> tuple[tuple[float, float], float] | None:
        """(centre, rms) of the best match on the map (or within `radius` of `near`), None when nothing passes. The template
        is resized to this map's scale first (its radius is 9 units of the map it was learned on), so a look learned in one
        window size still works in another."""
        scaled = self.at_unit(geo.size / 180.0)
        if scaled is not self:
            return scaled.match(bgr, geo, near, radius, max_rms)
        r = self.template.shape[0] // 2
        x0, y0, x1, y1 = geo.box()
        if near is not None:
            x0, y0 = max(x0, int(near[0] - radius - r)), max(y0, int(near[1] - radius - r))
            x1, y1 = min(x1, int(near[0] + radius + r + 1)), min(y1, int(near[1] + radius + r + 1))
        h, w = bgr.shape[:2]
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
        if x1 - x0 <= 2 * r + 1 or y1 - y0 <= 2 * r + 1:
            return None
        res = cv2.matchTemplate(bgr[y0:y1, x0:x1], self.template, cv2.TM_SQDIFF, mask=self.mask)
        best, _, (bx, by), _ = cv2.minMaxLoc(res)
        rms = float(np.sqrt(max(best, 0.0) / (self.mask.sum())))
        if rms > (min(max_rms, SHAPED_RMS) if self.shaped else max_rms):
            return None
        return (x0 + bx + r, y0 + by + r), rms


def outline_score(grey: np.ndarray, track: Track, left: float, lower: float, scale: float, unit: float, offset: float = 7.0) -> float:
    """How well the driveline, placed at (left, lower) with `scale` px per metre, lies on the map's light outline."""
    c = track.centre
    pts = np.stack([left + (c[:, 0] - track.bb_min[0]) * scale, lower - (c[:, 1] - track.bb_min[1]) * scale], 1)
    d = np.roll(pts, -1, axis=0) - pts
    side = np.stack([-d[:, 1], d[:, 0]], 1) / np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-6) * offset * unit
    h, w = grey.shape

    def sample(p):
        x, y = p[:, 0].round().astype(int), p[:, 1].round().astype(int)
        ok = (x >= 0) & (x < w) & (y >= 0) & (y < h)
        out = np.full(len(p), np.nan, dtype=np.float32)
        out[ok] = grey[y[ok], x[ok]]
        return out

    diff = sample(pts) - np.fmax(sample(pts + side), sample(pts - side))
    if np.isnan(diff).mean() > 0.2:  # most of the loop must be inside the view
        return -999.0
    return float(np.nanmedian(diff))


def calibrate(bgr: np.ndarray, track: Track, sizes=(180.0,), view: tuple[int, int, int, int] | None = None, origin=(0, 0)) -> tuple[MapGeometry, float]:
    """Find where this track's minimap is drawn in this view (bottom-left, right side, centre, a split-screen quarter):
    the place and size where the driveline best lies on the light outline. A coarse search over the whole view, then a fine
    one around the best. Returns the geometry and its outline score (above ~12: the map is there)."""
    grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = grey.shape
    vx0, vy0, vx1, vy1 = view or (0, 0, w, h)
    vw, vh = vx1 - vx0, vy1 - vy0
    dx, dz = track.bb_max - track.bb_min
    best = (-999.0, None)
    for size_cfg in sizes:
        unit = min(vw, vh) / 480.0
        size = size_cfg * unit
        scale = size / max(dx, dz)
        span_x, span_z = dx * scale, dz * scale
        for step, xs, ys in [(6, range(int(vx0), int(vx1 - span_x) + 1, 6), range(int(vy0 + span_z), int(vy1) + 1, 6))]:
            for left in xs:
                for lower in ys:
                    s = outline_score(grey, track, left, lower, scale, unit)
                    if s > best[0]:
                        best = (s, (left, lower, scale, unit, size))
    if best[1] is None:
        return MapGeometry.for_view(track, w, h), -999.0
    left0, lower0, scale, unit, size = best[1]
    fine = best
    for left in range(left0 - 6, left0 + 7):
        for lower in range(lower0 - 6, lower0 + 7):
            s = outline_score(grey, track, left, lower, scale, unit)
            if s > fine[0]:
                fine = (s, (left, lower, scale, unit, size))
    left, lower, scale, unit, size = fine[1]
    geo = MapGeometry(float(left), float(lower), scale, track.bb_min.copy(), size, vw, vh, (vx0, vy0))
    return geo, fine[0]


def map_visible(bgr: np.ndarray, geo: MapGeometry, track: Track, offset: float = 7.0, threshold: float = 12.0) -> bool:
    """Is this track's minimap on screen? The map's road outline is drawn light over the scene, so pixels on the projected
    driveline are brighter than pixels a few units to the side. Menus and result screens have no such line. Pixels covered by
    the icon or a message box only lower the contrast a little; the whole loop is sampled."""
    pts = geo.to_pixel(track.centre)
    nxt = np.roll(pts, -1, axis=0)
    d = nxt - pts
    norm = np.linalg.norm(d, axis=1, keepdims=True)
    side = np.stack([-d[:, 1], d[:, 0]], 1) / np.maximum(norm, 1e-6) * offset * (geo.size / 180.0)
    grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = grey.shape

    def sample(p):
        x = np.clip(p[:, 0].round().astype(int), 0, w - 1)
        y = np.clip(p[:, 1].round().astype(int), 0, h - 1)
        return grey[y, x]

    on = sample(pts)
    off = np.maximum(sample(pts + side), sample(pts - side))
    return float(np.median(on - off)) > threshold


def in_kart_zone(point: tuple[float, float], geo: MapGeometry) -> bool:
    """Is this pixel where the buddy's own kart model is always drawn (bottom centre of its view, 31-69% across, 48-80% down)?
    The view's size is recovered from the map geometry (the map is 10 units in from the bottom-left corner)."""
    x0, y0 = geo.origin
    x, y = point
    return x0 + 0.31 * geo.view_w <= x <= x0 + 0.69 * geo.view_w and y0 + 0.48 * geo.view_h <= y <= y0 + 0.80 * geo.view_h


def ring_kernel(unit: float) -> np.ndarray:
    """+1 shared over the icon frame's ring (radius 6.5-9.5 units), -1 shared over its inside (radius < 5.5): a ring scores
    near 1, a solid red patch (a kart's paint) near 0, whatever touches the ring from outside."""
    r_out, r_in, r_hole = 9.8 * unit, 6.2 * unit, 5.2 * unit
    size = int(np.ceil(r_out)) * 2 + 1
    yy, xx = np.mgrid[:size, :size] - size // 2
    rr = np.hypot(xx, yy)
    ring, hole = (rr <= r_out) & (rr >= r_in), rr < r_hole
    return (ring / ring.sum() - hole / hole.sum()).astype(np.float32)


def find_rings(bgr: np.ndarray, geo: MapGeometry, colour: str = "red", expect: float | None = None, threshold: float = 0.42,
               near: tuple[float, float] | None = None, radius: float = 80.0) -> list[tuple[tuple[float, float], float]]:
    """Ring-shaped frames of the given colour on the minimap (centre in `bgr` pixels, score 0-1), found by matching a ring
    kernel against the colour mask, so a ring touching other red (the kart's spoiler behind the map) is still found.
    With `near`, only that neighbourhood is searched (tracking: faster, and nothing far away can steal the match)."""
    x0, y0, x1, y1 = geo.box()
    if near is not None:
        x0, y0, x1, y1 = max(x0, int(near[0] - radius)), max(y0, int(near[1] - radius)), min(x1, int(near[0] + radius)), min(y1, int(near[1] + radius))
    h, w = bgr.shape[:2]
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return []
    unit = (expect / 20.0) if expect else geo.size / 180.0
    mask = frame_mask(bgr[y0:y1, x0:x1], colour).astype(np.float32)
    score = cv2.filter2D(mask, -1, ring_kernel(unit), borderType=cv2.BORDER_CONSTANT)
    found = []
    work = score.copy()
    for _ in range(4):  # the best few separate peaks
        _, best, _, (bx, by) = cv2.minMaxLoc(work)
        if best < threshold:
            break
        found.append(((x0 + float(bx), y0 + float(by)), float(best)))
        cv2.circle(work, (bx, by), int(12 * unit), -1.0, -1)
    return found


def find_blobs(bgr: np.ndarray, geo: MapGeometry, colour: str = "red", expect: float | None = None) -> list[tuple[tuple[float, float], float]]:
    """Every ring-shaped blob of the frame colour on the minimap, with a score (bigger is more ring-like)."""
    x0, y0, x1, y1 = geo.box()
    h, w = bgr.shape[:2]
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    mask = frame_mask(bgr[y0:y1, x0:x1], colour).astype(np.uint8)
    count, _, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    unit = geo.size / 180.0
    size = expect or 20.0 * unit
    found = []
    for i in range(1, count):
        x, y, bw, bh, area = stats[i]
        if not (0.55 * size <= bw <= 1.4 * size and 0.55 * size <= bh <= 1.4 * size):
            continue
        if not 0.75 <= bw / max(bh, 1) <= 1.33:
            continue
        fill = area / float(bw * bh)
        if fill > 0.45 or area < 0.08 * size * size:
            continue
        # the ring's centroid: sub-pixel, steadier than its box
        found.append(((x0 + float(cents[i][0]), y0 + float(cents[i][1])), (1.0 - abs(1.0 - bw / max(bh, 1))) * (1.0 - abs(fill - 0.25))))
    return found
