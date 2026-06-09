from api.app import AppleHealthPayload


def test_apple_health_payload_accepts_shortcuts_newline_numbers():
    payload = AppleHealthPayload(
        steps="2376\n0",
        active_calories="",
        resting_hr="",
    )

    assert payload.steps == 2376
    assert payload.active_calories is None
    assert payload.resting_hr is None


def test_apple_health_payload_sums_shortcuts_quantity_lists():
    payload = AppleHealthPayload(
        steps=["1200", "300.4"],
        active_calories="10.5\n2",
        resting_hr="0\n58",
    )

    assert payload.steps == 1500
    assert payload.active_calories == 12.5
    assert payload.resting_hr == 58.0
