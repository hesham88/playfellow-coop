"""The first real calls: three tiny, capped, confirmed requests (Muse Spark, SAM 3.1, Muse Voice Transcribe) that save the RAW
responses as fixtures and say, in one line each, whether the answer is shaped the way our parsers expect.

Why: the docs we built from may differ from the real service (they did for a local model engine once). Nothing builds on a
parser until it has been checked against real text. Rules: it refuses to run without MODEL_API_KEY in the environment; it
asks for a typed YES before it spends anything; every call sits behind one DailyBudget with a small total cap; the key is never
saved (a fixture is scrubbed of it even if a server echoes it back); request bodies (pictures, audio) are never saved."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

import httpx

from brain import BrainError
from playfellow_coop import _http, muse_brain, sam_marks, voice
from playfellow_coop.budget import DailyBudget
from playfellow_coop.muse_brain import MuseBrain
from playfellow_coop.sam_marks import SamMarker, answer_text, parse_boxes
from playfellow_coop.voice import MuseVoiceTranscriber

TOTAL_CAP_USD = 10.0
MUSE_PROMPT = 'You see one frame of a small maze game. Reply with JSON only: {"thought": "...", "say": "...", "actions": []}'
SAM_PHRASE = "coin"
SPOKEN = "grab the coins"
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "real"


class Recorder:
    """An httpx response hook that keeps the raw answer of each request (never the request itself)."""

    def __init__(self, key: str):
        self._key = key
        self.records: list[dict] = []

    def __call__(self, response: httpx.Response) -> None:
        response.read()
        text = response.text.replace(self._key, "***") if self._key else response.text
        try:
            body: object = json.loads(text)
        except ValueError:
            body = text
        self.records.append({"path": response.request.url.path, "status": response.status_code,
                             "content_type": response.headers.get("content-type", ""), "body": body})


def recording_client(recorder: Recorder) -> httpx.Client:
    client = _http.new_client()
    client.event_hooks["response"].append(recorder)
    return client


# ---- one line each: does the real answer look the way our parser expects? -------------------------------------------------
def problems_chat(body: object) -> list[str]:
    out = []
    try:
        content = body["choices"][0]["message"]["content"]  # type: ignore[index]
        if not isinstance(content, str) or not content.strip():
            out.append("choices[0].message.content is empty or not text")
    except (KeyError, IndexError, TypeError):
        out.append("no choices[0].message.content")
    usage = body.get("usage") if isinstance(body, dict) else None
    for field in ("prompt_tokens", "completion_tokens"):
        if not isinstance(usage, dict) or not isinstance(usage.get(field), int):
            out.append(f"no usage.{field} (the cost would be an estimate)")
    return out


def problems_sam(body: object) -> list[str]:
    text = answer_text(body)
    if not text:
        return ["no answer text found (neither output_text nor output[*].content[*].text)"]
    return [] if parse_boxes(text) else [f"no box tokens in the text; it starts: {text[:60]!r}"]


def problems_voice(body: object) -> list[str]:
    out = []
    if not isinstance(body, dict) or not isinstance(body.get("transcript"), str):
        out.append("no string `transcript` field")
    if not isinstance(body, dict) or not isinstance(body.get("audioDurationMs"), (int, float)):
        out.append("no `audioDurationMs` (the cost would use our own length)")
    return out


def synth_wav(text: str = SPOKEN) -> bytes | None:
    """A short spoken WAV (mono 16-bit 24 kHz) made by this PC's own speech engine, or None when there is none. Never faked."""
    if sys.platform != "win32":
        return None
    out = Path(tempfile.mkdtemp(prefix="pf-voice-")) / "say.wav"
    script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
              "[System.Speech.AudioFormat.AudioChannel]::Mono); $s.SetOutputToWaveFile($env:PF_OUT, $f); $s.Speak($env:PF_TEXT); $s.Dispose()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, capture_output=True, timeout=60,
                       env={**os.environ, "PF_OUT": str(out), "PF_TEXT": text})
        return out.read_bytes()
    except (subprocess.SubprocessError, OSError):
        return None


def arena_frame():
    from practice_arena.game import ArenaGame

    return ArenaGame().render()


def run(environ: dict | None = None, confirm: Callable[[str], str] = input, say: Callable[[str], None] = print,
        out_dir: Path = FIXTURES, budget_file: Path | None = None, wav_source: Callable[[], bytes | None] = synth_wav,
        frame_source: Callable = arena_frame, total_cap: float = TOTAL_CAP_USD) -> int:
    """Returns 0 when every answer matched, 1 when something differs (read the lines), 2 when it did not run."""
    env = os.environ if environ is None else environ
    key = (env.get("MODEL_API_KEY") or "").strip()
    if not key:
        say("Refusing to run: MODEL_API_KEY is not set in the environment. Nothing was sent.")
        return 2
    plan = (f"This makes 3 real calls and may spend up to ${total_cap:.2f} in total (in practice a few cents):\n"
            f"  1. Muse Spark: one Practice Arena frame and a fixed prompt\n  2. SAM 3.1: the same frame and the phrase {SAM_PHRASE!r}\n"
            f"  3. Muse Voice Transcribe: a short recording of {SPOKEN!r}\nType YES to go ahead: ")
    if confirm(plan).strip() != "YES":
        say("Not confirmed. Nothing was sent.")
        return 2
    budget_path = budget_file or Path(tempfile.mkdtemp(prefix="pf-smoke-")) / "budget.json"
    budget = DailyBudget(budget_path, cap_usd=total_cap, max_calls=10)
    out_dir.mkdir(parents=True, exist_ok=True)
    recorder = Recorder(key)
    frame = frame_source()
    results: list[tuple[str, list[str]]] = []

    def finish(name: str, filename: str, problems_for: Callable[[object], list[str]], error: BrainError | None = None) -> None:
        record = recorder.records[-1] if recorder.records else None
        if record is not None:
            (out_dir / filename).write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        if error is not None:
            failed = f"the call failed: {error.key}" + (f" ({error.detail})" if error.detail else "")
            # a 200 answer our parser rejected is exactly what this tool exists to explain: say what differs as well
            why = problems_for(record["body"]) if record is not None and record["status"] == 200 else []
            results.append((name, [failed] + why))
        elif record is None:
            results.append((name, ["no response was recorded"]))
        else:
            results.append((name, problems_for(record["body"])))

    muse = MuseBrain("muse-spark", key, budget=budget, client=recording_client(recorder))
    try:
        muse.ask(MUSE_PROMPT, "Where is the nearest coin?", [frame])
        finish("muse", "muse_chat.json", problems_chat)
    except BrainError as error:
        finish("muse", "muse_chat.json", problems_chat, error)
    finally:
        muse.close()

    recorder.records.clear()
    sam = SamMarker(key, prompts={"reward": SAM_PHRASE}, budget=budget, client=recording_client(recorder))
    try:
        sam(frame)
        if sam.last_error is not None:
            finish("sam", "sam_responses.json", problems_sam, sam.last_error)
        else:
            finish("sam", "sam_responses.json", problems_sam)
    finally:
        sam.close()

    recorder.records.clear()
    wav = wav_source()
    if wav is None:
        results.append(("voice", ["skipped: this PC has no speech engine to make a recording (nothing was invented)"]))
    else:
        transcriber = MuseVoiceTranscriber(key, budget=budget, client=recording_client(recorder))
        try:
            transcriber.transcribe(wav, keywords=["coins"])
            finish("voice", "voice_transcribe.json", problems_voice)
        except BrainError as error:
            finish("voice", "voice_transcribe.json", problems_voice, error)
        finally:
            transcriber.close()

    worst = 0
    for name, problems in results:
        if problems:
            worst = 1
        say(f"{name}: " + ("OK, the answer has the shape our parser expects" if not problems else "DIFFERS: " + "; ".join(problems)))
    spent = json.loads(budget_path.read_text(encoding="utf-8")) if budget_path.is_file() else {}
    say(f"spent about ${spent.get('spent_usd', 0):.4f} of the ${total_cap:.2f} cap; raw answers (key scrubbed) are in {out_dir}")
    return worst
