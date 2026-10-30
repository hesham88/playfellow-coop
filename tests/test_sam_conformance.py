"""K6: our SAM reader against the published protocol. With a local clone of github.com/meta-models/meta-sam (kept OUTSIDE this repository; set META_SAM_DIR to
it), every shared case must come out the same. Without one, that test is skipped and the rules are still pinned below with our own examples (written here, none
copied from the vendor's cases)."""
import json
import os
from pathlib import Path

import pytest

from playfellow_coop import sam_conformance, sam_protocol as sp
from playfellow_coop.sam_video import StrictStream, read_stream_strict

MASK = "!!!!!&!!!!!"  # our own payload: one_bit marker, a length prefix of 4, then exactly four packed bytes (envelope only; not a real mask)
BOX = "x1=1;y1=2;x2=5;y2=6;w=20;h=10"


def seg(ident="0", box=BOX, mask=f"x=0;y=0;data=3,3,{MASK}"):
    return f"{ident}<|box;{box}|><|mask;{mask}|>"


@pytest.mark.skipif(not os.environ.get("META_SAM_DIR"), reason="no meta-sam clone: set META_SAM_DIR to a clone kept outside this repository")
def test_every_shared_case_of_the_vendor_corpus_comes_out_the_same():
    clone = Path(os.environ["META_SAM_DIR"])
    verdicts = sam_conformance.run(clone)
    outputs = [v for v in verdicts if v.kind == "output"]
    prompts = [v for v in verdicts if v.kind == "object-prompt"]
    assert len(outputs) >= 40 and len(prompts) >= 20  # an empty or partial corpus must not pass by default
    assert [f"{v.name}: {v.detail}" for v in verdicts if not v.same] == []


def test_a_record_that_breaks_the_grammar_is_dropped_and_diagnosed_and_its_warnings_wait_for_an_accepted_record():
    text = "\n".join([
        "<0f>" + seg(box="x1=1;x1=1;y1=2;x2=5;y2=6;w=20;h=10;extra=1"),  # a repeated field: malformed, and its unknown field is NOT reported yet
        "<0f>" + seg(mask=f"x=2;y=0;data=3,3,{MASK}"),  # a mask that does not start at 0,0
        "<0f>" + seg(mask="x=0;y=0"),  # a mask without data
        "<0f>1<|box;" + BOX + "|>junk<|mask;x=0;y=0;data=3,3," + MASK + "|>",  # text between tokens
        "<0f>" + seg("4", box=BOX + ";extra=1"),  # accepted: now the unknown field is reported, once
        "<0f>" + seg("5", box=BOX + ";extra=2"),  # the same field again: no second warning
    ])
    parsed = sp.parse(text, strict=True, media="image")
    assert [r.object_key for r in parsed.records] == ["4", "5"]
    assert [(i.line, i.severity, i.code) for i in parsed.issues] == [(1, "error", "malformed_record"), (2, "error", "malformed_record"),
                                                                       (3, "error", "malformed_record"), (4, "error", "malformed_record"),
                                                                       (5, "warning", "ignored_field")]


def test_boxes_frames_payloads_confidence_and_prose_follow_the_protocol():
    text = "\n".join([
        "a sentence the model added",
        "<0f>" + seg("0", box="x1=6;y1=2;x2=5;y2=6;w=20;h=10") + "," + seg("1"),  # an impossible box drops only its own record
        "<3f>" + seg("2"),  # an image answer must be on frame 0
        "<0f>" + seg("3", mask="x=0;y=0;data=3,3,!!!!!&!!!!"),  # a truncated payload: the box stays, the mask goes
        "<0f>" + seg("4", box=BOX + ";c=-0") + "," + seg("5", box=BOX + ";c=1.5") + "," + seg("6", box=BOX + ";c=0.5;c=0.5"),
        "<0f>",  # a bare frame header
    ])
    parsed = sp.parse(text, strict=True, media="image")
    assert isinstance(parsed.items[0], sp.Prose) and parsed.items[0].text == "a sentence the model added"
    assert [r.object_key for r in parsed.records] == ["1", "3", "4", "5", "6"]
    by_key = {r.object_key: r for r in parsed.records}
    assert by_key["3"].mask is None and by_key["1"].mask.encoding == "one_bit" and by_key["1"].mask.payload == MASK
    assert by_key["1"].box == sp.Box(1, 2, 6, 7, 20, 10)  # inclusive x2/y2 made half-open
    assert by_key["4"].confidence == 0.0 and by_key["5"].confidence is None and by_key["6"].confidence is None
    assert [(i.line, i.code) for i in parsed.issues] == [(2, "invalid_box"), (3, "unexpected_frame"), (4, "invalid_mask_payload"),
                                                        (5, "ignored_confidence"), (6, "malformed_record")]


def test_a_second_complete_mask_for_the_same_object_and_frame_is_a_new_revision():
    parsed = sp.parse("<4f>" + seg("2") + "\n<4f>" + seg("2") + "\n<5f>" + seg("2"), strict=True, media="video")
    assert [r.mask.revision for r in parsed.records] == [1, 2, 1]


def test_the_real_recorded_answer_reads_the_same_strictly_and_forgivingly():
    """The answer SAM really sent on credit day (key-scrubbed fixture): the strict reading finds the same records, with no diagnostic, so switching the live marks
    path to the strict reading would change nothing for a real answer."""
    from playfellow_coop.sam_marks import answer_text
    fixture = Path(__file__).with_name("fixtures") / "real" / "sam_responses.json"
    if not fixture.is_file():
        pytest.skip("no recorded real SAM answer in this checkout")
    text = answer_text(json.loads(fixture.read_text(encoding="utf-8"))["body"])
    forgiving, strict = sp.parse(text), sp.parse(text, strict=True, media="image")
    assert strict.records and strict.issues == []
    assert [(r.object_id, r.box, r.confidence) for r in strict.records] == [(r.object_id, r.box, r.confidence) for r in forgiving.records]


def test_the_forgiving_default_reading_is_unchanged_for_older_fakes():
    parsed = sp.parse("<0f>1<|box;x1=1;y1=1;x2=5;y2=5;w=10;h=10|>")  # a box without its mask, as older fakes send
    assert [r.object_id for r in parsed.records] == [1] and parsed.issues == [] and parsed.items == []


def test_the_payload_envelope_checks_marker_alphabet_and_declared_length():
    assert sp.payload_envelope_ok(MASK) and sp.payload_envelope_ok("~!!!!&!!!!!!!!!!") is True  # lossless may carry trailing bytes
    assert not sp.payload_envelope_ok("?" + MASK[1:])  # no marker
    assert not sp.payload_envelope_ok(MASK[:-1])  # one byte short of the declared length
    assert not sp.payload_envelope_ok("!!!!!&!!!!!!!!!!")  # one_bit must be exact
    assert not sp.payload_envelope_ok("!!!!!&!!!!\"")  # a character outside the alphabet


def sse(event: dict) -> str:
    return "data: " + json.dumps(event)


def delta(text, item="msg", out=0, content=0):
    return sse({"type": "response.output_text.delta", "item_id": item, "output_index": out, "content_index": content, "delta": text})


def done(text, item="msg", out=0, content=0):
    return sse({"type": "response.output_text.done", "item_id": item, "output_index": out, "content_index": content, "text": text})


COMPLETED = sse({"type": "response.completed", "response": {"status": "completed", "usage": {"video_frames_processed": 50}}})


def test_one_lane_is_read_and_its_final_text_must_match_and_the_outcome_is_typed():
    line = "<0f>" + seg("7") + "\n"
    good = read_stream_strict([delta(line[:9]), delta(line[9:]), done(line), COMPLETED], media="image")
    assert good.outcome == {"status": "completed"} and [r.object_key for r in good.parsed.records] == ["7"] and good.frames_billed == 50
    only_done = read_stream_strict([done(line, out=-0.0), COMPLETED], media="image")  # a JSON -0.0 index is 0; the final text alone is the whole answer
    assert only_done.outcome == {"status": "completed"} and only_done.lane == ("msg", 0, 0) and len(only_done.parsed.records) == 1
    mixed = read_stream_strict([delta("<0f>"), delta(seg("1"), item="other", out=1)])
    assert mixed.error["code"] == "response_lane" and mixed.error["received_lane"] == {"item_id": "other", "output_index": 1, "content_index": 0}
    conflict = read_stream_strict([delta(line), done(line + "x"), COMPLETED])
    assert conflict.error["code"] == "response_lane" and conflict.outcome is None
    early = read_stream_strict([delta(line), COMPLETED])
    assert early.error["code"] == "response_lane"  # completed before the lane was final
    cut = read_stream_strict([delta(line + "<0f>" + seg("8"))])  # the source just ends: what arrived is read, the outcome says eof
    assert cut.outcome == {"status": "incomplete", "reason": "eof"} and [r.object_key for r in cut.parsed.records] == ["7", "8"]


def test_refusals_failures_and_a_broken_source_are_typed_errors_never_crashes():
    refusal = read_stream_strict([sse({"type": "response.content_part.done", "item_id": "msg", "output_index": 0, "content_index": 0,
                                       "part": {"type": "refusal", "refusal": "no"}})])
    assert refusal.error == {"code": "response_refusal", "message": "no"}
    failed = read_stream_strict([sse({"type": "response.failed", "response": {"error": {"message": ""}}})])
    assert failed.error == {"code": "response_failed", "message": ""}  # an empty message is kept empty

    class Broken:
        def __init__(self):
            self.lines = iter([done(""), COMPLETED])

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.lines)

        def close(self):
            raise OSError("socket")

    after_completion = read_stream_strict(Broken())
    assert after_completion.error["code"] == "source_error" and after_completion.error["source_operation"] == "return" and after_completion.outcome is None
    reasoning = StrictStream()
    reasoning.event({"type": "response.content_part.done", "item_id": "msg", "output_index": 0, "content_index": 0, "part": {"type": "reasoning_text", "text": "x"}})
    assert reasoning.status == "in_progress" and reasoning._final is None  # a reasoning part never finalizes the lane


def test_object_prompts_from_untyped_input_follow_the_documented_rules():
    def build(ident=3, box=None, points=None, size=(64, 48)):
        prompt = {"box": box or {"left": 2, "top": 3, "right": 12, "bottom": 13}}
        if points is not None:
            prompt["points"] = points
        return sp.build_object_prompt_from({"size": {"width": size[0], "height": size[1]}, "objects": [{"id": ident, "prompts": [prompt]}]})

    assert build("12") == "<0f>12<|box;x1=2;y1=3;x2=11;y2=12;w=64;h=48|>"
    assert build(points=[{"x": 5, "y": 6, "label": "negative"}, {"x": 7, "y": 8}]).endswith("-<|point;x=5;y=6;w=64;h=48|><|point;x=7;y=8;w=64;h=48|>")
    for kwargs, code in [({"ident": "012"}, "invalid_object_id"), ({"ident": True}, "invalid_object_id"), ({"box": {"left": 2.5, "top": 3, "right": 12, "bottom": 13}}, "invalid_box"),
                         ({"points": [{"x": 5, "y": 6, "label": "maybe"}]}, "invalid_point_label"), ({"size": (64.0, 48)}, "invalid_size")]:
        with pytest.raises(sp.ObjectPromptError) as error:
            build(**kwargs)
        assert error.value.code == code, kwargs
