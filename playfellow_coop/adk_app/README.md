# adk_app

PlayFellow on Google ADK (research R1 section 1.2 and 4.2, R2 section 1.3).

## Files

- `agents.py`: The ADK graph for one episode (research R1 section 1.2): a loop of perceive, route, decide, act, check.
- `callbacks.py`: The guardrails as plain functions (research R1 section 2.4 and 4.2): they run before a tool or an action, mutate it to something safe, and say what they changed.
