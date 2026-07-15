#!/usr/bin/env python3
"""One-shot prod backfill: classify NULL food_entries.processing_level.

77% of food_entries predate the processing_level column; the health score's
keyword fallback is English-only and (pre-fix) defaulted no-match to
"processed", which scored whole-food days (esp. Russian-language users) as
processed_pct=100. This classifies every distinct NULL name once via Haiku
(NOVA-ish rubric, same as the log_food tool guidance) and updates by name.

READ-COUNT → CLASSIFY → UPDATE. Idempotent: only touches NULL rows.
Run: DATABASE_URL=... ANTHROPIC_API_KEY=... python scripts/backfill_processing_level.py
"""
import json
import os
import re
import sys

from dotenv import load_dotenv

load_dotenv(os.environ.get("ENV_FILE", ".env"), override=False)

from anthropic import Anthropic                      # noqa: E402
from sqlalchemy import create_engine, text           # noqa: E402

url = os.environ["DATABASE_URL"]
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)
eng = create_engine(url, pool_pre_ping=True)
client = Anthropic()

RUBRIC = """Classify each food by HOW IT IS MADE (NOVA-style), not how healthy it sounds:
- whole: unprocessed/minimally processed — meat, fish, eggs, fruit, vegetables, rice, potatoes, oats, plain dairy, scratch-cooked dishes (baked chicken, omelet, steamed rice)
- processed: processed staples — bread, cheese, deli meat, protein bars/powder, canned goods, sandwiches/wraps/sushi, restaurant plates
- ultra_processed: formulated industrial products — soda, candy, chips, fast food, packaged desserts, instant noodles, energy drinks

Names may be in any language (Russian is common) — classify by meaning.
Reply with ONLY a JSON object mapping each input name EXACTLY as given to one of: "whole", "processed", "ultra_processed"."""


def classify(names: list[str]) -> dict:
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        thinking={"type": "disabled"},
        messages=[{"role": "user",
                   "content": RUBRIC + "\n\nNames:\n" + json.dumps(names, ensure_ascii=False)}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    return json.loads(m.group(0)) if m else {}


def main():
    with eng.connect() as c:
        names = [r[0] for r in c.execute(text(
            "select distinct parsed_food_name from food_entries "
            "where processing_level is null and parsed_food_name is not null "
            "and length(parsed_food_name) > 0 order by 1"))]
    print(f"{len(names)} distinct names to classify")

    BATCH = 40
    total_classified = updated = 0
    for i in range(0, len(names), BATCH):
        chunk = names[i:i + BATCH]
        try:
            got = classify(chunk)
        except Exception as e:
            print(f"  batch {i//BATCH}: classify failed ({e}); skipping", flush=True)
            continue
        # Commit PER BATCH — a killed run keeps its progress and the script
        # is rerunnable (only NULL rows are ever touched).
        with eng.begin() as c:
            for k, v in got.items():
                if k in chunk and v in ("whole", "processed", "ultra_processed"):
                    total_classified += 1
                    r = c.execute(text(
                        "update food_entries set processing_level = :lvl "
                        "where processing_level is null and parsed_food_name = :name"),
                        {"lvl": v, "name": k})
                    updated += r.rowcount
        print(f"  batch {i//BATCH + 1}/{(len(names)+BATCH-1)//BATCH}: "
              f"{total_classified} names → {updated} rows", flush=True)

    print(f"classified {total_classified}/{len(names)}; updated {updated} rows")
    with eng.connect() as c:
        left = c.execute(text(
            "select count(*) from food_entries where processing_level is null")).scalar()
    print(f"remaining NULL: {left}")


if __name__ == "__main__":
    sys.exit(main())
