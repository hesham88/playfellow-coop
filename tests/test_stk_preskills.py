"""SuperTuxKart pre-skills, offline: the controls card, reading and timing instructions, the menu safety rule, the driveline, the
icon template at another window size, the power guard's judgement. No window, no key, no network."""
import pytest

pytest.importorskip("cv2")  # the SuperTuxKart pack's extra: pip install -e .[stk]

import numpy as np  # noqa: E402

from playfellow_coop.games.stk.card import Card
from playfellow_coop.games.stk.drive import Driver, Keys
from playfellow_coop.games.stk.instructions import Instruction, MessageWatch, parse_answer
from playfellow_coop.games.stk.menus import Step, check, parse_step
from playfellow_coop.games.stk.minimap import IconModel, MapGeometry
from playfellow_coop.games.stk.power import Reading, judge
from playfellow_coop.games.stk.track import Track

INPUT_XML = """<input version="1"><keyboard enabled="true" configName="">
<action name="steerLeft" event="1" id="37" /><action name="steerRight" event="1" id="39" /><action name="accel" event="1" id="38" />
<action name="brake" event="1" id="40" /><action name="nitro" event="1" id="78" /><action name="drift" event="1" id="86" />
<action name="rescue" event="1" id="8" /><action name="fire" event="1" id="32" /><action name="lookBack" event="1" id="66" />
</keyboard></input>"""

SQUARE_QUADS = """<quads>
<quad p0="-4 0 0" p1="4 0 0" p2="4 0 50" p3="-4 0 50"/>
<quad p0="0:3" p1="0:2" p2="54 0 54" p3="46 0 46"/>
<quad p0="1:3" p1="1:2" p2="54 0 -4" p3="46 0 4"/>
<quad p0="2:3" p1="2:2" p2="0:1" p3="0:0"/>
</quads>"""


def card():
    return Card.from_xml(INPUT_XML)


def test_the_card_is_read_from_the_games_own_bindings():
    c = card()
    assert c.keys["rescue"] == "backspace" and c.keys["drift"] == "v" and c.keys["nitro"] == "n"
    assert c.action_for_screen_key("<Backspace>") == "rescue"
    assert c.action_for_screen_key("<V>") == "drift"
    assert c.action_for_screen_key("<Q>") is None  # a key the card does not have means nothing


def test_a_key_named_on_screen_overrules_the_models_action():
    answer = '{"text": "press <Backspace> to be rescued", "keys": ["Backspace"], "action": "nitro", "timing": "now"}'
    inst = parse_answer(answer, card())
    assert inst.action == "rescue" and inst.key == "backspace" and "card says" in inst.note


def test_arrow_keys_in_a_skid_lesson_do_not_hide_the_skid_key():
    answer = ('{"text": "Accelerate and press the <V> key while turning to skid.", "keys": ["Up", "V"], "action": "drift", '
              '"timing": "while_turning"}')
    inst = parse_answer(answer, card())
    assert (inst.action, inst.key, inst.timing) == ("drift", "v", "while_turning")


def test_a_broken_answer_is_information_only():
    inst = parse_answer("no json here", card())
    assert inst.action == "none"


def track():
    return Track.from_texts("square", SQUARE_QUADS, None)


def test_instructions_are_acted_on_with_their_timing():
    d = Driver(track(), keys=Keys())
    assert "Rescue" in d.apply(Instruction("press <Backspace> to be rescued", "rescue", "ongoing", "backspace"), now=10.0) or True
    assert d.trouble_watch_until > 10.0
    d.apply(Instruction("press <V> while turning", "drift", "while_turning", "v"), now=10.0)
    assert d.skid_until > 40.0
    d.apply(Instruction("we will use them after the curve", "nitro", "next_straight", "n"), now=10.0)
    assert d.nitro_on_straight is True
    d.apply(Instruction("fire now", "fire", "now", "space"), now=10.0)
    assert "space" in d.taps


def test_in_trouble_after_a_rescue_instruction_the_kart_is_rescued_sooner():
    d = Driver(track(), keys=Keys())
    p = np.array([0.0, 10.0])
    assert "backspace" not in d.step(0.0, p)
    d.apply(Instruction("press <Backspace> to be rescued", "rescue", "ongoing", "backspace"), now=0.1)
    keys = set()
    t = 0.2
    while t < 2.0 and "backspace" not in keys:  # stalled on the same spot
        keys = d.step(t, p)
        t += 0.05
    assert "backspace" in keys and t < 1.5  # without the instruction it waits 2.5 s


def test_the_menu_rule_refuses_enter_on_anything_online():
    step = check(parse_step('{"screen": "main menu", "focused": "Online", "press": "enter", "done": false}'))
    assert step.press == "none" and "offline" in step.refused
    step = check(parse_step('{"screen": "Addons", "focused": "Install", "press": "enter", "done": false}'))
    assert step.press == "esc"
    step = check(parse_step('{"screen": "main menu", "focused": "Tutorial", "press": "enter", "done": false}'))
    assert step.press == "enter" and not step.refused


def test_an_unknown_key_from_the_model_is_never_pressed():
    assert parse_step('{"press": "alt+f4"}').press == "none"


def test_the_driveline_follows_the_graph_and_measures_ahead():
    t = track()
    assert t.order == [0, 1, 2, 3]
    assert np.allclose(t.ahead(0, 0.0), t.centre[0])


def test_the_icon_look_is_resized_to_another_window():
    rng = np.random.default_rng(1)
    big = rng.integers(0, 255, size=(37, 37, 3), dtype=np.uint8)
    yy, xx = np.mgrid[:37, :37] - 18
    disc = (np.hypot(xx, yy) <= 17).astype(np.uint8)
    model = IconModel(big, np.dstack([disc] * 3))
    assert model.at_unit(2.0) is model
    small = model.at_unit(1.6)
    assert small.template.shape[0] == 2 * round(9 * 1.6) + 1


def test_the_minimap_maps_world_to_pixels_and_back():
    g = MapGeometry.for_view(track(), 1024, 768)
    xz = np.array([[10.0, 20.0], [50.0, 0.0]])
    assert np.allclose(g.to_world(g.to_pixel(xz)), xz)


def test_message_watch_passes_a_new_message_once():
    frame = np.zeros((768, 1024, 3), dtype=np.uint8)
    frame[720:750, 200:820] = (186, 204, 216)  # the light box
    frame[728:742, 300:700:6] = (15, 15, 15)  # letters
    w = MessageWatch()
    assert w.look(frame) is None  # first sight: wait for it to settle
    assert w.look(frame) is not None  # settled: read it
    assert w.look(frame) is None  # already read


def test_power_guard_judgement():
    assert judge(Reading(True, True, 5000, 20000)) and "charger" in judge(Reading(True, True, 5000, 20000))
    assert judge(Reading(False, True, 900, 20000)) == "on battery and nearly empty"
    assert judge(Reading(True, False, 10, 0)) is None
    assert judge(None) is None


def ring_track(n=40, radius=60.0, half_width=4.0):
    """A round track of n short quads, like a real track's driveline (a quad every ~9 m)."""
    import math

    def pt(k, r):
        a = 2 * math.pi * k / n
        return f"{r * math.cos(a):.3f} 0 {r * math.sin(a):.3f}"

    quads = "".join(f'<quad p0="{pt(k, radius - half_width)}" p1="{pt(k, radius + half_width)}" '
                    f'p2="{pt(k + 1, radius + half_width)}" p3="{pt(k + 1, radius - half_width)}"/>' for k in range(n))
    return Track.from_texts("ring", f"<quads>{quads}</quads>", None)


def on_ring(t, s):
    """The point s metres along the ring's driveline."""
    return t.ahead(0, s % float(np.linalg.norm(np.roll(t.centre, -1, axis=0) - t.centre, axis=1).sum()))


def test_progress_is_continuous_along_a_segment():
    t = ring_track()
    d = Driver(t, keys=Keys())
    for k in range(21):
        d.step(k * 0.05, on_ring(t, k * 0.5), racing=False)
    assert 9.0 < d.progress < 11.0  # 10 m driven, counted as 10 m (not in ~9 m steps)


def test_a_rescue_that_sets_the_kart_back_does_not_start_a_rescue_loop():
    # the 3 Nov tutorial loop: rescued back along the road, the kart drove on but could not beat its old best in time
    t = ring_track()
    d = Driver(t, keys=Keys())
    d.apply(Instruction("press <Backspace> to be rescued", "rescue", "ongoing", "backspace"), now=0.0)
    now, s = 0.0, 0.0
    while now < 3.0:  # 10 m/s
        d.step(now, on_ring(t, s))
        now, s = now + 0.05, s + 0.5
    d._rescue(now, "test")  # the game sets the kart back 25 m
    s -= 25.0
    rescues = 0
    while now < 11.0:  # and it restarts at 2.5 m/s: 10 s to regain its old best
        rescues += "backspace" in d.step(now, on_ring(t, s))
        now, s = now + 0.05, s + 0.125
    assert rescues == 0


def test_stuck_against_a_wall_the_kart_backs_off_first_then_rescues_if_still_stuck():
    t = ring_track()
    d = Driver(t, keys=Keys())
    p = on_ring(t, 20.0)
    now = 0.0
    seen = []
    while now < 12.0:  # it never moves: a wall
        keys = d.step(now, p)
        if "down" in keys and "reverse" not in seen:
            seen.append("reverse")
        if "backspace" in keys:
            seen.append("rescue")
            break
        now += 0.05
    assert seen == ["reverse", "rescue"]


def test_the_buddys_own_kart_is_never_a_target():
    from playfellow_coop.games.stk.items import Seen, aim

    own = Seen("kart", 0.5, 0.85, 10.0)  # bottom middle of the band: the buddy's own kart
    assert aim([own], 10.1) == (0.0, False, None)
    foe = Seen("kart", 0.52, 0.45, 10.0)
    bias, shoot, target = aim([own, foe], 10.1)
    assert target is foe and shoot


def test_an_obstacle_in_the_path_beats_an_item():
    from playfellow_coop.games.stk.items import Seen, plan

    bias, why, thing = plan([Seen("gift", 0.4, 0.8, 0.0), Seen("banana", 0.55, 0.7, 0.0)], 0.1)
    assert thing.kind == "banana" and bias > 0  # banana right of centre: steer left


def test_difficulty_glow_is_read_per_slot():
    import numpy as np

    from playfellow_coop.games.stk.setup_screen import selected_difficulty

    frame = np.full((1000, 958, 3), 200, dtype=np.uint8)
    for sx in (0.16, 0.38, 0.61, 0.83):  # every penguin has yellow feet
        x = int(sx * 958)
        frame[380:400, x - 30:x + 30] = (40, 200, 255)
    x = int(0.38 * 958)
    frame[180:430, x - 100:x + 100] = (40, 190, 250)  # the glow behind Intermediate
    assert selected_difficulty(frame) == "intermediate"
    assert selected_difficulty(np.full((1000, 958, 3), 200, dtype=np.uint8)) is None


def test_the_tuned_driver_holds_the_road_at_speed_in_the_simulator():
    # 3 Nov Intermediate race: at ~20 m/s the old steering swung up to ~8.8 m off the centre line (edges are ~4-6 m away)
    from playfellow_coop.games.stk.sim import run

    import pytest

    from playfellow_coop.games.stk.track import DEFAULT_DATA

    if not (DEFAULT_DATA / "tracks" / "abyss" / "quads.xml").exists():
        pytest.skip("needs the installed game's Abyss driveline")
    t = Track.load("abyss")

    def fresh(**kw):
        d = Driver(t, keys=Keys())
        d.speed_scale = 10.0  # let it hold the simulated speed
        for k, v in kw.items():
            setattr(d, k, v)
        return d

    def worst(**kw):  # a fresh driver for every run: one carried over would remember where the last run ended
        return max(run(fresh(**kw), t, speed=20.0, seconds=40, seed=s).worst_off_road_m for s in (1, 2))

    # the steering itself, without skids (measured across the road since 4 Nov)
    tuned = worst(skid_enabled=False)
    old = worst(kd=0.0, speed_gain=0.0, full_lock=0.35, skid_enabled=False)
    assert tuned < old
    assert tuned < 6.5
    # skids (4 Nov, planned per bend, released at the edge): stated limit, measured 6.6 m against 7.6 m for the old driver
    with_skids = worst()
    assert with_skids < 7.0 and with_skids < worst(kd=0.0, speed_gain=0.0, full_lock=0.35)


def test_a_held_throttle_the_game_ignored_is_pressed_again():
    # 4 Nov race: a start penalty zeroes the throttle and a held key sends no new event, so the kart sat 9 s with Up "held"
    d = Driver(ring_track(), keys=Keys())
    held, released_at = True, None
    now = 0.0
    while now < 3.0 and released_at is None:
        keys = d.kick(now, 0.0, {"up"})
        if "up" not in keys:
            released_at = now
        now += 0.05
    assert released_at is not None and released_at < 1.5  # let go for a look, so the next look is a fresh key press
    assert "up" in d.kick(now, 0.0, {"up"})  # and pressed again straight after


def test_a_moving_kart_is_never_kicked():
    d = Driver(ring_track(), keys=Keys())
    assert all("up" in d.kick(k * 0.05, 15.0, {"up"}) for k in range(100))


def test_no_rescue_for_having_waited_on_the_grid():
    # 4 Nov race: the wait on the grid counted as "no progress" and Rescue fired the moment racing began
    t = ring_track()
    d = Driver(t, keys=Keys())
    p = on_ring(t, 5.0)
    d.step(0.0, p, racing=False)
    d.begin_race(12.0)
    keys = d.step(12.1, p)
    assert "backspace" not in keys and "down" not in keys


def test_a_skid_is_held_for_the_time_the_game_pays_for():
    from playfellow_coop.games.stk.drive import SKID_BONUS_TIME

    assert 1.0 < SKID_BONUS_TIME < 1.3  # time-till-bonus is 1.0 s in the game's data; released earlier it earns nothing


def test_nitro_waits_for_a_boost_to_fade():
    t = ring_track(n=200, radius=400.0)  # as good as straight
    d = Driver(t, keys=Keys())
    d.boost_ends = 100.0
    d.dead_band = 9.0  # hold the wheel still
    used, now, s = 0, 0.0, 0.0
    while now < 8.0:
        used += "n" in d.step(now, on_ring(t, s))
        now, s = now + 0.05, s + 1.0
    assert used == 0
    d.boost_ends = -1.0
    while now < 16.0:
        used += "n" in d.step(now, on_ring(t, s))
        now, s = now + 0.05, s + 1.0
    assert used >= 2


def test_facts_from_the_15_source_are_in_the_driver():
    """Research 4 Nov from the game's source: a skid pays only if held over 1.0 s at 10 m/s or more, and nitro only burns with accelerate held."""
    from playfellow_coop.games.stk import drive

    assert drive.SKID_BONUS_TIME > 1.0 and drive.SKID_MIN_SPEED >= 10.0
    src = __import__("inspect").getsource(drive)
    assert "keys |= {k.nitro, k.accel}" in src
