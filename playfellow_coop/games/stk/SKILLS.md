# SuperTuxKart 1.5: skills of the game and its genre

89 skills. Status: built 4, known 54, tested 31.
Tier: game 46, genre 43.

## boosts

| Skill | Tier | Level | Status | What | How | Cue | Worked when |
|---|---|---|---|---|---|---|---|
| hop / low-air hop | game | intermediate | known | tap skid before a crest to land sooner | tap skid before a crest to land sooner |  |  |
| jumps and ramps | game | intermediate | known | straight and centred before a jump, no steering in the air | straight and centred before a jump, no steering in the air |  |  |
| rocket start | game | intermediate | tested | full throttle exactly at 'Set!' (countdown read locally) | full throttle exactly at 'Set!' (countdown read locally) |  |  |
| Avoid false start | genre | beginner | known | No input during "Ready!" | Never press Up/Down/N before "Set!" | "Ready!" text; on a fault, "Penalty time!!" plus a buzz | No penalty message |
| Collect nitro | genre | beginner | known | Fill the 20-unit tank | Drive over cans: small +1, big +3 | Blue cans (0,70,158) | Gauge rises; "nitro full" sound |
| Nitro burst | genre | beginner | known | +5 m/s while burning, +1 s, then a 2.4 s fade | N with Up held; at least 0.53 s per press | Blue light, nitro sound, gauge draining (bottom-right) | Speed rises; gauge falls |
| Rocket start (small) | genre | beginner | tested | Half boost | First press 0.3–0.5 s after "Set!" (derived from code) | "Set!" | Smaller zipper fire |
| Drafting | genre | intermediate | known | +3 m/s after leaving the slipstream | Stay in its wake at least 2.5 s (1.25 s dead centre), then pull out | Wind streaks switch to the "fast" texture | Bonus texture; speed up |
| Nitro challenge | genre | intermediate | known | Finish holding the required nitro | Collect; do not spend below the target (S: 20 units) | "Collect nitro!" banner | Challenge solved |
| Rocket start (big) | genre | intermediate | tested | Zipper-category start boost | First Up press 0.3 s or less after "Set!" appears, held through Go (derived from code; verify in play) | "Set!" text | Zipper fire and a speed jump at Go |
| Skid lockout awareness | genre | intermediate | known | New skid blocked | Wait min(skid time, 0.7 s) | Kart un-rotating | Next skid starts |
| Yellow skid | genre | intermediate | known | +4.5 m/s for 3 s | Steer, then V; hold more than 1.0 s; release V facing the exit | White sparks turn orange-yellow | Sparks continue after release; speed rises |
| brake-drift in hairpins | genre | intermediate | built | tap brake while drifting to pivot in tight hairpins | tap brake while drifting to pivot in tight hairpins |  |  |
| nitro on straights | genre | intermediate | tested | taps nitro when the road ahead is straight | taps nitro when the road ahead is straight |  |  |
| nitro tapping on a fading boost | genre | intermediate | known | tap nitro as a skid or zipper boost fades to hold top speed | tap nitro as a skid or zipper boost fades to hold top speed |  |  |
| predictive drift | genre | intermediate | tested | measures the bend ahead, holds skid + turn through it, releases lined up | measures the bend ahead, holds skid + turn through it, releases lined up |  |  |
| skid boost (yellow +16.2 km/h, red +23.4 km/h) | genre | intermediate | known | hold skid through a bend until sparks, release for a boost | hold skid through a bend until sparks, release for a boost |  |  |
| snaking on straights | genre | intermediate | known | chained hop-drifts on straights for repeated boosts | chained hop-drifts on straights for repeated boosts |  |  |
| zipper buffering | genre | intermediate | known | do not stack a zipper item or nitro on a ground zipper | do not stack a zipper item or nitro on a ground zipper |  |  |
| Red skid | genre | pro | known | +6.5 m/s for 4 s | Hold V more than 3.0 s | Red sparks or light | Larger boost after release |

## commands

| Skill | Tier | Level | Status | What | How | Cue | Worked when |
|---|---|---|---|---|---|---|---|
| command: driving tips | game | intermediate | tested | more nitro / more items / dodge more / calmer, for this race | more nitro / more items / dodge more / calmer, for this race |  |  |
| command: menu / restart / race X | game | intermediate | tested | voice or text makes the buddy go to the menu, restart, or start a race | voice or text makes the buddy go to the menu, restart, or start a race |  |  |
| command: stop / wait / take it back | game | intermediate | tested | F12 / F9 / voice / text | F12 / F9 / voice / text |  |  |
| never silent | game | intermediate | tested | the widget always says what the buddy is doing or waiting for | the widget always says what the buddy is doing or waiting for |  |  |

## driving

| Skill | Tier | Level | Status | What | How | Cue | Worked when |
|---|---|---|---|---|---|---|---|
| kart class: Tux, middleweight | game | intermediate | tested | top speed 90 km/h (25 m/s), balanced acceleration, 225 kg; speed caps are set from it | top speed 90 km/h (25 m/s), balanced acceleration, 225 kg; speed caps are set from it |  |  |
| shortcuts | game | intermediate | known | learned alternative routes per track | learned alternative routes per track |  |  |
| wall riding (magnet sections) | game | intermediate | known | ride gravity surfaces on Cocoa Temple / STK Enterprise | ride gravity surfaces on Cocoa Temple / STK Enterprise |  |  |
| braking points | genre | intermediate | built | brake before the bend, not in it | brake before the bend, not in it |  |  |
| calm straights | genre | intermediate | tested | holds the wheel still on straights (no weaving) | holds the wheel still on straights (no weaving) |  |  |
| driveline pursuit | genre | intermediate | tested | follows the road; looks further at speed | follows the road; looks further at speed |  |  |
| minimap localisation | genre | intermediate | tested | knows where the kart is on the track, 20 times a second | knows where the kart is on the track, 20 times a second |  |  |
| outside line in tight bends | genre | intermediate | tested | aims a little wide of the centre line in tight bends | aims a little wide of the centre line in tight bends |  |  |
| racing line (out-in-out) | genre | intermediate | built | wide entry, apex, wide exit for more speed through bends | wide entry, apex, wide exit for more speed through bends |  |  |
| speed for the bend ahead | genre | intermediate | tested | lifts before sharp bends, brakes a moment before very sharp ones | lifts before sharp bends, brakes a moment before very sharp ones |  |  |
| steering damping + speed schedule | genre | intermediate | tested | steers on where the error is going; gentler at speed | steers on where the error is going; gentler at speed |  |  |

## items

| Skill | Tier | Level | Status | What | How | Cue | Worked when |
|---|---|---|---|---|---|---|---|
| Basket ball | game | beginner | known | Homes in on 1st place | Space | Bouncing ball | Leader explodes (or loses its shield) |
| Cake | game | beginner | known | Homing lob, 1.5 s explosion | Space (B + Space = backwards) | Cake arc | Target explodes |
| Gum shield | game | beginner | known | Absorbs one hit, 10 s | Space with gum held | Bubble around the kart | Hit absorbed, shield pops |
| Parachute (use) | game | beginner | known | Slows every kart ahead | Space | Parachutes on the karts ahead | They slow |
| Bowling ball | game | intermediate | known | Rolling, wall-bouncing ball | Space or B + Space | Rolling ball | Target explodes |
| Gum drop | game | intermediate | known | Chaser held at 0.3 speed for 1 s | Hold B + Space | Rear view shows the gum | Chaser slows |
| Plunger back | game | intermediate | known | Blind the chaser 4.5 s | B + Space | (Victim sees a dark red Tux overlay) | Chaser drifts |
| Plunger forward | game | intermediate | known | Pull towards the target, +7 m/s | Space | Rubber band | You are pulled forward |
| Swatter | game | intermediate | known | Auto-swat within 3 m; victim at 0.5 speed for 5 s | Space, then drive within 3 m | Swatter in the kart's hand | Victim flattened |
| aimed firing (SAM) | game | intermediate | tested | fires only with an opponent lined up, never at itself | fires only with an opponent lined up, never at itself |  |  |
| fast banana eye | game | intermediate | tested | local yellow detector, 10 looks a second, dodges at once | local yellow detector, 10 looks a second, dodges at once |  |  |
| item blocking (drop behind) | game | intermediate | known | drop a banana behind to block projectiles | drop a banana behind to block projectiles |  |  |
| item hunt (SAM) | game | intermediate | tested | picks one reachable gift box or nitro on gentle road, then the next | picks one reachable gift box or nitro on gentle road, then the next |  |  |
| obstacle avoidance (SAM) | game | intermediate | tested | steers around bananas and crates in the path | steers around bananas and crates in the path |  |  |
| rear-firing (look back + fire) | game | intermediate | known | fire backwards at a kart close behind | fire backwards at a kart close behind |  |  |
| shielding (bubblegum) and swatter | game | intermediate | known | shield against incoming items; swat parachutes and bombs | shield against incoming items; swat parachutes and bombs |  |  |
| Zipper pad / item | genre | beginner | known | +15 m/s top speed, 3.5 s | Drive over the pad or press Space; never hold Down | Zipper fire, "weee" | Speed jump |
| Box discipline | genre | intermediate | known | Keep a saved item | Steer around cyan boxes (a new box overwrites) | Cyan boxes (31,202,253) | Item kept |
| Parachute brake-off | genre | intermediate | known | Shed a parachute early | Hold Down hard | Parachute on your kart | It drops once speed falls to about 1/3–1/2 |
| Switch | genre | intermediate | known | Boxes and bananas, nitro and gum swap for 5 s | Space | Items change look | Chasers hit bananas |

## learning

| Skill | Tier | Level | Status | What | How | Cue | Worked when |
|---|---|---|---|---|---|---|---|
| learning at each lap end | genre | intermediate | tested | a parallel thread adds the lap's trouble spots to the next lap | a parallel thread adds the lap's trouble spots to the next lap |  |  |
| track memorisation | genre | intermediate | tested | per-track notes of trouble spots and good lines | per-track notes of trouble spots and good lines |  |  |
| track notes | genre | intermediate | tested | comes into its noted trouble spots slower and wider | comes into its noted trouble spots slower and wider |  |  |

## menus

| Skill | Tier | Level | Status | What | How | Cue | Worked when |
|---|---|---|---|---|---|---|---|
| Menu navigation | game | beginner | known | Reach a race by keys | Arrows, Enter, Esc (focus order unverified) | Main menu icons | Screen advances |
| controls card | game | intermediate | tested | every key the buddy presses is a key the player really has bound | every key the buddy presses is a key the player really has bound |  |  |
| menu routes | game | intermediate | built | reaches races and menus with the keyboard, offline only | reaches races and menus with the keyboard, offline only |  |  |

## opponents

| Skill | Tier | Level | Status | What | How | Cue | Worked when |
|---|---|---|---|---|---|---|---|
| Unlock SuperTux difficulty | game | intermediate | known | Open the hardest tier | Reach 250 points (bonus karts at 190 and 280) | Difficulty ribbon shows SuperTux locked or unlocked | SuperTux selectable |

## perception

| Skill | Tier | Level | Status | What | How | Cue | Worked when |
|---|---|---|---|---|---|---|---|
| HUD reading | game | beginner | known | Locate state | Minimap BL, ranks TL, timer TR, lap under the timer, speed/nitro/place BR, item top-centre | Fixed regions | Values parse |
| read lesson boxes | game | intermediate | tested | reads on-screen instructions and acts on them at the right moment | reads on-screen instructions and acts on them at the right moment |  |  |

## playing

| Skill | Tier | Level | Status | What | How | Cue | Worked when |
|---|---|---|---|---|---|---|---|
| Look back | game | beginner | known | Rear camera | Hold B | Rear view | Can see karts behind |
| Normal Race | game | beginner | known | Finish first | Start boost, skids, items; laps set on track info | Place in the speedometer; lap counter | Lowest finishing position |
| 3 Strikes | game | intermediate | known | Last kart standing | Shield ready; hit the heart-marked spare-tire karts for lives | Tyre icons; "spare tire kart has been spawned!" | Lives regained; last alive |
| Bomb pass | game | intermediate | known | Hand off a 30 s bomb | Bump another kart | Bomb on your kart | The bomb moves to them |
| FTL survival | game | intermediate | known | Stay behind the leader | Sit in 2nd; never pass; hitting the leader adds 5 s | Kart labelled "Leader" | Not eliminated at zero |
| Free-For-All | game | intermediate | known | Top score | +1 per hit; avoid self-hits and falls (−1) | Scores in brackets by the names | Highest score at the time limit |
| GP consistency | game | intermediate | known | Most points | Finish top 2 every race; ties go to the lower total time | Standings | GP win |
| Ghost replay | game | intermediate | known | Beat a recorded ghost | Finish at or under the replay's minimum time | Ghost kart | Challenge passes |
| Time Trial | game | intermediate | known | Fastest time, no powerups | Pure driving; meet the story time limit | Timer top-right (counts down with a target) | Time at or under the limit |
| Beat Nolok | game | pro | known | Win Fort Magma | Perfect start; lead early; shield vs backward bowling and gum | Nolok kart | 1st place; unlocks gnu and nolok |
| Drive / steer | genre | beginner | known | Accelerate, brake/reverse, steer | Up, Down, Left/Right; about 0.225 s to full lock, 0.1 s to re-centre | Road, minimap | Kart follows the line |
| Lap Trial | genre | intermediate | known | Most laps in the time limit | Clean fast laps | Timer (lap display unverified) | Lap count at time-out |

## racing

| Skill | Tier | Level | Status | What | How | Cue | Worked when |
|---|---|---|---|---|---|---|---|
| comeback plan | genre | intermediate | known | when far behind: maximise items and nitro, take risks | when far behind: maximise items and nitro, take risks |  |  |
| defending | genre | intermediate | known | hold the inside line when a kart is close behind | hold the inside line when a kart is close behind |  |  |
| overtaking | genre | intermediate | known | pick the side, pass on a straight or the inside of a bend | pick the side, pass on a straight or the inside of a bend |  |  |
| position awareness | genre | intermediate | known | reads its place and lap from the screen and races accordingly | reads its place and lap from the screen and races accordingly |  |  |
| slipstream / drafting | genre | intermediate | known | tuck in behind a kart on a straight for a tow, then pass | tuck in behind a kart on a straight for a tow, then pass |  |  |

## recovery

| Skill | Tier | Level | Status | What | How | Cue | Worked when |
|---|---|---|---|---|---|---|---|
| focus + pause recovery | game | intermediate | tested | takes the front back and leaves the pause menu | takes the front back and leaves the pause menu |  |  |
| reverse off walls | game | intermediate | tested | backs off a wall with the wheel turned, before any rescue | backs off a wall with the wheel turned, before any rescue |  |  |
| Rescue | genre | beginner | tested | Back on the track | Backspace (not during another animation) | Kart lifted | Back on the track after 1.2 s |

## safety

| Skill | Tier | Level | Status | What | How | Cue | Worked when |
|---|---|---|---|---|---|---|---|
| hand-over (F9) and stop (F12) | genre | intermediate | tested | F9: the buddy lets go and waits; F12: everything stops | F9: the buddy lets go and waits; F12: everything stops |  |  |
| race gate | genre | intermediate | tested | no race key until the race map is on screen; never drives a menu | no race key until the race map is on screen; never drives a menu |  |  |
| results honesty check | genre | intermediate | tested | a win counts only if the results screen shows 1st and the right difficulty | a win counts only if the results screen shows 1st and the right difficulty |  |  |

## winning

| Skill | Tier | Level | Status | What | How | Cue | Worked when |
|---|---|---|---|---|---|---|---|
| Story challenge entry | game | beginner | known | Open a challenge | Drive to the spot, press Space (fire); do not change laps or karts | Challenge dialog | Dialog opens if the point gate is met |
| Egg Hunt | game | intermediate | known | Find all eggs | Explore; time is the score | Eggs on the track (HUD egg display unverified) | Hunt ends when all eggs are found |
