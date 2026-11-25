"""Blind pairwise judging of the A/B runs: per task and repeat, the two answers go to a judge model in both
orders, without saying which run had Polymetis. A side wins only when both orders agree; else it is a tie.

Usage: python judge.py TASKS.json OUT_DIR [--model opus] [--jobs 4]
"""
import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from run_ab import DROP_ENV
from summarize import read_run

PROMPT = """You are judging two answers to the same request. Judge only how well each answer serves the person who asked: is it correct, does it do what was asked, how useful and actionable is it, and do its length and format fit the request? Longer is not better by itself.

<request>
{request}
</request>

<answer_1>
{first}
</answer_1>

<answer_2>
{second}
</answer_2>

Reply with only a JSON object: {{"better": 1, 2, or 0 for a tie, "reason": "one sentence"}}"""

NO_TOOLS = "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,Skill,Task,Agent,NotebookEdit,TodoWrite"


def ask(request: str, first: str, second: str, args) -> dict:
    work = tempfile.mkdtemp(prefix="judge-", dir=Path(args.out) / "work")
    cmd = ["claude", "-p", PROMPT.format(request=request, first=first, second=second), "--model", args.model,
           "--output-format", "json", "--setting-sources", "project", "--no-session-persistence",
           "--disallowedTools", NO_TOOLS]
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    done = subprocess.run(cmd, cwd=work, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env,
                          timeout=600)
    try:
        text = json.loads(done.stdout).get("result") or ""
        return json.loads(re.search(r"\{.*\}", text, re.S).group(0))
    except (ValueError, AttributeError):
        return {"better": None, "reason": f"unreadable: {done.stdout[-200:]} {done.stderr[-200:]}"}


def judge(task: dict, rep: str, args) -> dict:
    out = Path(args.out)
    off, on = (read_run(out / f"{task['id']}.{rep}.{arm}.jsonl")["result"] or "" for arm in ("off", "on"))
    a = ask(task["prompt"], off, on, args)   # 1 = off, 2 = on
    b = ask(task["prompt"], on, off, args)   # 1 = on, 2 = off
    pick_a = {1: "off", 2: "on", 0: "tie"}.get(a.get("better"))
    pick_b = {1: "on", 2: "off", 0: "tie"}.get(b.get("better"))
    verdict = pick_a if pick_a == pick_b else "tie"
    return {"task": task["id"], "rep": rep, "verdict": verdict, "orders": [pick_a, pick_b],
            "reasons": [a.get("reason"), b.get("reason")]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks")
    parser.add_argument("out")
    parser.add_argument("--model", default="opus")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    out = Path(args.out)
    (out / "work").mkdir(exist_ok=True)
    tasks = {t["id"]: t for t in json.loads(Path(args.tasks).read_text(encoding="utf-8"))}
    pairs = sorted({tuple(p.name.split(".")[:2]) for p in out.glob("*.on.jsonl")})
    pairs = [(tasks[t], rep) for t, rep in pairs if t in tasks and (out / f"{t}.{rep}.off.jsonl").exists()]
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        verdicts = list(pool.map(lambda p: judge(*p, args), pairs))
    for v in verdicts:
        print(f"{v['task']:<12} {v['rep']} {v['verdict']:<4} orders={v['orders']} | {v['reasons'][0]}")
    count = {k: sum(v["verdict"] == k for v in verdicts) for k in ("on", "off", "tie")}
    print(f"with Polymetis better: {count['on']}, without better: {count['off']}, tie or split: {count['tie']}")
    json.dump(verdicts, open(out / "verdicts.json", "w"), indent=1)


if __name__ == "__main__":
    main()
