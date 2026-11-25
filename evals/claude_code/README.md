# Polymetis in Claude Code: measurements

The numbers in the main README's Claude Code section come from these scripts. They run on your own installed skills, so your numbers will differ.

1. `offline.py TASKS PLUGIN_DIR LISTING`: what Polymetis would tip for each task, without a model and for free. `LISTING` is a file in `listings/` in Polymetis's data folder: the skill list that Claude Code last showed in one project folder. Add `--grid` to try other thresholds.
2. `run_ab.py ab.json PLUGIN_DIR OUT --repeat 2`: runs a short warm-up prompt, so that Polymetis sees the folder's skill list, then each task with `claude -p` in that empty folder, with and without the plugin. This costs plan usage: about $0.30 a run on Sonnet.
3. `summarize.py ab.json OUT DATA_DIR`: the skills each run loaded, the tip it got, its cost and turns.
4. `judge.py ab.json OUT`: a blind comparison of each pair of answers by Opus, in both orders.

`offline.json` holds 48 tasks, 12 of them with no fitting skill; `ab.json` holds 14 tasks with their inputs. The `ok` field lists the skills that fit a task.
