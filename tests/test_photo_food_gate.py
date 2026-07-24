"""Photo [FOOD_LOG] blocks ride the structured logger (task #26) — the prod
phantom of 2026-07-24: a photo turn narrated a log that never fired."""
from core.conversation import photo_food_message

CAPP = ("[Photo received]\n\n[FOOD_LOG]\nINTENT: log\n"
        "PACKAGED: Starbucks Venti Hot Cappuccino, whole milk, extra hot, "
        "2 Splenda, 1 venti cup (24 fl oz), ? cal, ?g P, ?g C, ?g F\n"
        "CONFIDENCE: 0.55\n[/FOOD_LOG]")


def test_photo_log_block_synthesizes_logger_message():
    msg = photo_food_message(CAPP)
    assert msg is not None and msg.startswith("I had ")
    assert "Starbucks Venti Hot Cappuccino" in msg
    assert "venti cup" in msg
    assert "?" not in msg          # unknown-macro tail stripped


def test_non_log_intents_and_text_turns_pass_through():
    assert photo_food_message("I had a barebells bar") is None
    assert photo_food_message(CAPP.replace("INTENT: log", "INTENT: question")) is None
    diary = "[Photo received]\n[FOOD_DIARY]\nMEALS: ...\n[/FOOD_DIARY]"
    assert photo_food_message(diary) is None


def test_multi_item_photo_joins_items():
    block = ("[FOOD_LOG]\nINTENT: log\n"
             "ITEM: Grilled chicken breast, 6 oz, ~280 cal, 50g P\n"
             "ITEM: White rice, 1 cup, ~200 cal\n[/FOOD_LOG]")
    msg = photo_food_message(block)
    assert "chicken breast" in msg and "White rice" in msg and ";" in msg
