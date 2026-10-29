# harness

The four parts of the buddy's harness, in one package.

## Files

- `adk_compat.py`: Speak ADK's evaluation language without importing ADK: evalset JSON for our recorded runs, and ADK's three trajectory match types.
- `evaluate.py`: Evaluation: three ways to know the buddy did well, used together.
- `flow.py`: Tools and execution flow, part two: a small graph that does the work, runs independent checks in parallel, feeds failures back, and stops at a retry limit.
- `hooks.py`: Control-loop hooks: rules the loop enforces on itself, not suggestions in a prompt (Harness², research R5).
- `memory_bank.py`: Context and memory, part two: long-term facts that carry what worked into later games.
- `runtime.py`: The harness assembled: one object the turn loop holds.
- `security.py`: Runtime, security and privacy: outside text is data, sensitive actions need approval, every action says who did it, and what is kept is written down.
- `state.py`: Context and memory, part one: the session (the transcript) and its state (the scratchpad).
- `tools.py`: Tools and execution flow, part one: everything the buddy can do sits behind one door.
