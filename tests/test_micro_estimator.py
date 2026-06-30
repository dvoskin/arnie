"""The LLM micro-estimate fallback's parser: clean {key: amount}, drop junk and
hallucinated absurdities. The network call itself isn't unit-tested."""
from core.micro_estimator import _parse_estimate


def test_parses_clean_json():
    out = _parse_estimate('{"potassium": 420, "vitamin_c": 9, "vitamin_b6": 0.4}')
    assert out == {"potassium": 420.0, "vitamin_c": 9.0, "vitamin_b6": 0.4}


def test_tolerates_code_fences():
    out = _parse_estimate('```json\n{"iron": 2.0}\n```')
    assert out == {"iron": 2.0}


def test_drops_unknown_keys_zero_bool_and_absurd():
    # unknown key ignored; zero/negative dropped; bool dropped; >300% DV dropped
    out = _parse_estimate(
        '{"calcium": 120, "made_up": 5, "iron": 0, "zinc": -1, '
        '"vitamin_d": true, "potassium": 99999}'
    )
    assert out == {"calcium": 120.0}


def test_bad_input_returns_none():
    assert _parse_estimate("not json") is None
    assert _parse_estimate("[1,2,3]") is None
    assert _parse_estimate("{}") is None
    assert _parse_estimate("") is None
