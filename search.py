"""BM25 over the skills of an index: name, category and description, all local."""

from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache

from .catalog import Skill

K1, B = 1.2, 0.75
NAME_WEIGHT = 2  # a word in a skill's name counts as often as this
# a word, but not the tail of a contraction or possessive: "don't" gives "don", "github's" gives "github"
_WORD = re.compile(r"(?<![a-z0-9]['\u2019])[a-z0-9]+", re.I)
_PULL_REQUEST = re.compile(r"\bpull[ -]requests?\b", re.I)  # the words that GitHub's "PRs" stand for
_NOT_PLURAL = frozenset({"news", "canvas", "lens"})  # an "s" that is no plural; without it news meets new
STOPWORDS = frozenset("""
a an and are as at be but by can could do does for from had has have how i if in into is it its me my
of on or our please should so than that the their them then there these this those to us was we what
when where which while who why will with would you your
aan als bij dan dat de die dit een en er het hoe ik in is je jij kan kun maar me met mijn moet naar niet
nog of om onze ook op te tot u van voor wat wie wil zijn
add file files get help just like make need new read use want
""".split())  # the last row: words of any request to an agent, which name no skill


def _stem(word: str) -> str:
    # shortcut: a few English suffixes only, so that "merges", "merging" and "merge" meet, "debugging" and
    # "debug", "PRs" and "PR", and "remind" and "reminders"; Porter's stemmer is the upgrade when evals/ shows
    # misses on word forms
    if word in _NOT_PLURAL:
        return word
    if word.endswith(("ing", "ed")):
        stem = word[:-3] if word.endswith("ing") else word[:-2]
        if len(stem) >= 4:  # "debugg" and "plann" lose a letter, "install" and "pass" keep theirs
            word = stem[:-1] if stem[-1] == stem[-2] and stem[-1] not in "lsz" else stem
    elif word.endswith("s") and not word.endswith(("ss", "us")) and len(word) >= 3:
        word = word[:-1]
    # Porter's rule: "er" goes after a stem with two vowel-consonant runs, so "reminder" meets "remind"
    # while "merger" stays apart from "merge"
    if word.endswith("er") and len(re.findall(r"[aeiouy]+[^aeiouy]+", word[:-2])) > 1:
        word = word[:-2]
    return word[:-1] if len(word) >= 5 and word.endswith("e") else word


def words(text: str) -> list[str]:
    """The search words of a text: no stop words or bare numbers, and a single letter only as a capital, such as
    X or the M of M&A, not the -m or the b/ of a command or a diff."""
    found = _WORD.findall(_PULL_REQUEST.sub("pr", text or ""))
    return [_stem(w.lower()) for w in found
            if w.lower() not in STOPWORDS and (len(w) > 1 or w.isupper()) and not w.isdigit()]


def _document(skill: Skill) -> list[str]:
    return words(skill.name) * NAME_WEIGHT + words(skill.category.replace("/", " ")) + words(skill.description)


class Index:
    def __init__(self, skills: tuple[Skill, ...]):
        self.skills = skills
        self.docs = [Counter(_document(s)) for s in skills]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if skills else 1.0
        df = Counter(w for d in self.docs for w in d)
        n = len(skills)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def scores(self, query: str) -> list[float]:
        terms = set(words(query))
        out = []
        for doc, length in zip(self.docs, self.lengths):
            norm = K1 * (1 - B + B * length / (self.avg or 1.0))
            # over the skill's few words, not the query's: a pasted log has many thousands
            out.append(sum(self.idf[t] * n * (K1 + 1) / (n + norm) for t, n in doc.items() if t in terms))
        return out


@lru_cache(maxsize=32)  # a session's index stays the same for many turns
def index_for(skills: tuple[Skill, ...]) -> Index:
    return Index(skills)


def rank(query: str, skills, *, pin=(), block=frozenset(), limit: int = 10) -> list[tuple[str, float]]:
    """The best skills for the query as (name, score), pinned skills that are in the index first."""
    skills = tuple(s for s in skills if s.name not in block)
    if not skills:
        return []
    scores = dict(zip((s.name for s in skills), index_for(skills).scores(query)))
    pinned = [(n, round(scores[n], 2)) for n in dict.fromkeys(pin) if n in scores]
    taken = {n for n, _ in pinned}
    rest = sorted(((n, round(sc, 2)) for n, sc in scores.items() if n not in taken and sc > 0),
                  key=lambda x: (-x[1], x[0]))
    return (pinned + rest)[:max(limit, len(pinned))]
