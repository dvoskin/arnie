# PREREGISTRATION TEMPLATE

Copy to `docs/PREREG_<name>_<date>.md`. **Commit it before the first turn runs.**
Enforced by `tests/test_a_preregistration_declares_all_three_outcomes.py`.

## ⭐⭐⭐ Why the three-way vocabulary is mandatory

The C re-run (2026-08-31) preregistered two outcomes: *the effect falls inside
the null envelope*, and *the effect survives in the predicted direction*. The
actual result was that **the effect survived with its sign reversed** — the
intervention did the opposite of what it was built to do, by 15 points on a null
of 1.

That outcome was not wrong-but-anticipated. It was **unnameable in the document
that was supposed to anticipate it**, so a real and decisive result had to be
classified after the fact by the person who had just seen it. A prediction that
cannot name the outcome it gets is weaker evidence than one that can.

The gap was not carelessness about that run. **I enumerated only the outcomes I
could imagine wanting** — which is exactly the bias preregistration exists to
remove, arriving through the document's own structure.

## The three outcomes — all three, always, with their actions

```text
BENEFIT   the effect survives the null envelope in the intended direction
          -> the candidate has earned the next gate, NOT adoption

NULL      the effect falls inside the envelope
          -> no conclusion. Do not tune and re-run: an intervention that
             cannot beat its own noise has not been shown to do anything

HARM      the effect survives the envelope in the OPPOSITE direction
          -> ⛔ STOP OPTIMIZATION. Characterise the reversal before designing
             another candidate. Do NOT reach for "maybe the threshold just
             needs tuning" — a sign reversal means the mechanism is not what
             it was believed to be, and tuning a misunderstood mechanism
             produces a number, not knowledge
```

The HARM branch's action is the one that earns the vocabulary. A two-way
prediction leaves a reversal looking like a near-miss, and a near-miss invites
another parameter sweep.

## Required sections

1. **The acceptance condition**, in the requester's own words, quoted.
2. **What changed since the last run** — code, config, instrument.
3. **The arms** — including a NULL PAIR on the same behavioural SHA. No
   effect-size claim may use an envelope built from fewer than two comparable
   runs on the same `_code_sha`.
4. **The prediction**, stated before the run, with its mechanism.
5. **BENEFIT / NULL / HARM**, each with the action it binds you to.
6. **What is measured**, field by field.
7. **⛔ Refusal conditions** — what makes the run VOID rather than noisy.
   Void means void: a proof afterwards that the run was *probably* fine does
   not rescue it, because arguing past a refusal is what preregistration
   exists to prevent.
8. **What this run does NOT decide** — the questions it is not powered for.

## Amendments

Never edit a prediction after the first turn. Append a dated amendment stating
what happened and why; the original stands.
