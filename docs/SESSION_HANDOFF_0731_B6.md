# Handoff — 2026-07-31 (B6 voice pass)

Continues `docs/SESSION_HANDOFF_0731.md`. B7 was closed first (its own branch);
this pass took B6, the voice item. Read this, then the updated scorecard §8.

Everything below was proven by a test or the audit, not remembered.

## Where the work is

Branch `dvoskin/b6-voice-renderer`, cut from `origin/main` @ `50ba640`.
**Committed locally, not pushed, not deployed.** Independent of the B7 branch;
they touch different code and different scorecard sections, so they merge
cleanly. Full shuffled suite green at the tip.

```bash
python scripts/voice_audit.py                 # the evaluation — pre/post-seam violations
pytest tests/test_voice.py -q                 # contract + seam + corpus gate
```

## What §8 asked, and what each answer is

§8 was UNKNOWN because there was nothing to measure against: "no voice corpus,
no evaluation, no single renderer; voice ownership is spread across prompts,
composers and deterministic fallbacks." All three now exist.

**One renderer.** `core/voice.py` is the single source of truth. `normalize`
is the ONE character pass (em dash → comma, tilde → "about", whitespace), and
it fixed a real drift: `platform._sanitize_bubble` preserved an en dash so
"12–13%" survived, but `log_voice._clean` collapsed it — the same range
rendered two ways depending on which path voiced it. Both now delegate to
`core/voice`, so there is nothing left to keep in sync (the lesson
`core/recovery.py` already learned for the fallback pool).

**Sentence case, at the root.** The 2026-06-15 decision ("capitalize the first
word of every bubble, on every surface") was enforced only in the PROMPT, so
prompt-adjacent leaks survived: `handlers/onboarding.py` shipped "good to meet
you", the proactive scheduler shipped "morning {name}." next to "Good morning".
`enforce_sentence_case` now runs at the seam every bubble already flows through
(`Response.from_text`, streaming and non-streaming). The audit shows it fixes
**7/7** lowercase leads in the corpus, 0 shipped. Conservative by design — it
leaves iOS / eBay / iPhone (internal caps), URLs, emoji and number leads alone,
and non-Latin scripts pass through untouched. Kill switch `VOICE_SENTENCE_CASE`.

**A measurement.** `core.voice.check_voice` is a linter (em dash, tilde,
lowercase lead, joke emoji, helpdesk filler, exclamation pile, robotic ack,
leaked marker). `scripts/voice_audit.py` runs it over the corpus PRE- and
POST-seam, so you can see both how much the seam is doing and what it cannot fix.

**A corpus.** `tests/corpus/voice_corpus.py` — the bubbles the product ships
verbatim (recovery, onboarding, proactive), mirrored from their source, plus
curated representative turns and 4 negative controls that must keep tripping the
linter. It is NOT sampled from production: `extract_replay_corpus.py` writes
beta-user transcripts into this PUBLIC repo and is banned (see the parent
handoff). A deterministic corpus is the honest, CI-runnable version.

**A structured path.** `CoachMessagePlan` + `render` — a composer names intent
(read / receipt / nudge / ask) and the renderer voices it, in voice by
construction. Available now; the 20+ composer files adopt it incrementally.

## The one thing that needs YOUR voice call

The audit surfaces exactly **one shipped violation the seam cannot fix** (it
does not rewrite emoji): the proactive city-timezone ask ships 😅
(`scheduler/proactive_scheduler.py` `_CITY_NUDGES[0]`). I did NOT strip it,
because the main prompt contradicts itself on joke emoji — an APPROVED example
at `core/prompts/arnie.py:2378` uses 😂 ("royo bagel before bed 😂"), while a
rule at `arnie.py:2533` says "never 😂 😭". Settle that one way:

* if joke emoji are off-voice → remove " 😅" from `_CITY_NUDGES[0]` and delete
  the `arnie.py:2378` example, and the linter's `joke_emoji` rule is correct as
  is;
* if they're allowed when the user's energy invites it → relax
  `core/voice._JOKE_EMOJI` to context, and drop the frozen finding.

Either way, update `test_only_known_shipped_finding_is_the_city_nudge_joke_emoji`.

## What this pass did NOT do (scope, honest)

* The **LLM path still composes its own prose** under the prompt anchor. The
  seam normalizes and sentence-cases its output, but the renderer does not
  generate it — voice on that path still rests on the prompt.
* The **composers have not adopted `CoachMessagePlan`.** The linter measures
  that gap (run `voice_audit.py`); closing it is per-file follow-up work, best
  done a surface at a time behind the corpus gate.
* **Non-Latin sentence case** is deliberately unhandled — safe (never
  mis-cases) but it means a Russian lowercase lead is not fixed. Matches the
  RU-lane caution in memory.

## Next, in order (unchanged from the parent, minus B6/B7)

1. **B2** — 57 of 60 user-visible mutations off the contract;
   `mutation_inventory.py` ranks them.
2. **B5** — latency: `turn_metrics` exists, no data yet; the +54% p50
   regression is still unexplained.
3. **B9/B10** — backup restore + rollback rehearsal (ops, needs Danny).
4. **B1** — deploy. B1 CLOSED once this session (`/health` moved to `50ba640`),
   but the B6 and B7 branches now sit undeployed behind it.

## Files touched

New: `core/voice.py`, `scripts/voice_audit.py`, `tests/corpus/voice_corpus.py`,
`tests/test_voice.py`, this handoff.
Changed: `core/platform.py` (`_sanitize_bubble` delegates + sentence case),
`core/log_voice.py` (`_clean` delegates, fixing its en-dash range bug),
`core/recovery.py` (pool second bubbles to sentence case — they violated the
module's own "sentence case" docstring), `docs/MARKET_READINESS_SCORECARD.md`
(§8 + B6 row), and the seam tests `tests/test_platform_response.py`,
`tests/test_em_dash_wire_enforcement.py` (expected outputs now open capitalized).
