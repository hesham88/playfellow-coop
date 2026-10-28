"""Model-written skills (research R1 section 3.3, R2 section 4): a frontier model writes a small deterministic controller for a game nobody wrote a skill for, and the harness only lets
it near the game after it has passed a static gate, three offline checks, and an isolated process.

  ast_gate   layer 1: what the code may contain at all
  sandbox    layer 2: runs it in a separate, scrubbed process with a hard per-step time limit and a safe fallback action
  verify     the three gates against a recorded trace (latency and schema, counterfactual threat avoidance and anti-deadlock, a live trial)
  library    where verified skills live (`.agents/skills/<game>/`), with receipts; the only place this package writes
  promote    TORSI's rule: a candidate replaces the current skill only when validation strictly improves; the held-out test is never used to choose; hard spend cap
  synth      asks a model for the code (one retry with the violation) and runs the pipeline
"""
