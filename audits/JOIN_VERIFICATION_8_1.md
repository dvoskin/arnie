# Verifying the ask/write join (audit §8.1) in production

**Written before the merge, per the directive.** Every claim below is a query,
not a commit. Nothing here is `CLOSED` on a green suite — the suite proves the
join exists in code; only production proves it exists on traffic.

Baseline to compare against: the 18-hour master-audit window (2026-07-29 20:40
→ 07-30 14:40 UTC), where **every stored resolution carried
`candidate_products: null` and `anchor: None`**, and `event=answer_apply` never
appeared in the logs at all.

---

## 1 · The producer produces (the finding itself)

Stored resolutions now carry products. `staged_items` lives on the pending row.

```sql
-- Per ask turn: how many held items were stored, how many carry candidates,
-- and how many of those candidates are anchored to a product id.
SELECT
  p.id, p.created_at, p.kind,
  jsonb_array_length(p.payload->'staged_items')                   AS items,
  (SELECT count(*) FROM jsonb_array_elements(p.payload->'staged_items') i
    WHERE jsonb_array_length(COALESCE(i->'candidate_products','[]'::jsonb)) > 0)
                                                                  AS with_candidates,
  (SELECT count(*) FROM jsonb_array_elements(p.payload->'staged_items') i,
                        jsonb_array_elements(COALESCE(i->'candidate_products','[]'::jsonb)) c
    WHERE c->>'source_id' IS NOT NULL)                            AS anchored
FROM pending_questions p
WHERE p.payload ? 'staged_items'
  AND p.created_at > TIMESTAMP '2026-07-30 20:00'
ORDER BY p.created_at DESC;
```

**Pass:** `with_candidates > 0` on branded/looked-up items. **Fail — and this is
the number that matters:** `with_candidates = 0` across the window means the
producer is not reaching production traffic, exactly as before, and the join is
inert however green the suite is.

**Expected miss, not a failure:** a generic food nobody looked up (`leftover
soup`) stores zero candidates by design. Read the two populations apart:

```sql
SELECT i->>'food_class' AS food_class,
       count(*) FILTER (WHERE jsonb_array_length(
         COALESCE(i->'candidate_products','[]'::jsonb)) > 0) AS with_candidates,
       count(*)                                              AS items
FROM pending_questions p,
     jsonb_array_elements(p.payload->'staged_items') i
WHERE p.created_at > TIMESTAMP '2026-07-30 20:00'
GROUP BY 1 ORDER BY 3 DESC;
```

## 2 · What it cost (the constraint the fix ships under)

No new lookups on the critical path. The collection reads settled futures and a
cache the same turn filled; a lookup still in flight is treated as absent.

```
event=ask_candidates foods=<n> candidates=<n> anchored=<n>
```

Compare ask-turn latency against the pre-join distribution. **A parallel
closure pass has an open latency REGRESSION FLAG on the 07-30 16:00 deploy
(p50 11,032ms vs 7,159ms baseline, n=4) — that regression predates this change
and must not be attributed to it.** Read this against the same-build baseline,
not against the master audit's:

```sql
SELECT date_trunc('hour', timestamp) AS hour, count(*) AS turns,
       percentile_disc(0.5) WITHIN GROUP (ORDER BY duration_ms)  AS p50,
       percentile_disc(0.9) WITHIN GROUP (ORDER BY duration_ms)  AS p90
FROM conversation_logs
WHERE reasoning_json->'route'->>'lane' LIKE 'structured%'
  AND timestamp > TIMESTAMP '2026-07-30 20:00'
GROUP BY 1 ORDER BY 1;
```

**Fail:** structured-ask p50 rises against the same build without the join.
That would mean something on this path is fetching, and the fix is wrong.

## 3 · The shadow has something to measure (`FOOD_ANSWER_APPLY`)

The flag stays **off**. Its promotion condition is a measured agreement rate,
and until this join that rate was the agreement rate of a path that never ran:
`commit_from_answer` returned None every time, so no shadow line was ever
emitted.

```
event=answer_apply outcome=shadow food=<...> cal=<...> buildable=<bool>
```

**Pass:** shadow lines appear on answering turns, with `cal` non-null and
`buildable=True`. **Fail:** `cal=None`, or no lines at all — the answer turn is
still re-deriving, and the flag stays where it is.

The flip condition, when there is traffic to measure it on:

- ≥ 30 shadowed answering turns, and
- the shadowed calorie total within 10% of what the interpreter pass committed
  on the same turn, on ≥ 95% of them, and
- zero cases where the shadow priced a food the committed row did not name.

Disagreement is not a bug to suppress. A shadow that disagrees is the stored
resolution and the re-derivation describing different food, which is the defect
this whole phase is about — investigate it, do not tune the threshold.

## 4 · Identity stability (what the anchor buys)

```sql
-- A food asked about and then logged: did the committed row keep the product
-- the ask established, or did the answering turn substitute a prior?
SELECT p.id AS pending_id, p.payload->'staged_items'->0->'identity'->>'canonical_name' AS asked,
       f.food_name AS logged, f.created_at - p.created_at AS gap
FROM pending_questions p
JOIN food_entries f ON f.user_id = p.user_id
                   AND f.created_at BETWEEN p.created_at AND p.created_at + INTERVAL '30 minutes'
WHERE p.payload ? 'staged_items'
  AND p.created_at > TIMESTAMP '2026-07-30 20:00'
ORDER BY p.created_at DESC;
```

**Fail:** `logged` names a food from the user's history that `asked` does not —
the "Dollar pizza slices" write, thirteen hours after the user said
"sopressata".

## 5 · Statuses

| Claim | Status | Evidence needed |
|---|---|---|
| `candidate_products` has a producer | `FIXED LOCALLY` | §1 on real traffic |
| The join costs no lookup | `FIXED LOCALLY` | §2, same-build p50 |
| The answer-apply shadow is measurable | `FIXED LOCALLY` | §3 lines with non-null `cal` |
| `FOOD_ANSWER_APPLY` may be enabled | **not claimed** | §3 flip condition, ≥30 turns |
| Corrections reuse the stored resolution | `FIXED LOCALLY` | §6 below |

## 6 · Typed corrections (cause B)

A preparation or portion correction applies to the stored candidate instead of
re-searching the mutated string.

```
event=correction_apply outcome=<applied|shadow|declined> reason=<...>
```

```sql
-- Corrections that produced a new entry rather than updating one: the failure
-- the reuse path exists to prevent. 0 observed in the 18h window; this is the
-- regression watch, not a claim of improvement.
SELECT date_trunc('day', created_at) AS day, count(*)
FROM ledger_events
WHERE event_type = 'created' AND source LIKE '%update%'
  AND created_at > TIMESTAMP '2026-07-30 20:00'
GROUP BY 1;
```
