# THE EFFECTIVE PRODUCTION RUNTIME, from data/production_config_snapshot.json.
#
# ⛔⛔ NOT scripts/prodenv.sh. That file exports render.yaml's values and is
# WRONG about what production runs: it says TURN_COORDINATOR_MODE=new_observe
# where production runs new_execute, and it omits the three eligibility flags
# entirely -- which is why a local CF24 replay never reached the memory row.
# `pin_runtime` refuses any run that does not match this.
export TURN_COORDINATOR_MODE='new_execute'
export TURN_COORDINATOR_LANES='ledger_undo,structured_food'
export ENTITY_RESOLUTION_MODE='consume'
export NUTRITION_ACCURACY_V2='allowlist'
export NUTRITION_RESOLVER_MODE='live'
export FOOD_COMPOSER='true'
export FOOD_COMPOSER_MODEL='claude-sonnet-5'
export FOOD_GATE_MODEL='true'
export DEFAULT_MODEL='claude-sonnet-4-6'
export FOOD_PORTION_PRICING='true'
export QUICK_LOG_FOOD_WRITER='canonical'

# ⭐ COHORTS. Membership is what decides behaviour, so the SUBJECT must be
# enrolled exactly as user 26 is in production -- not "a user", user 26.
export TURN_COORDINATOR_ALLOWLIST='26'
export ENTITY_RESOLUTION_CONSUME_ALLOWLIST='26'
export NUTRITION_ACCURACY_V2_ALLOWLIST='26'

# harness-only, never production behaviour
export PROACTIVE_MESSAGING_ENABLED='false'
export VOICE_REPLIES_ENABLED='false'
