import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
# The repository root is the plugin, as Hermes installs it: load it as the package `polymetis`.
_spec = importlib.util.spec_from_file_location("polymetis", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
sys.modules["polymetis"] = importlib.util.module_from_spec(_spec)
if sys.version_info >= (3, 11):  # Hermes's side needs 3.11; the Claude Code hook also runs on macOS's own 3.9
    _spec.loader.exec_module(sys.modules["polymetis"])
