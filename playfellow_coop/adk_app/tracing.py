"""AD4: ADK's own tracing, beside our pf-trace/1 and the Perfetto export: one file to look at for the ADK side and the app side.

ADK records an OpenTelemetry span for every agent run (`invoke_agent`) and tool call (`execute_tool`). `SpanCapture` (the ADK environment only, AD1) collects
them in memory; `to_chrome` turns them into Chrome-trace events Perfetto opens, one track per agent; `merge` puts them beside the app-side document that
`trace_perfetto.to_events` makes from a pf-trace/1 file. ADK also records prompts, answers, tool arguments and tool results on its spans: none of that is ever
kept. Only the attributes in `ALLOWED` cross over, so the file holds names and timings, never a word, a picture or a key (the pf-trace rule).

    <adk env>/Scripts/python -m playfellow_coop.adk_app.tracing --game snake --seed 0 --steps 150 --out results/adk/episode
        plays one episode through the ADK graph with the game's local skill, and writes <out>.trace.jsonl (pf-trace/1, every turn tagged with who acted)
        and <out>.perfetto.json (the app side and the ADK spans together). No model, no spend.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ALLOWED = ("gen_ai.operation.name", "gen_ai.agent.name", "gen_ai.tool.name", "gen_ai.tool.type", "error.type")
PID = 2  # the app side (trace_perfetto) is process 1
CLOCK_NOTE = "ADK spans use their own clock, from the first span; the app side lays requests end to end (order and duration, not the time of day)"


class SpanCapture:
    """Collect ADK's OpenTelemetry spans in memory while it runs. Uses the global provider if one is set (adding a processor), else sets one."""

    def __init__(self):
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider()
            trace.set_tracer_provider(provider)
        self._exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(self._exporter))

    def spans(self) -> list[dict]:
        """Finished spans as plain dicts, oldest first, with only the allowed attributes."""
        out = []
        for span in self._exporter.get_finished_spans():
            attributes = {k: v for k, v in dict(span.attributes or {}).items() if k in ALLOWED}
            parent = span.parent.span_id if span.parent is not None else None
            out.append({"name": span.name, "start_ns": int(span.start_time), "end_ns": int(span.end_time), "span_id": span.context.span_id,
                        "parent_id": parent, "attributes": attributes})
        return sorted(out, key=lambda s: s["start_ns"])


def to_chrome(spans: list[dict]) -> list[dict]:
    """Chrome-trace events for Perfetto: a process "ADK agents", one thread per agent, a complete slice per span. Attributes outside ALLOWED are dropped
    here too, so a caller that hands raw spans cannot leak content."""
    if not spans:
        return []
    origin = min(s["start_ns"] for s in spans)
    threads: dict[str, int] = {}
    events = [{"ph": "M", "pid": PID, "name": "process_name", "args": {"name": "ADK agents"}}]
    for span in spans:
        attributes = {k: v for k, v in (span.get("attributes") or {}).items() if k in ALLOWED}
        agent = str(attributes.get("gen_ai.agent.name") or "adk")
        if agent not in threads:
            threads[agent] = len(threads) + 1
            events.append({"ph": "M", "pid": PID, "tid": threads[agent], "name": "thread_name", "args": {"name": agent}})
        start, end = span["start_ns"], max(span["end_ns"], span["start_ns"])
        events.append({"ph": "X", "pid": PID, "tid": threads[agent], "ts": (start - origin) // 1000, "dur": max(1, (end - start) // 1000),
                       "name": str(span["name"])[:80], "cat": str(attributes.get("gen_ai.operation.name") or "adk"), "args": attributes})
    return events


def merge(document: dict, adk_events: list[dict]) -> dict:
    """The app-side Perfetto document (trace_perfetto.to_events) with the ADK events beside it."""
    merged = {**document, "traceEvents": list(document.get("traceEvents", [])) + list(adk_events)}
    merged["metadata"] = {**document.get("metadata", {}), "adk_spans": sum(e.get("ph") == "X" for e in adk_events), "adk_clock": CLOCK_NOTE}
    return merged


def trace_episode(game: str, seed: int, steps: int, out: Path) -> dict:
    """Play one episode through the ADK graph with the game's local skill; write the pf-trace/1 file and the merged Perfetto file. Returns a summary."""
    from bench import arena_run as ar
    from playfellow_coop import trace as pf_trace
    from playfellow_coop import trace_perfetto
    from playfellow_coop.adk_app.agents import Deps, run_episode
    from playfellow_coop.gym import PlayfellowGym
    from playfellow_coop.harness.security import Identity
    from playfellow_coop.skills.registry import SKILLS

    capture = SpanCapture()
    out.parent.mkdir(parents=True, exist_ok=True)
    trace_path, perfetto_path = out.with_suffix(".trace.jsonl"), out.with_suffix(".perfetto.json")
    for path in (trace_path, perfetto_path):
        if path.exists():
            raise FileExistsError(path)  # like every trace: never written over
    who = Identity("adk:episode", "episode")  # run_episode's ADK session is named "episode"
    tracer = pf_trace.Trace(trace_path, f"adk-{game}-{seed}", who=who)
    env = PlayfellowGym(game, lambda s: ar.load_game(game, s), seed=seed)
    frame, _ = env.reset()
    skill = SKILLS[game]()
    skill.reset()
    box = {"frame": frame, "done": False}

    def decide(tier, state):
        try:
            key = skill.next_key(box["frame"])
        except Exception:  # noqa: BLE001 (a finished skill: nothing more to press)
            key = None
        return {"keys": [key] if key else [], "hold_ms": 0}

    def act(safe):
        key = safe["keys"][0] if safe["keys"] else None
        box["frame"], _, terminated, truncated, _ = env.step(key)
        box["done"] = terminated or truncated
        card = env.card()
        tracer.turn(actions=list(safe["keys"]), won=bool(card.won) if box["done"] else None, progress=card.progress)

    keys = [k for k in getattr(env, "action_space", [])] or ["left", "right", "up", "down", "space"]
    deps = Deps(grab=lambda: box["frame"], decide=decide, act=act, watch=lambda s: {"episode_terminated": box["done"]}, max_steps=steps,
                initial_state={"allowed_keys": keys, "socd_mode": "neutral", "fps": 60})
    result = run_episode(deps)
    tracer.close()
    spans = capture.spans()
    document = merge(trace_perfetto.to_events(trace_perfetto.read_trace(trace_path)), to_chrome(spans))
    with open(perfetto_path, "x", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False)
    card = env.card()
    return {"game": game, "seed": seed, "steps": int(result.get("step", 0)), "won": bool(card.won), "progress": card.progress, "adk_spans": len(spans),
            "agents": sorted({s["attributes"].get("gen_ai.agent.name", "") for s in spans} - {""}), "trace": trace_path.as_posix(), "perfetto": perfetto_path.as_posix()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One episode through the ADK graph, traced on both sides (AD4).")
    parser.add_argument("--game", default="snake")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--steps", type=int, default=150)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(trace_episode(args.game, args.seed, args.steps, args.out), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
