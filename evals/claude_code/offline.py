"""Offline: what the hook's ranking and pick would tip for each task, on this machine's real skills. Free.

Usage: python offline.py TASKS.json PLUGIN_DIR LISTING.json [--grid]
"""
import importlib.util
import json
import sys
from pathlib import Path

tasks_file, plugin, listing_file = (Path(a) for a in sys.argv[1:4])
spec = importlib.util.spec_from_file_location("polymetis", plugin / "__init__.py",
                                              submodule_search_locations=[str(plugin)])
pkg = importlib.util.module_from_spec(spec)
sys.modules["polymetis"] = pkg
spec.loader.exec_module(pkg)
from polymetis import claude_code as cc  # noqa: E402
from polymetis.search import rank  # noqa: E402

listed = cc.parse_listing(json.loads(listing_file.read_text())["content"])
skills = cc.catalog(listed, cc.disk_skills(cc.config_dir(), None))
tasks = json.loads(tasks_file.read_text())
ranked = {t["id"]: rank(t["prompt"], skills) for t in tasks}


def pick(cands, min_score, margin):
    if not cands:
        return None
    (best, top), second = cands[0], cands[1][1] if len(cands) > 1 else 0.0
    return best if top >= min_score and top >= margin * second else None


def score(min_score, margin):
    right = wrong = missed = false_tip = 0
    for t in tasks:
        p = pick(ranked[t["id"]], min_score, margin)
        if t["ok"]:
            right += p in t["ok"]
            wrong += p is not None and p not in t["ok"]
            missed += p is None
        else:
            false_tip += p is not None
    return right, wrong, missed, false_tip


if "--grid" in sys.argv:
    n_skill = sum(bool(t["ok"]) for t in tasks)
    print(f"{n_skill} skill tasks, {len(tasks) - n_skill} controls; cells: right/wrong/none + tips on controls")
    for margin in (1.0, 1.2, 1.3, 1.5, 1.75, 2.0):
        print(f"margin {margin:<4}", "  ".join(f"min{m:>4}: {r:>2}/{w:>2}/{x:>2}+{f}" for m in (3, 5, 7, 9, 11)
                                             for r, w, x, f in [score(m, margin)]))
else:
    for t in tasks:
        c = ranked[t["id"]]
        pos = next((i + 1 for i, (n, _) in enumerate(c) if n in t["ok"]), None)
        p = pick(c, cc.DEFAULTS.min_score, cc.MARGIN)
        mark = "-" if p is None else ("RIGHT" if p in t["ok"] else "WRONG")
        top = ", ".join(f"{n} {s:.1f}" for n, s in c[:3])
        print(f"{t['id']:<15} ok@{pos!s:<4} {mark:<5} | {top}")
    print(f"min {cc.DEFAULTS.min_score}, margin {cc.MARGIN} -> right/wrong/none + tips on controls:", score(cc.DEFAULTS.min_score, cc.MARGIN))
