"""Polymetis as a Claude Code plugin. Claude Code runs ``claude_code_hook.py <event>`` for each hook, with the
hook's JSON on stdin.

Each hook is a process of its own, so what a turn needs from an earlier hook sits in a small file per session in
the plugin's data folder. The skills are the ones in the list that Claude Code shows the model, as the session's
transcript records it, with their full descriptions from the SKILL.md files on disk: once the descriptions
outgrow Claude Code's budget, it lists many skills by name only.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import time
from pathlib import Path

from . import decide, log, report
from .catalog import Skill
from .config import Settings, parse_settings
from .search import rank

PLATFORM = "claude-code"
# a tip is all Polymetis changes in Claude Code, so it is on; 7 kept tips off small talk in the offline trial
DEFAULTS = Settings(apply=frozenset({"tips"}), min_score=7.0)
TIP_CHARS = 200  # of a skill's description in a tip
# the best skill must score this many times the next one: in Claude Code's long descriptions, a close second
# often meant a wrong first
MARGIN = 1.5
STALE_DAYS = 7  # a session's file that no hook touched for this long goes
_KEY = re.compile(r"([A-Za-z_][\w-]*):(?:[ \t]+(.*))?$")


def parse_listing(content: str) -> list[Skill]:
    """The skills in Claude Code's list: a ``- name: description`` row each, or ``- name`` alone for a skill
    whose description did not fit."""
    skills = []
    for row in content.splitlines():
        if row.startswith("- "):
            name, _, description = row[2:].partition(": ")  # a plugin's skill is plugin:skill, without a space
            if name.strip():
                skills.append(Skill(name.strip(), description.strip()))
    return skills


def listing_in(path: Path, offset: int) -> tuple[str | None, int]:
    """The newest full skill list in the transcript after byte ``offset``, and the offset after the last whole
    line. A list that only adds to an earlier one is left out."""
    try:
        with open(path, "rb") as handle:
            if handle.seek(0, os.SEEK_END) < offset:  # a shorter file than before: read it all again
                offset = 0
            handle.seek(offset)
            data = handle.read()
    except OSError:
        return None, offset
    end = data.rfind(b"\n") + 1  # a line still being written waits for the next hook
    content = None
    for line in data[:end].splitlines():
        if b'"skill_listing"' not in line:
            continue
        with contextlib.suppress(ValueError, TypeError, AttributeError, KeyError):
            item = json.loads(line)["attachment"]
            if item["type"] == "skill_listing" and item.get("isInitial", True) and isinstance(item["content"], str):
                content = item["content"]
    return content, offset + end


def _scalar(parts: list[str]) -> str:
    first, rest = parts[0].strip(), [p for p in parts[1:] if p]
    if not first or first[0] in "|>":  # the value is on the lines below
        return " ".join(rest)
    text = " ".join([first] + rest)
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return text[1:-1].replace('\\"', '"')
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    return text


def frontmatter(text: str) -> dict[str, str]:
    """The top-level fields of a Markdown file's YAML front matter, each as one line of text: plain, quoted,
    or a block below its key. No YAML library: the plugin adds no dependencies."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields, key, parts = {}, None, []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.lstrip().startswith("#"):
            continue
        match = _KEY.match(line)
        if match and not line[0].isspace():
            if key:
                fields[key] = _scalar(parts)
            key, parts = match.group(1), [match.group(2) or ""]
        elif key:
            parts.append(line.strip())
    else:  # no closing line
        return {}
    if key:
        fields[key] = _scalar(parts)
    return fields


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _describe(path: Path) -> tuple[str, str]:
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            fields = frontmatter(handle.read(32768))
    except OSError:
        return "", ""
    # Claude Code shows both fields as the skill's description
    return fields.get("name", ""), " ".join(v for v in (fields.get("description"), fields.get("when_to_use")) if v)


def _folders(value, default: str) -> list[str]:
    extra = [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)] \
        if isinstance(value, list) else []
    return list(dict.fromkeys([default, *extra]))


def _plugin_skills(root: Path) -> dict[str, str]:
    try:
        manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        plugin = manifest["name"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    if not isinstance(plugin, str) or not plugin:
        return {}
    found = {}
    for folder in _folders(manifest.get("skills"), "skills"):
        for md in sorted((root / folder).glob("*/SKILL.md")):
            name, text = _describe(md)
            found[f"{plugin}:{name or md.parent.name}"] = text
    for folder in _folders(manifest.get("commands"), "commands"):
        for md in sorted((root / folder).glob("*.md")):
            found.setdefault(f"{plugin}:{md.stem}", _describe(md)[1])
    return found


def disk_skills(base: Path, cwd: Path | None) -> dict[str, str]:
    """Each skill and plugin command on disk with its full description: of the newest install of each plugin,
    of the plugins and skills that the desktop app syncs, of the user and of the project."""
    newest: dict[Path, tuple[float, Path]] = {}
    for manifest in base.glob("plugins/cache/*/*/*/.claude-plugin/plugin.json"):
        with contextlib.suppress(OSError):
            mtime, plugin = manifest.stat().st_mtime, manifest.parents[2]
            if plugin not in newest or mtime > newest[plugin][0]:
                newest[plugin] = (mtime, manifest.parents[1])
    roots = [newest[p][1] for p in sorted(newest)]
    roots += [m.parents[1] for m in sorted(base.glob("plugins/synced/*/*/.claude-plugin/plugin.json"))]
    found = {}
    for root in roots:
        found.update(_plugin_skills(root))
    places = [(base, "skills/*/SKILL.md"), (base, "skills/synced/*/*/SKILL.md")]
    for folder, pattern in places + ([(cwd, ".claude/skills/*/SKILL.md")] if cwd else []):
        for md in sorted(folder.glob(pattern)):
            name, text = _describe(md)
            found[name or md.parent.name] = text
    return found


def catalog(listed: list[Skill], disk: dict[str, str]) -> tuple[Skill, ...]:
    """The skills to rank: the listed ones, with their full descriptions where the disk has them, under their
    name or their bare name, as the desktop app keeps the skills it syncs."""
    pairs = [(s.name, disk.get(s.name) or disk.get(s.name.partition(":")[2]) or s.description) for s in listed]
    return tuple(Skill(name, text, name.partition(":")[0] if ":" in name else "") for name, text in pairs)


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= TIP_CHARS else text[:TIP_CHARS].rsplit(" ", 1)[0] + "…"


def tip_text(skills: list[Skill]) -> str:
    listed = "; ".join(f"{s.name} ({_short(s.description)})" if s.description else s.name for s in skills)
    return (f"<polymetis>Installed skill{'s' if len(skills) > 1 else ''} that match{'' if len(skills) > 1 else 'es'} "
            f"this request: {listed}. Load it with the Skill tool before you answer, unless it clearly does not fit."
            "</polymetis>")


def pick(s: Settings, candidates: list[tuple[str, float]]) -> list[str]:
    """The one skill worth naming for this turn, if one stands out: above ``min_score`` and ``MARGIN`` times the
    next one."""
    if not candidates or s.max_tips == 0:
        return []
    (best, top), second = candidates[0], candidates[1][1] if len(candidates) > 1 else 0.0
    return [best] if top >= s.min_score and top >= MARGIN * second else []


def _read_json(path: Path) -> dict:
    with contextlib.suppress(OSError, ValueError):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    return {}


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    os.replace(temporary, path)


def settings(data: Path) -> Settings:
    """The settings in ``settings.json`` in the plugin's data folder, over this plugin's defaults."""
    user = _read_json(data / "settings.json")

    def get(key: str, default=None):
        value = user
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        return default if value is None else value
    found, problems = parse_settings(get, DEFAULTS)
    for problem in problems:  # names the key, never the value
        print(f"polymetis: settings.json: {problem}", file=sys.stderr)
    return found


def project_listing(data: Path, cwd) -> Path:
    """Where the last skill list that a session in the folder ``cwd`` saw is kept: a project can have skills of
    its own."""
    return data / "listings" / f"{decide.session_key(str(cwd or ''))}.json"


def _listing(data: Path, payload: dict, state: dict) -> str | None:
    """This session's newest skill list, else the one that the last session in its folder saw: a session's first
    prompt comes before its transcript holds a list."""
    transcript = payload.get("transcript_path")
    if isinstance(transcript, str) and transcript:
        content, state["offset"] = listing_in(Path(transcript), int(state.get("offset") or 0))
        if content is not None:
            state["listing"] = content
            _write_json(project_listing(data, payload.get("cwd")), {"content": content})
    for found in (state.get("listing"), _read_json(project_listing(data, payload.get("cwd"))).get("content")):
        if isinstance(found, str):
            return found
    return None


def _session(data: Path, payload: dict) -> tuple[str, Path]:
    key = decide.session_key(str(payload.get("session_id") or ""))
    return key, data / "sessions" / f"{key}.json"


def _end_turn(data: Path, key: str, state: dict, s: Settings, outcome: str) -> None:
    turn = state.pop("turn", None)
    if not isinstance(turn, dict) or not s.log:
        return
    log.write(data / log.NAME, {
        "time": turn["time"], "session": key, "chat": key, "turn": turn["number"], "platform": PLATFORM,
        "apply": sorted(s.apply), "candidates": turn["candidates"],
        "tip": turn["tip"], "tip_given": turn["given"], "used_skills": turn["used"],
        # a turn that the next prompt ends has no known end
        "duration_ms": None if outcome == "unknown" else int((time.time() - turn["time"]) * 1000),
        "outcome": outcome})


def _clean(data: Path) -> None:
    cutoff = time.time() - STALE_DAYS * 86400
    for path in (data / "sessions").glob("*.json"):
        with contextlib.suppress(OSError):
            if path.stat().st_mtime < cutoff:
                path.unlink()


def on_prompt(payload: dict, data: Path, base: Path, s: Settings) -> dict | None:
    text = payload.get("prompt")
    if not isinstance(text, str) or not text.strip() or text.lstrip().startswith("/"):
        return None
    key, path = _session(data, payload)
    state = _read_json(path)
    if not state:  # a new session: a good moment to remove old ones
        _clean(data)
    _end_turn(data, key, state, s, "unknown")
    listed = _listing(data, payload, state)
    cwd = payload.get("cwd")
    # without a list, no tip: a skill on disk can belong to a disabled plugin
    skills = () if listed is None else catalog(parse_listing(listed),
                                               disk_skills(base, Path(cwd) if isinstance(cwd, str) and cwd else None))
    candidates = rank(text, skills, block=s.block)  # no pins: Claude sees every skill anyway
    tipped = state.get("tipped") or []
    names = [n for n in pick(s, candidates) if n not in tipped]  # once per session: it stays in context
    given = bool(names) and "tips" in s.apply
    number = int(state.get("turns") or 0) + 1
    state.update(turns=number, turn={"time": round(time.time(), 3), "number": number, "tip": names, "given": given,
                                     "candidates": [[n, score] for n, score in candidates[:5]], "used": []})
    if given:
        state["tipped"] = tipped + names
    _write_json(path, state)
    if not given:
        return None
    by_name = {skill.name: skill for skill in skills}
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "additionalContext": tip_text([by_name[n] for n in names])}}


def on_skill(payload: dict, data: Path) -> None:
    tool_input = payload.get("tool_input")
    name = tool_input.get("skill") if isinstance(tool_input, dict) else None
    if payload.get("tool_name") != "Skill" or not isinstance(name, str):
        return
    _, path = _session(data, payload)
    state = _read_json(path)
    if isinstance(state.get("turn"), dict):
        state["turn"]["used"].append(name)
        _write_json(path, state)


def on_stop(payload: dict, data: Path, s: Settings, outcome: str) -> None:
    key, path = _session(data, payload)
    state = _read_json(path)
    _listing(data, payload, state)  # by now the transcript holds the list of the session's first prompt
    _end_turn(data, key, state, s, outcome)
    _write_json(path, state)


def handle(event: str, payload: dict, data: Path, base: Path) -> dict | None:
    """Run one hook. The dict, if any, is what the hook prints for Claude Code."""
    s = settings(data)
    if event == "UserPromptSubmit":
        return on_prompt(payload, data, base, s)
    if event == "PostToolUse":
        on_skill(payload, data)
    elif event in ("Stop", "StopFailure"):
        on_stop(payload, data, s, "completed" if event == "Stop" else "failed")
    return None


def main(argv: list[str]) -> int:
    """Run the hook that ``argv`` names, or with ``report [data folder]`` print the report. Whatever goes wrong,
    the user's prompt goes on: the exit code is 0."""
    base = config_dir()
    data = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or base / "polymetis")
    if argv[:1] == ["report"]:  # /polymetis:report passes the data folder: a command gets no plugin variables
        print(report.render(log.read((Path(argv[1]) if len(argv) > 1 and argv[1] else data) / log.NAME)))
        return 0
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        if not isinstance(payload, dict):
            return 0
        out = handle(argv[0] if argv else "", payload, data, base)
        if out:
            print(json.dumps(out))
    except Exception as e:  # the type only: a message may quote the prompt
        print(f"polymetis: {type(e).__name__}", file=sys.stderr)
    return 0
