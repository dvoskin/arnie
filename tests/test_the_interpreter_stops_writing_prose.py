"""The interpreter stops writing prose nobody reads.

`plan.model_say` is consumed in exactly one place — `render_committed` inside
`fallback()`. With `FOOD_COMPOSER=true` the sentence the user actually reads is
`compose_async()`'s own, written from the committed snapshot, the shared
persona and the thread. So on every successful turn the interpreter's `say`
and `note` were generated, policed by `enforce_say_contract`, carried through
the plan, and thrown away.

That is not free. Measured across four real production responses (the Takis
turn, the cheeseburger-and-apple turn, the double-cheeseburger correction and
the rice cake), `say` was **43% of the interpreter's output tokens** — and
output tokens are what the user sits and waits for. The interpreter's pass is
the largest single block in a food turn and it cannot stream, because its
output is JSON consumed programmatically.

So when the composer is on, the interpreter is told plainly that it does not
write the reply, and the prompt's narration spec is removed rather than
contradicted — a spec that says "1-2 warm sentences naming every item" sitting
next to "emit no say" is an instruction the model has to resolve, and it will
sometimes resolve it the expensive way.

What must survive the cut:

  * With the composer OFF the prompt is unchanged, byte for byte. That path is
    the escape hatch; it still writes its own prose.
  * `follow_up` stays in both builds. It is a single enum token rather than
    prose, so it costs nothing, and it is the only one of the three the
    fallback can still act on.
  * An empty `say` degrades to a complete, correct reply — the tokenized line
    from `enforce_say_contract`, or `_deterministic_line` from the snapshot.
    Neither invents a number; both name the items.
"""
import json
import re

import pytest

import core.food_turn as FT
from core.food_ledger import TransactionSnapshot, render_committed

NARRATE = FT._interpreter_system(narrate=True)
MUTED = FT._interpreter_system(narrate=False)

#: Phrases that exist only to make the interpreter write a sentence.
NARRATION_SPEC = ("the coach line the user sees",
                  'Optional "note"',
                  'update "say" starts',
                  "{batch_protein}g protein combined",
                  "Sound like a sharp coach texting")


# ── marker hygiene ───────────────────────────────────────────────────────────
def test_no_marker_reaches_the_model():
    """The failure mode of a marked-up prompt is an unbalanced marker leaking
    `[[SAY` into the system prompt, where it reads as noise the model has to
    interpret. Cheap to catch, invisible in production."""
    for build in (NARRATE, MUTED):
        assert "[[" not in build
        assert "SAY]]" not in build and "MUTE]]" not in build


def test_every_marker_is_balanced():
    opens = len(re.findall(r"\[\[(?:SAY|MUTE)", FT._SYSTEM))
    closes = len(re.findall(r"(?:SAY|MUTE)\]\]", FT._SYSTEM))
    assert opens == closes, f"{opens} opened, {closes} closed"


# ── the composer-off build is the prompt that shipped ────────────────────────
@pytest.mark.parametrize("spec", NARRATION_SPEC)
def test_the_escape_hatch_still_asks_for_prose(spec):
    assert spec in NARRATE


def test_the_escape_hatch_still_shows_say_in_its_examples():
    assert NARRATE.count('"say":') == 4


# ── the composer-on build asks for none of it ────────────────────────────────
@pytest.mark.parametrize("spec", NARRATION_SPEC)
def test_the_narration_spec_is_gone_not_contradicted(spec):
    assert spec not in MUTED


def test_the_muted_build_says_who_writes_the_reply():
    assert "YOU DO NOT WRITE THE REPLY" in MUTED


def test_the_action_examples_are_still_valid_json_without_say():
    """Three of the five `say` clauses sit mid-JSON. Removing one has to take
    its comma with it or the examples teach malformed output."""
    found = 0
    for m in re.finditer(r'\{"action":.*?\}\n', MUTED):
        frag = re.sub(r"\{[a-z_]+\}", "0", m.group(0).strip())
        json.loads(frag)          # raises if the comma was left behind
        assert '"say"' not in frag
        found += 1
    assert found == 5, f"expected 5 action examples, read {found}"


def test_follow_up_survives_the_cut():
    """An enum token, not prose — and the only one of the three that the
    fallback path can still turn into something the user sees."""
    assert '- Optional "follow_up":"save_as_regular"' in MUTED


def test_muting_removes_instruction_rather_than_adding_it():
    assert len(MUTED) < len(NARRATE)


# ── an empty say still produces a correct reply ──────────────────────────────
CALLS = [{"input": {"food_name": "Rice cake", "quantity": "1 cake"}},
         {"input": {"food_name": "Greek yogurt", "quantity": "1 cup"}}]


def test_an_empty_say_names_every_item_it_wrote():
    line = FT.enforce_say_contract("", CALLS)
    assert "Rice cake" in line and "Greek yogurt" in line


def test_an_empty_say_carries_no_number_of_its_own():
    """Every figure is a token the ledger fills from the committed day. The
    contract is unchanged by this cut — it was always the floor."""
    line = FT.enforce_say_contract("", CALLS)
    assert not re.findall(r"\d", re.sub(r"\{[a-z_]+\}", "", line))
    for token in ("{batch_cal}", "{batch_protein}", "{day_cal}", "{cal_left}"):
        assert token in line


SNAP = TransactionSnapshot(batch_cal=350, batch_protein=25, day_cal=1450,
                           day_protein=95, cal_target=2200, protein_target=160,
                           logged=("Rice cake", "Greek yogurt"))


def test_the_fallback_reads_the_committed_day_when_there_is_no_prose():
    text = render_committed("", "", "", SNAP)
    assert "Rice cake and Greek yogurt logged, 350 cal and 25g protein." in text
    assert "You're at 1450 with 750 left and 65g protein to go." in text


def test_the_fallback_can_still_offer_the_regular():
    """The reason `follow_up` was kept: with `say` and `note` gone this bubble
    is the only thing the interpreter still contributes to the fallback."""
    text = render_committed("", "", "save_as_regular", SNAP)
    assert text.count("|||") == 1
    assert "save that as one of your regulars" in text.split("|||")[1]
