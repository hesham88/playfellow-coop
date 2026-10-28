"""The four parts of the buddy's harness, in one package.

A harness is everything around the model: what it remembers, which tools it can use and in what order, where it may act and what it may touch, and how we
know it did well. One part per module, each with a plain job:

  1. Context and memory    state.py (the session transcript and the scratchpad), memory_bank.py (distilled facts that carry over to later games)
  2. Tools and flow        tools.py (skills and plain functions behind one door, optional outside tool servers), flow.py (steps, parallel checks, a retry limit, then ask the player)
  3. Runtime and security  security.py (outside text is data, never orders; approval before sensitive actions; who did what; what is stored and for how long)
  4. Evaluation            evaluate.py (code checks for clear rules, a model judge for clarity, the player's own review for what neither can see)

The design follows the harness course the owner supplied (reports/2026-10-28/harness course.txt) and Google's ADK pages it links; the code is our own.
"""
