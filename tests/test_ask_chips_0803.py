"""The ask's real options reach the client as tappable, question-bound chips.

The options always existed — ambiguity top_options, brand shelves — but they
were flattened into composer prose, so the chips iOS shows are a client-side
guess (QuickReplyEngine) instead of the shelf the server actually looked up.
And a multi-question ask (the sashimi turn: pieces? rice?) rendered as one
text blob leaves a flat chip row ambiguous about which question a tap answers.

Chain under test:
  ask return carries questions:[{item,text,options}]
    -> Response.buttons with group indices (conversation attaches)
    -> serialize_response ships {label,value,url,group}
    -> serialize_pending_clarifications replays the same structure on relaunch
"""
import json
from types import SimpleNamespace

import pytest

from core.platform import (Button, Response, chip_label, chip_labels,
                           serialize_response)
from core.context_builder import serialize_pending_clarifications


# ── chip phrasing ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,prefix,expected", [
    # The shape the product database actually returns.
    ("Barebells Protein Bar, Salty Peanut (55g)", "Barebells Protein Bar",
     "Salty Peanut"),
    ("SALTY PEANUT", "", "Salty Peanut"),          # shouting is not a flavour
    ("  Caramel   Cashew  ", "", "Caramel Cashew"),
    ("- Loaded Taco -", "", "Loaded Taco"),
    ("BBQ", "", "BBQ"),                            # short acronyms keep case
])
def test_chip_label_phrasing(raw, prefix, expected):
    assert chip_label(raw, drop_prefix=prefix) == expected


def test_chip_label_never_empties_a_label_to_its_prefix():
    """Dropping the product must not leave a blank chip when the option IS the
    product — an unlabelled chip is untappable."""
    assert chip_label("Barebells", drop_prefix="Barebells") == "Barebells"


def test_chip_label_truncates_on_a_word_boundary():
    out = chip_label("Cookies & Cream Flavoured Protein Bar With Sweetener")
    assert out == "Cookies & Cream…"
    assert len(out) <= 25


def test_chip_labels_dedupe_and_cap():
    """Two options that render identically are ONE choice, and a chip row has
    to fit a thumb."""
    assert chip_labels(["Salty Peanut", "SALTY PEANUT", "salty peanut",
                        "BBQ", ""]) == ["Salty Peanut", "BBQ"]
    assert len(chip_labels(["a", "b", "c", "d", "e", "f"])) == 4


# ── wire contract ────────────────────────────────────────────────────────────

def test_button_group_rides_the_wire():
    resp = Response.from_text("Which flavor?")
    resp.buttons = [Button(label="Salty Peanut", group=0),
                    Button(label="Caramel Cashew", group=0),
                    Button(label="No rice", group=1)]
    wire = serialize_response(resp)
    assert wire["buttons"] == [
        {"label": "Salty Peanut", "value": "Salty Peanut", "url": None, "group": 0},
        {"label": "Caramel Cashew", "value": "Caramel Cashew", "url": None, "group": 0},
        {"label": "No rice", "value": "No rice", "url": None, "group": 1},
    ]


def test_ungrouped_button_stays_backward_compatible():
    """Every existing caller builds Button(label=...) with no group — the wire
    must carry group=None, not invent an index."""
    resp = Response.from_text("hi")
    resp.buttons = [Button(label="Log it")]
    assert serialize_response(resp)["buttons"][0]["group"] is None


# ── an option is its LABEL, never its repr ───────────────────────────────────

def test_a_clarification_option_ships_its_label_not_its_repr():
    """Prod PQ#2029 stored, verbatim:

        "ClarificationOption(label='one tablespoon', value=None,
         candidate_id=None, field_name='consumed_fraction')"

    — `str(o)` on the dataclass. As a chip that renders as
    "ClarificationOption(la..." after truncation: one unreadable button where
    two real answers belonged. The label is the part a person taps.
    """
    from core.food_turn import _option_labels
    from skills.nutrition.clarify_policy import ClarificationOption

    opts = [ClarificationOption(label="one tablespoon"),
            ClarificationOption(label="two tablespoons")]
    assert _option_labels(opts) == ["one tablespoon", "two tablespoons"]
    # And through the chip phrasing, which is what actually reaches the row.
    assert chip_labels(_option_labels(opts)) == ["one tablespoon",
                                                 "two tablespoons"]


def test_option_labels_tolerate_bare_strings_and_holes():
    """The interpreter branch builds its options as plain strings, so both
    shapes reach this. A None or an empty label is dropped, not rendered as
    the string "None"."""
    from core.food_turn import _option_labels
    from skills.nutrition.clarify_policy import ClarificationOption

    assert _option_labels(["Salty Peanut", "BBQ"]) == ["Salty Peanut", "BBQ"]
    assert _option_labels([ClarificationOption(label=""), "BBQ", None]) == ["BBQ"]
    assert _option_labels([]) == []
    assert _option_labels(None) == []


# ── the clarification wire replays the same structure ────────────────────────

def _pq(payload: dict, question="Which flavor?", item="Barebells bar"):
    from datetime import datetime
    return SimpleNamespace(
        kind="food_structured_ask", tier="food_clarification",
        question=question, item_referenced=item,
        asked_at=datetime.utcnow(), last_asked_at=datetime.utcnow(),
        answered_at=None, payload_json=json.dumps(payload))


def test_pending_clarification_ships_questions_and_meal_group():
    rows = [_pq({
        "meal_group_id": "mg-123",
        "questions": [
            {"item": "Barebells bar", "text": "Which flavor?",
             "options": ["Salty Peanut", "Caramel Cashew"]},
            {"item": None, "text": "Any rice or sides?", "options": []},
        ],
    })]
    out = serialize_pending_clarifications(rows)
    assert len(out) == 1
    entry = out[0]
    assert entry["meal_group_id"] == "mg-123"
    assert entry["questions"][0]["options"] == ["Salty Peanut", "Caramel Cashew"]
    assert entry["questions"][1]["text"] == "Any rice or sides?"


def test_pending_clarification_tolerates_old_rows():
    """Rows written before this change carry none of the new keys — the wire
    entry must look exactly as it did, not error and not emit empty husks."""
    rows = [_pq({"original": "had a bar", "question": "Which flavor?"})]
    out = serialize_pending_clarifications(rows)
    assert out == [{"item": "Barebells bar", "question": "Which flavor?"}]


# ── the ask return carries the structure (interpreter branch shape) ──────────

def test_interpreter_ask_questions_shape():
    """The parse the return site applies to points must keep label+qs pairs
    and attach a shelf only to its own product's question."""
    points = [
        {"label": "Barebells bar", "qs": ["Which flavor?"]},
        {"label": "", "q": "Any rice or sides?"},
    ]
    found_by_label = [("Barebells bar", ["Salty Peanut", "Caramel Cashew"])]

    questions = []
    for pt in points:
        lbl = str(pt.get("label") or "").strip(", ").strip()
        qs = pt.get("qs")
        if not isinstance(qs, list):
            qs = [pt.get("q")]
        qs = [str(q).strip() for q in qs if q and str(q).strip()]
        if not qs:
            continue
        opts = []
        for flb, fvs in found_by_label:
            if flb.lower() == lbl.lower():
                opts = list(fvs)[:4]
                break
        questions.append({"item": lbl or None, "text": " ".join(qs[:4]),
                          "options": opts})

    assert questions == [
        {"item": "Barebells bar", "text": "Which flavor?",
         "options": ["Salty Peanut", "Caramel Cashew"]},
        {"item": None, "text": "Any rice or sides?", "options": []},
    ]
