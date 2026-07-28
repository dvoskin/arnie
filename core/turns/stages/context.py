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
        # `token_estimate` is COMPUTED LAZILY (see `ContextManifest`). It walked
        # the whole message list on every turn — the general lane's prompt plus
        # the thread — for a field nothing has ever read. The manifest is the
        # seed of per-turn token budgeting (P1) and stays; paying for it before
        # that exists does not.
        return ContextManifest(
            system_prompt=self.system,
            messages=self.messages,
            user_timezone=(request.metadata or {}).get("user_timezone", "UTC"),
            included_sections=("system", "messages"))
