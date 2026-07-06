"""Prompt pin: scanned/label nutrition data is exempt from the bias-high rules.

Prod regression (Danny, 2026-07-06): a barcode scan of FAGE Total 2% carried
the exact label (100 kcal / 14g protein per 150g), but the FOOD_ACCURACY
bias-high + reality-check-floor machinery overrode it — the model logged
300 cal / 30g "using FAGE's actual full label … rather than what you scanned."
The barcode rule already said "trust it fully"; the accuracy section needed the
explicit carve-out so the two never conflict."""
from core.prompts.arnie import build_arnie_system


def test_prompt_exempts_label_data_from_bias_high():
    s = build_arnie_system("telegram")
    assert "LABEL DATA IS EXEMPT FROM EVERY BIAS-HIGH RULE" in s


def test_prompt_forbids_correcting_scanned_values():
    s = build_arnie_system("telegram")
    assert 'NEVER "correct" scanned values' in s
    assert "the user is\nholding the container" in s or \
        "the user is holding the container" in s


def test_barcode_uncertainty_resolves_via_portion_question_not_macros():
    """A scan's only unknown is how much was eaten. Multi-serving containers earn
    ONE portion question; single-serve logs directly; macro inflation is never
    the resolution for portion doubt."""
    s = build_arnie_system("telegram")
    assert "the bias-high accuracy rules do NOT\n    apply" in s \
        or "the bias-high accuracy rules do NOT apply" in s
    assert "MULTI-SERVING container" in s
    assert "NEVER resolve\n        portion doubt by inflating macros" in s \
        or "NEVER resolve portion doubt by inflating macros" in s
