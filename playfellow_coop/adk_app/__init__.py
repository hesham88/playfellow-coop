"""PlayFellow on Google ADK (research R1 section 1.2 and 4.2, R2 section 1.3).

ADK is the deterministic spine: workflow agents loop the episode, custom agents do the perception, routing, skill and action work, and callbacks enforce the guardrails in code, outside any
prompt. The model-backed agents (tactical, strategic) are configured, not hard-wired, so the same graph runs with a fake brain in tests and with the Muse models in a paid run.

`import playfellow_coop.adk_app` costs nothing: ADK takes about five seconds to import, so it is loaded only inside `build_episode_agent` and `run_episode` (and a test proves the plain import
does not load it). `callbacks` holds the guardrail logic as plain functions that never need ADK.
"""
