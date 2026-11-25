"""The offline search numbers of evals/ may not get worse. Raise a floor when a change improves it."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))
import retrieval  # noqa: E402

from polymetis.config import Settings  # noqa: E402

# (set, distractors): (top 3, right tips, wrong tips, quiet on tasks without a skill)
FLOORS = {("written", 0): (31, 28, 1, 9), ("written", 141): (32, 30, 2, 8),
          ("live", 0): (9, 6, 1, 4), ("live", 141): (6, 6, 4, 3)}


@pytest.mark.parametrize("name, extra", sorted(FLOORS))
def test_the_search_keeps_its_offline_numbers(name, extra):
    skills, tasks = retrieval.load()
    m = retrieval.measure(skills, retrieval.of_set(tasks, name), extra, Settings().min_score)
    at3, right, wrong, quiet = FLOORS[name, extra]
    assert m["at3"] >= at3 and m["right_tips"] >= right and m["quiet_none"] >= quiet
    assert m["wrong_tips"] <= wrong


def test_the_fixture_is_complete():
    skills, tasks = retrieval.load()
    names = {s["name"] for s in skills}
    assert len(skills) == 185 and sum(s["bundled"] for s in skills) == 44
    assert all(set(t["skills"]) <= names for t in tasks) and len({t["id"] for t in tasks}) == len(tasks)
    assert {t.get("set", "written") for t in tasks} == {"written", "live"}
