"""Response assembly — bubble splitting + the em-dash sanitizer (a hard brand rule
the model keeps breaking, enforced deterministically on the way out)."""
from core.platform import Response


def test_em_dash_replaced_with_comma():
    r = Response.from_text("you're at 840 — protein's strong, keep it up")
    assert "—" not in " ".join(r.bubbles)
    assert r.bubbles == ["you're at 840, protein's strong, keep it up"]


def test_em_dash_stripped_across_bubbles():
    r = Response.from_text("logged it — nice pick.|||you're at 1,840 — basically there.")
    joined = " ".join(r.bubbles)
    assert "—" not in joined
    assert len(r.bubbles) == 2
    assert r.bubbles[0] == "logged it, nice pick."


def test_hyphen_ranges_survive():
    # number ranges use a hyphen, not an em dash — must NOT be touched
    r = Response.from_text("you're probably 12-13% body fat, 8-15 lbs to go")
    assert r.bubbles == ["you're probably 12-13% body fat, 8-15 lbs to go"]


def test_empty_text_is_not_a_dead_end():
    r = Response.from_text("")
    assert r.bubbles and r.bubbles[0] != "done."
    assert "what's the move" in r.bubbles[0].lower()


def test_double_spaces_collapsed_after_strip():
    r = Response.from_text("nice — clean day")
    assert "  " not in r.bubbles[0]
    assert r.bubbles[0] == "nice, clean day"
