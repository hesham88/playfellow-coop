# Skill catalogue: intermediate on abyss

AI karts faster and use items: the start boost, skid boosts, nitro and clean bends now decide it; fewer stalls.

Wins so far: novice abyss 2026-11-03 18:49 (5:49.238) and 20:54 (4:29.365, best lap 1:27.042), both 1st of 4

Track notes (abyss): trouble spots at driveline points [9, 22, 24, 26, 27, 58, 60, 76, 96, 98, 101, 114, 116, 125, 132, 136, 138, 150, 153, 160, 164, 165, 177]

| skill | family | area | from | what it does | status |
|---|---|---|---|---|---|
| controls card | pre-skill | controls | the game's own input.xml | every key the buddy presses is a key the player really has bound | built |
| read lesson boxes | AI-skill | reading | tutorial + help pages (Muse vision) | reads on-screen instructions and acts on them at the right moment | built |
| menu routes | AI-skill | menus | explored 3 Nov (Muse vision + tooltip reader) | reaches races and menus with the keyboard, offline only | partly |
| race gate | pre-skill | safety | built 3 Nov | no race key until the race map is on screen; never drives a menu | built |
| hand-over (F9) and stop (F12) | pre-skill | safety | owner request 3 Nov | F9: the buddy lets go and waits; F12: everything stops | built |
| rocket start | pre-skill | start | help page + guide: accelerate at 'Set!' | full throttle exactly at 'Set!' (countdown read locally) | built |
| kart class: Tux, middleweight | pre-skill | physics | owner's guide | top speed 90 km/h (25 m/s), balanced acceleration, 225 kg; speed caps are set from it | built |
| minimap localisation | pre-skill | driving | the game's quads.xml + learned icon look | knows where the kart is on the track, 20 times a second | built |
| driveline pursuit | pre-skill | driving | the game's own driveline | follows the road; looks further at speed | built |
| calm straights | pre-skill | driving | owner feedback 3 Nov | holds the wheel still on straights (no weaving) | built |
| speed for the bend ahead | pre-skill | driving | owner feedback 3 Nov (fell off curves) | lifts before sharp bends, brakes a moment before very sharp ones | built |
| outside line in tight bends | pre-skill | driving | race notes 3 Nov (inner-wall stalls) | aims a little wide of the centre line in tight bends | built |
| track notes | learned skill | learning | its own race notes | comes into its noted trouble spots slower and wider | built |
| nitro on straights | pre-skill | boosts | tutorial lesson | taps nitro when the road ahead is straight | built |
| nitro tapping on a fading boost | pre-skill | boosts | owner's guide | tap nitro as a skid or zipper boost fades to hold top speed | built (not yet proven in a race) |
| skid boost (yellow +16.2 km/h, red +23.4 km/h) | pre-skill | boosts | tutorial + owner's guide | hold skid through a bend at least 1 s (game data), release lined up with the exit | built (not yet proven in a race) |
| brake-drift in hairpins | pre-skill | boosts | owner's guide | tap brake while drifting to pivot in tight hairpins | partly (brake taps before very sharp bends, no drift) |
| snaking on straights | pre-skill | boosts | owner's guide (speedrun) | chained hop-drifts on straights for repeated boosts | known, not built (speedrun trick, too risky in races) |
| hop / low-air hop | pre-skill | airborne | owner's guide | tap skid before a crest to land sooner | known, not built (needs crest detection) |
| zipper buffering | pre-skill | boosts | owner's guide | do not stack a zipper item or nitro on a ground zipper | known, not built |
| reverse off walls | pre-skill | recovery | owner request 3 Nov | backs off a wall with the wheel turned, before any rescue | built |
| rescue | pre-skill | recovery | tutorial lesson | Rescue when stalled again, lost, or going nowhere | built |
| focus + pause recovery | pre-skill | recovery | races 3 Nov (game paused itself) | takes the front back and leaves the pause menu | built |
| item hunt (SAM) | AI-skill | items | owner request; SAM 3.1 + tracker | picks one reachable gift box or nitro on gentle road, then the next | built (gentle pulls only) |
| obstacle avoidance (SAM) | AI-skill | items | owner request; SAM 3.1 + tracker | steers around bananas and crates in the path | built (gentle) |
| aimed firing (SAM) | AI-skill | items | owner request; SAM 3.1 + tracker | fires only with an opponent lined up, never at itself | built |
| held power reading | AI-skill | items | the game's own icon files | knows which power and how many charges it holds, 25 ms a look | built |
| power rules per item | AI-skill | items | the game's own AI + data | each power used at its moment; never thrown just to empty the hand | built (not yet proven in a race) |
| rear-firing (look back + fire) | AI-skill | items | help page + owner's guide | fire backwards when leading and a power has been held too long | partly (no sight of karts behind) |
| shielding (bubblegum) and swatter | AI-skill | items | help page + owner's guide | shield or swat with an opponent very close | partly (attachments on the kart are not read yet) |
| item blocking (drop behind) | AI-skill | items | owner's guide | drop a banana behind to block projectiles | known, not built |
| wall riding (magnet sections) | pre-skill | tracks | owner's guide | ride gravity surfaces on Cocoa Temple / STK Enterprise | known, not needed on Abyss |
| predictive drift | pre-skill | boosts | owner + tutorial + guide | measures the bend ahead, holds skid + turn through it, releases lined up | built (first live trial) |
| fast banana eye | AI-skill | items | owner 3 Nov (SAM too slow for bananas) | local yellow detector, 10 looks a second, dodges at once | built |
| learning at each lap end | learned skill | learning | owner: 'act in real time while learning in parallel' | a parallel thread adds the lap's trouble spots to the next lap | built |
| steering damping + speed schedule | pre-skill | driving | kart simulator (sim.py), 3 Nov | steers on where the error is going; gentler at speed | built (simulator-proven) |
| racing line (out-in-out) | pre-skill | driving | racing genre | wide entry, apex, wide exit for more speed through bends | partly (outside aim in tight bends) |
| braking points | pre-skill | driving | racing genre | brake before the bend, not in it | partly (speed for the bend ahead) |
| slipstream / drafting | pre-skill | racing | racing genre | tuck in behind a kart on a straight for a tow, then pass | known, not built |
| overtaking | pre-skill | racing | racing genre | pick the side, pass on a straight or the inside of a bend | known, not built |
| defending | pre-skill | racing | racing genre | hold the inside line when a kart is close behind | known, not built (needs a look behind) |
| position awareness | pre-skill | racing | the game's HUD | reads its place from the standings ring; leaders keep leader-hitting powers | built |
| shortcuts | pre-skill | tracks | track exploration | learned alternative routes per track | known, not built |
| jumps and ramps | pre-skill | airborne | racing genre | straight and centred before a jump, no steering in the air | known, not built |
| track memorisation | learned skill | learning | its own races | per-track notes of trouble spots and good lines | built (trouble spots) |
| comeback plan | pre-skill | racing | racing genre | when far behind: maximise items and nitro, take risks | known, not built |
| results honesty check | pre-skill | safety | 3 Nov correction | a win counts only if the results screen shows 1st and the right difficulty | built |
| command: menu / restart / race X | command-skill | commands | owner 3 Nov | voice or text makes the buddy go to the menu, restart, or start a race | built |
| command: stop / wait / take it back | command-skill | commands | owner 3 Nov | F12 / F9 / voice / text | built |
| command: driving tips | command-skill | commands | owner 3 Nov | more nitro / more items / dodge more / calmer, for this race | built |
| never silent | command-skill | commands | owner 3 Nov | the widget always says what the buddy is doing or waiting for | built |
