# uxr-plugin

UX research operations plugin for Claude Code, currently v0.4.0.

One plugin for the research lifecycle: study tickets, specs, recruitment, interview scripts, reports, and decks. Code owns the rules (deterministic scripts; their offline selftests live in the repo's tests/uxr_selftests/); the model owns judgment. Drafts, never sends. Hooks fail open; exclusions fail closed. See docs/ARCHITECTURE.md for the vocabulary and principles.

## Install

From a marketplace, once one is published for this plugin:

```bash
claude plugin marketplace add <owner>/<marketplace-repo>
claude plugin install uxr-plugin
```

During development, load the plugin in place from a checkout:

```bash
claude --plugin-dir /path/to/uxr-plugin
```

Install paths may contain spaces; every hook command quotes the script path for exactly that reason.

## Verify

```bash
claude plugin validate .          # manifest and component paths
python3 scripts/smoke_test.py     # the authoritative all-local gate
```

The smoke test makes no network call. It checks the version triple (manifest, README, CHANGELOG), command and skill minimums, the selftest suite (`tests/uxr_selftests/` in a checkout; skipped in a standalone install), JSON schemas, front matter, the no-tracker-writes rule for `scripts/`, and dash-free recruitment templates. Exit 0 on pass.

## Configure

The config contract ships placeholders for every key. Copy it once and fill in your organization's real values (the copy is gitignored):

```bash
cp config/org.example.yaml config/org.yaml
```

Fill the values by hand from the contract comments (there is no wizard); verify the result with `python3 lib/config.py --print`, which dumps the resolved configuration and fails loudly on a missing key. Every command, script, and hook reads configuration through that one loader, `lib/config.py:load_config()`; environment overrides use `UXR_CONFIG__SECTION__KEY=value`.

## Quick start

1. Do nothing, or configure: the universal default research root is `~/uxr-workspaces` on every OS; `config/org.yaml` `paths.research_root` or `UXR_RESEARCH_DIRS` (platform path separator) override it, and existing workspaces keep working wherever they live.
2. Open a Claude Code session inside a study folder -- any folder under a research root, or any folder (or a parent below your home directory) holding `00-overview.md`.
3. The SessionStart hook injects one routing-pointer line (router skill, command pattern, config location). Outside research folders the plugin stays silent.

## Commands

| Command | What it does |
|---|---|
| `/uxr-new` | Guided interview with evidence sweep; validates the spec, then creates the ticket |
| `/uxr-mine` | Your open studies (closed states excluded; `all` to include them) |
| `/uxr-show KEY` | One ticket rendered from spec order, UXR fields first, newest 5 comments |
| `/uxr-edit KEY` | Edit via shorthand; drift check, validate, diff-preview gate, full-body push |
| `/uxr-move KEY PHASE` | Phase transitions gated on ticket readiness (`check` shows blockers) |
| `/uxr-init KEY` | Local study workspace from `templates/workspace/` (spec guard, gitignore gate) |
| `/uxr-recruit KEY` | Roster statuses, outreach drafts, calendar holds, fail-closed preflight |
| `/uxr-debrief KEY` | File the transcript, insight recap, upload plan (dry-run first) |
| `/uxr-notebook KEY` | NotebookLM stage prompts (browser skill; sign-in stop, never credentials) |
| `/uxr-report KEY` | Tiered report, HTML render with citation checks, one HCD gate, publish |
| `/uxr-deck KEY` | Persona-capped deck outline and pptx scaffold (`--dry-run` first) |
| `/uxr-cheatsheet` | Cheat sheet rebuilt from sources; drift check with explicit `go` |
| `/uxr-eod` | End-of-day draft from today's journal (dry-run; nothing posts automatically) |
| `/uxr-trace KEY` | Provenance: sources read, outputs written, per journal + transcripts |
| `/uxr-stats` | Usage stats from journal + analytics (offline) |
| `/uxr-feedback` | File plugin feedback as a GitHub issue after explicit `go` |

All are plugin-namespaced in practice (`/uxr-plugin:uxr-new`) since Claude Code namespaces plugin commands under the plugin name.

## MCP server

`mcp-server/server.py` is an optional Model Context Protocol surface over stdio, so local CLI harnesses (zcode, codex, claude-code, hermes-style runtimes) can drive the same deterministic scripts without loading the plugin. It is stdlib-only Python, makes no network calls, imports nothing from `lib/` (it shells out to `scripts/`), and speaks BOTH MCP protocol eras (verified against modelcontextprotocol.io on 2026-11-22): the current stable `2026-07-28` per-request era (stateless requests carrying `_meta` `io.modelcontextprotocol/protocolVersion` + `clientCapabilities`; `server/discover`; unsupported versions rejected with `-32022` + `data.supported`; results carry `resultType: "complete"`) and the initialize-handshake era for today's stdio harnesses (protocol versions `2025-06-18` and `2025-11-25`; an `initialize` request selects legacy semantics for the process, per the spec's dual-era rule). Newline-delimited JSON-RPC 2.0 on stdin/stdout; all diagnostics on stderr.

Tool schemas are derived, not hand-maintained: every script declares its own argument surface in a `MCP_SURFACE` table (and self-reports it via `python scripts/<name>.py --print-mcp-surface`), and the server reads those tables to build the `tools/list` JSON Schemas and the `tools/call` argv. It exposes:

<!-- BEGIN auto-generated MCP tool table (scripts/gen_mcp_docs.py) -->

Generated by `scripts/gen_mcp_docs.py` from each script's `MCP_SURFACE` table; run it after changing a script's flags. `tools/list` serves JSON Schemas derived from the same tables.

| Tool | Script | Arguments |
|---|---|---|
| `scaffold_workspace` | `scripts/scaffold_workspace.py` | `subcommand`: slug | scaffold | lookup-workspace | render-overview | append-outreach-entry | validate-recruitment, `--title` <string>, `--quarter` <string>, `--max-body` <integer>, `--template` <string>, `--target` <string>, `--mapping` <string>, `--readme` <string>, `--spec` <string>, `--ticket` <string>, `--log-path` <string>, `--date` <string>, `--name` <string>, `--slot` <string> repeat, `--hold` <string> repeat, `--channel` <string>, `--status-from` <string>, `--status-to` <string>, `--notes` <string>, `--action` <string>, `--path` <string>, `--method` <string>, `--no-commit` |
| `build_body` | `scripts/build_body.py` | `stdin` (string, required) |
| `parse_shorthand` | `scripts/parse_shorthand.py` | `stdin` (string, required) |
| `roster_apply` | `scripts/roster_apply.py` | `--spec` <string> required, `--ops` <string> required, `--out` <string> required, `--dry-run` |
| `recruit_funnel` | `scripts/recruit_funnel.py` | `--spec` <string>, `--wave` <string>, `--funnel-data` <string>, `--check-draft` <string>, `--today` <string>, `--preflight`, `--status`, `--reminder` |
| `classify` | `scripts/classify.py` | `subcommand`: intent | reply | method | decision | route-finding, `text` (string, required), `--prefix` <string>, `--rqs` <string>, `--category` <string> |
| `report_html` | `scripts/report_html.py` | `md` (string, required), `html` (string, required) |
| `deck_render` | `scripts/deck_render.py` | `subcommand`: lint | render, `outline` (string, required), `out` (string, required) |
| `uxr_stats` | `scripts/uxr_stats.py` | `--json`, `--days` |
| `review_checks` | `scripts/review_checks.py` | `path` (string, required) |

<!-- END auto-generated MCP tool table (scripts/gen_mcp_docs.py) -->

MCP docs are generated: run `python scripts/gen_mcp_docs.py` after changing a script's flags (or `--check` to verify).

There is no publish or send tool: drafts never send. Script stdout is returned verbatim (the caller never recomputes a number a script printed); a nonzero exit comes back as an error result with the stderr tail; each call is capped at 60 seconds, runs without a shell, and pins `PYTHONIOENCODING=utf-8` so non-ASCII output survives any platform locale. `resources/list` and `resources/read` expose `references/*.md` and `prompts/*/fragments/*.md` under `uxr://references/<name>` and `uxr://fragments/<prompt-dir>-<name>` as `text/markdown`; `prompts/list` and `prompts/get` expose `commands/*.md` (front-matter description, body as the template). The initialize/discover results carry a UXR domain summary in `instructions` for host-side delegation.

Install it into one harness (writes only the `uxr` entry; backs the config up to `<config>.uxr-backup` first; a second run is a no-op; `--force` replaces an existing entry; `--dry-run` prints the plan):

```bash
python mcp-server/install.py install --harness auto    # or zcode | codex | claude-code
python mcp-server/install.py status  --harness zcode   # real handshake check
python mcp-server/install.py uninstall --harness zcode
```

| Harness | Config file | Entry shape |
|---|---|---|
| zcode | `~/.zcode/cli/config.json` | `mcp.servers.uxr` (JSON) |
| codex | `~/.codex/config.toml` | `[mcp_servers.uxr]` table (TOML) |
| claude-code | `~/.claude.json` | top-level `mcpServers.uxr` (user scope) |
| hermes | not wired in this release | status UNKNOWN; see the note the command prints |

`status` exit codes: 0 healthy (the configured server answers a real initialize handshake and lists the tools), 1 missing (no config or no `uxr` entry), 2 broken handshake, 3 unsupported harness, 4 config parse failure. Uninstall removes only the `uxr` entry. The real zcode install runs at acceptance, with the owner present; this command never touches a live config during development. Update path (MAINTENANCE law 8): bump with `claude plugin update uxr-plugin@oliver-tree-ai-marketplace`; do not pin a stale version.

### Serve over HTTP (Gemini Connected Apps)

`mcp-server/serve.py` runs the same stdio server behind a stdlib HTTP bridge with auth and prints everything needed to register it in the consumer Gemini app (Connected Apps, Developer Mode). Gemini rejects static bearer auth, so the bridge embeds a minimal OAuth 2.1 provider (RFC 8414 discovery at `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server`, RFC 7591 dynamic client registration at `/register`, auto-approved `/authorize` for the single local operator, `/token` with authorization_code + rotating refresh_token grants and PKCE S256) and accepts either an OAuth-issued access token or the static bearer token (back-compat for non-Gemini clients). Unauthenticated requests answer 401 with `WWW-Authenticate: Bearer resource_metadata="..."`, which is what starts Gemini's OAuth dance:

```bash
python mcp-server/serve.py               # tunnel via cloudflared if installed
python mcp-server/serve.py --no-tunnel   # loopback only
```

Security bar: every MCP POST needs a valid token (constant-time compares; 401 on missing or wrong token, no localhost bypass); the static token is auto-generated on first serve with `secrets.token_urlsafe(32)` and stored under the plugin's gitignored `state/` folder (never committed, never logged), as are OAuth codes (single-use, 10 minutes) and tokens (opaque, short-lived, in memory only, gone on restart); the bridge binds `127.0.0.1` only, so the only public exposure is the cloudflared quick tunnel. Without cloudflared the command prints the exact install command per OS and exits cleanly. Stdlib only; the bridge shells out to `cloudflared` but adds no Python dependencies.

## Hooks

Wiring lives in `hooks/hooks.json`. Every hook command is the same polyglot, fail-open chain -- valid in both POSIX sh (Claude Code) and Windows cmd.exe (the ZCode runtime on Windows runs hook command strings through cmd.exe, where the previous POSIX-only wrapper could not execute at all):

```
python "${CLAUDE_PLUGIN_ROOT}/hooks/<name>.py" || python3 "${CLAUDE_PLUGIN_ROOT}/hooks/<name>.py" || exit 0
```

`python` is preferred (the Windows interpreter name), `python3` covers POSIX-only systems, and any total failure -- interpreter missing, script missing, script error -- exits 0, which both harnesses read as "skip, never block".

| Event | Matcher | Script | Built in issue |
|---|---|---|---|
| SessionStart | - | `ux_research_context.py` | 02 |
| SessionStart | - | `analytics_flush.py` | 09 |
| SessionEnd | - | `session_logger.py` (timeout 15) | 09 |
| SubagentStop | - | `review_gate.py`, `analytics.py` | 06, 09 |
| PreToolUse | `Write\|Edit` | `review_gate.py` | 06 |
| UserPromptExpansion | - | `analytics.py` | 09 |
| Stop | - | `session_logger.py`, `review_gate.py`, `provenance.py`, `analytics.py` | 06, 09 |
| UserPromptSubmit | - | `analytics.py` | 09 |

Hook contract: read the event JSON from stdin, catch every exception, exit 0 on any error, print nothing unless the event contract asks for output, and set an explicit `timeout` on any hook that does file work. Hooks built in later issues are wired now; the fail-open wrapper keeps the missing scripts harmless.

## Runtime compatibility

`hooks/hooks.json` carries the Claude Code event set plus additive entries for the events the ZCode runtime supports (verified against the runtime current at each release); every hook accepts either event name, and nothing Claude Code uses was removed.

On current ZCode runtimes the following hook UX works: the session journal upserts its row on `Stop` (one row per session, updated in place, the analytics summary emitted once), the HCD review gate writes its review marker from the `Stop` transcript scan and still reminds on `PreToolUse` (a Stop fire never overwrites a marker a SubagentStop wrote on Claude Code), and analytics records slash commands on `UserPromptSubmit` plus the `SessionStart` flush (where Claude Code fires both `UserPromptSubmit` and `UserPromptExpansion` for one command, a short same-session dedup window keeps the count at one).

Still Claude Code-only: the true `SessionEnd` final write of the workspace manifests (per-turn `Stop` fires keep the journal row current without them) and the `SubagentStop` agent-dispatch counter, which has no ZCode event. Acceptable: `Stop` fires each turn, so the journal stays current without `SessionEnd`. Commands, skills, agents, scripts, and all deterministic behavior are runtime-independent. Re-check support after runtime updates (`zcode plugins install` prints unsupported-event diagnostics per plugin).

## Development

- Every selftest module in `tests/uxr_selftests/` (repo checkout) passes offline; a standalone install ships no selftest code.
- `python3 scripts/smoke_test.py` is the pre-commit and CI gate.
- CI (`.github/workflows/plugin-ci.yml`) runs the smoke test plus a non-blocking `claude plugin validate` step (the CLI may require auth in CI; the smoke gate is authoritative). The workflow fires when this repo is used standalone; GitHub only reads workflows from a repository root's `.github/workflows/`, so when the plugin is vendored at a nested path the file is inert there and the local smoke gate is the authoritative check.
