# Design: the final submission pass (one entry point, a guided install, a README for players first)

Status: approved by the owner on 4 November 2026 (the order that started this pass). Reviews: `reviews/` beside this file.

## 1. Problem

Five outside reviews and one recorded critique read the repository the way a stranger does. They agree on four things:

1. **The README opens with measurements, not with the player.** Install and use come after two screens of tables, so a
   gamer with a tremor, a judge with ten minutes, or a contributor sees proof before they see how to start.
2. **Starting is harder than it should be.** The engine must be cloned beside this repository by hand; nothing checks
   that Python, the engine, the widget's Qt or the key are in place; SuperTuxKart has its own entry point; there is no
   command to list the open games, choose a model or store the key safely.
3. **The widget docks to the screen, not to the game,** when started from the main command (`--overlay`). Only the
   SuperTuxKart pack passes the game window to the widget today.
4. **The tone reads as defensive.** Inline file paths after every number, "we say that plainly", and stale notes ("when
   that merge lands", "after the owner's yes") make finished work look unfinished. Split controls are merged, yet the
   README still says they are on a branch.

## 2. Technical plan

- **One command, several verbs.** `python -m playfellow_coop` keeps every current flag. A first word selects a tool:
  `doctor`, `games`, `keys`, `models`, `stk`. Anything else runs the buddy exactly as today.
- **`doctor`** checks, in order: Python version, Windows, the engine (importable, at the pinned tag), this package's
  dependencies, the widget's Qt, the key (present or not, and where from; never a single character of it), and the
  open game windows. `doctor --fix` installs what is missing with pip and clones the engine at its tag beside this
  repository. Nothing in `doctor` sends a key or calls a model.
- **`games`** lists the open windows the engine may play (its own blocked-list applies), marks the ones it recognises,
  and prints the exact start command for each.
- **`keys`** stores the Meta key in the Windows credential manager (`keys set`, hidden input), shows only whether it is
  set and where from (`keys status`), and removes it (`keys remove`). It never prints, logs or sends the key.
- **`models`** lists the brains and model ids, with the measured cost per run from the committed result files, and how
  to run an open model on this PC for $0.
- **`stk`** forwards to the SuperTuxKart pack, so every game starts from one command.
- **The widget follows the game.** The main command hands the overlay a `follow` function built from the engine's own
  window finder; the widget then docks at the top centre of the game's client area and moves with it.
- **One-line install.** `bootstrap.ps1` (Windows) and `bootstrap.sh` create a virtual environment, clone the engine at
  `pre-hackathon`, install both, and run `doctor`.
- **README for three readers.** Order: what it is (TL;DR) -> install -> first game -> how to use (detect the game, start,
  widget, voice, hand-over) -> commands -> what it is built from (models, open models' cost) -> results (headline only)
  -> research -> what comes next -> judges -> contributing. The full measured tables move to `docs/metrics.md`, nothing
  dropped; one evidence note replaces the inline paths. Brand art from the video kit (logo, hero, banners, crew, icons).

## 3. Alternatives considered

- **Bundle the engine inside this repository.** Rejected: the hackathon rule is that this repository holds only event
  work; the engine stays an external dependency pinned to a tag. The bootstrap and `doctor --fix` remove the friction
  instead.
- **Docker image.** Rejected for play: a container cannot see or press keys in a Windows game window. It would only
  run the offline tests, which `bootstrap` + `pytest` already do natively. Not built; stated in the README.
- **A subparser rewrite of the CLI.** Rejected: it would change every existing flag and the tests around them. A
  first-word dispatch keeps all flags byte-for-byte.
- **Keep the tables in the README, only reorder.** Rejected: the critique's main point is the onboarding path; the
  README keeps the headline table and links the full set.

## 4. Detailed implementation (every file)

| File | Change |
|---|---|
| `playfellow_coop/cli_tools.py` (new) | `doctor`, `games`, `keys`, `models`, `stk`; pure functions with injectable probes so tests need no desktop, network or credential manager |
| `playfellow_coop/__main__.py` | first-word dispatch to `cli_tools`; `parts.follow` from the engine's window finder when `--overlay` is on |
| `playfellow_coop/overlay/runner.py` | `build_overlay` passes `parts.follow` to the Qt view; `game_follow()` helper |
| `tests/test_cli_tools.py` (new) | doctor ok/missing/fix plan, key never printed, keys set/status/remove with a fake store, games listing, models table, stk forwarding |
| `tests/test_overlay_follow.py` (new) | the follow function turns the engine's window box into the widget's rectangle; None when the game is gone |
| `bootstrap.ps1`, `bootstrap.sh` (new) | venv, engine clone at the tag, installs, doctor |
| `pyproject.toml` | `overlay` extra (PySide6) and `all` extra |
| `README.md` | rewritten in the order above, with the brand art |
| `docs/metrics.md` (new) | every measured table from the old README, unchanged numbers |
| `docs/img/brand/` (new) | logo, hero, section banners, dividers, crew, icons |
| `JUDGES.md` | the new one-line install and `doctor` |
| `docs/designs/final-submission/reviews/` | goldfish reviews of this design and of the README |

## 5. Answers to the readiness review (`reviews/01-readiness-goldfish.md`)

1. **Dispatch before the engine.** The first lines of `__main__.py`, before any engine import, check `sys.argv[1]`; a tool word runs
   `cli_tools.run()` and exits. `cli_tools` imports the engine only inside the checks that need it.
2. **`keyring`** joins the core dependencies. Extras: `overlay = [PySide6]`, `all = overlay + stk + video`.
3. **`stk`** forwards to `games.stk.mission` (the full run: widget + mission); `stk widget` forwards to the widget alone; every
   further argument passes through unchanged.
4. **Follow contract.** `overlay.runner.game_follow(screen, title)` (one place) calls the engine's `Screen.find`, which returns the
   game's *client area* as `WindowBox(left, top, width, height)`; it returns `(left, top, left+width, top+height)`, or `None` when the
   window is gone or the finder raises. It is one window lookup per tick and never raises. `__main__` only stores it on `parts.follow`;
   `build_overlay` reads that attribute, so its signature and every existing fake stay unchanged.
5. **Sources.** `models` reads the committed `results/fifteen/*.json` and `results/k-lane/*.json` (`cost_usd`/`episodes`/`wins` where
   present, else "not measured"). `games` uses the engine's `Screen.list_windows()`, `games.is_blocked()` and `games.detect_games()`,
   plus the controls cards in the engine's `controls/` folder. The engine check imports `play` and reads the clone's `git describe`
   when the engine folder is a git clone; otherwise it says "tag not checked".
6. See 4.
7. `DESIGN.md` is corrected to the `playfellow-coop` service.
8. `keys set` reads with `getpass`; `keys status` prints the source only (environment, credential manager, none), never characters
   or length; after `keys remove` it says when the environment variable still provides one. Tests use a sentinel and assert it is in
   neither stdout nor stderr.
9. `doctor --fix` prints the plan and asks; `--yes` skips the question. Tests inject the runner and assert nothing ran for real.
10. `bootstrap.sh` installs for the offline tests and replays on Linux/macOS; play is Windows-only, and it says so and exits 0.
11. Every desktop, keyring, pip and git touch is an injected callable; a test fails if the real `subprocess.run` is reached.
12. `tests/test_cli_tools.py::test_flags_still_reach_the_buddy` runs the old flag forms through the dispatcher and asserts they reach
    the unchanged parser.

**Done means:** every new command has a test written first; the full suite passes in one run; a stranger's install in a
clean virtual environment, following only the README, reaches `doctor` all green and a running offline session.
