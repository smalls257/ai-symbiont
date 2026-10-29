# egress: the one door out

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/egress/`.

**Purpose.** Every outbound HTTP call from `src/` goes through `post_json`. `policy.py` is a pure function that decides whether a payload may go to an endpoint; `client.py` is the thin client that sends it and logs what left. `credentials.py` loads the Meta key from `~/.config/symbiont/meta.env` into a redacted `ApiKey` that rides on the `Destination`; `spend.py` holds the one price table and the JSON-lines ledger with total and per-run caps (`SpendCapError` before a call); `spark.py` is `SparkSession`, the priced, capped chat client (`chat` for one prompt; `converse` for tool-calling turns over `Message`s that each declare their own provenance, tool results included). A call reserves its worst-case cost under a file lock before it is sent, checking the caps against the small `<ledger>.total.json` (a full re-scan happens once per process and raises `LedgerMismatchError` on disagreement; `Ledger.rebuild_total()` repairs); every call that leaves writes a ledger line (a failed or unmetered one at a flagged estimate, never $0). Empty replies and refusals raise. The default transport refuses redirects so the bearer key never follows a `Location`.

**Violation prevented: Silent Fallback at the privacy boundary** (a private record reaching a remote model, or a refused send turning into an empty reply) and **Black Box** on egress (no record of what was sent).

## Invariants
- The allowed set of modules that open connections is exactly this package. Act 1's Glimmer client, the localhost service client and Route A's memory model use `Endpoint.LOCAL_GLIMMER` / `LOCAL_SERVICE` / `LOCAL_MEMORY_MODEL` (loopback only: it reads private session steps); semgrep `sym-single-egress` fails any other any import under `src/` outside the allowed set (stdlib minus network modules, `symbiont`, `numpy`, `vizdoom`), dynamic imports of network modules and network subprocesses; the import-linter contract `network-only-through-egress` is the second net.
- The one door in is `service/server.py` (`http.server`, literal `127.0.0.1` bind, no host parameter, no outbound call), held by semgrep `sym-service-server-transport` and one import-linter exception. Clients reach it through `Endpoint.LOCAL_SERVICE` and `post_json`; there is no second loopback check.
- Spark, Contributor and Wonder endpoints (`REMOTE`) refuse: empty provenance, any `spark_safe=False` record, SWE-chat, non-https, private hosts, and every host outside `REMOTE_HOSTS` (`api.meta.ai`; a new API is a new entry plus a policy test). Local endpoints take any provenance but only loopback/LAN hosts.
- Logs hold endpoint, host, byte size, record count and dataset names. Never the text (semgrep `sym-no-prompt-logging`).
- A new remote model API is a new `Endpoint` member plus a policy test, not a new HTTP call.

## Imports
- May import: `records`. Nothing in the pure core imports this package (`.importlinter`).

## Commands
`uv run pytest tests/egress -q`

## Review focus
Does any payload to a remote endpoint carry provenance from `Store.spark_view()`? Is any refusal path a return value instead of a raise?
