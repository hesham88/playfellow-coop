# universal

The universal game interface: treat every game as a black box and use only the channels a human uses (pixels in, key and mouse out).

## Files

- `actions.py`: Pillar 1 (doing) and the guardrails of pillar 4: the model's action tokens become native inputs, and impossible ones never reach the game.
- `cache.py`: A state-action memory: do not ask the model again about a screen it has already answered (research R1 section 3.4 tier 3, R2 section 5.1 ActionCache and SPIKE's memory bank).
- `chunks.py`: Action chunks: one model call, many 33 ms actions, keys that stay down (research R1 section 2.1, R3 section 7 phase 1, Lumine's 30 Hz scheme).
- `eog.py`: End-of-game detection from pixels, without needing a distinct "game over" screen (research R1 section 3.1, R2 section 3.1).
- `flow_grounding.py`: Grounding for worlds that move on their own (research R2 section 3.2: flow with and without contingency).
- `frames.py`: Pillar 1, seeing: whatever the screen grabber hands over becomes ONE standard picture (height x width x 3, uint8, RGB).
- `hold.py`: Hold timing and opposite-direction cleaning: the physics of getting an input into a game (research R1 section 3.6 and section 2.4, R4 section 7.4).
- `hud.py`: Pillar 2, reading the screen's own furniture: bars, timers and text, with no knowledge of the game's code.
- `live.py`: The live loop's three cost levers, in one place the session can switch on (research R1 sections 2.3 and 3.4, R4 section 8).
- `motion.py`: Pillar 2, moving things: what changed between two pictures, where the camera went, and which things are moving, from pixels alone.
- `rate.py`: How fast pictures really arrive: the measured picture rate and the delay of the grabber.
- `scan_backend.py`: The engine's hands, pressing hardware scan codes instead of virtual-key messages.
- `skin_grounding.py`: Zero-shot grounding of an unknown skin or game from the first frames (research R1 section 3.2, R2 section 3.2).
- `state.py`: Pillar 4, knowing how it is going: what kind of screen this is, and whether the player's goal has been reached.
- `state_fit.py`: Build time only: teach the state classifier what a game's own screens look like, by playing the game and labelling its pictures from the game's state.
- `tiers.py`: Three loops, one router: who decides right now (research R1 sections 1.2 and 2.3, R4 section 8.1, SPIKE's event-triggered dual controller).
- `timing.py`: Pillar 3, the ticking clock and the running game.
- `watch.py`: The screen watch: the turn loop's one question to the universal interface, "what kind of screen is this, and is it worth asking the model?"
- `winio.py`: Windows input and window handling for real games (research R1 section 3.6, R4 section 2): focus, high-DPI coordinates, scan-code input.
