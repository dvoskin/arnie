"""cleanup_users.py must NEVER delete a cross-platform LINK identity.

A linked secondary row looks exactly like junk (no name, not onboarded, ~1 conv)
because its real history lives on the canonical account. Deleting it silently
breaks that user's OTHER platform (the Gi-Telegram incident). The delete loop's
guard refuses any user that participates in a link in EITHER direction:

  • links_out — the user's own linked_to_user_id is set (it's a secondary pointing
    at a canonical)
  • links_in  — some other user's linked_to_user_id points AT this user (it's a
    canonical referenced by a secondary)

The guard predicate was extracted into an importable helper
`scripts/cleanup_users._is_protected_link(db, user)` (a minimal refactor of the
file under test) so it can be pinned directly. These tests load that helper from
the script file and assert both link directions read as protected, and that a
genuinely unlinked junk row does not.
"""
import importlib.util
import os

import pytest

from db.models import User, UserPreferences


# Load the script by file path (scripts/ isn't an importable package here) and
# grab the extracted guard predicate. Importing the module also proves the
# refactored script still imports cleanly.
_SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "cleanup_users.py",
)
_spec = importlib.util.spec_from_file_location("cleanup_users_under_test", _SCRIPT_PATH)
cleanup_users = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cleanup_users)
_is_protected_link = cleanup_users._is_protected_link


async def _add_user(db, **kw):
    kw.setdefault("onboarding_completed", False)
    u = User(**kw)
    db.add(u)
    await db.flush()
    db.add(UserPreferences(user_id=u.id))
    await db.commit()
    return u


def test_script_still_dry_run_by_default():
    """The APPLY gate must stay off unless APPLY=1 — the refactor must not have
    flipped the script to destructive-by-default."""
    # APPLY is read at import time from the env; the test env doesn't set it.
    assert cleanup_users.APPLY is False


async def test_secondary_pointing_at_canonical_is_protected(db, make_user):
    """links_out direction: a secondary whose linked_to_user_id points at a
    canonical must be refused even though it otherwise looks like junk."""
    canonical = await make_user(telegram_id="ios:canon", name="Canon", onboarded=True)
    secondary = await _add_user(db, telegram_id="tg:sec", name=None,
                                linked_to_user_id=canonical.id)
    assert await _is_protected_link(db, secondary) is True


async def test_canonical_referenced_by_secondary_is_protected(db, make_user):
    """links_in direction: a canonical that another user's linked_to_user_id
    points AT must be refused (deleting it orphans the secondary's platform)."""
    canonical = await make_user(telegram_id="ios:canon2", name="Canon2", onboarded=True)
    # A secondary that references the canonical.
    await _add_user(db, telegram_id="tg:sec2", name=None,
                    linked_to_user_id=canonical.id)
    assert await _is_protected_link(db, canonical) is True


async def test_unlinked_junk_is_not_protected(db, make_user):
    """An account with no link in either direction is NOT protected by this
    guard (the other safety guards decide whether it's junk)."""
    junk = await _add_user(db, telegram_id="tg:junk", name=None)
    assert await _is_protected_link(db, junk) is False


async def test_both_directions_at_once_is_protected(db, make_user):
    """A middle node that both points at a canonical AND is pointed at by a
    third row is protected (either condition suffices)."""
    canonical = await make_user(telegram_id="ios:canon3", name="Canon3", onboarded=True)
    middle = await _add_user(db, telegram_id="tg:mid", name=None,
                             linked_to_user_id=canonical.id)
    await _add_user(db, telegram_id="tg:leaf", name=None,
                    linked_to_user_id=middle.id)
    assert await _is_protected_link(db, middle) is True
    assert await _is_protected_link(db, canonical) is True
