"""Voice seam-bypass fixes (0802).

The character voice contract (em dash -> comma, ~ -> "about") is enforced at
`platform._sanitize_bubble`, which runs on `|||` BUBBLES. Two surfaces ship text
OUTSIDE that seam and so leaked hand-written em dashes/tildes to iOS raw:

  * `core/receipt.py` build_receipt -> `verdict`/`next` in the card payload
  * `core/reasoning.py` _step -> `label`/`detail` in Response.reasoning

Both now voice their strings at the source. En dash (used for numeric ranges like
55-60) is deliberately preserved, so these assert only em dash + tilde.
"""
from core.reasoning import _step
from core.receipt import _voiced, build_receipt

EM = "—"   # em dash — must be gone
TILDE = "~"     # must become "about"


def test_receipt_voiced_strips_em_dash_and_tilde():
    out = _voiced({"verdict": f"That's logged {EM} nice work", "next": "aim ~ 30g"})
    assert EM not in out["verdict"]
    assert TILDE not in out["next"]


def test_receipt_voiced_leaves_clean_text_alone():
    out = _voiced({"verdict": "You're on pace, nothing to correct."})
    assert out["verdict"] == "You're on pace, nothing to correct."


def test_reasoning_step_voices_label_and_detail():
    s = _step("checkmark.circle", f"Duplicate check {EM} already logged",
              "about ~ 5g off")
    assert EM not in s["label"]
    assert TILDE not in s["detail"]


def test_build_receipt_verdict_carries_no_em_dash():
    # A substantially-over-target log yields a verdict; it ships in the card
    # payload, so it must be voiced by the time build_receipt returns.
    out = build_receipt(calories=900, protein=10, total_cal=3000,
                        total_protein=50, cal_target=2000, protein_target=150,
                        local_hour=20)
    assert "verdict" in out
    assert EM not in out["verdict"]
    if out.get("next"):
        assert EM not in out["next"]
