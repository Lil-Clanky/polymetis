"""Polymetis as a Claude Code plugin: the skill list, the SKILL.md files on disk, and the hooks."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from polymetis import claude_code, log, report
from polymetis.catalog import Skill


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def skill_md(name: str, description: str, extra: str = "") -> str:
    return f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n# {name}\n"


LISTING = ("The following skills are available for use with the Skill tool:\n\n"
           "- graphify: Turn any input into a knowledge graph\n"
           "- design:ux-copy\n"
           "- superpowers:brainstorming: You MUST use this before any creative work: features, components\n"
           "- simplify: Review the changed code for reuse and simplification\n")


def listing_line(content: str, initial: bool = True) -> str:
    return json.dumps({"type": "attachment", "attachment": {"type": "skill_listing", "content": content,
                                                            "isInitial": initial}}) + "\n"


# --- the skill list that Claude Code shows the model ---

def test_listing_rows_with_and_without_a_description():
    assert claude_code.parse_listing(LISTING) == [
        Skill("graphify", "Turn any input into a knowledge graph"), Skill("design:ux-copy", ""),
        Skill("superpowers:brainstorming", "You MUST use this before any creative work: features, components"),
        Skill("simplify", "Review the changed code for reuse and simplification")]


def test_listing_from_the_transcript_reads_whole_new_lines_only(tmp_path):
    t = write(tmp_path / "t.jsonl", json.dumps({"type": "user"}) + "\n" + listing_line(LISTING))
    content, offset = claude_code.listing_in(t, 0)
    assert content == LISTING and offset == t.stat().st_size
    with open(t, "a", encoding="utf-8") as handle:  # a list that only adds, and a line still being written
        handle.write(listing_line("- only: one", initial=False) + '{"type": "attach')
    content, later = claude_code.listing_in(t, offset)
    assert content is None and offset < later < t.stat().st_size
    assert claude_code.listing_in(tmp_path / "missing.jsonl", 0) == (None, 0)


def test_listing_from_a_transcript_that_got_shorter_starts_over(tmp_path):
    t = write(tmp_path / "t.jsonl", listing_line(LISTING))
    assert claude_code.listing_in(t, 10 ** 9) == (LISTING, t.stat().st_size)


# --- SKILL.md files ---

@pytest.mark.parametrize("text, expected", [
    ("---\nname: a\ndescription: Does A. Use when: B.\n---\nbody", {"name": "a", "description": "Does A. Use when: B."}),
    ('---\ndescription: "Say \\"hi\\" when asked"\n---\n', {"description": 'Say "hi" when asked'}),
    ("---\ndescription: 'It''s quoted'\n---\n", {"description": "It's quoted"}),
    ("---\ndescription: >\n  Folded over\n  two lines\nname: b\n---\n", {"description": "Folded over two lines", "name": "b"}),
    ("---\ndescription: |-\n  Literal\n  block\n---\n", {"description": "Literal block"}),
    ("---\ndescription: Starts here\n  and goes on\n# a comment\nname: c\n---\n",
     {"description": "Starts here and goes on", "name": "c"}),
    ("---\ndescription:\n  On the next line\nallowed-tools:\n  - Bash\n---\n",
     {"description": "On the next line", "allowed-tools": "- Bash"}),
    ("no front matter\n", {}),
    ("---\nname: unclosed\n", {}),
])
def test_front_matter(text, expected):
    assert claude_code.frontmatter(text) == expected


def test_disk_skills_of_plugins_synced_plugins_user_and_project(tmp_path):
    base, cwd = tmp_path / "claude", tmp_path / "project"
    old = base / "plugins/cache/mkt/plug/0.9.0"
    write(old / ".claude-plugin/plugin.json", '{"name": "plug"}')
    write(old / "skills/alpha/SKILL.md", skill_md("alpha", "Old text"))
    os.utime(old / ".claude-plugin/plugin.json", (1, 1))  # the older install of the same plugin
    new = base / "plugins/cache/mkt/plug/1.0.0"
    write(new / ".claude-plugin/plugin.json", '{"name": "plug"}')
    write(new / "skills/alpha/SKILL.md", skill_md("alpha", "Alpha does a", "when_to_use: Use for a-tasks\n"))
    write(new / "commands/beta.md", "---\ndescription: Beta command\n---\nRun beta.\n")
    synced = base / "plugins/synced/s1/x1"
    write(synced / ".claude-plugin/plugin.json", '{"name": "design", "skills": "./.claude/skills/"}')
    write(synced / ".claude/skills/ux-copy/SKILL.md", skill_md("ux-copy", "Write and review UX copy"))
    write(base / "plugins/cache/mkt/broken/1/.claude-plugin/plugin.json", "{not json")
    write(base / "skills/gamma/SKILL.md", skill_md("gamma", "Gamma helps"))
    write(base / "skills/synced/s1/delta/SKILL.md", skill_md("delta", "Delta helps"))
    write(cwd / ".claude/skills/eps/SKILL.md", "---\ndescription: Eps helps\n---\n")
    assert claude_code.disk_skills(base, cwd) == {
        "plug:alpha": "Alpha does a Use for a-tasks", "plug:beta": "Beta command",
        "design:ux-copy": "Write and review UX copy", "gamma": "Gamma helps", "delta": "Delta helps",
        "eps": "Eps helps"}


def test_catalog_takes_the_listed_names_and_the_full_descriptions():
    disk = {"design:ux-copy": "Write and review UX copy", "graphify": "Full graphify text", "orphan": "Not listed"}
    assert claude_code.catalog(claude_code.parse_listing(LISTING), disk) == (
        Skill("graphify", "Full graphify text"), Skill("design:ux-copy", "Write and review UX copy", "design"),
        Skill("superpowers:brainstorming", "You MUST use this before any creative work: features, components",
              "superpowers"),
        Skill("simplify", "Review the changed code for reuse and simplification"))


def test_catalog_finds_a_listed_skill_by_its_bare_name():
    # the desktop app lists the skills it syncs as anthropic-skills:<name>, and keeps them on disk as <name>
    assert claude_code.catalog([Skill("anthropic-skills:pdf", "")], {"pdf": "Read and fill PDFs"}) == (
        Skill("anthropic-skills:pdf", "Read and fill PDFs", "anthropic-skills"),)


def test_the_marketplace_offers_the_plugin_and_its_report_command():
    root = Path(claude_code.__file__).resolve().parent
    manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert [(p["name"], p["source"]) for p in market["plugins"]] == [(manifest["name"], "./")]
    command = (root / "commands" / "report.md").read_text(encoding="utf-8")
    assert "disable-model-invocation: true" in command
    assert '!`python3 "${CLAUDE_PLUGIN_ROOT}/claude_code_hook.py" report "${CLAUDE_PLUGIN_DATA}"`' in command


def test_the_plugin_manifest_runs_the_hook_script_for_each_event():
    root = Path(claude_code.__file__).resolve().parent
    manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    hooks = manifest["hooks"]
    assert set(hooks) == {"UserPromptSubmit", "PostToolUse", "Stop", "StopFailure"}
    assert hooks["PostToolUse"][0]["matcher"] == "Skill"
    for event, groups in hooks.items():
        command = groups[0]["hooks"][0]["command"]
        assert command == f'python3 "${{CLAUDE_PLUGIN_ROOT}}/claude_code_hook.py" {event}'
    assert (root / "claude_code_hook.py").is_file() and manifest["name"] == "polymetis"


def test_catalog_without_a_list_takes_what_is_on_disk():
    assert claude_code.catalog(None, {"b:x": "X", "a": "A"}) == (Skill("a", "A"), Skill("b:x", "X", "b"))


def test_a_tip_names_each_skill_with_its_description_cut_short():
    text = claude_code.tip_text([Skill("design:ux-copy", "Write and review UX copy"), Skill("long", "word " * 100),
                                 Skill("bare", "")])
    assert "design:ux-copy (Write and review UX copy); long (word word" in text and "; bare." in text
    assert "Skill tool" in text and "…" in text and len(text) < 500


@pytest.mark.parametrize("candidates, expected", [
    ([("a", 22.6), ("b", 10.3)], ["a"]),        # stands out: the tip
    ([("a", 13.3), ("b", 10.6)], []),           # a close second: in the trial, such a first was often wrong
    ([("a", 9.0)], ["a"]),                      # nothing else matched
    ([("a", 6.0)], []),                         # below min_score: Claude Code's 7
    ([], []),
])
def test_a_tip_needs_a_skill_that_stands_out(candidates, expected):
    s = claude_code.settings(Path("/nowhere"))
    assert claude_code.pick(s, candidates) == expected


def test_no_tips_with_max_tips_zero():
    assert claude_code.pick(claude_code.Settings(max_tips=0), [("a", 22.6)]) == []


# --- the hooks ---

@pytest.fixture
def home(tmp_path):
    base = tmp_path / "claude"
    plugin = base / "plugins/cache/mkt/rev/1.0.0"
    write(plugin / ".claude-plugin/plugin.json", '{"name": "rev"}')
    write(plugin / "skills/review-pr/SKILL.md", skill_md("review-pr", "Review a pull request for bugs and style before merging"))
    write(plugin / "skills/write-docs/SKILL.md", skill_md("write-docs", "Write documentation, READMEs and runbooks"))
    data = tmp_path / "data"
    write(data / "settings.json", json.dumps({"min_score": 0.5}))  # two skills score lower than many
    return base, data


def prompt(text: str, session: str = "s1", transcript: Path | None = None) -> dict:
    return {"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": text, "cwd": "/nowhere",
            "transcript_path": str(transcript or "/nowhere/t.jsonl")}


def run(event: str, payload: dict, home) -> dict | None:
    base, data = home
    return claude_code.handle(event, payload, data, base)


def context(out: dict | None) -> str:
    assert out and out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    return out["hookSpecificOutput"]["additionalContext"]


def test_a_turn_gets_a_tip_and_one_log_line_without_message_text(home):
    tip = context(run("UserPromptSubmit", prompt("Please review my pull request before merging"), home))
    assert "rev:review-pr (Review a pull request" in tip and "write-docs" not in tip
    assert run("PostToolUse", {"session_id": "s1", "tool_name": "Skill", "tool_input": {"skill": "rev:review-pr"}},
               home) is None
    assert run("Stop", {"session_id": "s1", "transcript_path": "/nowhere/t.jsonl"}, home) is None
    path = home[1] / log.NAME
    [record] = log.read(path)
    assert record["tip"] == ["rev:review-pr"] and record["tip_given"] is True and record["platform"] == "claude-code"
    assert record["used_skills"] == ["rev:review-pr"] and record["outcome"] == "completed"
    assert "level" not in record and record["duration_ms"] >= 0  # levels are Hermes's
    assert "merging" not in path.read_text(encoding="utf-8")


def test_shadow_mode_logs_the_tip_without_giving_it(home):
    write(home[1] / "settings.json", json.dumps({"min_score": 0.5, "apply": []}))
    assert run("UserPromptSubmit", prompt("Please review my pull request before merging"), home) is None
    run("Stop", {"session_id": "s1"}, home)
    [record] = log.read(home[1] / log.NAME)
    assert record["tip"] == ["rev:review-pr"] and record["tip_given"] is False


def test_a_skill_gets_one_tip_per_session(home):
    assert "rev:review-pr" in context(run("UserPromptSubmit", prompt("Review this pull request"), home))
    assert run("UserPromptSubmit", prompt("Now review the pull request again"), home) is None
    assert "rev:review-pr" in context(run("UserPromptSubmit", prompt("Review this pull request", session="s2"), home))


def test_slash_commands_and_empty_prompts_are_left_alone(home):
    for text in ("/review-pr 12", "   ", None):
        assert run("UserPromptSubmit", prompt(text), home) is None
    assert not (home[1] / "sessions").exists() and not (home[1] / log.NAME).exists()


def test_a_turn_without_its_end_is_logged_when_the_next_starts(home):
    run("UserPromptSubmit", prompt("Review this pull request"), home)
    run("UserPromptSubmit", prompt("Write docs for it"), home)
    run("StopFailure", {"session_id": "s1"}, home)
    first, second = log.read(home[1] / log.NAME)
    assert (first["outcome"], first["turn"], first["duration_ms"]) == ("unknown", 1, None)
    assert (second["outcome"], second["turn"]) == ("failed", 2)


def test_the_transcript_list_limits_and_names_the_skills(home, tmp_path):
    listing = "- rev:review-pr\n- code-review: Review code changes for bugs\n"
    transcript = write(tmp_path / "t.jsonl", listing_line(listing))
    tip = context(run("UserPromptSubmit", prompt("Review this pull request", transcript=transcript), home))
    assert "rev:review-pr (Review a pull request" in tip  # listed by name only, described from disk
    # on disk but not in the list: Claude Code does not offer it here, so it gets no tip
    assert run("UserPromptSubmit", prompt("Write documentation and runbooks", "s2", transcript), home) is None


def test_a_new_session_starts_from_the_list_the_last_one_saw(home, tmp_path):
    transcript = write(tmp_path / "t.jsonl", listing_line("- builtin-deploy: Deploy the app to staging and production\n"))
    run("UserPromptSubmit", prompt("hello", transcript=tmp_path / "not-yet.jsonl"), home)
    run("Stop", {"session_id": "s1", "transcript_path": str(transcript)}, home)  # the transcript has its list now
    assert "builtin-deploy" in context(run("UserPromptSubmit", prompt("Deploy the app to staging", "s2"), home))


def test_old_session_files_go(home):
    run("UserPromptSubmit", prompt("Review this pull request"), home)
    [old] = (home[1] / "sessions").glob("*.json")
    os.utime(old, (1, 1))
    run("UserPromptSubmit", prompt("Review this pull request", session="s2"), home)
    assert not old.exists() and len(list((home[1] / "sessions").glob("*.json"))) == 1


def test_bad_settings_keep_their_defaults(home):
    write(home[1] / "settings.json", json.dumps({"min_score": "high", "max_tips": 1}))
    assert claude_code.settings(home[1]).min_score == 7.0
    assert claude_code.settings(home[1]).max_tips == 1 and claude_code.settings(home[1]).apply == {"tips"}


def test_main_prints_the_hook_output(home, monkeypatch, capsys):
    base, data = home
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(base))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(prompt("Review my pull request")).encode())))
    assert claude_code.main(["UserPromptSubmit"]) == 0
    assert "rev:review-pr" in context(json.loads(capsys.readouterr().out))


def test_the_report_counts_tips_and_loaded_skills(home, capsys):
    run("UserPromptSubmit", prompt("Please review my pull request before merging"), home)
    run("PostToolUse", {"session_id": "s1", "tool_name": "Skill", "tool_input": {"skill": "rev:review-pr"}}, home)
    run("Stop", {"session_id": "s1"}, home)
    assert claude_code.main(["report", str(home[1])]) == 0
    out = capsys.readouterr().out
    assert "1 session, 1 turn." in out and "loaded a matching skill in 1 of 1 turns with a tip" in out
    assert "rev:review-pr 1" in out


def test_the_report_leaves_out_what_only_hermes_logs():
    now = 1_800_000_000.0
    records = [{"time": now - t * 86400, "session": s, "platform": "claude-code", "tip": [], "used_skills": [],
                "outcome": "completed"} for t, s in ((100, "a"), (1, "b"))]
    out = report.render(records, now=now)
    assert "1 session, 1 turn." in out
    assert "Session levels" not in out and "Tool errors" not in out and "hermes" not in out.lower()


@pytest.mark.parametrize("stdin", ["not json", "[1, 2]", ""])
def test_bad_input_never_blocks_the_prompt(home, monkeypatch, capsys, stdin):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(home[1]))
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(stdin.encode())))
    assert claude_code.main(["UserPromptSubmit"]) == 0
    assert capsys.readouterr().out == ""


def test_the_hook_script_runs_from_any_folder(home, tmp_path):
    base, data = home
    root = Path(claude_code.__file__).resolve().parent
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(base), "CLAUDE_PLUGIN_DATA": str(data)}
    done = subprocess.run([sys.executable, str(root / "claude_code_hook.py"), "UserPromptSubmit"], cwd=tmp_path,
                          input=json.dumps(prompt("Review my pull request")), capture_output=True, text=True,
                          env=env, timeout=60)
    assert done.returncode == 0 and "rev:review-pr" in context(json.loads(done.stdout))
    subprocess.run([sys.executable, str(root / "claude_code_hook.py"), "Stop"], input="{}", text=True, env=env,
                   timeout=60, check=True)
