# adk_app

PlayFellow on Google ADK (research R1 section 1.2 and 4.2, R2 section 1.3).

## Files

- `agents.py`: The ADK graph for one episode (research R1 section 1.2): a loop of perceive, route, decide, act, check.
- `callbacks.py`: The guardrails as plain functions (research R1 section 2.4 and 4.2): they run before a tool or an action, mutate it to something safe, and say what they changed.
- `tracing.py`: AD4: ADK's own tracing, beside our pf-trace/1 and the Perfetto export: one file to look at for the ADK side and the app side.
- `arena_eval/`: AD3: ADK's own evaluator scores our arena runs (`agent.py` is the agent it runs, `run.py` exports the evalset with our harness and writes the result).

## Environment (AD1)

ADK runs in its own virtual environment, never the app's: `python tools/adk_env.py --venv <a folder outside this repository>` installs
`requirements-adk.txt` (google-adk pinned to one version), checks it, and writes the exact resolved set to `requirements-adk.lock`
(`--from-lock` reproduces it). They cannot share one environment anyway: google-adk 2.13.0 needs websockets below 16 and our realtime voice
needs 16 or later. The tests that run the graph on ADK's runner skip, with that reason, in any environment without ADK, and run in this one:
`<folder>/Scripts/python -m pytest tests/test_adk_app.py`.
