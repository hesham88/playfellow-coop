# playfellow_coop

playfellow-coop: event work that plugs into the open PlayFellow engine.

## Files

- `__main__.py`: `python -m playfellow_coop`: play a game WITH the buddy.
- `_http.py`: The one way this package talks to the Meta Model API: a plain httpx client that ignores proxy and CA environment variables and refuses redirects, and one table that turns a status code into the engine's friendly BrainError.
- `backoff.py`: How to fail well against the Meta Model API: which errors to retry, how long to wait, and when to slow down before the limit.
- `bench.py`: The speed bench: run N turns of the composed loop and write ONE results file in the pf-results/1 shape.
- `budget.py`: A daily spending cap for the Muse brain, kept in a small file so a restart does not reset it.
- `control_words.py`: The few spoken (or typed) words that steer the HAND-OVER itself, matched exactly, with no AI: "stop", "you take it", "I've got it".
- `cua_brain.py`: The computer-use brain: the Responses API's native computer tool, behind the engine's one brain contract `ask(system, text, images) -> str`.
- `dry_run.py`: A dry run: the buddy looks, thinks and says what it would press, and nothing is ever pressed.
- `fakes.py`: A fake SAM server for offline demos and tests.
- `fastpath.py`: An optional Rust fast path (rust/fastpath) with an identical pure-Python twin.
- `handover.py`: The hand-over: the player takes the controls with one key (F9), plays, and gives them back with the same key.
- `harness_loop.py`: Propose, probe, compose: improve the buddy's harness on one task while the model stays fixed.
- `microphone.py`: Microphone capture behind a small interface, so everything above it is tested with a pretend microphone.
- `muse_brain.py`: The Muse brain: asks a Muse model on the Meta Model API what to do next.
- `push_to_talk.py`: Hold a key, speak, release: the spoken words become a command for the buddy.
- `realtime_voice.py`: Realtime push-to-talk: hold a key, speak, release; the words become a command for the buddy.
- `sam_eval.py`: Score SAM marks against the Practice Arena's own truth: precision, recall and latency, offline.
- `sam_marks.py`: SAM 3.1 marks: ask Meta's segmentation model where things are, and turn the answer into the engine's own marks.
- `sam_protocol.py`: The SAM 3.1 wire format, read and written exactly as the published docs describe it (dev.meta.ai/docs/sam: segmenting, reading segmentation output, client libraries).
- `sam_video.py`: SAM on a short clip instead of many single pictures: record recent frames, encode an MP4, upload it once, stream the answer, parse it frame by frame, delete the file.
- `session.py`: The plugin's own turn loop, written fresh around the engine's PUBLIC building blocks (no copy of the engine's play loop).
- `session_log.py`: The raw session log for the replay recorder (demo/record_replay.py): `--log <path>` writes it, nothing else ever does.
- `smoke.py`: The first real calls: five tiny, capped, confirmed requests (Muse Spark; SAM 3.1 twice, the second with a phrase that matches nothing; Muse Voice Transcribe once as a file and once over the realtime socket for at most 5 s of audio) that...
- `spatial.py`: A "that way is blocked" note for the planner, from marks alone (the one idea of JEV-Star's failed-option masking that fits here).
- `stage_timer.py`: Per-stage timing for one turn, and the summary the speed bench writes.
- `trace.py`: pf-trace/1: a JSON-lines trace of every request the session makes, for the credit-day trials and the cost report (demo/trace_report.py).
- `trace_perfetto.py`: Turn a pf-trace/1 file into a Chrome-trace JSON that Perfetto (Google, Apache-2.0, github.com/google/perfetto) opens: slices for each request and its encode, wait and parse parts on one track per stage, counters for tokens and cost, and...
- `tracking.py`: Follow what SAM found between SAM calls: fast, free, and honest about when to ask SAM again.
- `vlm_grounding.py`: Perception grounding by the language model itself (docs: image understanding, "Localize objects with perception grounding").
- `voice.py`: Voice commands ("grab the coins on the left"): Muse Voice Transcribe turns a short recording into text, and a typed line does the same job, so the demo never depends on a microphone.

## Folders

- `adk_app/`: see its README.md
- `agent/`: see its README.md
- `evalkit/`: see its README.md
- `gym/`: see its README.md
- `harness/`: see its README.md
- `overlay/`: see its README.md
- `serve/`: see its README.md
- `skills/`: see its README.md
- `skillsmith/`: see its README.md
- `universal/`: see its README.md
