"""The interpreter stops writing prose nobody reads — take two.

`plan.model_say` reaches exactly one consumer, `render_committed` inside
`fallback()`. With FOOD_COMPOSER=true the sentence the user reads is
`compose_async()`'s own, written from the committed snapshot, the shared
persona and the thread. So on every successful turn the interpreter's `say`
and `note` were generated, policed by `enforce_say_contract`, carried through
the plan, and discarded. Measured per field across four real production
responses, narration is 39% of the interpreter's output tokens — and output
tokens are what the user waits on, on the one stage of a food turn that
cannot stream because its output is JSON read programmatically.

THE FIRST ATTEMPT AT THIS SHIPPED A REGRESSION (f3aa3be, reverted 99f330a),
and this file exists mostly because of how it failed. The mute instruction
said:

    Your entire output is the decision and the rows.

and sat directly beneath DECIDE BEFORE YOU WRITE, the rule that chooses ask
over log. An ask's output is decision + rows + `points` + `ready` +
`ambiguities` + `context`, so the strongest adjacency in the prompt told the
model to drop the last four. Empty `points` means no question can be built;
a doubted cucumber was logged at a portion nobody chose, and a material one
left the lane entirely.

Two things are different now, and both are asserted below rather than
described:

  * The instruction lives in the OUTPUT CONTRACT at the top, where the model
    forms its output shape — not beside a decision rule it has nothing to do
    with. `test_the_mute_instruction_is_nowhere_near_the_ask_rule` pins the
    distance.
  * It names only the two fields it removes and says explicitly that
    everything else is unchanged. A negative instruction has to be bounded or
    the model bounds it. `test_the_muted_build_still_demands_…` pins that.

Underneath, `_ask_becomes_log` (58f4d82) means the same failure would now
degrade in-lane instead of handing the turn to legacy. This is the prompt
half; that was the structural half.
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

#: The fields an ask is MADE of. Losing any one of them is the regression.
STRUCTURAL = ("points", "ambiguities", "ready", "context", "items",
              "follow_up")


# ── the regression, pinned two ways ──────────────────────────────────────────
@pytest.mark.parametrize("field", STRUCTURAL)
def test_the_muted_build_still_demands_every_structural_field(field):
    """What f3aa3be took away. A prompt that removes narration must remove
    ONLY narration."""
    assert f'"{field}"' in MUTED


def test_the_muted_build_says_the_other_fields_are_unchanged():
    """The bound on the negative instruction. Without it the model decides
    for itself how far "emit no say" reaches, and last time it reached four
    fields too far."""
    flat = " ".join(MUTED.split())
    assert "EVERY OTHER FIELD IS UNCHANGED" in flat
    for field in ("points", "ready", "ambiguities", "context"):
        assert field in flat.split("EVERY OTHER FIELD IS UNCHANGED")[1][:400]


def test_the_mute_instruction_is_nowhere_near_the_ask_rule():
    """Placement was half the bug. The instruction belongs where the model
    forms its OUTPUT SHAPE, not adjacent to the rule that decides whether to
    ask — the strongest adjacency in a prompt is a real force."""
    mute_at = MUTED.index("You do NOT write the reply")
    ask_at = MUTED.index("DECIDE BEFORE YOU WRITE")
    assert mute_at < MUTED.index("Pick exactly one action"), (
        "the mute instruction drifted out of the output contract")
    assert ask_at - mute_at > 5000, (
        "the mute instruction is back beside the ask/log decision")


def test_the_muted_build_never_claims_the_output_is_only_rows():
    """The exact sentence that caused it, banned by name."""
    assert "entire output is the decision and the rows" not in MUTED


# ── the two builds ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("spec", NARRATION_SPEC)
def test_the_escape_hatch_still_asks_for_prose(spec):
    assert spec in NARRATE


@pytest.mark.parametrize("spec", NARRATION_SPEC)
def test_the_narration_spec_is_removed_not_contradicted(spec):
    """A spec saying "1-2 warm sentences" beside "emit no say" is a conflict
    the model has to resolve, and it will sometimes resolve it expensively."""
    assert spec not in MUTED


def test_no_marker_reaches_the_model():
    for build in (NARRATE, MUTED):
        assert "[[" not in build
        assert "SAY]]" not in build and "MUTE]]" not in build


def test_every_marker_is_balanced():
    opens = len(re.findall(r"\[\[(?:SAY|MUTE)", FT._SYSTEM))
    closes = len(re.findall(r"(?:SAY|MUTE)\]\]", FT._SYSTEM))
    assert opens == closes, f"{opens} opened, {closes} closed"


def test_the_action_examples_are_still_valid_json_without_say():
    """Three of the five `say` clauses sit mid-JSON. Removing one has to take
    its comma with it or the examples teach malformed output."""
    found = 0
    for m in re.finditer(r'\{"action":.*?\}\n', MUTED):
        frag = re.sub(r"\{[a-z_]+\}", "0", m.group(0).strip())
        json.loads(frag)
        assert '"say"' not in frag
        found += 1
    assert found == 5, f"expected 5 action examples, read {found}"


def test_follow_up_survives_the_cut():
    """An enum token, not prose — and the only one of the three the fallback
    path can still turn into something the user sees."""
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
    text = render_committed("", "", "save_as_regular", SNAP)
    assert "save that as one of your regulars" in text.split("|||")[-1]
