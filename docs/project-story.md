# Project story: a co-op for hands that can't keep up

## Who this is for

Adult gamers whose hands limit their play: people who play one-handed, people with tremor, with repetitive strain or fatigue, with slower reactions than the game expects. Not as a diagnosis and never as a label — the person decides if this describes them. For them, the choice today is often between adaptive hardware, a friend at the keyboard, or not playing the game at all.

PlayFellow adds a software option: an AI buddy that watches one game window, plans over numbered marks on the screen, and presses **only the keys on a controls card the player approved**. The player steers. Two controls never leave the player's hands:

- **F9 — take over / hand back.** At any moment the player takes the controls; every held key is released, the buddy presses nothing and asks no AI. F9 again hands control back, with a one-line summary built only from counted facts.
- **F12 — stop.** Instant, total, and it cannot be switched off in settings.

## Why this shape

An assistant that plays *instead of* you takes the game away. An assistant that plays *with* you, inside a list of keys you chose, keeps the game yours — and keeps you safe in it. That is why the marks, the planner and the debrief all answer to the controls card, and why the debrief may only say what it counted.

## Honest impact, at event scale

This is a hackathon build, and we claim only what exists:

**Measured (in the repo, reproducible):** the hand-over, the marks scoring harness, the stage timing and the spending cap are built and tested offline (pretend eyes, hands and brain; a fake SAM/Muse server; the Practice Arena's own ground truth). The underlying engine's last measured scoreboard before the event was level L0 of its public ladder: safety layer, controls cards and the Arena working, no ladder level passed by a learned navigator yet. We publish that scoreboard; we do not round it up.

**Not yet measured (labelled planned or unverified wherever it appears):** no live Muse or SAM call has been made yet — the endpoint and response shapes are unverified until the first capped real call; the hand-over has not yet been run live on the Arena; no disabled gamer has played with this build yet. The first live runs and the first consenting-adult play sessions are the next steps, and their results will be published either way.

**How much it could matter, if it works:** every game with a controls card becomes a game that can be shared between a player and a buddy, at the speed the player's hands allow, in English or Arabic, on an ordinary Windows PC. We do not put a number on that today; the honest measure will be the first play sessions: minutes played past the point where the player's hands would have stopped, counted with them, in their words.

## What we will never do with it

No play against other people online, no ranked or prize play, no input injection, no claim above the measured level, and no one's story without their pay, consent and own words.
