# skillsmith

Model-written skills (research R1 section 3.3, R2 section 4): a frontier model writes a small deterministic controller for a game nobody wrote a skill for, and the harness only lets it near the game after it has passed a static gate,...

## Files

- `_worker.py`: The isolated worker: runs one generated skill, one observation per line.
- `ast_gate.py`: Layer 1: a static allow-list over the code a model wrote, before anything runs it.
- `library.py`: Where verified skills live: `<root>/.agents/skills/<game>/<name>.py`, each with a receipt, plus one `EXPERIENCE.md` of evidence-backed lessons (research R2 section 1.2).
- `loop.py`: Propose, Probe, Compose: the self-improvement loop (Harness² and TORSI, research R2 section 1.2 and 4.1, R5), run offline between matches.
- `osjail.py`: Layer 3: operating-system containment for the skill worker, so a gap in the two language layers (static gate, proxied modules) is not a full escape.
- `promote.py`: When a candidate skill may replace the current one (TORSI and Harness² "Compose", research R2 section 4.1) and how much the search may spend.
- `sandbox.py`: Layer 2: run a verified skill in a separate process that cannot see our secrets, with a hard time limit per step and a safe fallback.
- `synth.py`: Ask a model for a controller, check it, and run the whole pipeline (research R1 section 3.3 steps 1 to 3, R2 section 4.1).
- `verify.py`: The three offline gates a model-written skill must pass before it may touch a game (research R1 section 3.3, R2 section 4.1).
