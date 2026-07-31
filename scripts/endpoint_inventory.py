"""Every HTTP surface, how it authenticates, and where the credential rides.

B7 asks four questions of the API and this answers all four from one pass:

    1. what admin/debug endpoints exist
    2. does any credential ride in a URL (path or query string)
    3. what is rate limited
    4. does every inbound webhook verify its sender

It walks the LIVE route table — `api.app:app` after every router is included —
not the source tree. A grep for `@router.post` cannot see that a route is
mounted under a prefix, and cannot see a dependency injected by `Depends`. The
route table can. Auth that comes from a dependency is therefore read off
`route.dependant`, and auth that comes from a call inside the handler is read
off the handler's own source, one level into module-level helpers.

Same rule as `mutation_inventory.py`: a marker that is not found is `unknown`,
never `false`. But unlike the mutation contract, an endpoint's auth is
determinable — if this reports `none` for something that is in fact gated, that
is a bug in this script, and `--strict` exists to make it fail loudly.

    python scripts/endpoint_inventory.py                 # the report
    python scripts/endpoint_inventory.py --json FILE     # machine-readable
    python scripts/endpoint_inventory.py --strict        # exit 1 on a finding
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The inventory only reads the route table, but importing the app builds a DB
# engine. Point it at a scratch file so a clean checkout can run this with no
# environment at all — the whole point of an inventory is that anyone can rerun
# it and get the same answer.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./_endpoint_inventory.db")

#: A parameter with one of these names carries a secret. Matched on the whole
#: name, not a substring: `token_type` is not a credential and `webhook_token`
#: is. Kept explicit so adding a new credential parameter is a deliberate act.
CREDENTIAL_PARAMS = {
    "token", "admin_token", "webhook_token", "secret", "key", "api_key",
    "apikey", "password", "credential", "access_token", "session_token",
    "sig", "signature",
}

#: How each auth mechanism proves itself. Dependency names are matched against
#: the resolved `Depends(...)` callables; source markers against the handler.
AUTH_BY_DEPENDENCY = {
    "current_identity": "session",
    "require_admin": "admin_header",
}
AUTH_BY_SOURCE = (
    ("construct_event", "webhook_signature"),         # Stripe
    ("verify_bb_signature", "webhook_signature"),      # BlueBubbles/iMessage
    ("verify_telegram_secret", "webhook_signature"),   # Telegram secret-token header
    ("TELEGRAM_BOT_TOKEN", "shared_secret"),           # Telegram path-token compare
    ("get_user_by_webhook_token", "capability_token"),
    ("verify_provider_credential", "provider_credential"),  # Apple/device sign-in
    ("verify_apple_identity_token", "provider_credential"),
    ("verify_session_token", "session"),
)

#: Anything that names one of these is limited. `ratelimit` is the shared
#: `core.ratelimit` module (matches the import and every `ratelimit.check*`
#: call); the two `_rl` names are the hand-rolled per-IP dicts that predate it
#: and are kept until they are folded into the shared limiter.
RATE_LIMIT_MARKERS = ("ratelimit", "check_request", "_signup_rl", "_prereg_rl")

#: Unauthenticated ON PURPOSE. Listing them is the point: an endpoint that is
#: public because nobody gated it and one that is public because the internet
#: must reach it look identical in a route table, and only one is a finding.
PUBLIC_BY_DESIGN = {
    "/", "/health", "/healthz", "/favicon.ico", "/favicon.png",
    "/robots.txt", "/privacy", "/terms", "/support",
    "/join", "/landing",                       # marketing / onboarding HTML
    "/imessage/start", "/api/preregister",     # rate-limited signup surfaces
    "/whoop/callback", "/oura/callback",       # OAuth redirect targets
    "/health/apple/guide",
    # Sign-in exchanges: reachable pre-auth by definition, gated by a verified
    # provider credential (Apple token / device id) and a one-time SETUP code.
    "/api/v1/auth/session", "/api/v1/auth/exchange-pairing-code",
}

ADMIN_PREFIXES = ("/admin", "/debug", "/internal", "/api/debug")


def _flatten_dependencies(dependant) -> list:
    """Every callable in a route's dependency tree, depth-first."""
    out = []
    for sub in getattr(dependant, "dependencies", []) or []:
        if sub.call is not None:
            out.append(sub.call)
        out.extend(_flatten_dependencies(sub))
    return out


def _handler_source(endpoint) -> str:
    """The handler body plus the bodies of module-level helpers it names.

    One level deep, for the same reason `mutation_inventory` stops at one: a
    full call-graph walk reaches `db.queries` and marks everything gated.
    """
    try:
        src = inspect.getsource(endpoint)
    except (OSError, TypeError):
        return ""
    module = sys.modules.get(getattr(endpoint, "__module__", ""), None)
    if module is None:
        return src
    parts = [src]
    for name, obj in vars(module).items():
        if not inspect.isfunction(obj) or obj is endpoint:
            continue
        if name not in src:
            continue
        try:
            parts.append(inspect.getsource(obj))
        except (OSError, TypeError):
            pass
    return "\n".join(parts)


def _credentials_in_url(route) -> list:
    """(location, name) for every credential-shaped parameter in the URL.

    Path and query only. A credential in a header or a cookie is not in the
    URL, which is the entire distinction B7 is asking about: URLs are written
    to proxy access logs, browser history and `Referer`, and headers are not.
    """
    found = []
    dep = route.dependant
    for field in getattr(dep, "path_params", []) or []:
        if field.name in CREDENTIAL_PARAMS:
            found.append(("path", field.name))
    for field in getattr(dep, "query_params", []) or []:
        if field.name in CREDENTIAL_PARAMS:
            found.append(("query", field.name))
    return found


def _dependency_source(route) -> str:
    """Concatenated source of every callable in the route's dependency tree.

    Auth and rate-limiting moved OUT of handlers and INTO a shared dependency
    (`require_admin`), so a scan that reads only the handler now misses both. A
    route gated by a dependency that calls `ratelimit.check_request` is rate
    limited even though its handler says nothing about it.
    """
    parts = []
    for call in _flatten_dependencies(route.dependant):
        try:
            parts.append(inspect.getsource(inspect.unwrap(call)))
        except (OSError, TypeError):
            pass
    return "\n".join(parts)


def classify(route) -> dict:
    endpoint = route.endpoint
    source = _handler_source(endpoint)
    dep_source = _dependency_source(route)

    dep_mechanisms = []
    for call in _flatten_dependencies(route.dependant):
        name = getattr(call, "__name__", "")
        if name in AUTH_BY_DEPENDENCY and AUTH_BY_DEPENDENCY[name] not in dep_mechanisms:
            dep_mechanisms.append(AUTH_BY_DEPENDENCY[name])

    # A dependency is authoritative: when a route is gated by one, a `TOKEN`
    # or `webhook_token` mentioned INSIDE its handler is incidental (the admin
    # broadcast sends with the bot token; the dashboard builds capability URLs),
    # not a second auth path. Only fall back to scanning the handler when no
    # dependency proves the auth — which is exactly the capability-token and
    # webhook-signature routes that authenticate in-handler.
    if dep_mechanisms:
        mechanisms = dep_mechanisms
    else:
        mechanisms = []
        for marker, mechanism in AUTH_BY_SOURCE:
            if marker in source and mechanism not in mechanisms:
                mechanisms.append(mechanism)

    # WebSocket routes have no `methods`. They are still a surface — one that
    # upgrades and then streams, so an ungated one leaks for as long as it lives.
    raw = getattr(route, "methods", None)
    methods = (sorted(raw - {"HEAD", "OPTIONS"}) or sorted(raw)) if raw else ["WS"]
    is_admin = route.path.startswith(ADMIN_PREFIXES)
    creds = _credentials_in_url(route)

    return {
        "path": route.path,
        "methods": methods,
        "name": getattr(endpoint, "__name__", "?"),
        "module": getattr(endpoint, "__module__", "?"),
        "admin": is_admin,
        "auth": mechanisms or ["none"],
        "credential_in_url": [f"{where}:{name}" for where, name in creds],
        "rate_limited": any(m in source or m in dep_source for m in RATE_LIMIT_MARKERS),
        "mutating": bool({"POST", "PUT", "PATCH", "DELETE"} & set(methods)),
        "public_by_design": route.path in PUBLIC_BY_DESIGN,
    }


def findings(rows: list) -> list:
    """A finding is a row that fails one of B7's four questions."""
    out = []
    for r in rows:
        if r["credential_in_url"]:
            out.append((r, f"credential in URL ({', '.join(r['credential_in_url'])})"))
        if r["auth"] == ["none"] and not r["public_by_design"]:
            out.append((r, "no authentication and not declared public"))
        if r["admin"] and not r["rate_limited"]:
            out.append((r, "admin surface with no rate limit"))
        if r["auth"] == ["shared_secret"]:
            out.append((r, "shared secret compared in the handler, not a signature"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="FILE")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any finding remains")
    args = ap.parse_args()

    from api.app import app  # imported late: it builds an engine on import

    rows = []
    for route in app.routes:
        if not hasattr(route, "dependant"):     # Mount, static files
            continue
        rows.append(classify(route))
    rows.sort(key=lambda r: (not r["admin"], r["path"]))

    def table(subset, title):
        if not subset:
            return
        print(f"\n{title}  ({len(subset)})")
        print(f"{'method':<7} {'path':<42} {'auth':<20} {'cred-in-url':<16} limited")
        print("-" * 96)
        for r in subset:
            print(f"{','.join(r['methods'])[:6]:<7} {r['path'][:41]:<42} "
                  f"{'+'.join(r['auth'])[:19]:<20} "
                  f"{(','.join(r['credential_in_url']) or '-')[:15]:<16} "
                  f"{'yes' if r['rate_limited'] else '-'}")

    print(f"\n{len(rows)} HTTP surfaces on the live route table\n")
    table([r for r in rows if r["admin"]], "ADMIN / DEBUG")
    table([r for r in rows if r["credential_in_url"] and not r["admin"]],
          "CREDENTIAL IN THE URL (non-admin)")
    table([r for r in rows if r["auth"] == ["none"] and not r["public_by_design"]
           and not r["admin"]], "UNAUTHENTICATED, NOT DECLARED PUBLIC")

    auth_counts = Counter(a for r in rows for a in r["auth"])
    print(f"\nauth mechanisms   : {dict(auth_counts)}")
    print(f"admin surfaces    : {sum(1 for r in rows if r['admin'])}")
    print(f"credential in URL : {sum(1 for r in rows if r['credential_in_url'])}")
    print(f"rate limited      : {sum(1 for r in rows if r['rate_limited'])}")

    found = findings(rows)
    print(f"\nFINDINGS: {len(found)}")
    for r, why in found:
        print(f"  {','.join(r['methods']):<6} {r['path']:<40} {why}")
    if not found:
        print("  none")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"\nwrote {len(rows)} rows to {args.json}")

    return 1 if (args.strict and found) else 0


if __name__ == "__main__":
    sys.exit(main())
