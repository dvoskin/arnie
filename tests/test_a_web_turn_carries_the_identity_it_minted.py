"""The web turn mints an identity and then does not hand it over.

⛔⛔ A HALF-APPLIED FIX IS HARDER TO SEE THAN A MISSING ONE. `api/app.py`'s web
chat endpoint already carries the repair in its own comment — "THE WEB TURN GETS
AN IDENTITY … every web turn landed with turn_id NULL and any ledger event it
produced was unjoinable. Measured over an 18h production window: 5 of 77 turns,
all web." It mints `make_turn_id("web", None, user.id, text)` and binds
`CURRENT_TURN_ID`. Both correct, and both insufficient:

`core.conversation.run_turn` does not read the contextvar. It builds its trace
and its `RequestTrace` from **`kwargs["turn_id"]`**:

    fields = dict(turn_id=(kwargs.get("turn_id") or ""), …)

and the web call site passes every other argument by keyword except that one. So
the contextvar fixed the ledger stamp and left the two instruments that answer
"which turn was this" reading an empty string.

Measured in production 2026-09-10, one web control turn on 79d3611:

    event=food_trace turn=- operation=- user=u59df5811dac8 channel=web …
    turn_metrics: ('', 26, 'web', 'turn:log', 'ok', 16582, '79d3611f74d3')

⭐ THE CHANNEL WAS RIGHT AND THE TURN WAS BLANK, which is the worst shape for a
canary: it looks attributable. A per-channel measurement that cannot join a
settlement back to its turn cannot show which turn produced which row.

An AST assertion rather than a grep, for the reason `test_turn_ownership_invariant`
already gives: these modules are dense with prose about `turn_id`, and a mention
in a comment is not an argument at a call site.
"""
import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
WEB = REPO / "api" / "app.py"


def _run_turn_calls(path: pathlib.Path) -> list:
    """Every `run_turn(...)` call in a module, as (lineno, keyword names)."""
    tree = ast.parse(path.read_text())
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        if name != "run_turn":
            continue
        out.append((node.lineno, {k.arg for k in node.keywords if k.arg}))
    return out


def test_the_web_turn_hands_its_identity_to_the_pipeline():
    calls = _run_turn_calls(WEB)
    assert calls, (
        "no run_turn() call found in api/app.py — if the web endpoint moved, "
        "move this invariant with it rather than deleting it")
    for lineno, kwargs in calls:
        assert "turn_id" in kwargs, (
            f"api/app.py:{lineno} calls run_turn() without turn_id=. The "
            f"endpoint mints one and binds CURRENT_TURN_ID, but "
            f"core.conversation.run_turn reads kwargs['turn_id'] to build both "
            f"the food trace and the RequestTrace — so the turn emits "
            f"`turn=-` and a turn_metrics row keyed on ''. Keywords passed: "
            f"{sorted(kwargs)}")
