"""Speak ADK's evaluation language without importing ADK: evalset JSON for our recorded runs, and ADK's three trajectory match types.

ADK (adk.dev, evaluate) describes a test as an evalset: cases with a conversation, the expected tool calls (`intermediate_data.tool_uses`) and the final answer. A recorded PlayFellow run
(the skill the model chose, the keys it pressed) can be written in that shape, so the same file can be scored by ADK's own tools later and by `trajectory_match` here today. Nothing here
imports ADK; it only produces and reads plain JSON.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

MATCH_TYPES = ("EXACT", "IN_ORDER", "ANY_ORDER")


def _key(call: dict) -> str:
    return json.dumps({"name": call.get("name"), "args": call.get("args") or {}}, sort_keys=True)


def trajectory_match(expected: list[dict], actual: list[dict], match_type: str = "IN_ORDER") -> float:
    """1.0 or 0.0 by ADK's rules. EXACT: the same calls in the same order and nothing extra. IN_ORDER: the expected calls appear in order, extra calls between them are fine.
    ANY_ORDER: every expected call appears, in any order, extras are fine (each expected call needs its own matching actual call)."""
    if match_type not in MATCH_TYPES:
        raise ValueError(f"match_type is one of {MATCH_TYPES}")
    want, got = [_key(c) for c in expected], [_key(c) for c in actual]
    if match_type == "EXACT":
        return 1.0 if want == got else 0.0
    if match_type == "IN_ORDER":
        position = 0
        for call in got:
            if position < len(want) and call == want[position]:
                position += 1
        return 1.0 if position == len(want) else 0.0
    missing = Counter(want) - Counter(got)
    return 1.0 if not missing else 0.0


def eval_case(eval_id: str, turns: list[dict], app_name: str = "playfellow", user_id: str = "player", state: dict | None = None) -> dict:
    """One ADK eval case. Each turn: {"user": text, "final": text, "tool_uses": [{"name", "args"}]}."""
    conversation = []
    for index, turn in enumerate(turns, start=1):
        item = {"invocation_id": f"inv_{index}", "user_content": {"parts": [{"text": str(turn.get("user", ""))}]},
                "intermediate_data": {"tool_uses": [{"name": c["name"], "args": c.get("args") or {}} for c in turn.get("tool_uses", [])]}}
        if turn.get("final") is not None:
            item["final_response"] = {"role": "model", "parts": [{"text": str(turn["final"])}]}
        conversation.append(item)
    return {"eval_id": eval_id, "conversation": conversation, "session_input": {"app_name": app_name, "user_id": user_id, "state": state or {}}}


def evalset(eval_set_id: str, name: str, cases: list[dict], description: str = "") -> dict:
    return {"eval_set_id": eval_set_id, "name": name, "description": description, "eval_cases": cases}


def save_evalset(path: Path, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")


def expected_calls(case: dict) -> list[dict]:
    """The expected tool calls of a case, all turns in order (read back from an evalset file)."""
    return [call for turn in case.get("conversation", []) for call in (turn.get("intermediate_data") or {}).get("tool_uses", [])]
