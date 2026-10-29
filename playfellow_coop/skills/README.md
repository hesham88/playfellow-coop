# skills

Skills: small local controllers the buddy can run for many game steps from one model decision.

## Files

- `base.py`: The skill contract and the loop that runs one.
- `book.py`: A skill book: the skills one game offers, how the model is told about them, and how a chosen skill is run through the session's own hands.
- `box_pusher.py`: Push boxes onto goals (the puzzle skill): read walls, boxes, goals and the player from the picture, search for the whole move list, then walk it.
- `calibration.py`: Build a Look for a game by watching it be played (BUILD TIME only).
- `grid_chase.py`: Chase the food on a grid without trapping yourself (the snake-style skill).
- `lane_runner.py`: Run down lanes, dodge what comes, grab coins (the runner skill).
- `looks.py`: A look: how one game's things appear in pixels, so the same skill reads the same game drawn another way.
- `looks_build.py`: Building a look (BUILD TIME only): turn labelled patch colours into prototypes, and save looks as JSON.
- `paddle_track.py`: Keep a paddle under the ball (the brick-breaker skill): launch, follow the ball's predicted landing spot, and aim shots at the bricks that are left.
- `pixels.py`: Reading a game picture: nearest-colour tests on single pixels and small areas.
- `registry.py`: Which skills exist for which game (the controls-card name of the game).
- `skill_brain.py`: A brain wrapper that lets ANY brain use skills, without touching the engine's loop.
- `tile_merge.py`: Slide-and-merge boards (the 2048-style skill): read the tile numbers from their colours, look two moves ahead, keep the big tile in a corner.
