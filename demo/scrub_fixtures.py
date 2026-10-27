"""Scrub the credit-day fixtures (tests/fixtures/real/*.json) before anyone reads them or a test uses them.

    python demo/scrub_fixtures.py [folder]

What it does: request, response, organisation and account ids, e-mail addresses, key shapes, paths and anything else account-bound become
FIXED placeholders OF THE SAME TYPE (a UUID stays a UUID, a number stays a number, "prefix-abc123" stays "prefix-000000"), so the shape of
every file is intact and the parsers can still be checked against it. Free text is cleaned too (an e-mail inside a sentence, a path, a
Bearer token). Nothing else is touched: model names, tokens counts, transcripts, box tokens and timings stay exactly as the service sent them.

What it never does: it never talks to a network, never runs any other program and never commits; it only rewrites the files in the folder
(only when something changed) and prints how many replacements it made per kind, never a value. The architect reads the scrubbed files
before anything is committed."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DEFAULT_FOLDER = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "real"
NIL_UUID = "00000000-0000-0000-0000-000000000000"
PLACEHOLDER = "placeholder-id"
EMAIL_PLACEHOLDER = "user@example.com"
PATH_PLACEHOLDER = "/path/placeholder"

# key names that are account-bound: any of these words in the key (split at capitals, "_" and "-"), or "apikey" across two words
ID_WORDS = {"id", "ids", "uid", "uuid", "email", "org", "organization", "organisation", "account", "tenant", "user", "username",
            "fingerprint", "trace", "project", "secret", "token", "apikey", "password", "phone"}
TOKENS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")

UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
BEARER = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=\-]{10,}")
KEY_SHAPE = re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{20,}|\bpdl_[A-Za-z0-9_]{8,}|[A-Za-z0-9+/_\-]{40,}")
PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"';,)]*|\\\\[^\s\"';,)]+|(?<![\w:/.])~/[^\s\"';,)]*|(?<![\w:/.])/(?:home|Users|users|root|etc|var|tmp|mnt)/[^\s\"';,)]*")
PREFIXED_ID = re.compile(r"\b(org|acct|account|proj|project|usr|req|resp|chatcmpl)([-_])([A-Za-z0-9]{6,})\b")
OPAQUE = re.compile(r"[A-Za-z0-9]{8,}")
HEX = re.compile(r"[0-9a-fA-F]{8,}")
PREFIX_SEP_REST = re.compile(r"([A-Za-z]+)([-_])([A-Za-z0-9]{6,})")


def id_like(key: str) -> bool:
    words = [t.lower() for t in TOKENS.findall(key)]
    return any(w in ID_WORDS for w in words) or "apikey" in "".join(words)


def placeholder(value):
    """The fixed placeholder for an account-bound value: same type, same length where it has one."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return value
    if isinstance(value, int):
        return 0
    if isinstance(value, float):
        return 0.0
    if value in ("", "***", "Bearer ***", PLACEHOLDER, EMAIL_PLACEHOLDER, NIL_UUID, PATH_PLACEHOLDER):  # already a placeholder (the recorder's own)
        return value
    if UUID.fullmatch(value):
        return NIL_UUID
    if EMAIL.fullmatch(value):
        return EMAIL_PLACEHOLDER
    if BEARER.fullmatch(value) or KEY_SHAPE.fullmatch(value):
        return "***"
    prefixed = PREFIX_SEP_REST.fullmatch(value)
    if prefixed:
        return prefixed.group(1) + prefixed.group(2) + "0" * len(prefixed.group(3))
    if HEX.fullmatch(value) or OPAQUE.fullmatch(value):
        return "0" * len(value)
    return PLACEHOLDER


def _clean_text(text: str, counts: dict) -> str:
    def swap(kind, pattern, replacement):
        nonlocal text

        def one(match):
            new = replacement(match) if callable(replacement) else replacement
            if new != match.group(0):
                counts[kind] = counts.get(kind, 0) + 1
            return new

        text = pattern.sub(one, text)

    swap("emails", EMAIL, EMAIL_PLACEHOLDER)
    swap("keys", BEARER, "Bearer ***")
    swap("keys", KEY_SHAPE, "***")
    swap("uuids", UUID, NIL_UUID)
    swap("paths", PATH, PATH_PLACEHOLDER)
    swap("ids", PREFIXED_ID, lambda m: m.group(1) + m.group(2) + "0" * len(m.group(3)))
    return text


def _walk(value, path: str, account_bound: bool, counts: dict, leaks: list):
    if isinstance(value, dict):
        return {k: _walk(v, f"{path}.{k}" if path else k, account_bound or id_like(k), counts, leaks) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, f"{path}[{i}]", account_bound, counts, leaks) for i, v in enumerate(value)]
    if isinstance(value, bool) or value is None:
        return value
    if account_bound and isinstance(value, (int, float, str)):
        new = placeholder(value)
        if new != value:
            counts["ids"] = counts.get("ids", 0) + 1
            leaks.append(path)
        return new
    if isinstance(value, str):
        before = dict(counts)
        new = _clean_text(value, counts)
        if new != value or counts != before:
            leaks.append(path)
        return new
    return value


def scrub(record):
    """(the scrubbed copy, {kind: number of replacements}). The original is not changed."""
    counts: dict = {}
    return _walk(record, "", False, counts, []), counts


def leaks(record) -> list[str]:
    """The JSON paths of every value that scrubbing would still change (empty = clean)."""
    found: list[str] = []
    _walk(record, "", False, {}, found)
    return found


def main(argv: list[str] | None = None) -> int:
    folder = Path((argv if argv is not None else sys.argv[1:])[0]) if (argv if argv is not None else sys.argv[1:]) else DEFAULT_FOLDER
    if not folder.is_dir():
        print(f"No such folder: {folder.name}. Nothing was changed.")
        return 2
    worst, changed_any = 0, False
    for path in sorted(folder.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            print(f"{path.name}: not valid JSON, left alone")
            worst = 1
            continue
        clean, counts = scrub(record)
        if clean != record:
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
            temporary.replace(path)
            changed_any = True
            print(f"{path.name}: " + ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items())))
    if not changed_any and worst == 0:
        print("nothing to scrub")
    elif changed_any:
        print("Scrubbed in place. Now read the files; do not commit them. Tell the supervisor.")
    return worst


if __name__ == "__main__":
    sys.exit(main())
