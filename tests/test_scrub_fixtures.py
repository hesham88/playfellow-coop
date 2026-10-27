"""The scrub step for the credit-day fixtures: ids, e-mails, key shapes, paths and anything account-bound become fixed placeholders OF THE
SAME TYPE, the shape of every file stays intact, and a test FAILS if an id-like field survives in tests/fixtures/real/*.json.
The tool only scrubs: it never runs git and never commits."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from playfellow_coop import smoke

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import scrub_fixtures as sf  # noqa: E402

NIL = "00000000-0000-0000-0000-000000000000"
WIN_PATH = "C:" + "\\Users\\bob\\notes.txt"
KEYISH = "sk-" + "a1b2c3d4e5f6" * 3


def sample() -> dict:
    return {
        "path": "/v1/chat/completions", "status": 200, "content_type": "application/json",
        "body": {
            "id": "chatcmpl-AbC123xyz789", "sessionId": "3f2b8c1e-1a2b-4c5d-8e9f-0123456789ab", "requestId": "a1b2c3d4e5f60718",
            "organization": "org-Q9w8e7r6t5y4", "account_id": 123456, "userId": 77, "created": 1730000000, "model": "muse-spark",
            "system_fingerprint": "fp_44709d6fcb", "valid": True, "paid": "yes", "keywords": ["coins"], "turns": [],
            "usage": {"prompt_tokens": 120, "completion_tokens": 15}, "audioDurationMs": 1500, "transcript": "grab the coins",
            "choices": [{"index": 0, "message": {"role": "user", "content": "hello"}}],
        },
    }


def shape(value):
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [shape(v) for v in value]
    return type(value).__name__


# ---- ids become placeholders of the same type ---------------------------------------------------------------------------------
def test_ids_become_placeholders_of_the_same_type_and_length():
    out, _ = sf.scrub(sample())
    body = out["body"]
    assert body["id"] == "chatcmpl-" + "0" * len("AbC123xyz789")
    assert body["sessionId"] == NIL and body["requestId"] == "0" * 16
    assert body["organization"] == "org-" + "0" * len("Q9w8e7r6t5y4")
    assert body["account_id"] == 0 and body["userId"] == 0 and isinstance(body["account_id"], int)
    assert body["system_fingerprint"] == "fp_" + "0" * len("44709d6fcb")


def test_everything_else_is_left_exactly_as_it_was():
    out, _ = sf.scrub(sample())
    body, before = out["body"], sample()["body"]
    for field in ("created", "model", "valid", "paid", "keywords", "turns", "usage", "audioDurationMs", "transcript", "choices"):
        assert body[field] == before[field], field
    assert out["path"] == "/v1/chat/completions" and out["status"] == 200


def test_the_shape_of_the_file_is_intact():
    out, _ = sf.scrub(sample())
    assert shape(out) == shape(sample())


def test_everything_inside_an_account_bound_object_is_replaced():
    record = {"organization": {"id": "org-abcdef123456", "name": "Acme Games Ltd", "seats": 5}, "keep": "me"}
    out, _ = sf.scrub(record)
    assert out["organization"] == {"id": "org-" + "0" * 12, "name": sf.PLACEHOLDER, "seats": 0} and out["keep"] == "me"
    assert shape(out) == shape(record)


# ---- text inside ordinary fields -----------------------------------------------------------------------------------------------
def test_emails_keys_paths_and_uuids_inside_text_are_replaced():
    text = f"mail bob@example.com or use Bearer abcdef0123456789abcd and {KEYISH}; file {WIN_PATH}; id 3f2b8c1e-1a2b-4c5d-8e9f-0123456789ab"
    out, counts = sf.scrub({"body": {"note": text}})
    result = out["body"]["note"]
    assert result == f"mail user@example.com or use Bearer *** and ***; file {sf.PATH_PLACEHOLDER}; id {NIL}"
    assert counts == {"emails": 1, "keys": 2, "paths": 1, "uuids": 1}
    assert isinstance(result, str)


def test_unix_and_home_paths_are_replaced_too():
    out, _ = sf.scrub({"a": "see /home/bob/x.json and ~/secret.txt and /Users/bob/y"})
    assert "bob" not in out["a"] and out["a"].count(sf.PATH_PLACEHOLDER) == 3


def test_a_model_name_or_a_box_token_is_not_mistaken_for_anything():
    record = {"model": "muse-voice-transcribe-1.0", "text": "<1f>1<|box;x1=10;y1=20;x2=58;y2=68;w=480;h=432|><|mask;lossless|>"}
    out, counts = sf.scrub(record)
    assert out == record and counts == {}


def test_scrubbing_twice_changes_nothing_more():
    once, _ = sf.scrub(sample())
    twice, counts = sf.scrub(once)
    assert twice == once and counts == {}


def test_arabic_text_survives():
    out, _ = sf.scrub({"transcript": "اجمع العملات"})
    assert out["transcript"] == "اجمع العملات"


# ---- finding what is left ---------------------------------------------------------------------------------------------------------
def test_leaks_names_every_field_that_would_change_and_is_empty_after_scrubbing():
    leaks = sf.leaks(sample())
    assert "body.id" in leaks and "body.sessionId" in leaks and "body.account_id" in leaks and "body.choices" not in leaks
    assert sf.leaks(sf.scrub(sample())[0]) == []


def test_a_leak_inside_a_list_is_named_with_its_index():
    assert sf.leaks({"body": {"turns": [{"requestId": "abcdef0123456789"}]}}) == ["body.turns[0].requestId"]


# ---- the folder ----------------------------------------------------------------------------------------------------------------------
def test_no_id_like_field_survives_in_any_real_fixture_file():
    """FAILS the moment a raw credit-day file is dropped in tests/fixtures/real without being scrubbed (run demo/scrub_fixtures.py)."""
    bad = {}
    for path in sorted(smoke.FIXTURES.glob("*.json")):
        found = sf.leaks(json.loads(path.read_text(encoding="utf-8")))
        if found:
            bad[path.name] = found
    assert bad == {}, f"run `python demo/scrub_fixtures.py` first; unscrubbed: {bad}"


def test_the_default_folder_is_the_fixture_folder():
    assert sf.DEFAULT_FOLDER == smoke.FIXTURES


def test_the_command_scrubs_files_in_place_and_reports_counts_never_values(tmp_path, capsys):
    path = tmp_path / "a.json"
    path.write_text(json.dumps(sample(), indent=2), encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not json, not touched", encoding="utf-8")
    assert sf.main([str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert "a.json" in printed and "3f2b8c1e" not in printed and "chatcmpl-AbC" not in printed and "org-Q9" not in printed
    assert sf.leaks(json.loads(path.read_text(encoding="utf-8"))) == []
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "not json, not touched"
    assert sf.main([str(tmp_path)]) == 0 and "nothing to scrub" in capsys.readouterr().out  # the second run finds nothing


def test_the_command_refuses_a_missing_folder_and_leaves_a_broken_file_alone(tmp_path, capsys):
    assert sf.main([str(tmp_path / "nowhere")]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert sf.main([str(tmp_path)]) == 1 and bad.read_text(encoding="utf-8") == "{not json"
    assert "bad.json" in capsys.readouterr().out


def test_the_tool_never_runs_git_or_commits():
    source = (Path(sf.__file__)).read_text(encoding="utf-8")
    assert "subprocess" not in source and "os.system" not in source and "git " not in source.replace("git ignores", "")


@pytest.mark.parametrize("key", ["id", "Id", "requestId", "request_id", "sessionID", "user", "userName", "organization", "orgId", "email",
                                 "accessToken", "api_key", "apiKey", "traceId", "project_id", "tenant", "account"])
def test_these_key_names_are_account_bound(key):
    out, _ = sf.scrub({key: "abcdef0123456789"})
    assert out[key] != "abcdef0123456789"


@pytest.mark.parametrize("key", ["model", "keywords", "transcript", "audioDurationMs", "valid", "paid", "created", "role", "content", "text"])
def test_these_key_names_are_not(key):
    out, _ = sf.scrub({key: "abcdef0123456789"})
    assert out[key] == "abcdef0123456789"


def test_an_address_is_not_taken_for_a_path():
    record = {"note": "see https://api.meta.ai/v1/asr/realtime and wss://example.org/x"}
    assert sf.scrub(record)[0] == record


def test_a_key_already_replaced_by_the_recorder_stays_as_it_is():
    record = {"sent": [{"json": {"authorization": {"accessToken": "Bearer ***"}}}]}
    assert sf.scrub(record) == (record, {}) and sf.leaks(record) == []


def test_the_owner_checklist_tells_the_owner_not_to_commit_the_fixtures_and_to_scrub_first():
    text = (Path(__file__).resolve().parents[1] / "docs" / "owner-live-checks.md").read_text(encoding="utf-8")
    assert "Do not commit the fixture files; tell the supervisor." in text
    assert "python demo/first_real_calls.py" in text and "python demo/scrub_fixtures.py" in text
    assert text.index("python demo/first_real_calls.py") < text.index("python demo/scrub_fixtures.py") < text.index("Do not commit the fixture files")
    for name in ("muse_chat.json", "sam_responses.json", "sam_no_match.json", "voice_transcribe.json", "realtime_voice.json"):
        assert name in text


def test_the_owner_checklist_never_has_the_key_typed_in_plain_view_and_clears_it_afterwards():
    text = (Path(__file__).resolve().parents[1] / "docs" / "owner-live-checks.md").read_text(encoding="utf-8")
    assert '$env:MODEL_API_KEY = Read-Host -MaskInput "Meta key"' in text  # typed masked, never shown
    assert '"<your key>"' not in text
    assert "do not paste the key into any chat, file or message" in text
    assert text.index("Remove-Item Env:MODEL_API_KEY") > text.index("python demo/scrub_fixtures.py")  # cleared at the very end
    assert "then close the window" in text


def test_the_owner_checklist_says_which_powershell_and_gives_a_fallback_that_works_in_the_old_one():
    text = (Path(__file__).resolve().parents[1] / "docs" / "owner-live-checks.md").read_text(encoding="utf-8")
    assert 'open PowerShell 7 ("pwsh"), not "Windows PowerShell"' in text  # -MaskInput exists only in 7
    fallback = "$s = Read-Host -AsSecureString \"Meta key\"; $env:MODEL_API_KEY = [Net.NetworkCredential]::new('', $s).Password; Remove-Variable s"
    assert fallback in text and text.index(fallback) > text.index("-MaskInput")  # for Windows PowerShell 5.1, on its own line
    assert "never typed on the command line" in text and "saves command lines to disk" in text
    section = text[text.index("Credit day: the first real calls"):]
    assert not any("MODEL_API_KEY = \"" in line or "MODEL_API_KEY=" in line for line in section.splitlines())  # no line puts a literal key in
