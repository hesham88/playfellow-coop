"""The SAM 3.1 wire format, checked against the examples printed in the vendor's docs (reading segmentation output, segmenting with prompts, client libraries)."""
from __future__ import annotations

import pytest

from playfellow_coop import sam_protocol as sp

IMAGE_LINE = ("<0f>0<|box;x1=353;y1=382;x2=453;y2=427;w=537;h=561|><|mask;x=0;y=0;data=46,101,~abc|>,"
              "1<|box;x1=260;y1=382;x2=340;y2=427;w=537;h=561|><|mask;x=0;y=0;data=46,81,~def|>,"
              "2<|box;x1=516;y1=117;x2=536;y2=150;w=537;h=561|><|mask;x=0;y=0;data=34,21,~ghi|>")
VIDEO_LINE = "<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,60,~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x(|>,1<|box;x1=155;y1=228;x2=202;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,48,~!!!!J!0c[q=Pj_zs=*4C4(/./x#:/`S_GnD`=o3?X{emCgO$y@|>"
CONFIDENT = "<0f>1<|box;x1=444;y1=625;x2=679;y2=850;w=1800;h=1200;c=0.9609375|><|mask;x=0;y=0;c=0.9609375;data=226,236,!payload|>"


def test_an_image_answer_has_one_record_per_match_with_inclusive_boxes_made_half_open():
    parsed = sp.parse(IMAGE_LINE)
    assert [r.object_id for r in parsed.records] == [0, 1, 2] and parsed.frames() == [0] and parsed.diagnostics == []
    first = parsed.records[0]
    assert (first.box.left, first.box.top, first.box.right, first.box.bottom) == (353, 382, 454, 428)  # x2 + 1, y2 + 1
    assert (first.box.width, first.box.height) == (537, 561) and first.confidence is None  # absence is not zero
    assert first.mask.rows == 46 and first.mask.cols == 101 and first.mask.encoding == "lossless"  # height first, then width


def test_a_mask_payload_full_of_marker_characters_is_read_by_its_first_character_only():
    parsed = sp.parse(VIDEO_LINE)
    assert [r.object_id for r in parsed.records] == [0, 1]
    assert parsed.records[0].mask.encoding == "lossless" and parsed.records[0].mask.rows == 27 and parsed.records[0].mask.cols == 60
    assert sp.parse(CONFIDENT).records[0].mask.encoding == "one_bit"


def test_confidence_is_read_from_both_tokens_and_is_the_same_on_the_record():
    record = sp.parse(CONFIDENT).records[0]
    assert record.confidence == pytest.approx(0.9609375) and record.mask.confidence == pytest.approx(0.9609375)
    assert sp.parse("<0f>1<|box;x1=1;y1=1;x2=5;y2=5;w=10;h=10;c=7|>").records[0].confidence is None  # outside 0 to 1: not trusted


def test_frames_may_skip_and_come_out_of_order_and_ids_are_sparse_so_records_are_keyed_by_marker_and_id():
    text = ("<30f>1<|box;x1=1;y1=1;x2=9;y2=9;w=100;h=100|><|mask;x=0;y=0;data=9,9,!a|>\n"
            "<31f>1<|box;x1=2;y1=1;x2=10;y2=9;w=100;h=100|><|mask;x=0;y=0;data=9,9,!a|>,3<|box;x1=50;y1=50;x2=60;y2=60;w=100;h=100|><|mask;x=0;y=0;data=11,11,!b|>\n"
            "<29f>1<|box;x1=0;y1=1;x2=8;y2=9;w=100;h=100|><|mask;x=0;y=0;data=9,9,!a|>")
    parsed = sp.parse(text)
    assert parsed.frames() == [29, 30, 31]
    assert sorted(parsed.by_object()) == [1, 3] and [r.frame for r in parsed.by_object()[1]] == [30, 31, 29]  # arrival order, not frame order
    assert [r.object_id for r in parsed.on_frame(31)] == [1, 3]


def test_zero_matches_is_an_empty_answer_not_an_error_and_bad_lines_are_diagnostics_not_crashes():
    assert sp.parse("").records == [] and sp.parse(None).records == []
    parsed = sp.parse("no marker here\n<0f>0<|box;x1=9;y1=9;x2=2;y2=2;w=10;h=10|>\n<0f>5<|box;x1=1;y1=1;x2=3;y2=3;w=10;h=10|>")
    assert [r.object_id for r in parsed.records] == [5] and len(parsed.diagnostics) == 2


def test_the_documented_prompt_examples_are_reproduced_exactly():
    image = sp.build_object_prompt((1800, 1200), [
        sp.PromptObject(1, (sp.FramePrompt(box=sp.PromptBox(444, 626, 676, 850)),)),
        sp.PromptObject(2, (sp.FramePrompt(points=(sp.PromptPoint(1430, 700), sp.PromptPoint(1300, 450, negative=True))),)),
    ])
    assert image == "<0f>1<|box;x1=444;y1=626;x2=675;y2=849;w=1800;h=1200|>,2<|point;x=1430;y=700;w=1800;h=1200|>-<|point;x=1300;y=450;w=1800;h=1200|>"
    video = sp.build_object_prompt((640, 480), [sp.PromptObject(1, (
        sp.FramePrompt(frame=30, box=sp.PromptBox(10, 20, 40, 60)),
        sp.FramePrompt(frame=120, points=(sp.PromptPoint(20, 40), sp.PromptPoint(30, 50, negative=True))),
    ))])
    assert video == "<30f>1<|box;x1=10;y1=20;x2=39;y2=59;w=640;h=480|><120f>1<|point;x=20;y=40;w=640;h=480|>-<|point;x=30;y=50;w=640;h=480|>"


def test_a_box_from_an_answer_can_be_fed_back_as_a_prompt_for_the_same_object():
    record = sp.parse(IMAGE_LINE).records[0]
    box = record.box
    text = sp.build_object_prompt((box.width, box.height), [sp.PromptObject(record.object_id, (sp.FramePrompt(box=sp.PromptBox(box.left, box.top, box.right, box.bottom)),))])
    assert "x1=353;y1=382;x2=453;y2=427" in text  # the half-open box round-trips to the inclusive wire form


@pytest.mark.parametrize("objects, code", [
    ([], "no_objects"),
    ([sp.PromptObject(-1, (sp.FramePrompt(points=(sp.PromptPoint(1, 1),)),))], "invalid_object_id"),
    ([sp.PromptObject(1, (sp.FramePrompt(points=(sp.PromptPoint(1, 1),)),)), sp.PromptObject(1, (sp.FramePrompt(points=(sp.PromptPoint(2, 2),)),))], "duplicate_object_id"),
    ([sp.PromptObject(1, ())], "empty_object"),
    ([sp.PromptObject(1, (sp.FramePrompt(),))], "empty_prompt"),
    ([sp.PromptObject(1, (sp.FramePrompt(points=(sp.PromptPoint(1, 1),)), sp.FramePrompt(points=(sp.PromptPoint(2, 2),))))], "duplicate_frame"),
    ([sp.PromptObject(1, (sp.FramePrompt(frame=-1, points=(sp.PromptPoint(1, 1),)),))], "invalid_frame"),
    ([sp.PromptObject(1, (sp.FramePrompt(box=sp.PromptBox(5, 5, 5, 9)),))], "invalid_box"),
    ([sp.PromptObject(1, (sp.FramePrompt(points=(sp.PromptPoint(500, 1),)),))], "invalid_point"),
])
def test_prompts_the_builder_cannot_encode_are_refused_with_a_documented_code(objects, code):
    with pytest.raises(sp.ObjectPromptError) as error:
        sp.build_object_prompt((100, 100), objects)
    assert error.value.code == code


def test_request_metadata_values_are_strings_and_the_choices_are_checked():
    assert sp.request_metadata() == {"mask_encoding": "one_bit", "include_confidence": "true"}
    assert sp.request_metadata(mask_encoding=None, confidence=False, direction="forward") == {"propagation_direction": "forward"}
    with pytest.raises(ValueError):
        sp.request_metadata(mask_encoding="png")
    with pytest.raises(ValueError):
        sp.request_metadata(direction="sideways")


def test_error_statuses_are_classified_the_way_the_docs_say():
    assert sp.classify_status(400) == "permanent" and sp.classify_status(404) == "model_not_found"
    assert sp.classify_status(200, '{"error": {"code": "model_not_found"}}') == "model_not_found"
    assert sp.classify_status(401) == "bad_key" and sp.classify_status(429) == "retry" and sp.classify_status(503) == "retry"


def test_the_limits_are_the_published_numbers():
    assert (sp.MAX_OBJECTS, sp.MAX_VIDEO_FRAMES, sp.MIN_BILLED_VIDEO_FRAMES) == (16, 15000, 50)
