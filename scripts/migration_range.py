"""Print `<parent>:<head>` for the newest migration — the range CI compiles.

Why a range and not `upgrade head --sql`: the full chain cannot compile
offline. A self-healing migration in the history calls `sa.inspect()` on the
connection, and offline mode hands it a MockConnection, so the whole replay
dies on a migration that is fine in production. That is the same "verify
migrations in ISOLATION" rule this repo already learned the hard way — seed the
schema, stamp the parent, upgrade one step.

Compiling the head against POSTGRES is the part that matters. Offline mode is
where the last migration bug lived: `op.execute()` returns None there, so an
unguarded `.rowcount` print crashed the Postgres compile while every local
SQLite test passed.

**Alembic resolves the graph, not a regex here.** The first version of this
script parsed `revision` / `down_revision` out of the files and reported FIVE
heads where alembic reports one — a down_revision spelling it did not match
makes a referenced parent look unreferenced. A CI gate that is wrong about the
thing it gates is worse than no gate, and the tool that owns the graph is the
one that should answer questions about it.

Exits non-zero when the head cannot be resolved, so CI fails loudly rather
than silently compiling nothing.
"""
from __future__ import annotations

import pathlib
import sys


def main() -> int:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = pathlib.Path(__file__).resolve().parent.parent
    script = ScriptDirectory.from_config(Config(str(root / "alembic.ini")))

    heads = list(script.get_heads())
    if len(heads) != 1:
        print(f"expected exactly 1 alembic head, found {len(heads)}: {heads}",
              file=sys.stderr)
        return 1

    revision = script.get_revision(heads[0])
    down = revision.down_revision
    # A merge point has a tuple of parents; there is nothing to compile as a
    # single linear step, and the merge itself is what wants review.
    if isinstance(down, (tuple, list)):
        print(f"head {revision.revision} is a merge of {tuple(down)} — "
              f"compile it by hand", file=sys.stderr)
        return 1
    print(f"{down or 'base'}:{revision.revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
