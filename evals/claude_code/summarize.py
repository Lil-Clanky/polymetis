"""What each run did: the skills it loaded, its cost, turns and answer length, and the tip Polymetis gave.

Usage: python summarize.py TASKS.json OUT_DIR [POLYMETIS_DATA_DIR]
"""
import hashlib
import json
import sys
from pathlib import Path


def read_run(path: Path) -> dict:
    run = {"skills": [], "result": None, "cost": None, "turns": None, "session": None, "ms": None}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "system" and d.get("subtype") == "init":
            run["session"] = d.get("session_id")
        elif d.get("type") == "assistant":
            for c in d["message"]["content"]:
                if c.get("type") == "tool_use" and c.get("name") == "Skill":
                    run["skills"].append(c["input"].get("skill"))
        elif d.get("type") == "result":
            run.update(result=d.get("result"), cost=d.get("total_cost_usd"), turns=d.get("num_turns"),
                       ms=d.get("duration_ms"), subtype=d.get("subtype"))
    return run


def tips(data: Path | None) -> dict:
    found = {}
    if data and (data / "decisions.jsonl").exists():
        for line in (data / "decisions.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            found[r["session"]] = r
    return found


def main() -> None:
    tasks = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    by_key = tips(Path(sys.argv[3]) if len(sys.argv) > 3 else None)
    rows = []
    for path in sorted(out.glob("*.jsonl")):
        task_id, rep, arm = path.name[:-len(".jsonl")].rsplit(".", 2)
        task = next((t for t in tasks if t["id"] == task_id), None)
        if task is None:
            continue
        run = read_run(path)
        key = hashlib.sha256((run["session"] or "").encode()).hexdigest()[:12]
        record = by_key.get(key, {})
        rows.append({"task": task_id, "rep": rep, "arm": arm, "want": task["skill"], "skills": run["skills"],
                     "hit": task["skill"] in run["skills"] if task["skill"] else not run["skills"],
                     "tip": record.get("tip") if arm == "on" else None, "cost": run["cost"], "turns": run["turns"],
                     "chars": len(run["result"] or ""), "ok": run.get("subtype") == "success"})
    for r in rows:
        print(f"{r['task']:<12} {r['rep']} {r['arm']:<3} ok={r['ok']!s:<5} hit={r['hit']!s:<5} "
              f"skills={','.join(s or '?' for s in r['skills']) or '-':<40} tip={','.join(r['tip'] or []) or '-':<36} "
              f"${r['cost'] or 0:.3f} turns={r['turns']} chars={r['chars']}")
    for arm in ("off", "on"):
        rs = [r for r in rows if r["arm"] == arm]
        want = [r for r in rs if r["want"]]
        print(f"{arm}: {len(rs)} runs, expected skill loaded {sum(r['hit'] for r in want)}/{len(want)}, "
              f"cost ${sum(r['cost'] or 0 for r in rs):.2f}, mean chars {sum(r['chars'] for r in rs) / (len(rs) or 1):.0f}")
    json.dump(rows, open(out / "summary.json", "w"), indent=1)


if __name__ == "__main__":
    main()
