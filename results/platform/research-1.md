# Rayman Legends and metroidvania games: own research (pass 1)

Marks: [V] verified on this PC or in our own code. [S] from a web search snippet (the full page refused automated reading). [K] from general knowledge, NOT verified: treat as a hypothesis. [M] measured in our own live run on 2 Nov.

Blocked sources: speedrun.com guide, raymanpc.com wiki and manual, trueachievements, primagames, strategywiki (HTTP 403), fandom (402), IGN (refused). So this pass is thin on exact numbers; the Deep Research pass must fill them.

## 1. What we already have [V]

- Controls card `controls/rayman_legends.yaml` in the engine: genre platformer; LEFT, RIGHT, UP, DOWN, RUN_LEFT, RUN_RIGHT, JUMP_RIGHT, and raw keys SPACE, ENTER, ESC, W, A, S, D, Q, E, Z, X, C, SHIFT, BACKSPACE, TAB.
- Card hint: from the title screen press a key, choose Continue; menus are arrows plus Enter; on-screen hints like "[W] Open" and "(ESC) Help" show keys; attack is S; Teensies in floating cages need a jump or glide, then attack.
- Genre skill `skills/platform_runner.py` (`run_and_jump`): runs, jumps when the picture stops moving, jumps again, backs off, attacks every few steps, and jumps at pits it can see in pixels. Its own notes list the limits: busy backgrounds and hazards that look like ground are not seen.
- `pace.py`: real-time genres get several actions a turn (platformer, metroidvania and others).
- Owner's live run, 2 Nov [M]: 31 of 31 turns chose one action; the widget shows over full-screen Rayman; keys reach the game by scan code (private `dev/rayman/key_check.py`).
- Installed for this user: a save exists under Documents\Rayman Legends; no install found under Ubisoft launcher `games`, so the install path is unknown. Key bindings not read from a file yet.
- Private rule: results only in public, no Rayman media, no copied art or levels.

## 2. Game structure

- [S] Over 120 levels, about 40 remastered from Rayman Origins. Worlds are paintings in a gallery hub; Teensies unlock worlds. Levels can be played in any order within what is open.
- [S] Each level: 10 Teensies; Lums for a cup. Gold usually needs 600 Lums, "can vary by level". Single-player levels give up to 2 gold cups: one for all 10 Teensies, one for Lums.
- [S] Cups: Bronze, Silver, Gold, Diamond. Awesomeness points per cup: Bronze 1, Silver 5, Gold 10, Platinum 50. Diamond in a world painting needs all Teensies and gold in every level.
- [S] Modes: story paintings, Invaded versions (speed runs), music/rhythm levels, Back to Origins, daily and weekly online Challenges. For us: Challenges are online leaderboards and stay out of scope.
- [S] On PC, Murfy moves by himself; the player presses a button when prompted (cut ropes, move mechanisms, grab enemies).

## 3. Moves

- [S] Hold jump after jumping to hover and cross gaps. Wall jump: leap off walls. Air kick can be cancelled with a hover, for stalling or a second kick; used to speed up boss fights.
- [K] Run key held gives sprint. Attack during a jump gives an air kick; attack with down in the air is a ground pound. Holding attack charges a stronger punch. Running up curved walls keeps momentum. Hanging on ledges and swinging on ropes. Bubbles and Lum bubbles pop on touch. A hit in the air with no heart means death. A heart absorbs one hit. Lum King doubles Lum value for a short time. Skull coins are worth many Lums but must be reached and carried to safety. Death returns to the last checkpoint.

## 4. Hazards and what to read in the picture [K]

Enemies; spikes; rising water or lava scrolling levels; chase levels where the screen pushes the player; music levels where jumps are timed to the beat; underwater levels with oxygen-free swimming; dark levels; dragon-flying levels; boss arenas with patterns.

## 5. Metroidvania genre

- [S] Core loop: gain an ability, remember a wall you could not pass, go back, pass it. Note every blocked path and carry that list.
- [S] Map: read it often, use markers, shortcuts, save points. Rushing causes deaths; spend currency on upgrades and maps.
- [S] Bosses: 2-3 phases with learnable patterns. Survive by only dodging first, to learn the pattern; then attack in safe openings; prepare before the fight.
- [S] Discovery: some items are hidden in plain sight, others behind subtle clues.
- [K] Skills: i-frames on dash; hit-and-retreat; health management; farm safely; check dead ends for false walls; restock at save rooms; manage ammo; return to the last save on low health; record boss phase changes; route planning by shortest ability-unlocked path.

## 6. What a program needs for these genres

| Need | Status |
|---|---|
| Stuck, gap and enemy reading | Partly: `run_and_jump`, weak on busy art |
| Knowing where it is in a level | Missing: no map in Rayman; progress must come from scroll motion |
| Reading hints and prompts ("[W] Open", Murfy) | Reader built for STK; not wired here |
| Menus and gallery | Missing; `menus.Navigator` can be reused |
| Boss patterns | Missing |
| Memory of blocked paths and abilities (metroidvania) | Missing |
| Death and checkpoint recovery | Missing |

## 7. Open questions for pass 2

1. Exact default PC keyboard bindings, and how to read them from this install.
2. Every move with inputs, timing windows and uses, including speedrun tech.
3. Lum thresholds per cup and how much each collectible is worth.
4. Teensy locations rules (where they hide, cues in the picture).
5. All level types and the skill each needs, including music levels and how to follow the beat from audio or pictures.
6. Murfy prompts: what appears and which key.
7. Enemy and boss behaviours and patterns by world.
8. Menu and gallery flow from title to any level.
9. Pixel-only ways to read hearts, Lums, Teensies, checkpoints and death.
10. For metroidvanias: a method for an automatic map of explored rooms from pixels, blocked-path memory, boss learning across attempts.
