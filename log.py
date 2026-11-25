"""The decision log: one JSON object per line, in a file only the user can read."""

import contextlib
import json
import os
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
NAME = "decisions.jsonl"
_TEXT = (str, type(None))
_COUNT = (int, float, type(None))
# the fields the report reads, with the types Polymetis writes; a hand edit or an older format may differ
_TYPES = {"time": (int, float), "session": _TEXT, "platform": _TEXT, "level": _TEXT, "local": _TEXT,
          "outcome": _TEXT, "tool_errors": _COUNT, "tokens_in": _COUNT, "tokens_out": _COUNT}
_NAME_LISTS = ("answered_by", "tip", "chosen", "used_skills")


def write(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        if path.stat().st_size >= MAX_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))  # keep one older file
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _fits(record: dict) -> bool:
    return (all(isinstance(record[k], kinds) for k, kinds in _TYPES.items() if k in record)
            and all(isinstance(record.get(k) or [], list) and all(isinstance(n, str) for n in record.get(k) or [])
                    for k in _NAME_LISTS))


def read(path: Path) -> list[dict]:
    """Every record of the log and its older file, oldest first. Lines that do not parse, or whose fields
    have other types than Polymetis writes, are skipped. A file that exists but cannot be read raises OSError."""
    records = []
    for part in (path.with_name(path.name + ".1"), path):
        try:
            lines = part.read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            continue
        for line in lines:
            with contextlib.suppress(ValueError):
                record = json.loads(line)
                if isinstance(record, dict) and _fits(record):
                    records.append(record)
    return records
