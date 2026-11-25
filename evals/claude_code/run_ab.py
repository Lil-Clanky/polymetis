"""A/B in Claude Code: each task once without and once with Polymetis, with `claude -p` on one model, in one
empty folder. A first prompt there lets Polymetis see the folder's skill list: it gives no tip without one. Runs
that finished before are kept, so a stopped batch can go on.

Usage: python run_ab.py TASKS.json PLUGIN_DIR OUT_DIR [--model sonnet] [--jobs 4] [--repeat 1]
"""
import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
from pathlib import Path

# the host session's links: a test run should not talk to the app that this session runs in
DROP_ENV = ("CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_HOST_SESSION_ID",
            "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ATTENDED")


def run(task: dict, arm: str, rep: int, args) -> str:
    out = Path(args.out) / f"{task['id']}.{rep}.{arm}.jsonl"
    if out.exists() and '"type":"result"' in out.read_text(encoding="utf-8", errors="replace"):
        return f"{out.name}: kept"
    work = Path(args.out) / "work"
    cmd = ["claude", "-p", task["prompt"], "--model", args.model, "--output-format", "stream-json", "--verbose",
           "--allowedTools", "Skill", "--max-budget-usd", "2"]
    if arm == "on":
        cmd += ["--plugin-dir", args.plugin]
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    with open(out, "w", encoding="utf-8") as handle:
        try:
            done = subprocess.run(cmd, cwd=work, stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.PIPE,
                                  env=env, timeout=900, text=True)
            code = done.returncode
            err = done.stderr[-300:]
        except subprocess.TimeoutExpired:
            code, err = "timeout", ""
    return f"{out.name}: exit {code} {err.strip()[:200]}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks")
    parser.add_argument("plugin")
    parser.add_argument("out")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    (Path(args.out) / "work").mkdir(parents=True, exist_ok=True)
    tasks = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
    if args.only:
        tasks = [t for t in tasks if t["id"] in args.only.split(",")]
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    subprocess.run(["claude", "-p", "Say hi.", "--model", "haiku", "--plugin-dir", args.plugin, "--max-budget-usd", "0.5"],
                   cwd=Path(args.out) / "work", stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=300)
    jobs = [(t, arm, rep) for rep in range(args.repeat) for t in tasks for arm in ("off", "on")]
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        for line in pool.map(lambda j: run(*j, args), jobs):
            print(line, flush=True)


if __name__ == "__main__":
    sys.exit(main())
