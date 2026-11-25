---
description: Show what Polymetis tipped and which skills Claude loaded, from its log on this machine
disable-model-invocation: true
allowed-tools: Bash(python3:*)
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/claude_code_hook.py" report "${CLAUDE_PLUGIN_DATA}"`

Show the report above to the user exactly as it is, with no comments.
