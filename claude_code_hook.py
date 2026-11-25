"""Claude Code runs this file for each of Polymetis's hooks: ``python3 claude_code_hook.py <event>``."""

import sys
import types
from pathlib import Path

# the plugin's folder is the package `polymetis`, whatever Claude Code named the folder; without its __init__,
# which loads the Hermes side, so that this also runs on the Python 3.9 that macOS ships
_package = types.ModuleType("polymetis")
_package.__path__ = [str(Path(__file__).resolve().parent)]
sys.modules["polymetis"] = _package

from polymetis import claude_code  # noqa: E402

if __name__ == "__main__":
    sys.exit(claude_code.main(sys.argv[1:]))
