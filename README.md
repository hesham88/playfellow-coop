# meta-playfellow

**Built on the PlayFellow engine (hesham88/playfellow, tag `pre-hackathon` = the engine at kickoff plus packaging/test-isolation commits made in the first hour; no new features). Everything in this repo was built during the event.**

PlayFellow is an open-source engine that plays a PC game *with* you: it watches one game window, asks a brain what to do next, and presses only the keys that game's controls card allows. This repo adds the event work as a plugin package. It does not contain the engine; it installs it.

## What is new in this repo

| Piece | What it does | Status |
|---|---|---|
| `meta_playfellow/muse_brain.py` | A brain that asks a Muse model on the Meta Model API what to do. Pinned address, no proxy or CA variables, redirects refused, a daily spending cap that stops a call before it is sent, the key never shown | built, tested against a fake server; no live call yet |
| `meta_playfellow/budget.py` | The daily cap, kept in a small file so a restart does not reset it | built |
| SAM 3.1 marks | Labels what is on screen so the brain can say "go to R1" instead of guessing pixels | planned |
| Stage timer and speed bench | Times each step of a turn and writes a results file | planned |
| Hand-over | You and the buddy pass the controls back and forth with one key | planned |

Items marked planned are not built: a row changes only when a dated commit shows it.

## Install and run

```
git clone --branch pre-hackathon https://github.com/hesham88/playfellow.git
pip install -e playfellow
pip install -e .
```

The engine's controls cards and settings files sit next to its code, so the engine is installed editable (`-e`), from a clone of the tag.

## Tests

```
python -m pytest -q
```

Every test runs offline: a fake server on 127.0.0.1 stands in for the Meta API, and nothing presses a key, grabs the screen or spends money.

## What this does and does not do

It plays and talks with you. It does not judge or score the player. The demo uses our own Practice Arena, the arena pack and one open-source game.

## Credits and licence

Built by Hesham Aboul-Fetouh ([@hesham88](https://github.com/hesham88)) with AI coding assistance, including Muse Code. Licence: see the engine repository's `LICENSE`, which applies here as well. Meta, Muse and SAM are Meta's names, used here as plain text; this project is not affiliated with or endorsed by Meta.
