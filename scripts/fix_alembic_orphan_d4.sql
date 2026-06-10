-- One-time fix for the alembic_version orphan caused by the failed
-- first deploy of the non_training_activity migration.
--
-- Background: my old migration file used revision id `d4e5f6a7b8c9` which
-- collided with the existing `drop_daily_log_status.py`. Before alembic
-- raised the collision error, it had already run my migration's upgrade()
-- function (adding the users.non_training_activity column) and stamped
-- `d4e5f6a7b8c9` to alembic_version. After I renamed the file to
-- `f7e8d9c0b1a2_add_non_training_activity.py`, the DB's stamped id no
-- longer corresponds to any of my files — it now resolves to the
-- existing `drop_daily_log_status` migration (also id `d4e5f6a7b8c9`),
-- whose chain leads to `c9d0e1f2a3b4` — which is ALSO in alembic_version.
-- That collision is the "overlaps" error in the preDeployCommand.
--
-- The DB schema state matches f7e8d9c0b1a2 (column exists), so we just
-- need to relabel the alembic_version row. Idempotent — if d4 isn't
-- there, the UPDATE is a no-op.

-- 1) Confirm what we're about to fix. Should show 'd4e5f6a7b8c9' for the
--    orphan row plus the two legitimate head rows.
SELECT version_num FROM alembic_version ORDER BY version_num;

-- 2) Confirm the column my old migration added is actually present.
--    If non_training_activity is in users.columns, the upgrade ran.
SELECT column_name FROM information_schema.columns
WHERE table_name = 'users' AND column_name = 'non_training_activity';

-- 3) Relabel the orphan. After this, alembic_version contains the three
--    legitimate heads: f7e8d9c0b1a2, c9d0e1f2a3b4, b2c3d4e5f6a7.
UPDATE alembic_version
SET version_num = 'f7e8d9c0b1a2'
WHERE version_num = 'd4e5f6a7b8c9';

-- 4) Verify post-fix state. Should now be three rows, none equal to d4.
SELECT version_num FROM alembic_version ORDER BY version_num;
