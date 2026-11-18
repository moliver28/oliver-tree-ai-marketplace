---
{
  "id": "config-setup",
  "version": 1,
  "vars": [],
  "vars_source": "config",
  "when": [],
  "fragments": [],
  "default": "prompt.md",
  "budget": {"max_lines": 6, "max_vars": 0}
}
---
Load configuration once: run `python "$${CLAUDE_PLUGIN_ROOT}/lib/config.py" --print` (when `CLAUDE_PLUGIN_ROOT` is not set, run it with the path of the plugin directory that holds `lib/`, `config/`, and `references/`). Cache the resolved values for the session. Every `<placeholder>` in the command you are running is filled from that output; hardcode nothing: no organization value lives in a command or a script.
