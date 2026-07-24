"""Cross-source workout dedup — the CalAI rule.

The same physical session reported by two sources (Whoop walk + Apple
'Workout', Oura run + Whoop run) is ONE workout. Every synced-source ingest
(apple_health, whoop, oura) must check candidates against sessions OTHER
sources already own on that day before writing. Within-source repeats are
already handled by each lane's source_ref upsert; this guards the seams
between lanes.
"""


def is_cross_source_dup(cand_start_utc, cand_dur, other_occurred, other_dur) -> bool:
    """Prefer timestamps (starts within 30 min + durations within ~40%); with
    no timestamps to compare, treat same-day near-identical durations as the
    same session (the exact shape of the Whoop-walk / Apple-'Workout' pair)."""
    if cand_start_utc is not None and other_occurred is not None:
        delta_min = abs((cand_start_utc - other_occurred).total_seconds()) / 60
        if delta_min > 30:
            return False
        if not cand_dur or not other_dur:
            return True
        lo, hi = sorted([float(cand_dur), float(other_dur)])
        return hi <= lo * 1.4 + 3
    if cand_dur and other_dur:
        return abs(float(cand_dur) - float(other_dur)) <= 3
    return False
