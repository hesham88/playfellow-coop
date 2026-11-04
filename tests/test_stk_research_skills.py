"""The skills built from the 4 Nov research (game source + data), proven offline: bend speed from the kart's turning circle,
skids planned per bend with the game's three skid levels, the item line from the track's own items, the kart's minimap look
made from the game's icon file. These prove the logic, not a race win."""
import math

import numpy as np
import pytest

from playfellow_coop.games.stk.drive import (Driver, Keys, SKID_BONUS_TIME, SKID_RED_TIME, skid_level, turn_radius)
from playfellow_coop.games.stk.track import Track, TrackItem


def ring_track(radius: float = 60.0, points: int = 240, width: float = 10.0) -> Track:
    """A circle of quads, anti-clockwise in world X, Z: one long bend of the given radius."""
    quads = []
    for i in range(points):
        a0, a1 = 2 * math.pi * i / points, 2 * math.pi * (i + 1) / points
        def p(a, r):
            return np.array([r * math.cos(a), 0.0, r * math.sin(a)])
        quads.append(np.stack([p(a0, radius + width / 2), p(a1, radius + width / 2), p(a1, radius - width / 2), p(a0, radius - width / 2)]))
    corners = np.concatenate(quads)[:, [0, 2]]
    centre = np.array([q[:, [0, 2]].mean(axis=0) for q in quads])
    return Track("ring", quads, list(range(points)), centre, np.full(points, width), corners.min(axis=0), corners.max(axis=0))


def straight_then_bend() -> Track:
    """200 m straight along +X, then a 90 degree anti-clockwise bend of radius 30 m, then 200 m straight along +Z, closed back."""
    pts = [np.array([x, 0.0]) for x in np.arange(0, 200, 2.0)]
    for a in np.linspace(0, math.pi / 2, 24)[1:]:
        pts.append(np.array([200 + 30 * math.sin(a), 30 - 30 * math.cos(a)]))
    pts += [np.array([230.0, z]) for z in np.arange(32, 230, 2.0)]
    for a in np.linspace(0, math.pi, 40)[1:-1]:  # a wide turn back to the start
        pts.append(np.array([115 + 115 * math.cos(a), 230 + 60 * math.sin(a)]))
    pts += [np.array([0.0, z]) for z in np.arange(228, 0, -2.0)]
    centre = np.array(pts)
    quads = [np.stack([np.array([c[0], 0, c[1]])] * 4) for c in centre]
    return Track("bend", quads, list(range(len(centre))), centre, np.full(len(centre), 10.0), centre.min(axis=0) - 5, centre.max(axis=0) + 5)


def test_turning_circle_comes_from_the_game_table():
    assert turn_radius(10.0, "medium") == pytest.approx(8.625)
    assert turn_radius(25.0, "heavy") == pytest.approx(19.5)
    assert turn_radius(20.0, "medium") == pytest.approx(8.625 + 10 * (17.25 - 8.625) / 15)


def test_skid_levels_are_the_games_three():
    assert skid_level(0.9) == 1 and skid_level(0.5) == 0 and skid_level(0.1) == -1


def test_the_bends_are_found_with_their_radius():
    bends = Track.corners(straight_then_bend())
    first = bends[0]
    assert first.side == 1 and first.radius == pytest.approx(30.0, rel=0.25) and math.degrees(first.angle) == pytest.approx(90, abs=15)


def drive_through(driver: Driver, path, speed: float, hz: float = 20.0):
    """Feed positions along a path at a steady speed; return the key sets."""
    out, t = [], 0.0
    for p in path:
        out.append(driver.step(t, np.asarray(p, float)))
        t += 1.0 / hz
    return out


def path_along(track: Track, speed: float, seconds: float, hz: float = 20.0):
    d = Driver(track)
    pts, s = [], 0.0
    for _ in range(int(seconds * hz)):
        i = int(np.searchsorted(d._cum, s % d.lap_length, side="right") - 1)
        a, b = track.centre[i], track.centre[(i + 1) % len(track.centre)]
        seg = d._seg[i]
        pts.append(a + (b - a) * ((s % d.lap_length - d._cum[i]) / seg if seg else 0))
        s += speed / hz
    return pts


def test_a_wide_bend_is_taken_at_full_throttle():
    track = ring_track(radius=60.0)
    driver = Driver(track, skid_enabled=False)
    keys = drive_through(driver, path_along(track, 20.0, 4.0), 20.0)
    assert all("up" in k for k in keys[10:])  # 60 m bend: wider than the kart's 14 m circle at 20 m/s
    assert not any("down" in k for k in keys)


def test_a_bend_tighter_than_the_kart_makes_it_lift():
    track = ring_track(radius=9.0, points=120, width=6.0)
    driver = Driver(track, skid_enabled=False)
    keys = drive_through(driver, path_along(track, 20.0, 2.0), 20.0)
    assert any("up" not in k for k in keys[10:])


def test_a_long_bend_gets_a_red_skid_steered_with_the_three_levels():
    track = ring_track(radius=30.0)  # inside the skid band: the middle skid level (0.5) follows a 30 m bend at 20 m/s
    driver = Driver(track)
    keys = drive_through(driver, path_along(track, 20.0, 6.0), 20.0)
    held = [k for k in keys if "v" in k]
    assert held and driver.skid_target == SKID_RED_TIME
    assert len(held) / 20.0 >= SKID_RED_TIME  # held at least long enough for the red bonus
    starts = [e for e in driver.log if len(e) == 4 and e[1] == "drift"]
    assert len(starts) == 1  # one skid for the bend this lap, not a new one every look


def test_no_skid_on_a_bend_too_wide_for_the_middle_skid_level():
    track = ring_track(radius=80.0)
    driver = Driver(track)
    drive_through(driver, path_along(track, 20.0, 6.0), 20.0)
    assert not [e for e in driver.log if len(e) == 4 and e[1] == "drift"]


def test_a_skid_ends_with_no_counter_steer():
    track = straight_then_bend()
    driver = Driver(track)
    keys = drive_through(driver, path_along(track, 20.0, 14.0), 20.0)
    ends = [e for e in driver.log if len(e) == 4 and e[1] == "drift end"]
    assert ends and ends[0][3] in ("yellow", "red")
    t_end = ends[0][0]
    after = keys[int(round(t_end * 20)) + 1:int(round(t_end * 20)) + 4]
    assert all("left" not in k and "right" not in k for k in after)


def test_a_short_bend_gets_no_skid():
    driver = Driver(straight_then_bend())
    bend = driver.bends[0]
    assert bend.arc / 20.0 >= SKID_BONUS_TIME  # 47 m of bend at 20 m/s: 2.4 s, a yellow
    driver.bends = [type(bend)(bend.first, bend.last, bend.s0, bend.s0 + 15.0, bend.side, bend.angle, 15.0, bend.radius, bend.width)]
    drive_through(driver, path_along(driver.track, 20.0, 12.0), 20.0)
    assert not [e for e in driver.log if len(e) == 4 and e[1] == "drift"]


def items_row(s: float, kinds_offsets):
    return [TrackItem(k, np.zeros(2), 0, s, off) for k, off in kinds_offsets]


def settle(driver, looks: int = 20) -> float:
    """The line after a second of looks while the items are still ahead (it moves 0.4 m a look)."""
    y = 0.0
    for _ in range(looks):
        y = driver.plan_line(10.0, half_width=5.0)
    return y


def test_the_line_takes_a_side_box_and_stays_clear_of_the_banana():
    driver = Driver(straight_then_bend())
    driver.items = items_row(40.0, [("item", 4.0), ("banana", 0.0), ("item", -4.0)])
    y = settle(driver)
    assert abs(abs(y) - 4.0) <= 1.1 and abs(y) >= 2.2  # on a straight: the side box itself, far from the banana


def test_with_a_power_in_hand_boxes_stop_pulling():
    driver = Driver(straight_then_bend())
    driver.items = items_row(40.0, [("item", 4.0)])
    driver.held_power = "zipper"
    assert abs(settle(driver)) < 0.5


def test_nitro_cans_pull_the_line():
    driver = Driver(straight_then_bend())
    driver.items = items_row(40.0, [("small-nitro", -2.0)])
    assert settle(driver) == pytest.approx(-2.0, abs=0.5)
    driver = Driver(straight_then_bend())
    driver.items = items_row(40.0, [("small-nitro", -3.5)])
    assert settle(driver) == pytest.approx(-3.5, abs=0.6)  # on a straight the line reaches it (4 Nov: most Abyss cans are 2-4 m out)


def test_near_a_bend_the_line_stays_within_its_bend_limit():
    from playfellow_coop.games.stk.drive import LINE_LIMIT

    driver = Driver(straight_then_bend())
    bend = driver.bends[0]
    driver.items = items_row(bend.s0 + 10.0, [("item", 4.0)])
    y = 0.0
    for _ in range(20):
        y = driver.plan_line(bend.s0 - 20.0, half_width=5.0)
    assert abs(y) <= LINE_LIMIT + 1e-9


def test_the_real_abyss_items_and_bends_load():
    from playfellow_coop.games.stk.paths import game_data
    from playfellow_coop.games.stk.track import load_items

    if not (game_data() / "tracks" / "abyss" / "scene.xml").exists():
        pytest.skip("the game is not installed here")
    track = Track.load("abyss")
    items = load_items(track)
    kinds = {k: sum(1 for i in items if i.kind == k) for k in ("item", "small-nitro", "big-nitro", "banana")}
    assert kinds == {"item": 14, "small-nitro": 7, "big-nitro": 1, "banana": 6}
    assert all(abs(i.offset) < 6.0 for i in items)
    bends = track.corners()
    assert len(bends) == 8 and min(b.radius for b in bends) > 25.0  # every Abyss bend is wider than any kart's circle


def test_a_kart_icon_made_from_the_game_file_looks_like_the_live_one():
    cv2 = pytest.importorskip("cv2")
    from pathlib import Path

    from playfellow_coop.games.stk.minimap import IconModel, MATCH_RMS
    from playfellow_coop.games.stk.paths import PRESKILLS, game_data, kart_info

    learned = PRESKILLS / "icon-kart.png"
    tux = kart_info("tux").get("icon")
    if not learned.exists() or tux is None or not Path(tux).exists():
        pytest.skip("needs the live-learned icon and the installed game")
    live = cv2.imread(str(learned), cv2.IMREAD_COLOR).astype(np.float32)
    model = IconModel.from_game_icon(tux, r=live.shape[0] // 2)
    made = model.template.astype(np.float32)
    shape = model.mask[:, :, 0] > 0  # only the icon's own pixels count (the backdrop differs from race to race)
    assert float(np.sqrt(((made - live)[shape] ** 2).mean())) < MATCH_RMS
    assert kart_info("puffy").get("class") == "heavy"


def test_every_research_skill_marked_built_names_a_real_catalogue_skill():
    from playfellow_coop.games.stk.catalogue import RESEARCH_BUILT, SKILLS, research_rows

    names = {n for n, *_ in SKILLS}
    assert set(RESEARCH_BUILT.values()) - names == set()
    rows = research_rows()
    assert len(rows) >= 90 and {r["id"] for r in rows} >= set(RESEARCH_BUILT)


def test_the_kart_is_chosen_by_its_name_on_the_kart_screen():
    # 4 Nov: the menu reader kept Tux while Puffy was asked, so the buddy never found itself on the minimap
    from playfellow_coop.games.stk.mission import kart_walk

    for start, puffy in (((0, 3), (2, 3)), ((0, 3), (1, 5))):
        grid = {(r, c): f"kart{r}{c}" for r in range(4) for c in range(7)}
        grid[start], grid[puffy] = "tux", "puffy"
        pos = list(start)

        def tap(k):
            d = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}[k]
            pos[0], pos[1] = min(max(pos[0] + d[0], 0), 3), min(max(pos[1] + d[1], 0), 6)

        assert kart_walk(lambda: grid[tuple(pos)], tap, "Puffy", say=lambda s: None, wait=0)
        assert tuple(pos) == puffy


def test_a_look_made_from_the_icon_file_finds_the_kart_over_any_backdrop():
    # 4 Nov 05:22: Puffy's icon in a race had a green ring and the map showing through; a look with a red backdrop never
    # matched, so the buddy never saw itself and pressed nothing. Only the icon's own pixels are compared now.
    cv2 = pytest.importorskip("cv2")
    from playfellow_coop.games.stk.minimap import IconModel, MapGeometry
    from playfellow_coop.games.stk.paths import kart_info

    icon_file = kart_info("puffy").get("icon")
    if icon_file is None or not icon_file.exists():
        pytest.skip("the game is not installed here")
    track = ring_track(radius=60.0)
    geo = MapGeometry.for_view(track, 958, 1000)
    rng = np.random.default_rng(5)
    frame = cv2.GaussianBlur(rng.integers(0, 255, (1000, 958, 3), dtype=np.uint8), (7, 7), 0)
    empty = frame.copy()
    model = IconModel.from_game_icon(icon_file)
    scaled = model.at_unit(geo.size / 180.0)
    r = scaled.template.shape[0] // 2
    x0, y0, x1, y1 = geo.box()
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    cv2.circle(frame, (cx, cy), r, (0, 140, 0), 2)  # the green ring the game drew
    patch = frame[cy - r:cy + r + 1, cx - r:cx + r + 1]
    m = scaled.mask > 0
    patch[m] = scaled.template[m]
    hit = model.match(frame, geo)
    assert hit is not None and abs(hit[0][0] - cx) <= 2 and abs(hit[0][1] - cy) <= 2
    assert model.match(empty, geo) is None
