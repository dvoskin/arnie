"""Two waits a food turn took because of the order things were written in.

Neither is a decision changing. Both are the user watching a dot.
"""
import pytest


# ── the gate asked the model before it asked the free signals ────────────────
def test_the_free_food_signals_are_evaluated_before_the_model_gate():
    """The gate was an `or` chain that awaited Haiku THIRD:

        prior · photo · AWAIT food_relevance · board+destructive · thread

    `or` short-circuits, so a turn that is food because the thread is active —
    or because the board plus a destructive verb say so — paid a model round
    trip to be told something two free terms already knew, and only then could
    the "Logging…" indicator morph.
    """
    import inspect
    import core.conversation as C
    source = inspect.getsource(C)
    free = source.index("_food_now = bool(_sft_prior is not None")
    gated = source.index("elif not (_food_now")
    assert free < gated, "the free signals must be settled before the gate"
    # ...and the model call is now the last resort rather than the third term.
    assert "or await _sft_relevant(_user_text or \"\"," in source[gated:gated + 400]


def test_the_indicator_fires_on_the_free_signals_not_after_the_model():
    import inspect
    import core.conversation as C
    source = inspect.getsource(C)
    fire = source.index("and _food_now\n                    and on_tool_start")
    gated = source.index("elif not (_food_now")
    assert fire < gated
    # The cold-start fire below must not double-announce.
    assert "if on_tool_start and \"log_food\" not in _announced:" in source


def test_nothing_announces_logging_on_a_turn_that_is_not_food():
    """Every term in the early fire is a signal that ALREADY says food — which
    is exactly why the model call can be skipped on it. Firing the indicator on
    anything weaker would be a promise the turn cannot keep."""
    import inspect
    import core.conversation as C
    source = inspect.getsource(C)
    block = source[source.index("_food_now = bool("):]
    block = block[:block.index(")\n")]
    for term in ("_sft_prior is not None", "_photo_food is not None",
                 "_route_mid", "_sft_dest"):
        assert term in block
    assert "_sft_relevant" not in block, "the model gate is not a free signal"


# ── the web-label lane ran behind USDA and OFF instead of beside them ────────
@pytest.mark.asyncio
async def test_the_web_label_lane_is_prewarmed_for_a_single_item(monkeypatch):
    """`_fetch_usda_off` overlapped USDA with OFF and items with each other, and
    left the web lane out — so it ran AFTER both, inline, per item. On the 18:23
    turn that was the lane that answered, and enrichment was 5.1 s of a 16 s
    turn.

    Deliberately NOT gated on the two-item rule the USDA/OFF fan-out uses: this
    is not overlapping items with each other, it is overlapping a lane that
    starts only once two others have finished, so one item is enough."""
    import handlers.tool_executor as TE

    calls = []

    async def _fake_web(food_name, quantity):
        calls.append((food_name, quantity))
        return {"per100g": {"calories": 400}, "_match": 0.9}

    monkeypatch.setattr(TE, "_web_lookup_packaged", _fake_web)
    token = TE._WEB_LABEL_PREFETCH.set({})
    try:
        await TE._prewarm_enrichment([
            {"name": "log_food",
             "input": {"food_name": "Barebells Salty Peanut Bar",
                       "is_packaged": True, "quantity": "1 bar"}}])
        assert calls == [("Barebells Salty Peanut Bar", "1 bar")]
        assert TE._WEB_LABEL_PREFETCH.get()
    finally:
        TE._WEB_LABEL_PREFETCH.reset(token)


@pytest.mark.asyncio
async def test_a_prewarmed_miss_is_an_answer_and_is_not_re_asked(monkeypatch):
    """A product with no readable label is a stable fact for the length of a
    turn. An EXCEPTION is not — that is "we do not know", and the inline call
    still gets its chance."""
    import handlers.tool_executor as TE

    async def _missing(food_name, quantity):
        return None

    async def _broken(food_name, quantity):
        raise RuntimeError("tavily down")

    for fetch, expect_cached in ((_missing, True), (_broken, False)):
        monkeypatch.setattr(TE, "_web_lookup_packaged", fetch)
        token = TE._WEB_LABEL_PREFETCH.set({})
        try:
            await TE._prewarm_enrichment([
                {"name": "log_food",
                 "input": {"food_name": "Royo Everything Bagel",
                           "is_packaged": True}}])
            cached = TE._WEB_LABEL_PREFETCH.get()
            assert bool(cached) is expect_cached, fetch.__name__
        finally:
            TE._WEB_LABEL_PREFETCH.reset(token)


def test_the_consumer_prefers_the_prewarmed_answer():
    import inspect
    import handlers.tool_executor as TE
    source = inspect.getsource(TE.fetch_candidates)
    assert "_wl_cache = _WEB_LABEL_PREFETCH.get()" in source
    assert "web = _wl_cache[name_norm]" in source
    # Same function, same arguments -> a prewarmed answer is byte-identical to
    # the inline one. This is a question of WHEN the round trip was paid.
    assert "web = await _web_lookup_packaged(food_name, inp.get(\"quantity\"))" \
        in source


def test_generic_foods_are_still_left_out_of_the_web_lane():
    """The web lane is a label lookup. A generic has no label, and asking is
    both slow and a source of wrong-product answers."""
    import inspect
    import handlers.tool_executor as TE
    source = inspect.getsource(TE._prewarm_enrichment)
    assert "is_generic_food_name(fn)" in source
    assert "_web_names = [nn for nn in names if plan[nn][1]]" in source
