# Polymetis offline evaluation

This measures Polymetis's skill search without a model, a network or Hermes. It ranks the skills of an index for each task the way Polymetis does and counts how often the right skill comes out on top, and how many tips a `min_score` would give.

```
python evals/retrieval.py
```

`tests/test_polymetis_eval.py` runs the same measurement and fails when the numbers get worse.

## Files

- `tasks.json`: 63 tasks. 48 were written for this eval, 32 in English and 16 in Dutch: 38 name the skills that fit them; 10 need no skill, and some of those share words with a skill on purpose ("merge sort", "a whole note"). The other 15, marked `"set": "live"`, are messages that a tester sent to Hermes; see [Live set](#live-set).
- `skills.json`: the names, categories and descriptions of the 185 skills in Hermes Agent, as its index shows them: the 44 bundled skills and 141 optional ones. They come from Hermes Agent at commit 2506f5b0 (github.com/NousResearch/hermes-agent), MIT License, Copyright (c) 2025 Nous Research.
- `retrieval.py`: the measurement, apart for the written and the live set. The index holds the 44 bundled skills, plus 0, 50 or all 141 optional skills as distractors.

## Results

The written set, measured on 2026-11-25 with the default `min_score` of 5.

| Index | Language | Top 1 | Top 3 | Top 10 |
|---|---|---|---|---|
| 44 skills | en | 21/26 | 23/26 | 24/26 |
| 44 skills | nl | 8/12 | 8/12 | 8/12 |
| 94 skills | en | 21/26 | 24/26 | 24/26 |
| 94 skills | nl | 8/12 | 8/12 | 8/12 |
| 185 skills | en | 21/26 | 23/26 | 24/26 |
| 185 skills | nl | 9/12 | 9/12 | 9/12 |

| min_score | Index | Right tips | Wrong tips | Quiet on tasks without a skill |
|---|---|---|---|---|
| 4 | 44 skills | 28/38 | 1/48 | 9/10 |
| 4 | 185 skills | 31/38 | 5/48 | 8/10 |
| 5 | 44 skills | 28/38 | 1/48 | 9/10 |
| 5 | 185 skills | 30/38 | 2/48 | 8/10 |
| 6 | 44 skills | 19/38 | 0/48 | 10/10 |
| 6 | 185 skills | 27/38 | 3/48 | 8/10 |

A right tip names at least one skill that fits the task. A wrong tip names only skills that do not fit, or comes on a task that needs no skill. At 5 the tips stay mostly right on small and large indexes; at 6 the small index loses a third of its tips.

## What the numbers say

- English tasks find their skill in most cases. The misses use words that no description holds: "Where is my iPad?" for `findmy`, "drive from Utrecht to Groningen" for `maps`, "doesn't sound like an AI wrote it" for `humanizer`.
- Dutch tasks only work when they contain an English word or a product name, such as GitHub, PDF, YouTube, Obsidian, arXiv or inbox. "Zet een herinnering" and "vergadernotities" find nothing. A missed tip leaves the turn as Hermes runs it without Polymetis; for a local model it means the session starts at `none`.
- The wrong tips come from words that a skill shares with an unrelated question, such as "music" and "note" in a question about music theory.

## Live set

15 messages that a tester sent to Hermes in live test sessions on 2026-11-24, 13 in English and 2 in Dutch, with the skills that the tester judged to fit: 10 tasks with a skill and 5 without. Four messages that nearly repeated another were left out. Measured on 2026-11-25 with the default `min_score` of 5:

| Index | Language | Top 1 | Top 3 | Top 10 |
|---|---|---|---|---|
| 44 skills | en | 7/8 | 8/8 | 8/8 |
| 44 skills | nl | 0/2 | 1/2 | 2/2 |
| 185 skills | en | 6/8 | 6/8 | 8/8 |
| 185 skills | nl | 0/2 | 0/2 | 2/2 |

| Index | Right tips | Wrong tips | Quiet on tasks without a skill |
|---|---|---|---|
| 44 skills | 6/10 | 1/15 | 4/5 |
| 185 skills | 6/10 | 4/15 | 3/5 |

- "Can you open a PR for this fix?", in English and in Dutch, has only "pr" and "fix" to go on: `github` comes in the top 3 but under `min_score`, so there is no tip.
- A review request with a diff pasted in spreads its score over the words of the diff. With 44 skills `github` stays just under `min_score`; with 185, diff words such as "mean", "order" and "return" tip unrelated skills.
- The Dutch "reviewen" finds no skill, like the Dutch words of the written set.
- Of the tasks without a skill, "add a function, with a test" gets a tip for `test-driven-development`, which is arguable, and with 185 skills also `computer-use`, because "computes" and "computer" share a stem. With 185 skills, reading "a large CSV file" without loading it into "memory" tips `peft`.

## Limits

The written tasks were written by the author of the search, with the skill descriptions at hand, so they flatter it. The search changes of 2026-11-25 were made while looking at the live set: word forms such as "debugging" and "PRs", "pull request" read as "PR", no tails of contractions, no numbers or lower-case single letters, and words that any request uses, such as "read", "file" and "make", as stop words. At the default `min_score` they kept or improved every number of the written set, but the live set flatters the search too; a new set of live messages is the real check. The live set is small and one tester labelled it, so one task moves its numbers by 7 to 10 points. The scores depend on the size of the index, which is why the distractor rows exist. Nothing here says whether a tip helps a model; that needs the live evaluation in `docs/design.md`, which has not been run.
