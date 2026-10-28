"""Tools and execution flow, part one: everything the buddy can do sits behind one door.

A tool is a name, a plain sentence about it, and a function. Skills, small helper functions, memory search, and tools offered by an outside tool server (MCP) are all
registered the same way and called the same way, so the safety rules apply to all of them at once:

  * an unknown name does nothing, and a tool outside the allow-list (the tool filter) does not exist for the model;
  * guards run before the tool and can refuse it (a policy check on the model's arguments, like ADK's before-tool callback);
  * a sensitive tool needs the player's approval first (always, or only when a rule over the arguments says so);
  * a crash becomes an error answer, never a crash of the game session;
  * the answer is always a dict with a "status" key (ok or error), like ADK's function tools; an outside tool's text is fenced as untrusted data;
  * every call and every answer is written to the session with who made it.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from playfellow_coop.harness.security import Confirmation, fence
from playfellow_coop.harness.state import Session

KINDS = ("skill", "function", "mcp")
Guard = Callable[["Tool", dict], "str | None"]  # returns a reason to refuse, or None to allow


@dataclass
class Tool:
    name: str
    about: str  # one plain sentence: the model reads it to choose
    run: Callable[..., Any]
    kind: str = "function"
    needs_confirm: "bool | Callable[[dict], bool]" = False  # True: always ask; a function: ask when it returns True (a crash in it means ask)
    schema: dict = field(default_factory=dict)  # a small JSON schema of the arguments; empty means none
    confirm_samples: tuple = ()  # example arguments: a rule that never asks on any of them is refused when the tool is registered


@dataclass
class Outcome:
    tool: str
    ok: bool
    result: dict = field(default_factory=dict)  # always has "status"
    error: str = ""  # "unknown_tool", "not_allowed", "blocked:<why>", "not_approved", "failed:<why>"
    text: str = ""  # what the model reads: fenced when the tool is an outside one


def _status_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value if "status" in value else {"status": "ok", **value}
    return {"status": "ok", "result": value}


class ToolRegistry:
    def __init__(self, session: Session | None = None, confirmation: Confirmation | None = None, allowed: set[str] | None = None):
        self.session = session
        self.confirmation = confirmation or Confirmation()
        self.allowed = None if allowed is None else set(allowed)  # the tool filter: only these names are visible and callable
        self._tools: dict[str, Tool] = {}
        self._guards: list[Guard] = []

    def register(self, tool: Tool) -> None:
        if tool.kind not in KINDS or not tool.name.replace("_", "").replace(".", "").isalnum():
            raise ValueError(f"bad tool {tool.name!r}")
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        if callable(tool.needs_confirm) and tool.confirm_samples and not any(self._asks(tool, dict(s)) for s in tool.confirm_samples):
            raise ValueError(f"the approval rule of {tool.name!r} never asks on its own examples: it would remove the gate")
        self._tools[tool.name] = tool

    def add_guard(self, guard: Guard) -> None:
        self._guards.append(guard)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(n for n in self._tools if self.allowed is None or n in self.allowed)

    def describe(self) -> str:
        return "\n".join(f"- {n}: {self._tools[n].about}" + (" (may ask the player first)" if self._tools[n].needs_confirm else "") for n in self.names)

    @staticmethod
    def _bad_arguments(tool: Tool, arguments: dict) -> str:
        """Only declared arguments get through. A name that starts with an underscore is always refused (it could reach a function's own internal parameters), a tool
        that declares a schema accepts only the names in its properties, and a plain function accepts only the parameters its signature has."""
        for key in arguments:
            if not isinstance(key, str) or key.startswith("_"):
                return f"argument {str(key)[:20]!r} is not allowed"
        props = (tool.schema or {}).get("properties")
        if props is not None:
            extra = [k for k in arguments if k not in props]
            return f"undeclared argument {extra[0]!r}" if extra else ""
        if tool.kind != "mcp":
            try:
                params = inspect.signature(tool.run).parameters
            except (TypeError, ValueError):
                return ""
            if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
                extra = [k for k in arguments if k not in params]
                return f"undeclared argument {extra[0]!r}" if extra else ""
        return ""

    @staticmethod
    def _asks(tool: Tool, arguments: dict) -> bool:
        gate = tool.needs_confirm
        if callable(gate):
            try:
                return bool(gate(arguments))
            except Exception:  # a rule that crashes asks: the safe answer
                return True
        return bool(gate)

    def call(self, name: str, arguments: dict | None = None, who: dict | None = None) -> Outcome:
        arguments = dict(arguments or {})
        self._note("tool_call", {"tool": name, "args": arguments}, who)
        tool = self._tools.get(name)
        if tool is None:
            return self._finish(Outcome(name, False, {"status": "error"}, "unknown_tool"), who)
        if self.allowed is not None and name not in self.allowed:
            return self._finish(Outcome(name, False, {"status": "error"}, "not_allowed"), who)
        refused = self._bad_arguments(tool, arguments)
        if refused:
            return self._finish(Outcome(name, False, {"status": "error"}, f"blocked:{refused}"[:120]), who)
        for guard in self._guards:
            try:
                reason = guard(tool, arguments)
            except Exception as error:  # a guard that crashes refuses
                reason = f"guard crashed ({type(error).__name__})"
            if reason:
                return self._finish(Outcome(name, False, {"status": "error"}, f"blocked:{reason}"[:120]), who)
        if self._asks(tool, arguments) and not self.confirmation.approve(name, arguments):
            return self._finish(Outcome(name, False, {"status": "error"}, "not_approved"), who)
        try:
            result = _status_dict(tool.run(**arguments))
        except Exception as error:  # a tool's crash is an answer, not the end of the session
            return self._finish(Outcome(name, False, {"status": "error"}, f"failed:{type(error).__name__}"), who)
        shown = str(result)
        text = fence(f"answer of tool {name}", shown) if tool.kind == "mcp" else shown[:500]
        return self._finish(Outcome(name, True, result, text=text), who)

    def _note(self, kind: str, data: dict, who: dict | None) -> None:
        if self.session is not None:
            self.session.append(kind, data, who=who)

    def _finish(self, outcome: Outcome, who: dict | None) -> Outcome:
        self._note("tool_result", {"tool": outcome.tool, "ok": outcome.ok, "error": outcome.error}, who)
        return outcome


# ---- adapters: skills, memory, outside tool servers
def skill_tool(book, parts, box, stop: Callable[[], bool]) -> Tool:
    """The game's skill as a tool: running it plays many steps. Its answer says how many and why it stopped."""
    def run(max_steps: int | None = None) -> dict:
        result = book.run(book.skill.name, parts, box, stop, max_steps=max_steps)
        return {"status": "ok", "steps": result.steps, "stopped": result.stopped}
    return Tool(book.skill.name, book.skill.about, run, kind="skill")


def memory_tool(bank, game: str) -> Tool:
    """Search the long-term facts for this game ('load memory' when the agent decides). Read-only; the answer is fenced data."""
    def run(limit: int = 4) -> dict:
        return {"status": "ok", "facts": bank.context_for(game, max(1, min(int(limit), 8)))}
    return Tool("memory.search", "Recall what worked before in this game.", run, kind="function")


class McpClient(Protocol):
    """What the registry needs from an MCP connection: list the tools it offers and call one. A real client wraps the protocol; tests use a fake."""

    def list_tools(self) -> list[dict]: ...

    def call_tool(self, name: str, arguments: dict) -> Any: ...


def _remote_call(client: McpClient, remote: str) -> Callable[..., Any]:
    """Bind the remote tool's name in a closure. It must never be a parameter the model's arguments could reach: otherwise a read-only tool's name could be used
    to call a sensitive remote tool without the approval that tool needs."""
    def run(**arguments):
        return client.call_tool(remote, arguments)
    return run


def register_mcp(registry: ToolRegistry, client: McpClient, prefix: str, read_only: set[str] | None = None) -> list[str]:
    """Offer an outside server's tools. Each is `<prefix>.<name>`; every one asks the player first unless it is named in `read_only`.

    The server's description of its own tools is data too: it is cleaned and shortened before it reaches the model.
    """
    added = []
    for spec in client.list_tools():
        remote = str(spec.get("name", ""))
        if not remote:
            continue
        local = f"{prefix}.{remote}"
        about = fence("tool description", str(spec.get("description", "")), limit=160).replace("\n", " ")
        registry.register(Tool(local, about, _remote_call(client, remote), kind="mcp",
                               needs_confirm=remote not in (read_only or set()), schema=spec.get("input_schema") or {}))
        added.append(local)
    return added
