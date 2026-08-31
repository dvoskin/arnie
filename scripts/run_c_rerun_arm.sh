#!/bin/bash
# ONE ARM OF THE C RE-RUN. See docs/PREREG_C_RERUN_2026-08-31.md.
#
#   ./scripts/run_c_rerun_arm.sh <out.jsonl> <false|true> [reps] [cases]
#
# ⭐ THE ARM IS THE ONLY THING THAT VARIES. Every other declared flag is
# exported to its render.yaml value, and `pin_config` refuses the run if one
# drifts. `FOOD_EXTRAS_REPORT_ONLY` is named in MEASUREMENT_ARM so the guard
# allows it AND records it under `_arm` in the output's first line.
set -euo pipefail
OUT="$1"; ARM="$2"; REPS_IN="${3:-2}"; CASES_IN="${4:-1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25}"

# secrets only — never the production DATABASE_URL
export ANTHROPIC_API_KEY="$(grep -E '^ANTHROPIC_API_KEY=' ../arnie/.env | cut -d= -f2-)"
# ⛔ LOCAL POSTGRES. The harness writes synthetic identities and deletes them;
# it must never touch the production database. `+psycopg`, not `+asyncpg` —
# asyncpg breaks this harness.
export ARNIE_DATABASE_URL="${ARNIE_DATABASE_URL:-postgresql+psycopg://danielvoskin@localhost/arnie_test}"
# ⛔⛔ THE APP-GLOBAL ENGINE READS `DATABASE_URL`, NOT `ARNIE_DATABASE_URL`.
# Leaving it unset silently drops the app half of the turn onto the repo's
# `arnie.db` sqlite -- which has no `turn_metrics` and no history -- while the
# harness half talks to Postgres. A run split across two databases is not the
# product, and the first smoke test showed c1 producing NO ambiguities at all
# under that split.
export DATABASE_URL="$ARNIE_DATABASE_URL"

export TURN_COORDINATOR_MODE=new_observe
export TURN_COORDINATOR_OBSERVE_DEEP=false
export NUTRITION_RESOLVER_MODE=live
export FOOD_COMPOSER=true
export FOOD_MICROS_DEFERRED=true
export FOOD_LATE_HEADSUP=false
export FOOD_LATE_HEADSUP_DELAY_S=3.5
export FOOD_FAST_PATH_SHADOW=on
export FOOD_GATE_MODEL=true
export DEFAULT_MODEL=claude-sonnet-4-6
export PROACTIVE_MESSAGING_ENABLED=false
export VOICE_REPLIES_ENABLED=false

export FOOD_EXTRAS_REPORT_ONLY="$ARM"
export MEASUREMENT_ARM=FOOD_EXTRAS_REPORT_ONLY
export MEASUREMENT_MODE=census
export REPS="$REPS_IN"
export ONLY_CASES="$CASES_IN"
export OUTJSONL="$OUT"

echo "ARM FOOD_EXTRAS_REPORT_ONLY=$ARM  reps=$REPS_IN  -> $OUT"
exec ../arnie/.venv/bin/python scripts/characterise_ask_producer.py
