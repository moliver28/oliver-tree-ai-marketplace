# VET-NOTES — uxr-plugin staging

Staged: 2026-11-17 from the local `uxr-plugin` checkout @ `a0c274f` ("fix(hooks): cmd.exe-compatible polyglot hook commands").
Source repo was NOT modified. Excluded from staging: `.git/` (310 files), `__pycache__/` + `*.pyc` (22), `.token-optimizer/` (14). Staged content: 106 files, byte-identical to source except the redactions below.

## Redactions applied to the staged copy (only file modified: `config/org.example.yaml`)

Employer/brand name leakage in "Example shape" comments — the brand of the
organization this plugin was originally built for appeared as example values.
Replaced with neutral placeholders (details of the original strings are held by
the marketplace orchestrator, not repeated here):

- Line 32 (`tracker.base_url` example): real tenant URL -> `https://your-company.atlassian.net`
- Line 203 (`org.internal_domains` example): two real domains -> `["your-company.com", "your-company.co"]`
- Line 208 (`org.brand_name` example): real brand name -> `Your Company`

No other file was modified. All other "example shape" values were already generic.

## Vet results

1. Secrets: none. All `api_key` occurrences are empty config defaults
   (`api_key: ""`), function signatures, or a test dummy (`"k"`). The one
   `Bearer` occurrence builds a header from a runtime-configured value. No
   private keys, high-entropy tokens, or credential-bearing URLs.
2. Personal data: none beyond the redactions above. `references/personas.json`
   holds audience archetypes (Leadership, Design team, ...), not real people.
   All names/emails in tests are fictional fixtures (Ada, Rook Example, Vera
   Vendor, ada@example.com, acme.example, ...). No phone numbers.
   `moliver28` appears only as author attribution (plugin.json, repo slug,
   schema `$id` URLs on the author's github.io).
3. Machine-bound paths: none (`F:\`, `F:/`, `C:\Users`, `C:/Users` all zero hits).
4. Dangling refs: none. All `hooks/hooks.json` script paths, `plugin.json`
   dirs (`./commands`, `./skills`), and cross-file references resolve.
   `config/org.yaml` is referenced but intentionally absent: it is the
   documented, gitignored per-organization config users create from
   `org.example.yaml`.

## Kept metadata

- `.claude-plugin/plugin.json`: version 0.1.0, author `moliver28` (approved attribution).
- `.claude-plugin/marketplace.json`: version 0.1.0.

## Marketplace-law edits applied on port (2026-11-17)

After staging, these files were edited in the oliver-tree-ai-marketplace copy to pass the
marketplace description law and changelog heading law (verify.py). No other file changed.

- `skills/interview-script/SKILL.md`, `skills/notebooklm/SKILL.md`, `skills/ux-research-tickets/SKILL.md`:
  descriptions rewritten to carry the required `use when the user says` trigger phrases and stay under the length cap.
- `CHANGELOG.md`: release heading changed to Keep a Changelog bracket form `## [0.1.0] - 2026-11-09` (content unchanged).
- `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`: descriptions updated to the same trigger-phrase form.
