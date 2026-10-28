"""The ADK graph for one episode (research R1 section 1.2): a loop of perceive, route, decide, act, check.

    episode (LoopAgent)
      perception (ParallelAgent): hud, spatial, entities       -> state: obs, hud, position, entities
      router                                                   -> state: tier (reflex, tactical, strategic) and why
      decider                                                  -> state: action (the local skill at reflex; a model at the others, behind `deps.decide`)
      actuator                                                 -> guardrails in code, then the keys; state: pressed, notes
      watcher                                                  -> end-of-game detector; sets episode_terminated and escalates out of the loop

Every agent is a small `BaseAgent` that calls an injected function in `Deps`, so the graph is the same with fakes (tests), the hand-written skills (gym) and the Muse models (a paid run).
No agent has more than a few responsibilities, which is ADK's own advice against one agent with a pile of tools. ADK is imported here, inside the builder, never at module scope.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Callable

from playfellow_coop.adk_app.callbacks import episode_should_stop, guard_action


@dataclass
class Deps:
    """What the graph needs from the rest of the harness. Every field is a plain callable."""
    grab: Callable[[], Any]  # the current picture
    perceive_hud: Callable[[Any], dict] = lambda frame: {}
    perceive_space: Callable[[Any], dict] = lambda frame: {}
    perceive_entities: Callable[[Any], dict] = lambda frame: {}
    route: Callable[[dict], tuple[str, list[str]]] = lambda state: ("reflex", [])
    decide: Callable[[str, dict], dict] = lambda tier, state: {"keys": [], "hold_ms": 0}
    act: Callable[[dict], None] = lambda safe_action: None
    watch: Callable[[dict], dict] = lambda state: {}
    initial_state: dict = field(default_factory=dict)
    max_steps: int = 600


def build_episode_agent(deps: Deps):
    """The root LoopAgent for one episode. Imports ADK here (about five seconds the first time)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # ADK 2 marks LoopAgent and ParallelAgent as deprecated in favour of Workflow; the documented behaviour is what we use
        from google.adk.agents import BaseAgent, LoopAgent, ParallelAgent
        from google.adk.agents.invocation_context import InvocationContext
        from google.adk.events import Event, EventActions

        def event(agent, delta: dict, escalate: bool = False):
            return Event(author=agent.name, actions=EventActions(state_delta=delta, escalate=escalate or None))

        class Perception(BaseAgent):
            kind: str = "hud"

            async def _run_async_impl(self, ctx: InvocationContext):
                frame = ctx.session.state.get("frame")
                reader = {"hud": deps.perceive_hud, "spatial": deps.perceive_space, "entities": deps.perceive_entities}[self.kind]
                yield event(self, {self.kind: reader(frame)})

        class Grab(BaseAgent):
            async def _run_async_impl(self, ctx: InvocationContext):
                step = int(ctx.session.state.get("step", 0))
                yield event(self, {"frame": deps.grab(), "step": step})

        class Router(BaseAgent):
            async def _run_async_impl(self, ctx: InvocationContext):
                tier, why = deps.route(dict(ctx.session.state))
                yield event(self, {"tier": tier, "tier_reasons": why})

        class Decider(BaseAgent):
            async def _run_async_impl(self, ctx: InvocationContext):
                state = dict(ctx.session.state)
                yield event(self, {"action": deps.decide(state.get("tier", "reflex"), state)})

        class Actuator(BaseAgent):
            async def _run_async_impl(self, ctx: InvocationContext):
                state = dict(ctx.session.state)
                guard_state = {k: state[k] for k in ("allowed_keys", "socd_mode", "fps", "focus_ok") if k in state}
                safe, notes = guard_action(state.get("action") or {}, guard_state)
                deps.act(safe)
                yield event(self, {"pressed": safe, "guard_notes": notes, "step": int(state.get("step", 0)) + 1})

        class Watcher(BaseAgent):
            async def _run_async_impl(self, ctx: InvocationContext):
                state = dict(ctx.session.state)
                delta = dict(deps.watch(state))
                merged = {**state, **delta}
                stop = episode_should_stop(merged)
                delta["episode_terminated"] = bool(merged.get("episode_terminated")) or stop
                yield event(self, delta, escalate=stop)

        perception = ParallelAgent(name="perception", sub_agents=[Perception(name="hud", kind="hud"), Perception(name="spatial", kind="spatial"),
                                                                  Perception(name="entities", kind="entities")])
        return LoopAgent(name="episode", max_iterations=max(1, deps.max_steps + 1),
                         sub_agents=[Grab(name="grab"), perception, Router(name="router"), Decider(name="decider"), Actuator(name="actuator"), Watcher(name="watcher")])


async def run_episode_async(deps: Deps) -> dict:
    """Run one episode on ADK's runner with an in-memory session. Returns the final session state plus how many events the run produced."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    root = build_episode_agent(deps)
    service = InMemorySessionService()
    runner = Runner(app_name="playfellow", agent=root, session_service=service)
    state = {"step": 0, "max_steps": deps.max_steps, **deps.initial_state}
    await service.create_session(app_name="playfellow", user_id="player", session_id="episode", state=state)
    count = 0
    async for _ in runner.run_async(user_id="player", session_id="episode", new_message=types.Content(role="user", parts=[types.Part(text="play")])):
        count += 1
    final = await service.get_session(app_name="playfellow", user_id="player", session_id="episode")
    out = {k: v for k, v in dict(final.state).items() if k != "frame"}  # the picture is not kept in the summary
    out["events"] = count
    return out


def run_episode(deps: Deps) -> dict:
    import asyncio
    return asyncio.run(run_episode_async(deps))
