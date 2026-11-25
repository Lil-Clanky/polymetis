"""Hermes's skill index: read it from a system prompt, and cut it down for a smaller request.

Hermes writes the index as an ``<available_skills>`` block, one ``- name: description`` row per
skill, under ``category:`` headers, or a ``category [names only]: a, b`` row for categories outside
the coding context (agent/prompt_builder.py, ``_render_skills_index``).
"""

import re
from dataclasses import dataclass

OPEN, CLOSE = "<available_skills>", "</available_skills>"
HEADER = "## Skills\n"
LAST_LINE = "Only proceed without loading a skill if genuinely none are relevant to the task."
# the hints of decide.hint only; text that a user puts between these tags stays. A match starts only at the first
# of a run of newlines, else \n* is tried at every blank line of a long paste, which is quadratic.
HINT = re.compile(r"(?<!\n)\n*<skill-hint>Relevant skills?: [^<\n]*\. Load one with skill_view if you need it\.</skill-hint>")
# shortcut: drops whole sentences that point at skill_view( or name skill_manage, which matches Hermes's
# wording today; a sentence with a dot inside would be cut short, revisit when the wording changes.
# A match may start only where a sentence can, at a line's start or after ". ": without that anchor the
# leading [^.\n]* is tried at every position of a long line, which is quadratic.
_SENTENCE = r"(?:^|(?<=\n)|(?<=\.[ \t]))[^.\n]*{}[^.\n]*\.?[ \t]?"
# a call on one line, [^)]* ate the lines after; and a short one, as an unclosed call scanned to the line's end
POINTER = re.compile(_SENTENCE.format(r"\bskill_view\([^)\n]{0,200}\)"))
MANAGE = re.compile(_SENTENCE.format(r"\bskill_manage\b"))
# Hermes's skills section: its header, lines that start no other heading or block, then the opening tag
SECTION = re.compile(r"^## Skills\n(?:(?!#|<available_skills>)[^\n]*\n)*?(?=<available_skills>\n)", re.M)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str = ""
    category: str = ""


def is_text_part(part) -> bool:
    """A text part of a message: ``{"type": "text", "text": ...}`` as OpenAI and Anthropic send it,
    ``input_text`` in the Responses API, or Bedrock's ``{"text": ...}``."""
    return isinstance(part, dict) and isinstance(part.get("text"), str) and \
        part.get("type", "text") in ("text", "input_text")


def text_of(content) -> str:
    """The text of a message content: a string, or the text parts of a list of parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p["text"] for p in content if is_text_part(p))
    return ""


def _skills(body: str) -> list[Skill]:
    skills, category = [], ""
    for line in body.splitlines():
        row = line.strip()
        if row.startswith("- "):
            name, _, desc = row[2:].partition(": ")  # qualified names such as plugin:skill have no space
            nested = line.startswith("    ")  # a one-skill category is a top-level row of its own
            skills.append(Skill(name.strip(), desc.strip(), category if nested else ""))
        elif row.endswith(":") and row[:-1].strip():
            category = row[:-1].strip()
        elif " [names only]: " in row:
            category, _, names = row.partition(" [names only]: ")
            skills += [Skill(n.strip(), "", category.strip()) for n in names.split(",") if n.strip()]
            category = ""
    return list({s.name: s for s in skills}.values())


def _line_starts(text: str, tag: str):
    """The positions where ``tag`` starts a line."""
    i = text.find(tag)
    while i >= 0:
        if i == 0 or text[i - 1] == "\n":
            yield i
        i = text.find(tag, i + 1)


def _best(text: str, starts: list[int], last: bool) -> tuple[int, int] | None:
    """Of the blocks that open at ``starts`` and close at the next closing tag that starts a line, without
    another of ``starts`` inside, the one with the most skills; of equal ones the last if ``last``."""
    best, end = None, -1
    for i, start in enumerate(starts):
        if end < start:  # each search goes forward only, so many tags take linear time
            end = text.find("\n" + CLOSE, start)
            if end < 0:
                break
            end += 1
        if i + 1 < len(starts) and starts[i + 1] < end:
            continue
        size = len(_skills(text[start + len(OPEN):end]))
        if best is None or size > best[0] or (last and size == best[0]):
            best = (size, start, end + len(CLOSE))
    return best[1:] if best else None


def _block(text: str) -> tuple[int, int] | None:
    """The span of Hermes's index. Its tags start a line; a skill's description may hold them further on, as
    Hermes writes descriptions as they are. Context files come before the index in the system prompt and memory
    after it, and either may show a block of its own, so a block in Hermes's "## Skills" section comes first.
    Without that section, as in a Hermes that names it differently, the biggest block that starts a line counts,
    of equal ones the last, as context files are more likely to hold an example.
    shortcut: of two equal "## Skills" sections the first, as a client's own system prompt comes after the
    index; revisit if a context file with a copy of that section shows up"""
    return _best(text, [m.end() for m in SECTION.finditer(text)], last=False) or \
        _best(text, list(_line_starts(text, OPEN)), last=True)


def parse_index(system_text: str) -> list[Skill] | None:
    """The skills in the index, or None when the prompt has no index."""
    span = _block(system_text or "")
    return None if span is None else _skills(system_text[span[0] + len(OPEN):span[1] - len(CLOSE)])


def _without_block(text: str) -> str:
    span = _block(text)
    if span is None:
        return text
    start, end = span
    header = text.rfind(HEADER, 0, start)
    if header >= 0 and "\n## " not in text[header + len(HEADER):start]:
        start = header
    tail = text[end:]
    stripped = tail.lstrip("\n")
    if stripped.startswith(LAST_LINE):
        end += len(tail) - len(stripped) + len(LAST_LINE)
    # Hermes may follow the block with notes in parentheses about hidden or unloadable skills; they end
    # with ".)" and can hold parentheses of their own, such as skill_view(name)
    while (rest := text[end:]).startswith("\n("):
        cut = rest.find(".)", 2)
        end += cut + 2 if cut >= 0 else len(rest)
    return (text[:start].rstrip("\n") + "\n\n" + text[end:].lstrip("\n")).strip("\n")


def strip_skills(text: str) -> str:
    """The system prompt without the skill index and without the sentences that point at skill_view or
    skill_manage."""
    return MANAGE.sub("", POINTER.sub("", _without_block(text)))


def keep_skills(text: str, names) -> str:
    """The system prompt with an index of only the named skills, or without an index when none is left. A
    request with this index keeps skill_view only, so the sentences that name skill_manage go."""
    wanted = set(names)
    skills = [s for s in parse_index(text) or [] if s.name in wanted]
    span = _block(text)
    if span is None or not skills:
        return strip_skills(text)
    rows = "\n".join(f"  - {s.name}: {s.description}" if s.description else f"  - {s.name}" for s in skills)
    return MANAGE.sub("", text[:span[0]] + OPEN + "\n" + rows + "\n" + CLOSE + text[span[1]:])


def strip_hints(text: str) -> str:
    return HINT.sub("", text)
