"""Endless Sky pre-skills: the logic, tested without the game. Key facts are checked against the installed game when it is present."""
import numpy as np
import pytest

from playfellow_coop.games.endless_sky import flight, hud
from playfellow_coop.games.endless_sky.routes import StarMap
from playfellow_coop.games.endless_sky.card import load_card, read_card
from playfellow_coop.games.endless_sky.save import find_job, read_pilot
from playfellow_coop.games.endless_sky.screen import Line, bounty_line, classify, selected_model

CARD = {"thrust": "up", "autosteer": "e", "fire": "tab", "hostile": "r", "land": "l", "reverse": "down"}
KEYS = '"Forward thrust" 1073741906\n"Auto steer" 101\n"Fire primary weapon" 9\n"Initiate hyperspace jump" 106\n'
SAVE = '''pilot Fello Playfellow
date 16 11 3013
system Arcturus
planet "New Greenland"
account
\tcredits 45497
conditions
\t"Intro [0]: done"
\t"combat rating" 3
ship Sparrow
\tname Fellow
mission "Intro [1 Interceptor]"
\tname "Escort convoy to Gemstone"
\tdestination Gemstone
"available job" "Bounty Hunting (Very Tiny)"
\tname "Wanted fighter near Holeb"
\tdescription "A small pirate fighter named the Rat has been attacking merchants near the Holeb system."
\tjob
\tnpc kill
\t\tship Scrapper
\t\t\tsystem Holeb
\t\ton kill
\t\t\tpayment 25000
"available job" "Bulk Delivery [0]"
\tname "Bulk delivery to Placer"
\tdestination Placer
\ton complete
\t\tpayment 29400
'''


def blank(w=958, h=1000):
    return np.zeros((h, w, 3), dtype=np.uint8)


def ring(frame, cx, cy, r, colour, share=1.0):
    for a in np.radians(np.arange(0, 360 * share, 0.5)):
        frame[int(cy - r * np.cos(a)), int(cx + r * np.sin(a))] = colour


def lit(frame, shields=1.0, hull=1.0):
    h, w = frame.shape[:2]
    ring(frame, w - 75, 155, 60, (217, 140, 110), shields)
    ring(frame, w - 75, 155, 55, (110, 158, 178), hull)
    return frame


def test_the_card_comes_from_the_keys_file_format():
    assert read_card(KEYS) == {"thrust": "up", "autosteer": "e", "fire": "tab", "jump": "j"}


def test_the_installed_game_binds_the_keys_the_skills_use():
    try:
        card = load_card()
    except OSError:
        pytest.skip("game not installed")
    assert (card["fire"], card["hostile"], card["land"], card["jump"], card["map"]) == ("tab", "r", "l", "j", "m")


def test_the_save_gives_place_money_conditions_jobs_and_the_bounty_target():
    pilot = read_pilot(SAVE)
    assert (pilot.name, pilot.system, pilot.planet, pilot.credits) == ("Fello Playfellow", "Arcturus", "New Greenland", 45497)
    assert pilot.done("Intro [0]") and not pilot.done("Intro [1 Interceptor]")
    assert pilot.ships == ["Sparrow"]
    bounties = [j for j in pilot.jobs if j.is_bounty]
    assert len(bounties) == 1 and bounties[0].npc_systems == ["Holeb"] and bounties[0].payment == 25000
    assert [j.payment for j in pilot.jobs if not j.is_bounty] == [29400]


def test_rings_read_as_the_share_of_the_circle_that_is_lit():
    h = hud.read_hud(lit(blank(), shields=0.5, hull=0.25))
    assert h.bright and h.shields == pytest.approx(0.5, abs=0.05) and h.hull == pytest.approx(0.25, abs=0.05)
    assert not h.has_target


def test_a_covered_hud_is_not_flight():
    assert not hud.read_hud(blank()).bright


def test_radar_blips_are_placed_and_ranged_by_the_radar_scale():
    f = blank()
    f[128, 128 + 10:128 + 12] = (51, 76, 217)  # hostile colour, 10.5 px east
    f[80, 128:130] = (255, 255, 255)  # the selected target, white
    found = {c.kind: c for c in hud.contacts(f)}
    assert found["hostile"].distance == pytest.approx(10.5 * 40, abs=20)
    assert found["target"].distance == pytest.approx(48 * 40, abs=40)


def test_a_planet_disc_on_the_radar_is_not_a_ship():
    f = blank()
    f[60:80, 60:80] = (51, 76, 217)
    assert hud.contacts(f) == []


def hud_with(distance=None, hull=1.0, shields=1.0, heat=0.2, energy=0.9, target=True):
    contacts = [] if distance is None else [hud.Contact(distance / 40.0, 0.0, "target" if target else "hostile")]
    return hud.Hud(True, shields, hull, energy, heat, 1.0, 0.5, 0.5, target, contacts)


def test_far_target_closes_with_guns_on_lead_and_holds_fire():
    order = flight.fight_tick(hud_with(distance=1200), CARD)
    assert order.keys == {"e", "up"}


def test_in_range_it_fires_and_stops_thrusting_when_close():
    assert flight.fight_tick(hud_with(distance=150), CARD).keys == {"e", "tab"}
    assert flight.fight_tick(hud_with(distance=280), CARD).keys == {"e", "tab"}  # inside gun range: no more speed
    assert flight.fight_tick(hud_with(distance=330), CARD).keys == {"e", "up", "tab"}


def test_no_target_selected_selects_the_nearest_hostile():
    assert "r" in flight.fight_tick(hud_with(distance=900, target=False), CARD).taps


def test_guns_rest_when_overheating_or_out_of_energy():
    assert "tab" not in flight.fight_tick(hud_with(distance=150, heat=0.95), CARD).keys
    assert "tab" not in flight.fight_tick(hud_with(distance=150, energy=0.02), CARD).keys


def test_low_hull_with_shields_down_breaks_off_to_land():
    order = flight.fight_tick(hud_with(distance=150, hull=0.55, shields=0.0), CARD)  # above the 45% where a Sparrow is disabled
    assert order.retreat and order.taps == ["l"] and not order.keys


def test_low_hull_with_shields_still_up_keeps_fighting():
    assert not flight.fight_tick(hud_with(distance=150, hull=0.2, shields=0.5), CARD).retreat


def test_no_hostiles_at_all_presses_nothing():
    h = hud_with()
    h.has_target = False
    assert flight.fight_tick(h, CARD).keys == set()


def test_an_idle_ship_always_gets_a_plan():
    """Owner 4 Nov: the ship must never just keep moving straight."""
    assert flight.idle_plan(True, False) == "jump"
    assert flight.idle_plan(False, True) == "land"
    assert flight.idle_plan(False, False) == "map"


def lines(*texts):
    return [Line(t, 0, i * 20) for i, t in enumerate(texts)]


def test_screens_are_named_from_what_they_show():
    f = lit(blank())
    assert classify(f, lines("Navigation:", "no target")).name == "flight"
    g = blank()
    assert classify(g, lines("Back to Menu", "Start Game", "Gamerules")).name == "start"
    assert classify(g, lines("Shipyard", "Outfitter", "Hire Crew", "Depart")).name == "planet"
    assert classify(g, lines("You have:", "Buy", "Sell", "Sell Hull", "Leave")).name == "shipyard"


def test_a_dialog_is_a_dark_hud_with_a_grey_panel_and_a_button():
    f = blank()
    h, w = f.shape[:2]
    f[h // 2 - 100:h // 2 + 100, w // 2 - 120:w // 2 + 120] = 32
    assert classify(f, lines("Welcome to the sky!", "OK")).name == "dialog"


def test_a_conversation_is_the_grey_sheet_on_the_left():
    f = blank()
    f[:, :580] = 32
    assert classify(f, lines("Sounds good!")).name == "conversation"


MINI = """system Hub
	pos 0 0
	link North
	link East
	link West
system North
	pos 0 -100
	link Hub
system East
	pos 100 10
	link Hub
	link Far
system West
	pos -100 0
	link Hub
system Far
	pos 200 10
	link East
"""


def test_a_route_is_the_shortest_chain_of_links():
    m = StarMap.from_text(MINI)
    assert m.route("Hub", "Far") == ["East", "Far"]
    assert m.route("Hub", "Hub") == []
    assert m.route("West", "Nowhere") == []


def test_the_jump_key_walks_links_clockwise_from_straight_up():
    m = StarMap.from_text(MINI)
    assert m.clockwise_links("Hub") == ["North", "East", "West"]
    assert (m.presses_to("Hub", "North"), m.presses_to("Hub", "East"), m.presses_to("Hub", "West")) == (1, 2, 3)


def test_the_real_map_reproduces_what_the_game_did():
    """Seen on 4 Nov: from Rutilicus one press of the jump key on the map selected Menkent (top right), and Arcturus is another link."""
    try:
        m = StarMap.load()
    except OSError:
        pytest.skip("game not installed")
    assert m.clockwise_links("Rutilicus")[0] == "Menkent"
    assert "Arcturus" in m.links["Rutilicus"]


def test_a_planet_screen_with_the_hud_lit_is_the_planet_not_flight():
    """The landed screen keeps the HUD lit behind it and even says 'no target'."""
    assert classify(lit(blank()), lines("Landed on:", "no target", "Trading", "Job Board", "Shipyard", "Depart")).name == "planet"


def test_a_system_is_found_on_the_map_by_its_offset_from_the_current_one():
    m = StarMap.from_text(MINI)
    assert m.map_offset("Hub", "East") == (100.0, 10.0)
    assert m.map_offset("East", "Hub", zoom=2.0) == (-200.0, -20.0)


def test_the_tank_says_how_many_jumps_are_left():
    """4 Nov: three wandering jumps emptied a Sparrow and stranded the test pilot."""
    m = StarMap.from_text(MINI)
    assert (m.fuel_jumps(1.0), m.fuel_jumps(0.67), m.fuel_jumps(0.34), m.fuel_jumps(0.05)) == (3, 2, 1, 0)


def test_the_fuel_bar_is_read():
    f = lit(blank())
    f[233 + 96:425, f.shape[1] - 54] = (110, 158, 178)
    assert hud.read_hud(f).fuel == pytest.approx(0.5, abs=0.02)


def test_a_conversation_over_the_planet_is_the_conversation():
    """4 Nov: James's offer opened over the planet; its Depart button still read through and the buddy never answered him."""
    f = lit(blank())
    f[:, :580] = 32
    assert classify(f, lines("Nothing quite like buying your very first starship", "Shipyard", "Depart")).name == "conversation"


def test_only_the_named_pilots_save_counts(tmp_path):
    """A new pilot has no save before the first landing; an older pilot's file must not be read as theirs."""
    from playfellow_coop.games.endless_sky.save import load_pilot

    (tmp_path / "Other Pilot.txt").write_text(SAVE.replace("Fello Playfellow", "Other Pilot"), encoding="utf-8")
    assert load_pilot("Fello Playfellow", tmp_path) is None
    (tmp_path / "Fello Playfellow.txt").write_text(SAVE, encoding="utf-8")
    assert load_pilot("Fello Playfellow", tmp_path).credits == 45497


def test_the_selected_ship_is_read_from_the_detail_line_not_the_list():
    """4 Nov: 'Sparrow' is always in the list, so the buddy bought the Shuttle that was really selected."""
    listed = [Line("Shuttle", 170, 50), Line("Sparrow", 170, 700)]
    assert selected_model(listed) == ""
    assert selected_model(listed + [Line("model:", 430, 770), Line("Shuttle", 610, 770)]) == "shuttle"
    assert selected_model(listed + [Line("model: Sparrow", 430, 770)]) == "sparrow"


def test_a_bounty_on_the_board_is_found_by_its_title():
    assert bounty_line(lines("Delivery to Glaze", "Wanted fighter near Holeb")).text == "Wanted fighter near Holeb"
    assert bounty_line(lines("Delivery to Glaze")) is None


def test_the_taken_job_is_found_by_its_title_whatever_list_it_is_in():
    pilot = read_pilot(SAVE)
    assert find_job(pilot, "Wanted Fighter near Holeb").npc_systems == ["Holeb"]  # the reader's capitals do not matter
    assert find_job(pilot, "Escort convoy to Gemstone").destination == "Gemstone"
    assert find_job(pilot, "Wanted interceptor near Holeb") is None


def test_closing_too_fast_on_a_far_target_brakes_instead_of_thrusting():
    """4 Nov, first real fight: thrusting the whole way in, the range swung 184 to 1444 and the beams (range 300) hardly touched the target."""
    order = flight.fight_tick(hud_with(distance=500), CARD, closing=900.0)
    assert order.keys == {"down"}


def test_a_slow_approach_keeps_thrusting_and_a_fast_enough_one_coasts():
    assert flight.fight_tick(hud_with(distance=1200), CARD, closing=100.0).keys == {"e", "up"}
    assert flight.fight_tick(hud_with(distance=500), CARD, closing=flight.approach_limit(500, flight.Rules()) + 5).keys == {"e"}


def test_in_range_it_keeps_firing_whatever_the_speed():
    assert "tab" in flight.fight_tick(hud_with(distance=250), CARD, closing=900.0).keys


def test_too_much_drift_near_the_target_brakes():
    assert flight.fight_tick(hud_with(distance=700), CARD, closing=0.0, drift=800.0).keys == {"down"}


def test_the_approach_limit_falls_with_distance():
    r = flight.Rules()
    assert flight.approach_limit(5000, r) == r.top_approach
    assert flight.approach_limit(195, r) == r.creep
    assert flight.approach_limit(300, r) < flight.approach_limit(600, r)


def test_range_rate_is_smoothed_over_a_second():
    rate = flight.RangeRate()
    assert rate.update(0.0, 1000.0) == 0.0
    assert rate.update(0.5, 800.0) == pytest.approx(400.0)
    assert rate.update(1.0, 600.0) == pytest.approx(400.0)
    assert rate.update(1.2, None) == 0.0


def test_the_speedometer_reads_how_far_the_stars_slid():
    rng = np.random.default_rng(1)
    sky = np.zeros((1000, 958, 3), dtype=np.uint8)
    for x, y in zip(rng.integers(0, 958, 900), rng.integers(0, 1000, 900)):
        sky[y, x] = 255
    meter = hud.Speedometer()
    meter.update(sky, 0.0)
    slid = np.roll(sky, 6, axis=1)
    assert meter.update(slid, 0.1) == pytest.approx(0.4 * 60.0, abs=4.0)


def test_the_screen_of_a_destroyed_ship_is_not_a_paid_bounty():
    """4 Nov: HUD words matched and the buddy said 'Bounty paid' over a wreck."""
    wreck = "Rasalhague 30,479 credits Malachai the Deadly Wasp Bounty (mission target) Your Sparrow Fellow has been destroyed."
    assert not flight.bounty_paid(wreck, 40491, 40491)
    assert flight.destroyed(wreck)


def test_paid_means_the_game_said_so_or_the_money_came():
    assert flight.bounty_paid("The Zagan the Cold has been eliminated. Shortly afterwards the government sends you 25,000 credits", None, None)
    assert flight.bounty_paid("", 40000, 65000)
    assert not flight.bounty_paid("", 40000, 37500)


def test_only_a_fair_fight_in_fuel_reach_is_taken():
    assert flight.job_is_fair(["Scrapper"], 1) == ""
    assert flight.job_is_fair(["Wasp"], 2) == ""  # fair since the refit
    assert "out-guns" in flight.job_is_fair(["Bastion"], 1)
    assert "fuel" in flight.job_is_fair(["Scrapper"], 3)
    assert flight.job_is_fair([], 1) != ""


def test_the_save_names_the_ships_hunted():
    assert [j.npc_ships for j in read_pilot(SAVE).jobs if j.is_bounty] == [["Scrapper"]]


def test_the_menu_after_a_lost_ship_is_a_menu():
    assert classify(blank(), lines("pilot:", "Fello Trial3", "You have died.", "Welcome to Endless Sky!", "Preferences")).name == "menu"


def test_a_job_already_turned_down_is_not_taken_for_a_new_one_with_the_same_title():
    pilot = read_pilot(SAVE)
    job = find_job(pilot, "Wanted fighter near Holeb")
    assert find_job(pilot, "Wanted fighter near Holeb", {job.description}) is None


def test_the_refit_fits_what_ports_weapon_space_and_money_allow():
    """After buying a Sparrow: 38,000 credits; selling two Beam Lasers gives 58,000 (outfitter, 4 Nov)."""
    assert flight.refit_plan(38000) == 4
    assert flight.refit_plan(0, lasers=0) == 0
    assert flight.refit_plan(0, lasers=1) == 1
    assert flight.refit_plan(38000, weapon_space=12) == 2


def test_blasters_open_fire_at_their_own_range_and_stop_closing_there():
    rules = flight.Rules(weapon_range=flight.BLASTER_RANGE)
    assert flight.fight_tick(hud_with(distance=450), CARD, rules).keys == {"e", "tab"}
    assert "tab" not in flight.fight_tick(hud_with(distance=700), CARD, rules).keys
