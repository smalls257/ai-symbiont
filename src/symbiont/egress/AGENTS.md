# egress: the one door out

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/egress/`.

**Purpose.** Every outbound HTTP call from `src/` goes through this package, and it has two halves.

- **Shipped (the published wheel):** `policy.py` decides whether a payload may go to a local endpoint and `client.py` (`post_json`) sends it and logs what left. Every `Endpoint` is local (`LOCAL_SERVICE` and `LOCAL_MEMORY_MODEL` loopback only, `LOCAL_GLIMMER` loopback or LAN); no remote host and no credential exist in these files, so an install cannot reach a remote model. `download.py` is the GET-only Hugging Face door for the nightly kit.
- **Research only (excluded from the wheel in `pyproject.toml`, guarded by `tests/test_published_wheel.py`):** `remote_send.py` is the remote door (`RemoteEndpoint`, `RemoteDestination` with the redacted `ApiKey`, `check_remote`, `post_remote_json`, `REMOTE_HOSTS` derived from `providers.PROVIDERS`). `credentials.py` loads the Meta key from `~/.config/symbiont/meta.env`; `spend.py` holds the one price table and the JSON-lines ledger with total and per-run caps (`SpendCapError` before a call); `remote_chat.py` holds `RemoteChatSession(provider)`, the priced, capped chat client (`chat` for one prompt; `converse` for tool-calling turns over `Message`s that each declare their own provenance, tool results included). A call reserves its worst-case cost under a file lock before it is sent, checking the caps against the small `<ledger>.total.json` (a full re-scan happens once per process and raises `LedgerMismatchError` on disagreement; `Ledger.rebuild_total()` repairs); every call that leaves writes a ledger line (a failed or unmetered one at a flagged estimate, never $0). Empty replies and refusals raise. Both doors share `open_without_redirects`, so the bearer key never follows a `Location`.

A shipped module never imports a research one; the wheel test builds the wheel and fails on any import that does not resolve inside it.

**Violation prevented: Silent Fallback at the privacy boundary** (a private record reaching a remote model, or a refused send turning into an empty reply) and **Black Box** on egress (no record of what was sent).

## Invariants
- The allowed set of modules that open connections is exactly this package. Act 1's Glimmer client, the localhost service client and Route A's memory model use `Endpoint.LOCAL_GLIMMER` / `LOCAL_SERVICE` / `LOCAL_MEMORY_MODEL` (loopback only: it reads private session steps); semgrep `sym-single-egress` fails any other any import under `src/` outside the allowed set (stdlib minus network modules, `symbiont`, `numpy`, `vizdoom`), dynamic imports of network modules and network subprocesses; the import-linter contract `network-only-through-egress` is the second net.
- The one door in is `service/server.py` (`http.server`, literal `127.0.0.1` bind, no host parameter, no outbound call), held by semgrep `sym-service-server-transport` and one import-linter exception. Clients reach it through `Endpoint.LOCAL_SERVICE` and `post_json`; there is no second loopback check.
- Remote chat, Contributor and Wonder endpoints (`RemoteEndpoint`, research only) refuse: empty provenance, any `remote_safe=False` record, SWE-chat, non-https, private hosts, and every host outside `REMOTE_HOSTS` (derived from `PROVIDERS`; `api.meta.ai` today; a new API is a new `PROVIDERS` entry plus a test in `test_remote_send.py`, never a setting). Local endpoints take any payload but only loopback/LAN hosts.
- Logs hold endpoint, host, byte size, record count and dataset names. Never the text (semgrep `sym-no-prompt-logging`).
- `download.py` is the second door: GET-only model-file downloads from Hugging Face (`download_file`, `get_json`), owner-approved so the MCP tool can fetch the Llama base (`unsloth/Llama-3.2-1B-Instruct`, a public copy of Meta's weights; the meta-llama repo is gated) and the nightly kit. https only; hosts `huggingface.co` and `*.hf.co` (measured redirect targets: `us.aws.cdn.hf.co`, formerly `cas-bridge.xethub.hf.co`, `cdn-lfs*.hf.co`), checked on the URL and on every redirect; no payload, no credential; temp file, exact-size check, atomic rename; logs host and path, never the query. Tests use a fake opener.
- A new remote model API is a new `PROVIDERS` entry on the research side, never a new `Endpoint` in the shipped policy.

## Imports
- May import: `records`. Nothing in the pure core imports this package (`.importlinter`).

## Commands
`uv run pytest tests/egress -q`

## Review focus
Does any payload to a remote endpoint carry provenance from `Store.remote_view()`? Does a shipped file now import a research one (the wheel test says so)? Is any refusal path a return value instead of a raise?
