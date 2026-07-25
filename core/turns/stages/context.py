"""Context assembly.

Delegated turns get their context built inside run_turn(); this stage records
WHAT the turn was given so the manifest exists on every turn, not only native
ones. The omitted list is empty here by construction — legacy assembles a
fixed prompt — and becomes real when per-turn token budgeting lands (P1).
"""
from __future__ import annotations

from core.turns.models import ContextManifest


class LegacyContextStage:
    def __init__(self, system: str = "", messages=None, **_ignored):
        self.system = system or ""
        self.messages = tuple(messages or ())

    async def run(self, request) -> ContextManifest:
        return ContextManifest(
            system_prompt=self.system,
            messages=self.messages,
            user_timezone=(request.metadata or {}).get("user_timezone", "UTC"),
            # Cheap and honest: ~4 characters per token, labelled an estimate
            # rather than reported as a measurement.
            token_estimate=(len(self.system)
                            + sum(len(str(m.get("content", "")))
                                  for m in self.messages
                                  if isinstance(m, dict))) // 4,
            included_sections=("system", "messages"))
