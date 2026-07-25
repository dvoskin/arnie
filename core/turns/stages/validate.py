"""Policy validation. Phase 1: a delegation plan is always approved for
execution — the legacy pipeline carries its own policy. Native lanes replace
this with the deterministic policy engine (core/food_ledger)."""
from __future__ import annotations

from core.turns.models import ValidationResult


class LegacyValidationStage:
    async def run(self, request, context=None, route=None, plan=None) -> ValidationResult:
        return ValidationResult(disposition="execute",
                                approved_operations=(),
                                policy_version="legacy-adapter-v1")
