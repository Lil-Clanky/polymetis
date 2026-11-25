"""The report: counts from the decision log, and proposals. It reads and prints; it never changes a setting."""

import datetime
import time
from collections import Counter, defaultdict

DAY = 86400.0
MIN_SPAN_DAYS = 14  # proposals to disable a skill need at least this much log
ABLATION_EVERY_DAYS = 90
NEW_MODEL_DAYS = 7


def _span_days(records) -> float:
    times = [r.get("time", 0) for r in records]
    return (max(times) - min(times)) / DAY if times else 0.0


def _share(part: int, whole: int) -> str:
    return f"{part} of {whole}" if whole else "0"


def _n(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _ablation(all_records, now: float) -> list[str]:
    recent = [r for r in all_records if now - r.get("time", 0) <= ABLATION_EVERY_DAYS * DAY]
    if any(r.get("arm") in ("normal", "ablation") for r in recent):  # one runs or ran, also with no chat in its arm yet
        return []
    first_seen: dict[str, float] = {}
    for r in sorted(all_records, key=lambda r: r.get("time", 0)):
        for model in r.get("answered_by") or []:
            first_seen.setdefault(model, r.get("time", 0))
    oldest = min((r.get("time", now) for r in all_records), default=now)
    new = sorted(m for m, t in first_seen.items() if now - t <= NEW_MODEL_DAYS * DAY and t - oldest > DAY)
    if not new and now - oldest < ABLATION_EVERY_DAYS * DAY:
        return []
    until = (datetime.date.fromtimestamp(now) + datetime.timedelta(days=6)).isoformat()  # its last day: a week
    why = (f"new model(s) since {NEW_MODEL_DAYS} days: {', '.join(new)}" if new
           else f"no ablation in the last {ABLATION_EVERY_DAYS} days")
    return ["", f"Proposal: run an ablation week ({why}). A quarter of new sessions then runs without skills,",
            "and this report compares both groups. Set it with this command, then restart Hermes or the gateway:",
            # the date in quotes: Hermes copies its config through JSON for every new session, and a YAML date breaks that
            f"  hermes config set plugins.entries.polymetis.settings.ablation '{{share: 0.25, until: \"{until}\"}}'"]


def _compare(records) -> list[str]:
    if not any(r.get("arm") == "ablation" for r in records):
        return []
    # only sessions that started while the ablation ran, up to when they left their group; a turn without a
    # request that Polymetis saw shows nothing the ablation changed, and a subagent's turn is a whole task
    grouped = [r for r in records if r.get("arm") in ("normal", "ablation")]
    unseen = sum(not r.get("api_calls") for r in grouped)
    arms, subagents = defaultdict(list), defaultdict(list)
    for r in grouped:
        if r.get("api_calls"):
            (subagents if r.get("platform") == "subagent" else arms)[r["arm"]].append(r)
    lines = ["", "Ablation comparison (per turn unless noted):",
             f"  {'group':<10} {'sessions':>8} {'turns':>6} {'tool errors':>11} {'corrections':>11} "
             f"{'repeats':>7} {'failed':>6} {'tokens':>8}"]
    for name in ("normal", "ablation"):
        rs = arms.get(name, [])
        n = len(rs) or 1
        sessions = len({r.get("session") for r in rs})
        lines.append(
            f"  {name:<10} {sessions:>8} {len(rs):>6} {sum(r.get('tool_errors') or 0 for r in rs) / n:>11.2f} "
            f"{sum(bool(r.get('correction')) for r in rs) / n:>11.2f} {sum(bool(r.get('repeat')) for r in rs) / n:>7.2f} "
            f"{sum(r.get('outcome') == 'failed' for r in rs) / n:>6.2f} "
            f"{sum((r.get('tokens_in') or 0) + (r.get('tokens_out') or 0) for r in rs) / n:>8.0f}")
    if subagents:
        lines.append("  Subagents that delegate_task started, apart from the turns above:")
        for name in ("normal", "ablation"):
            rs = subagents.get(name, [])
            n = len({r.get("session") for r in rs})
            tokens = sum((r.get("tokens_in") or 0) + (r.get("tokens_out") or 0) for r in rs)
            lines.append(f"  {name:<10} {n:>8} subagents, {tokens / (n or 1):.0f} tokens each")
    if unseen:
        lines.append(f"  Left out: {_n(unseen, 'turn')} without a request that Polymetis saw.")
    lines.append("  Few sessions give noisy numbers; compare again after a full week.")
    return lines


def render(all_records, *, days: int = 30, catalogs: dict[str, list[str]] | None = None,
           now: float | None = None) -> str:
    now = time.time() if now is None else now
    records = [r for r in all_records if now - r.get("time", 0) <= days * DAY]
    if not records:
        return (f"Polymetis logged no turns in the last {days} days. It writes one line per turn while the "
                "setting `log` is on and the plugin is enabled.")
    sessions = {}
    for r in records:
        sessions[r.get("session")] = r  # the last record of a session holds its final level
    out = [f"Polymetis report, last {days} days: {_n(len(sessions), 'session')}, {_n(len(records), 'turn')}."]

    levels = Counter(r.get("level") or "undecided" for r in sessions.values())
    out.append("Session levels: " + ", ".join(f"{k} {v}" for k, v in sorted(levels.items())) + ".")
    platforms = Counter(r.get("platform") or "unknown" for r in records)
    out.append("Turns per platform: " + ", ".join(f"{k} {v}" for k, v in platforms.most_common()) + ".")

    tipped = [r for r in records if r.get("tip")]
    sent = [r for r in tipped if r.get("tip_given")]
    quiet = [r for r in tipped if not r.get("tip_given")]  # with apply off, or in the ablation arm

    def hits(rs):
        return sum(bool(set(r.get("tip") or []) & set(r.get("used_skills") or [])) for r in rs)
    loaded = [r for r in records if r.get("used_skills")]
    untipped = sum(not set(r.get("used_skills") or []) & set(r.get("tip") or []) for r in loaded)
    out.append(f"Tips: a skill matched in {_n(len(tipped), 'turn')}, and {len(sent)} of these got a tip. The model "
               f"loaded a matching skill in {_share(hits(sent), len(sent))} turns with a tip, and in "
               f"{_share(hits(quiet), len(quiet))} turns without one.")
    out.append(f"Skills loaded: in {_n(len(loaded), 'turn')}, {untipped} of them without a matching tip.")

    used = Counter(name for r in records for name in r.get("used_skills") or [])
    if used:
        out.append("Most loaded skills: " + ", ".join(f"{k} {v}" for k, v in used.most_common(10)) + ".")

    local = Counter(r.get("local") for r in records if r.get("local"))
    if local:
        misses = sum(1 for r in records if r.get("local") and set(r.get("tip") or []) - set(r.get("chosen") or []))
        out.append("Requests prepared for a local model, sent there or not: " + ", ".join(f"{k} {v}" for k, v in local.most_common())
                   + f". Turns whose best skill was not in the local set: {misses}.")

    outcomes = Counter(r.get("outcome") or "unknown" for r in records)
    errors = sum(r.get("tool_errors") or 0 for r in records)
    corrections = sum(bool(r.get("correction")) for r in records)
    repeats = sum(bool(r.get("repeat")) for r in records)
    out.append("Outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(outcomes.items()))
               + f". Tool errors: {errors}. Messages that read as a correction: {corrections}, as a repeat: {repeats}.")

    names = sorted({n for names in (catalogs or {}).values() for n in names})
    if names:
        if _span_days(records) < MIN_SPAN_DAYS:
            out.append(f"Unused skills: the log covers {_span_days(records):.0f} days; this needs "
                       f"{MIN_SPAN_DAYS} days or more.")
        else:
            unused = [n for n in names if n not in used]
            if unused:
                out += ["", f"Proposal: {_n(len(unused), 'skill')} {'was' if len(unused) == 1 else 'were'} not "
                        f"loaded in the last {days} days. Hermes lists every enabled skill in each prompt. To leave "
                        "one out, add it to `skills.disabled` in config.yaml:", "  " + ", ".join(unused)]
    out += _compare(records)
    out += _ablation(all_records, now)
    return "\n".join(out)
