# CF24 — FROZEN STATUS, 2026-08-25

*Danny's status freeze. This supersedes any earlier closure language for CF24.
Read it before proposing work in this area.*

```
CF23 containment           ✅ CLOSED
CF24 trust architecture    ✅ BUILT
CF24 known readers         ✅ GUARDED
CF24 production closure    ⛔ OPEN — 3050 consumer unattributed
CF25 OFF qualification     ✅ VALID SEPARATE FIX
Memory-use instrumentation 🟡 READY TO DEPLOY
Producer poisoning defect  🟡 OPEN / REPRODUCIBLE
Product roadmap            ⏸ PAUSED ONLY UNTIL CF24 ATTRIBUTION CLOSES
```

**⛔ NO GENERALIZED MEMORY OR PRICING REDESIGN IS AUTHORIZED FROM HERE.**

## CF24's closure condition — narrow, and it does not widen

1. Identify the consumer that used row 936.
2. Block that path **through the shared trust boundary**, not at the caller —
   another direct reader can always exist.
3. Exact regression of the 3050 shape.
4. Clean production replay.

Do not expand scope unless the instrumentation points somewhere new.

## The next milestone, in full

Deploy `7fd15d9` → wait for one recurrence or force one controlled replay →
name the consumer → close the seam → return to oils.

## What is settled, and what is not

**The trust model works.** A controlled production probe addressed memory row
886 (`cucumber`, 179 kcal/100g, P7.14 C14.3 F10.7) by exact key — usage bumped
5→6, six milliseconds before the commit — and the entry committed **13 kcal,
not 179**. A twelve-fold error, correctly refused, with `cal_100` unchanged
afterwards. Production **can** refuse untrusted memory.

**One path consumed row 936 anyway.** Entry 3050 committed 525 kcal, the exact
×1.2 image of that row, on the CF24 build. Five candidates were eliminated with
production data rather than by reading code: the enrichment cache, the tier-0
history override, provider retrieval, an in-turn write, and both guarded
readers (which refuse the same row and item in local reproduction). The
consumer is unidentified.

## Two lessons this incident is worth remembering for

### ⛔⛔⛔ PARTIAL CORRECTION OF A WRONG-IDENTITY ROW IS UNSAFE

The first repair of entry 3050 fixed calories and macros and left sugar and
sodium carrying the other food's profile — 2343 mg against a truth of 166.5,
which a later edit then dutifully scaled. **When the whole row came from the
wrong food, every field came from the wrong food.** A wrong-identity repair
restores the entire evidence-owned nutrition payload, never selected fields.

### ⛔⛔⛔ INTERNAL CONSISTENCY IS ALMOST USELESS AS AUTHORITY EVIDENCE

Entry 3050's macros reconstructed its calories perfectly:
`4(10.6) + 4(76.6) + 9(19.4) = 523 ≈ 525`. The row was completely false. A
whole row scaled from one wrong source agrees with itself by construction.
**Provenance and identity binding are the only reliable basis** — which is why
the CF25 repair sits at the identity boundary and carries no calorie threshold
and no macro sanity check.

## The producer defect stays separate

Entry 3053 / row 1031 is its live fixture. One turn, one food, three numbers:

```
interpreter    500 kcal   P5      C40     F36
entry 3053     590 kcal   P6.0    C40.0   F44.0
row 1031       643/100g   P14.3   C42.9   F50.0    ← written by that same turn
```

The cache stores a number the meal never used. This is how row 936 (Aug 2), row
886 and row 1031 were all created. **It deserves its own defect record and
exact fixture, and must not be conflated with CF24 containment** — bad rows can
be created independently of whatever consumed one on Aug 25.
