# Production configuration, per render.yaml + Danny's dashboard confirmation
# of FOOD_GATE_MODEL=true (2026-08-27).
export TURN_COORDINATOR_MODE='new_observe'
export TURN_COORDINATOR_OBSERVE_DEEP='false'   # declared deviation: cost, see _ALLOWED_DEVIATIONS
export NUTRITION_RESOLVER_MODE='live'
export FOOD_COMPOSER='true'
export FOOD_MICROS_DEFERRED='true'
export FOOD_LATE_HEADSUP='false'
export FOOD_LATE_HEADSUP_DELAY_S='3.5'
export FOOD_FAST_PATH_SHADOW='on'
export FOOD_GATE_MODEL='true'
export DEFAULT_MODEL='claude-sonnet-4-6'
export VOICE_REPLIES_ENABLED='false'
# declared deviations (see _ALLOWED_DEVIATIONS in the harness)
export PROACTIVE_MESSAGING_ENABLED='false'
