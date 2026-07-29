"""Record which functions actually RUN, as a pytest plugin.

    python -m pytest tests/ -p scripts.trace_hits -q
    FUNC_HITS_OUT=/tmp/hits.json python -m pytest ...

Static analysis produces candidates; this produces evidence. A symbol the
parser cannot see a caller for and that never executes is a different claim
from one that merely looks unreferenced — and only the first is worth acting
on, which is why nothing in this sprint gets deleted on the static pass alone.

Uses `sys.monitoring` (3.12+) rather than `sys.setprofile`: the callback fires
on PY_START only, costs a dict insert, and can be disabled per-code-object
once seen, so the suite runs at roughly its normal speed instead of the
several-times slowdown a profile hook imposes.

What this evidence does NOT cover, and the report must not pretend otherwise:
a function the tests never reach may still be reached in production. Test
coverage answers "is this exercised here", never "is this dead".
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = pathlib.Path(os.getenv("FUNC_HITS_OUT", ROOT / "func_hits.json"))

_HITS: set = set()
_TOOL = 3          # a free tool id; 0-2 are debugger/coverage/profiler


def _record(code, _offset):
    try:
        path = code.co_filename
        if path.startswith(str(ROOT)):
            _HITS.add(f"{path[len(str(ROOT)) + 1:]}::{code.co_qualname}")
    except Exception:
        pass
    # Seen once is all this asks. Turning the event off for this code object
    # keeps a hot inner loop from paying for a fact already recorded.
    return sys.monitoring.DISABLE


def pytest_configure(config):
    mon = sys.monitoring
    try:
        mon.use_tool_id(_TOOL, "reachability")
    except ValueError:                       # already in use — run unmonitored
        return
    mon.register_callback(_TOOL, mon.events.PY_START, _record)
    mon.set_events(_TOOL, mon.events.PY_START)


def pytest_unconfigure(config):
    mon = sys.monitoring
    try:
        mon.set_events(_TOOL, 0)
        mon.free_tool_id(_TOOL)
    except Exception:
        pass
    OUT.write_text(json.dumps(sorted(_HITS), indent=0))
    print(f"\n  {len(_HITS):,} functions executed -> {OUT}")
