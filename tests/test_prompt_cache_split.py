"""Prompt-cache split — the static system prompt must be its own cacheable block,
separate from the per-turn dynamic context, so Anthropic's prefix cache actually
hits (the old single-block form glued the ever-changing context onto the cached
prefix, invalidating it every turn)."""
from core.llm import CACHE_BREAK, _split_system_for_cache


def test_split_is_byte_identical_and_strips_marker():
    static = "You are Arnie. " * 50          # stands in for the ~38k-token prompt
    context = "[TODAY] 1800 cal · [WEARABLE] recovery 62"
    system = f"{static}{CACHE_BREAK}{context}"

    prefix, suffix = _split_system_for_cache(system)
    # concatenation equals the original `static + "\n\n" + context` exactly
    assert prefix + suffix == f"{static}\n\n{context}"
    # the marker never survives into either block (so it can't reach the API)
    assert CACHE_BREAK not in prefix and CACHE_BREAK not in suffix
    # the static prefix (the cached part) is isolated and ends with the separator
    assert prefix == static + "\n\n"
    assert suffix == context


def test_no_marker_falls_back_to_single_block():
    # onboarding / reflect / repair systems carry no marker → whole thing cached
    prefix, suffix = _split_system_for_cache("a plain system prompt")
    assert prefix is None
    assert suffix == "a plain system prompt"


def test_static_prefix_is_stable_across_turns():
    # Same static prompt + DIFFERENT context each turn must yield the SAME cached
    # prefix (that's the whole point — the prefix is what Anthropic caches).
    static = "STATIC PROMPT"
    p1, _ = _split_system_for_cache(f"{static}{CACHE_BREAK}context turn 1")
    p2, _ = _split_system_for_cache(f"{static}{CACHE_BREAK}totally different turn 2")
    assert p1 == p2 == static + "\n\n"
