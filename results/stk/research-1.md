# SuperTuxKart 1.5 and racing games: own research (pass 1)

Marks: [V] read in the installed game's data or its source. [G] from a guide or wiki, not checked in the game. [M] measured in our own races (3-4 Nov). [O] from the owner's pasted guides; where a number could be checked it is marked as confirmed.

Sources: installed `data/kart_characteristics.xml`, `stk_config.xml`, `powerup.xml`, `tips.xml`, `input.xml`, tutorial `scene.xml`; stk-code `skidding.cpp`, `skidding_ai.cpp`, `player_controller.cpp`, `local_player_controller.cpp`, `kart.cpp`, `attachment.cpp`, `graph.cpp`, `race_gui.cpp`; supertuxkart.net Powerups and Physics pages. Blocked: the speedrun.com guide (403) and the freegamedev forum thread (refused); only search snippets of those were seen.

## 1. Physics numbers, medium kart (Tux) [V]

| Thing | Value |
|---|---|
| Base top speed | 25 m/s, 950 engine power |
| Difficulty scale on top speed / power | Novice 0.6 / 0.7, Intermediate 0.8 / 0.83, Expert 0.92 / 0.92, SuperTux 1 / 1 |
| So top speed | Novice 15, Intermediate 20, Expert 23, SuperTux 25 m/s |
| Turn radius by speed | 0 m/s: 2 m; 10: 7.5 m; 25: 15 m; 45: 30 m |
| Reverse | 0.65 of top speed |
| Start boost | `startup time="0.3 0.5" boost="8 4"`: +8 m/s in the tighter window, +4 in the wider |
| Start penalty | 1 s if accelerate, brake or nitro is active during "Ready!" (`stk_config startup penalty="1"`) |
| Skid | min speed 10 m/s; bonus after 1.0 s: +4.5 m/s for 3 s; after 3.0 s: +6.5 m/s for 4 s; given when skid is released |
| Nitro | +5 m/s cap; can holds max 20; small can 1, big can 3; fade 2.4 s |
| Zipper | +15 m/s cap, 3.5 s, speed gain 4.5, force 250 |
| Slipstream | 8 m behind, 4 m wide at 20 m/s; min 8 m/s; 2.5 s to earn, up to 8 s; +3 m/s, fade 2 s; inner area earns twice as fast |
| Rescue | 1.2 s |
| Explosion | 1.5 s out; 7 s invulnerable after; radius 6 m |
| Anvil ("anchor") | 2 s, speed x0.2 at once, adds weight |
| Parachute | 3 s (2.5 for others hit), friction 5; braking gets rid of it faster |
| Bubblegum | shield 10 s; ground gum speed x0.3 for 1 s |
| Swatter | 10 s active, range 9 m, flattened kart 5 s |

**What this means:** on Intermediate all karts share the 20 m/s cap, so a clean lap only ties the AI. The gaps are decided by boosts: red skid +6.5 (33%), skid +4.5, nitro +5, slipstream +3, zipper +15. [M] Our speed was median 18.8, p90 21.9 m/s in the 3:36 race; winner 3:32. We lost 4.3 s over 3 laps.

## 2. The start [V]

- During "Ready!": any accel, brake or nitro earns the penalty. Source: `if (penalty_ticks == 0 && phase == READY_PHASE) displayPenaltyWarning()`.
- During the penalty the game zeroes the throttle each tick; a held key sends no new event, so it must be pressed again. [M] 9 s lost on 4 Nov.
- Start boost is measured from the start of "Set!"-to-go timing by `getStartupBoostFromStartTicks`; a press that is too slow gets 0. Exact reference point not confirmed: test by logging.
- Tips file: "You get a startup boost if you start accelerating during Set".
- [M] Countdown on our recording: Ready about 0.9 s, Set about 0.7 s, Go 0.6 s on screen.

## 3. Skidding [V]

- Start needs: steering not zero, speed above 10 m/s, skid key down, not in the air.
- Starting a skid gives a small jump (hop).
- During a skid the steering is remapped to a reduced range on the skid's side: "You can't stop turning while skidding. Good kart orientation at the skid's start is paramount" (tips).
- Bonus comes on RELEASE of the skid key, and steering hard right after can use it up (config comment).
- Tips: "Skidding makes you much faster, do it whenever safe."
- [G] Red skids are strongest; hold the turn away during the skid to widen the arc. [O] Yellow +16.2 km/h and red +23.4 km/h: CONFIRMED by the config (4.5 and 6.5 m/s).
- [O] Snaking (chained hop-drifts on straights), brake-drift in hairpins, low-air hop: speedrun methods, not checked.
- [M] Our predictive drift was tried live and the owner reports poor drifting. Needs a proper controller and proof in the simulator.

## 4. Items [V, source AI and Powerups page]

Effects:
- Banana: gives an attachment at random: anvil, bomb or parachute (`ticks % 3`; 2 options in time trial). This is the "anchor" the owner keeps seeing, costing x0.2 speed at once.
- Gift box: a random power. Nitro bottle: small 1, big 3.
- Zipper: 3.5 s, use on long straights, not before tight turns, do not chain or stack on a ground zipper.
- Bowling ball: rolls straight, rebounds; wait for straight line; fire backward with look-back held.
- Cake: homes within 90; fire at someone ahead, or backward.
- Plunger: forward pulls you; backward blinds for 4.5 s.
- Swatter: automatic on nearby karts; removes bombs and parachutes.
- Bubblegum: shield 10 s if used; or dropped as gum. Shield stops all but homing rubber ball squash.
- Homing rubber ball: homes on the leader; destroyed by precise backward shot; shield helps.
- Parachute: hits karts ahead. Switch: turns boxes into bananas and nitro into gum for 5 s.
- Short nitro bursts are more efficient (tips); "store at least 2 big cans worth".

How the game's own AI uses them (`skidding_ai.cpp`), a ready-made rule set:
- Cake: 2 s between uses; target ahead under 20 or behind under 25, aligned.
- Bowling: 3-5 s between uses; aligned under 0.2 rad; ahead under 10, behind under 30.
- Plunger: backward if a kart behind is closer; 5 s between uses; within 30.
- Bubblegum: shield against incoming items within its radius or to remove attachments; drop behind a kart closer than 8, directly behind.
- Swatter: only with a slower kart in range, or to remove an attachment.
- Item look-ahead 30 m; reject an item needing too large a steering change at this speed.
- Nitro at top skill: keep a reserve of 4-12, use when a boost fade passes a threshold, avoid when speed is already over the safe limit; use below 5 km/h.
- Curves: maximum turn speed from curve radius; brake when above it and steering over 0.95.
- Slipstream: chase a target kart when ready, then overtake.
- Harder difficulties rubber-band: AI speed caps vary with distance to the player.

## 5. Our measured problems [M]

| Problem | Evidence | Cause or status |
|---|---|---|
| Swinging | 49 flips/min at worst; 25 in the best race | Reduced by damping in the simulator and live |
| Bananas | Owner: still hit often | Fast eye catches 4 of 5 labelled frames; false hit on icons, stars |
| Gift boxes missed | Owner: many | SAM is 2-3 s late; local colour detector rejected on Abyss |
| Items wasted | Owner: wrong use | Fire rule uses a kart phrase only; no idea which item is held |
| Slow in curves | Owner | Speed table too low earlier; raised; not tuned per curve |
| Drift | Owner: not learned | Unproven controller |
| Start | 9 s lost once | Fixed offline, not proven live |
| No item knowledge | Code never reads the held power | Biggest gap: the power icon sits at top centre |

## 6. What can be read from pixels

Position list (left), lap count, time, nitro gauge (bottom right, speed arc), held power icon (top), minimap with all karts, attachment icon, "Wrong way!", countdown. Not yet read: held power, nitro amount, own place, karts behind, speed.

## 7. Racing genre fundamentals [G, general knowledge]

Racing line: outside, apex, outside; brake before the corner; earliest throttle on exit matters most because it sets the following straight. Momentum: in a low-power kart the line must stay open, so avoid scrubbing speed. Slipstream on straights then pass at the end. Defend by holding the inside before a corner. Items: keep a defensive item when leading; attack when chasing. Memorise tracks. Consistency wins over peak speed. In Mario Kart-type games the same order applies: start boost, drift tiers, item holding, shortcuts.

## 8. Open questions for pass 2

1. Exact start-boost timing reference and best press moment.
2. A controller for skidding from keys only: when to start, counter-steer pattern, when to release, on which corner radii.
3. Chaining: nitro as a skid bonus fades; value of a tap against holding.
4. Item priority table per position (1st, mid, last), and when to hold.
5. How AI difficulty and rubber-banding work on Intermediate, Expert, SuperTux, and how the player exploits them.
6. Antediluvian Abyss line: shortcuts, ramps, falls, items, per-corner notes. Other tracks' special hazards.
7. Unlocking SuperTux difficulty; what the game actually requires.
8. Pixel-only ways to read: held power, nitro level, position, karts behind.
9. What beats AI at the highest level for a bot reacting at 20 Hz with minimap-only position.
10. Skills from other racing games that transfer, and which do not.
