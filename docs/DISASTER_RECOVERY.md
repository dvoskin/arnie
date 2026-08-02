# Disaster recovery — backup, restore, rollback (B9/B10)

**Status: runbook + tooling ready; the live rehearsal needs Danny's Render access.**
This converts the "backup restore tested: UNKNOWN — never attempted" and "rollback
rehearsed: never performed" rows in `docs/MARKET_READINESS_SCORECARD.md` into a
procedure that can be run and dated.

Design principle: **production is never the test subject.** Every drill runs
against a throwaway target or is a read-only verification.

## What we protect (two stores, one recovery unit)

1. **Postgres `arnie-db`** (Render-managed) — all structured data: users, food &
   exercise entries, `daily_logs`, `ledger_events`, `conversation_logs`,
   `turn_metrics`, `idempotency_records`, etc. Schema tracked by Alembic
   (`alembic_version`).
2. **`/data` disk `arnie-data`** (1 GB) — per-user coaching memory the DB does NOT
   hold: `/data/users/<id>/arnie_memory.md`, `profile.md`, and the legacy
   `/data/arnie.db` SQLite fallback. `memory/memory_manager.py` states these
   capture patterns "not otherwise derivable from the structured DB."

**A full restore needs BOTH stores.** Restoring only Postgres silently loses every
user's memory/profile files. The two are not captured by one snapshot, so accept
minor cross-store time skew.

## Current state (as investigated 2026-08-02)

- **No backup code, script, or CI job exists in the repo** (`.github/workflows/`
  has only `ci.yml` + the nightly eval cron). Backups, if any, are a Render
  *platform* capability, not repo-configured or verified.
- Render's managed Postgres (paid `basic-256mb`) almost certainly has automated
  backups — `scripts/restore_links.py` proves one was consulted once — but the
  schedule/retention/PITR have **never been verified**. → step (a).
- **The `/data` disk has no backup of any kind.** This is the real gap. → step (d).
- Deploys are manual in the Render dashboard; `/health` stamps the live commit +
  schema head; `scripts/release_check.py` reads it.

### Prod baseline (from `scripts/verify_db_restore.py`, 2026-08-02)

```
schema (alembic): metrics001
users 123 · daily_logs 377 · food_entries 1916 · exercise_entries 566
ledger_events 596 · conversation_logs 7300 · turn_metrics 57 · idempotency_records 0
```
Re-run before any drill to get a fresh comparison baseline.

## Rollback posture (read before any rollback)

- **Code rollback is safe and simple.** One Python process, no rolling-deploy
  window (`docs/DEPLOYED_STATE_2026-07-31.md`), so redeploying the prior SHA fully
  replaces the running code. Verify with `/health`.
- **Never use `alembic downgrade` as a rollback for a data incident.** 60 of 61
  migrations have real `downgrade()` bodies that `drop_column` — running them is
  permanent data loss. The safe combination is **code-back + schema-forward**:
  migrations are additive, so old code tolerates newer columns. To go backward on
  *data*, restore from backup — never downgrade.

---

## Runbook

### (a) Verify a Postgres backup exists and is recent — *Danny (Render dashboard)*
1. Render → `arnie-db` → **Backups** / **Recovery**.
2. Confirm automated backups are ON; record the **latest timestamp**, **retention
   window**, and whether **Point-In-Time Recovery** is available on this plan.
3. Record the finding (closes the scorecard UNKNOWN). If backups are OFF, stop and
   enable them before launch.

### (b) Restore-to-a-throwaway-target drill — *Danny triggers; script verifies*
1. **Danny:** from `arnie-db` Backups, **restore the latest backup into a NEW
   instance** (Render's restore creates a new instance — it never overwrites the
   source). Name it e.g. `arnie-db-restore-drill`.
2. **Danny:** copy the drill instance's connection string.
3. **Verify (either runs it):**
   ```bash
   DATABASE_URL=<PROD_URL> COMPARE_DATABASE_URL=<DRILL_URL> \
     python scripts/verify_db_restore.py --compare "$COMPARE_DATABASE_URL"
   ```
   Success = `VERIFY OK` (schema matches, row counts align within expected drift).
4. **Danny:** delete the throwaway instance.

### (c) Code-rollback drill — *Danny deploys; script verifies*
1. Record current state: `python scripts/release_check.py` + save `/health` JSON.
2. Prior known-good SHA from `git log` on the deployed branch.
3. **Danny:** Render → `arnie-bot` → **Manual Deploy → Deploy a specific commit**
   (or **Rollback**) → the prior SHA.
4. **Verify:** `python scripts/release_check.py <prior_sha>` and poll `/health`
   until `commit` matches and `schema.in_sync == true` (schema stays forward —
   expected). Record the observed duration = your RTO.
5. Roll forward the same way; re-verify. **Do not** pair with `alembic downgrade`.

### (d) `/data` disk backup — *the real gap; needs Danny*
The disk holds unreconstructable per-user memory. Until a mechanism exists:
1. **Confirm** whether Render snapshots `arnie-data` (dashboard) and record retention.
2. **Add an off-box backup** — `scripts/backup_data_disk.sh` tars + checksums
   `/data/users` and prints the artifact path; run it in the Render service shell
   (where `/data` is mounted) and copy the artifact off-box (object storage), or
   wire it as a cron. Restore-verify: untar into a scratch dir and confirm a
   sample `<id>/arnie_memory.md` + `profile.md` are present and non-empty.
3. **Restore rule:** a full recovery = Postgres restore **and** disk restore
   together.

### (e) Who does what
**Needs Danny (Render dashboard / DB / service shell):** read the Backups tab (a);
trigger + delete the restore instance and hand over its URL (b); perform the
rollback/roll-forward deploy (c); confirm disk snapshots + run/schedule the disk
backup (d); confirm `preDeployCommand: alembic upgrade heads` is actually wired in
the dashboard (render.yaml is reference-only).

**Automated / scripted here (no privileged access):** `scripts/verify_db_restore.py`
(schema + per-table counts, single or `--compare` diff); `release_check.py` +
`/health` for post-rollback verification; `scripts/backup_data_disk.sh` for the
disk artifact; this document.
