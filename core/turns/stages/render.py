"""Rendering. Phase 1: the legacy pipeline already produced the Response, so
this stage surfaces it. Native lanes render from the committed snapshot."""
from __future__ import annotations


class PassthroughRenderStage:
    async def run(self, request, context=None, route=None, plan=None,
                  validation=None, snapshot=None):
        execution = getattr(snapshot, "execution", None)
        return getattr(execution, "response", None) or execution
