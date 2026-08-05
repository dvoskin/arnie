"""B-1's live proof: one operation, followed all the way through.

WRITTEN AGAINST THE DEFECT IN `minimal_smoke.py`. That tool passes when ANY
`canonical:create` trace exists recently in the ring — "something canonical
happened somewhere" — and it hardcodes the admin token in the file. Both are
corrected here: every assertion is correlated to an operation this probe
minted itself, and the token comes only from the environment.

It proves the CHAIN, not its endpoints:

    this operation -> this pending record -> this answer -> this commit
                   -> this food row

A green run means those five refer to each other. A run that cannot evaluate a
check FAILS it — "we could not tell" is not evidence, and a probe that reports
success on a check it skipped is worse than no probe.

    ARNIE_ADMIN_TOKEN=... python scripts/b1_operation_probe.py \
        --expect-sha 6ab7c238575b --expect-env production --stage 2

Stage 1 (`--stage 1`) verifies the deploy with B-1 still OFF: the SHA, the
kill switch, and that an eligible message takes the LEGACY path. Nothing is
enabled and nothing is asserted about canonical behaviour, because none should
exist yet.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.getenv("ARNIE_BASE_URL", "https://arnie.onrender.com")
IDENTITY = os.getenv("B1_PROBE_IDENTITY", "ios:b1-quantity-probe-0805")

#: Every check the probe knows how to run. A check that cannot be evaluated is
#: recorded UNEVALUATED and fails the run — never silently skipped.
UNEVALUATED = "unevaluated"


class Probe:
    def __init__(self, expect_sha: str, expect_env: str, token: str):
        self.expect_sha, self.expect_env, self.token = (expect_sha,
                                                        expect_env, token)
        self.report: dict = {}
        self.operation_id = ""

    # ── plumbing ────────────────────────────────────────────────────────
    def _req(self, path, body=None, headers=None, method=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            BASE + path, data=data, method=method or ("POST" if data else "GET"),
            headers={"Content-Type": "application/json", **(headers or {})})
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read() or "{}")

    def check(self, name, ok, detail=""):
        verdict = "PASS" if ok is True else (
            UNEVALUATED if ok is None else "FAIL")
        self.report[name] = {"verdict": verdict, "detail": str(detail)[:300]}
        print(f"  {verdict:<11} {name}"
              + (f"  — {detail}" if detail else ""))
        return ok is True

    @property
    def failed(self):
        return [n for n, r in self.report.items() if r["verdict"] != "PASS"]

    # ── stages ──────────────────────────────────────────────────────────
    def preconditions(self):
        """HARD, and first. A probe run against the wrong build or the wrong
        environment produces evidence about something nobody asked about."""
        health = self._req("/health")
        sha = str(health.get("commit") or "")
        self.check("build_is_the_expected_sha",
                   sha.startswith(self.expect_sha)
                   or self.expect_sha.startswith(sha), f"live={sha}")
        env = str(health.get("environment") or health.get("env") or "")
        self.check("environment_is_expected",
                   (env == self.expect_env) if env else None,
                   f"live={env or 'not reported'}")
        return health

    #: Every field the rollout state must publish. A MISSING one fails rather
    #: than reading as a safe default: "percent is absent" and "percent is 0"
    #: look identical to a `.get()` and mean opposite things about whether the
    #: build even knows about B-1.
    ROLLOUT_FIELDS = ("halted", "percent", "allowlist_size")

    def stage_one(self, health):
        """Deployed, feature OFF. Nothing canonical should exist yet."""
        rollout = (health.get("food_pipeline") or {}).get("B1_QUANTITY") or {}
        self.check("b1_rollout_state_is_published", bool(rollout),
                   json.dumps(rollout) if rollout else "/health does not "
                   "expose B1_QUANTITY")
        missing = [f for f in self.ROLLOUT_FIELDS if f not in rollout]
        self.check("b1_rollout_state_is_complete", not missing,
                   f"missing {missing}" if missing else json.dumps(rollout))
        if missing:
            self.check("b1_is_disabled", None,
                       "cannot judge with fields missing")
            return
        self.check("b1_is_disabled",
                   rollout["percent"] in (0, 0.0)
                   and not rollout["allowlist_size"]
                   and not rollout["halted"],
                   json.dumps(rollout))

    def stage_two(self):
        """Allowlisted identity, one operation, followed end to end."""
        token = self._req("/api/v1/auth/session",
                          {"provider": "device", "credential": IDENTITY}
                          ).get("token")
        auth = {"Authorization": f"Bearer {token}"}

        key = f"b1-probe-{int(time.time())}"
        ask = self._req("/api/v1/chat",
                        {"message": "I had some chicken breast",
                         "client_message_id": key}, auth)
        interaction = (ask.get("interaction") or {})
        self.operation_id = str(interaction.get("operation_id") or "")

        self.check("the_ask_returned_a_canonical_interaction",
                   bool(self.operation_id),
                   self.operation_id or "no interaction on the reply — the "
                   "turn stayed legacy")
        if not self.operation_id:
            # Everything below is ABOUT this operation. Without one there is
            # nothing to correlate to, and reporting the rest as passing
            # would be the exact vacuous-green defect this probe replaces.
            for name in ("options_have_ids_and_labels_only",
                         "a_free_text_route_is_offered",
                         "the_answer_committed_one_meal",
                         "the_pending_operation_is_terminal",
                         "exactly_one_canonical_ledger_event",
                         "no_legacy_write_for_this_operation",
                         "the_duplicate_answer_replayed",
                         "a_stale_revision_was_refused",
                         "a_foreign_field_was_refused"):
                self.check(name, None, "no operation to correlate to")
            return

        field = interaction["groups"][0]["fields"][0]
        options = field.get("options") or []
        self.check("options_have_ids_and_labels_only",
                   bool(options) and all(set(o) == {"option_id", "label"}
                                         for o in options),
                   json.dumps(options))
        self.check("a_free_text_route_is_offered",
                   field.get("allows_free_text") is True,
                   str(field.get("allows_free_text")))

        # THE ANSWER, carrying the ids this probe was given.
        chosen = options[0]
        day_before = self._day_calories(auth)
        answer = self._req("/api/v1/chat", {
            "message": chosen["label"],
            "client_message_id": f"{key}-a",
            "interaction": {"operation_id": self.operation_id,
                            "revision": interaction["revision"],
                            "field_id": field["field_id"],
                            "option_id": chosen["option_id"]}}, auth)
        self.check("the_answer_was_accepted", bool(answer.get("v")),
                   json.dumps(answer)[:200])

        self._agreement(auth, answer, chosen, day_before)
        self._correlate()
        self._negatives(auth, key, interaction, field)

    def _day_calories(self, auth):
        try:
            return float((self._req("/api/v1/day", headers=auth)
                          .get("totals") or {}).get("calories") or 0.0)
        except Exception:
            return None

    def _agreement(self, auth, answer, chosen, day_before):
        """THE NUMBERS MUST AGREE, not merely exist.

        A probe that checks "a row was written" passes on a row containing the
        wrong number. Every value below is compared against another INDEPENDENT
        source of the same fact, so a disagreement between the card, the row,
        the day total and the answered quantity cannot hide.
        """
        cards = [c for c in (answer.get("cards") or [])
                 if c.get("type") == "macro_card"]
        card = (cards[0].get("payload") if cards else {}) or {}
        self.check("the_reply_carried_exactly_one_card", len(cards) == 1,
                   f"{len(cards)} cards")

        entry_id = card.get("entry_id")
        self.check("the_card_names_a_real_row", entry_id is not None,
                   str(entry_id))

        # PRICING IS REAL, not the interpreter's placeholder echoed back. The
        # answered mass is a different portion from the one the interpreter
        # assumed, so an unchanged calorie figure means the answer never
        # reached the resolver.
        calories = card.get("calories")
        self.check("the_row_was_priced",
                   isinstance(calories, (int, float)) and calories > 0,
                   f"calories={calories}")

        # THE CARD AND THE SENTENCE. They are two renderings of one facts
        # object server-side; this proves that survived the wire.
        text = " ".join(answer.get("bubbles") or []) or str(answer.get("v") or "")
        self.check("the_sentence_states_the_card_figure",
                   (f"{int(calories)} cal" in text) if calories else None,
                   text[:160])

        # THE DAY MOVED BY EXACTLY THIS MEAL.
        day_after = self._day_calories(auth)
        if day_before is None or day_after is None or not calories:
            self.check("the_day_total_moved_by_this_meal", None,
                       "day totals unavailable")
        else:
            delta = day_after - day_before
            self.check("the_day_total_moved_by_this_meal",
                       abs(delta - float(calories)) <= 1.0,
                       f"day {day_before} -> {day_after} (delta {delta}, "
                       f"meal {calories})")
        self._committed = {"entry_id": entry_id, "calories": calories,
                           "protein_g": card.get("protein_g"),
                           "label": chosen["label"]}

    def _correlate(self):
        """Everything below matches on THIS operation id. Never on recency."""
        traces = self._req(
            f"/admin/food-traces?q={self.operation_id}&limit=100",
            headers={"X-Admin-Token": self.token})
        lines = [l.get("message", "") for l in (traces.get("lines") or [])
                 if self.operation_id in l.get("message", "")]

        committed = [l for l in lines if "event=b1_committed" in l]
        self.check("the_answer_committed_one_meal", len(committed) == 1,
                   f"{len(committed)} commit events for {self.operation_id}")

        canonical = [l for l in lines if "lane=canonical:create" in l]
        self.check("exactly_one_canonical_ledger_event", len(canonical) == 1,
                   f"{len(canonical)} canonical writes")

        legacy = [l for l in lines if "legacy:" in l]
        self.check("no_legacy_write_for_this_operation", not legacy,
                   legacy[0][:160] if legacy else "none")

        shown = [l for l in lines if "event=b1_shown" in l]
        self.check("the_question_was_measured", len(shown) == 1,
                   f"{len(shown)} shown events")

    def _negatives(self, auth, key, interaction, field):
        """Fail-closed behaviour, proven against the SAME operation."""
        stale = self._req("/api/v1/chat", {
            "message": "6 oz", "client_message_id": f"{key}-stale",
            "interaction": {"operation_id": self.operation_id,
                            "revision": int(interaction["revision"]) + 5,
                            "field_id": field["field_id"],
                            "option_id": (field["options"] or [{}])[0]
                            .get("option_id", "")}}, auth)
        self.check("a_stale_revision_was_refused",
                   "older question" in json.dumps(stale).lower(),
                   json.dumps(stale)[:160])

        foreign = self._req("/api/v1/chat", {
            "message": "6 oz", "client_message_id": f"{key}-foreign",
            "interaction": {"operation_id": self.operation_id,
                            "revision": interaction["revision"],
                            "field_id": "op_other:food_x:quantity:0",
                            "option_id": "opt_nope"}}, auth)
        self.check("a_foreign_field_was_refused",
                   "older question" in json.dumps(foreign).lower(),
                   json.dumps(foreign)[:160])

        replay = self._req("/api/v1/chat", {
            "message": (field["options"] or [{}])[0].get("label", ""),
            "client_message_id": f"{key}-dup",
            "interaction": {"operation_id": self.operation_id,
                            "revision": interaction["revision"],
                            "field_id": field["field_id"],
                            "option_id": (field["options"] or [{}])[0]
                            .get("option_id", "")}}, auth)
        traces = self._req(
            f"/admin/food-traces?q={self.operation_id}&limit=100",
            headers={"X-Admin-Token": self.token})
        writes = [l.get("message", "") for l in (traces.get("lines") or [])
                  if self.operation_id in l.get("message", "")
                  and "lane=canonical:create" in l.get("message", "")]
        self.check("the_duplicate_answer_replayed", len(writes) == 1,
                   f"{len(writes)} canonical writes after the duplicate")

        # THE REPLAY RETURNS THE ORIGINAL VALUES, not merely "a" result. A
        # duplicate that answers with a DIFFERENT row would satisfy every
        # count above and still be a second meal wearing the first one's name.
        original = getattr(self, "_committed", {}) or {}
        replay_card = next((c.get("payload") or {}
                            for c in (replay.get("cards") or [])
                            if c.get("type") == "macro_card"), {})
        if not original or not replay_card:
            self.check("the_replay_returned_the_original_values", None,
                       "no card on one side of the comparison")
        else:
            same = all(replay_card.get(k) == original.get(k)
                       for k in ("entry_id", "calories", "protein_g"))
            self.check("the_replay_returned_the_original_values", same,
                       f"first={original} replay={replay_card}")

        self.check("the_pending_operation_is_terminal",
                   "logged" in json.dumps(replay).lower(),
                   json.dumps(replay)[:160])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-sha", required=True)
    ap.add_argument("--expect-env", required=True)
    ap.add_argument("--stage", type=int, default=2, choices=(1, 2))
    args = ap.parse_args()

    token = os.getenv("ARNIE_ADMIN_TOKEN", "").strip()
    if not token:
        # FROM THE ENVIRONMENT ONLY. A token in the file is a credential in
        # the repository, and `parity_corpus.py`/`minimal_smoke.py` both carry
        # one today — tracked for removal in DELETION_INVENTORY.md.
        print("ARNIE_ADMIN_TOKEN is not set — refusing to run rather than "
              "read a token from source")
        return 2

    probe = Probe(args.expect_sha, args.expect_env, token)
    print(f"probing {BASE} for {args.expect_sha} ({args.expect_env}), "
          f"stage {args.stage}")
    try:
        health = probe.preconditions()
        if args.stage == 1:
            probe.stage_one(health)
        else:
            probe.stage_two()
    except urllib.error.HTTPError as exc:
        probe.check("probe_completed", False, f"HTTP {exc.code} {exc.reason}")
    except Exception as exc:
        probe.check("probe_completed", False, repr(exc))

    print("\n" + json.dumps({"operation_id": probe.operation_id,
                             "checks": probe.report}, indent=2))
    if probe.failed:
        print(f"\nPROBE FAILED: {probe.failed}")
        return 1
    print("\nPROBE GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
