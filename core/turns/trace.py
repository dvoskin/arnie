"""Phase-level turn trace (P0.2). Extends the single-line event=turn_trace
with per-stage timings, so "why did it route here?" and "where did the time
go?" are answerable from one greppable stream. Never raises."""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class TurnTrace:
    def __init__(self, tag: str = ""):
        self.tag = tag
        self._t0 = time.monotonic()
        self._last = self._t0

    def transition(self, state) -> None:
        try:
            now = time.monotonic()
            ms = int((now - self._last) * 1000)
            self._last = now
            phase = getattr(state.phase, "value", str(state.phase))
            state.timings_ms[phase] = ms
            lane = getattr(getattr(state.route, "lane", None), "value", "-")
            logger.info(
                f"event=turn_phase {self.tag} turn={state.request.turn_id} "
                f"phase={phase} lane={lane} ms={ms}")
        except Exception:
            pass

    def total_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)
