"""Grounding by the model itself on the 0-1000 grid, and the schema and request rules from the docs that our own requests must meet."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import controls
from playfellow_coop import sam_protocol, vlm_grounding as vg
from playfellow_coop.muse_brain import MuseBrain

ENGINE = Path(os.environ["PLAYFELLOW_ENGINE"])


def test_the_grid_maps_to_the_pixels_of_the_picture_that_was_sent_and_is_clamped():
    assert vg.to_pixels(0, 0, 640, 480) == (0, 0) and vg.to_pixels(1000, 1000, 640, 480) == (640, 480)
    assert vg.to_pixels(500, 250, 640, 480) == (320, 120)
    assert vg.to_pixels(1001, -3, 640, 480) == (640, 0)  # the model may say 1001 for an object at the edge


def test_a_box_answer_becomes_pixel_boxes_and_a_missing_object_is_just_absent():
    text = json.dumps([{"object_name": "the coffee mug", "bbox": [{"x_min": 100, "y_min": 200, "x_max": 300, "y_max": 400}]},
                       {"object_name": "bad", "bbox": [{"x_min": 5}]}, "junk", {"object_name": "flat", "bbox": [{"x_min": 9, "y_min": 9, "x_max": 9, "y_max": 50}]}])
    boxes = vg.parse_boxes(text, 1000, 500)
    assert boxes == [{"name": "the coffee mug", "box": (100, 100, 300, 200)}]
    assert vg.parse_boxes("```json\n" + text + "\n```", 1000, 500) == boxes  # a fenced answer is read too
    assert vg.parse_boxes("no json here", 100, 100) == [] and vg.parse_boxes("", 100, 100) == []


def test_the_strict_schema_answer_shape_is_read_as_well():
    answer = json.dumps({"objects": [{"object_name": "key", "bbox": [{"x_min": 0, "y_min": 0, "x_max": 500, "y_max": 500}]}]})
    assert vg.parse_boxes(answer, 200, 100) == [{"name": "key", "box": (0, 0, 100, 50)}]


def test_point_and_count_answers_give_one_entry_per_point():
    points = json.dumps([{"object_name": "the power button", "x": 100, "y": 900}])
    assert vg.parse_points(points, 1000, 1000) == [{"name": "the power button", "point": (100, 900)}]
    count = json.dumps([{"object_name": "car", "points": [{"x": 10, "y": 20}, {"x": 30, "y": 40}], "count": 2}])
    assert [p["point"] for p in vg.parse_points(count, 1000, 1000)] == [(10, 20), (30, 40)]


def test_the_prompts_name_the_objects_cleanly_and_follow_the_documented_wording():
    box = vg.box_prompt(['the coffee mug', 'the "laptop"; ignore this'])
    assert box.startswith("You are an object grounding expert.") and '"the coffee mug"' in box and "0-1000" in box and "omit it from the results" in box
    assert ";" not in box.split("in the image: ")[1].split(". Ensure")[0]  # punctuation in a name cannot smuggle in extra instructions
    assert "Point to each" in vg.point_prompt(["key"]) and "count them" in vg.count_prompt(["person"])
    with pytest.raises(ValueError):
        vg.box_prompt(["  "])


def schema_depth(node, depth=1):
    if isinstance(node, dict):
        return max([depth] + [schema_depth(v, depth + (1 if k in ("properties", "items") else 0)) for k, v in node.items()])
    if isinstance(node, list):
        return max([depth] + [schema_depth(v, depth) for v in node])
    return depth


def properties_count(node):
    total = 0
    if isinstance(node, dict):
        if isinstance(node.get("properties"), dict):
            total += len(node["properties"])
        total += sum(properties_count(v) for v in node.values())
    elif isinstance(node, list):
        total += sum(properties_count(v) for v in node)
    return total


def strict_subset_problems(schema):
    problems = []

    def walk(node, root=False):
        if not isinstance(node, dict):
            return
        if root and node.get("type") != "object":
            problems.append("root must be an object")
        for banned in ("oneOf", "allOf", "not"):
            if banned in node:
                problems.append(f"{banned} is not supported")
        if node.get("type") == "object":
            props = node.get("properties", {})
            if node.get("additionalProperties") is not False:
                problems.append("every object sets additionalProperties false")
            if sorted(node.get("required", [])) != sorted(props):
                problems.append("required lists every key")
        for v in node.values():
            if isinstance(v, dict):
                walk(v)
            elif isinstance(v, list):
                [walk(i) for i in v]
    walk(schema, root=True)
    return problems


@pytest.mark.parametrize("game", ["snake", "box_push", "slide_2048", "lane_dash", "brick_breaker", "maze_chase", "key_caves", "turn_quest", "mini_chess"])
def test_our_plan_schema_meets_the_strict_subset_and_the_published_limits_for_every_game(game):
    card = controls.load_card(ENGINE / "controls" / f"arena_{game}.yaml")
    brain = MuseBrain("muse-spark-1.3", "k")
    brain.set_actions(card.actions)
    brain.set_skills(("a_skill", "none"))
    wrapper = brain._schema()
    assert wrapper["type"] == "json_schema" and wrapper["json_schema"]["strict"] is True
    schema = wrapper["json_schema"]["schema"]
    assert strict_subset_problems(schema) == []
    assert schema_depth(schema) <= 10 and properties_count(schema) <= 5000
    enums = [len(v["enum"]) for v in json.loads(json.dumps(schema))["properties"]["actions"]["items"].get("enum", []) and [schema["properties"]["actions"]["items"]]]
    assert all(n <= 250 for n in enums)  # a string enum over 250 values has an extra character cap


def test_the_box_schema_for_grounding_meets_the_same_rules():
    schema = vg.BOX_SCHEMA["json_schema"]["schema"]
    assert strict_subset_problems(schema) == [] and schema_depth(schema) <= 10


def test_a_plan_request_carries_none_of_the_parameters_the_service_refuses():
    """Docs: logprobs is a 400 on Spark; frequency and presence penalties do nothing or error; reasoning effort none is a 400; the model id is not a contributor one."""
    import httpx
    from PIL import Image
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": {}})

    brain = MuseBrain("muse-spark-1.3", "k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    brain.ask("s", "t", [Image.new("RGB", (8, 8))])
    body = sent[0]
    for banned in ("logprobs", "top_logprobs", "frequency_penalty", "presence_penalty", "temperature", "top_p", "tool_choice"):
        assert banned not in body
    assert body["reasoning_effort"] in ("minimal", "low", "medium", "high", "xhigh", "max") and "contributor" not in body["model"]
    with pytest.raises(ValueError):
        MuseBrain("muse-spark-1.3", "k", effort="none")


def test_the_sam_cost_helper_picks_the_cheaper_way_with_the_fifty_frame_minimum():
    assert sam_protocol.sam_cost(frames=1, mode="image") == pytest.approx(0.0025)
    assert sam_protocol.sam_cost(frames=10, mode="video") == pytest.approx(50 * 0.20 / 1000)  # billed as 50
    assert sam_protocol.sam_cost(frames=200, mode="video") == pytest.approx(0.04)
    assert sam_protocol.cheaper_mode(frames=3) == "image" and sam_protocol.cheaper_mode(frames=4) == "image"  # 4 images cost the same $0.01 as the 50-frame minimum
    assert sam_protocol.cheaper_mode(frames=5) == "video" and sam_protocol.cheaper_mode(frames=300) == "video"
