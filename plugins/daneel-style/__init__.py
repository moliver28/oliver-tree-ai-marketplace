"""Daneel style enforcement for Hermes.

Reads ~/.hermes/scripts/daneel_style_rules.yaml and enforces the voice in
two directions:

- transform_llm_output: applies every auto-fixable repair and, when
  unfixable violations remain, appends a bracketed style note so the
  model sees the correction on its next turn.
- pre_llm_call: on the first turn of a session, injects a compact
  digest of the live rules as context (after the user message).

Enable/disable: set `style_enforcement.enabled: false` in config.yaml,
or DANEEL_STYLE_ENFORCE=0 in the environment.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent
RULES_PATH = Path.home() / ".hermes" / "scripts" / "daneel_style_rules.yaml"

try:
    import yaml
except ImportError:
    yaml = None

try:
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        "daneel_style_lint", Path.home() / ".hermes" / "scripts" / "daneel_style_lint.py"
    )
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    load_rules = _mod.load_rules
    lint_text = _mod.lint_text
    fix_text = _mod.fix_text
except Exception:
    load_rules = lint_text = fix_text = None


def _enabled() -> bool:
    import os
    if os.environ.get("DANEE_STYLE_FORCE"):
        return True
    if os.environ.get("DANEE_STYLE_DISABLE") or os.environ.get("DANEE_STYLE_ENFORCE") == "0":
        return False
    # Respect config.yaml's style_enforcement.enabled when reachable.
    try:
        from hermes_cli.config import cfg_get
        from hermes_cli.config import load_cli_config  # any loader; both read the user file
        cfg = load_cli_config()
        v = cfg_get(cfg, "style_enforcement.enabled")
        if v is False:
            return False
    except Exception:
        pass
    return True


def _rules():
    if load_rules is None or yaml is None:
        return {}
    try:
        return load_rules(str(RULES_PATH))
    except Exception:
        return {}


def _note_block(text: str, rules) -> str:
    """Apply fixes and append a style-note listing unfixable violations, if any."""
    if not text:
        return text
    fixed = fix_text(text, rules)
    remaining = lint_text(fixed, rules)
    real = [v for v in remaining if v["severity"] == "error"]
    if not real:
        return fixed
    lines = [f"- {v['rule']} (line {v['line']}): {v['match']!r}" for v in real[:5]]
    note = "\n\n<style_note>Style enforcement flagged: " + "; ".join(lines) + ". Rewrite these in the next turn.</style_note>"
    return fixed + note


def register(ctx):
    """Plugin entry point."""
    def transform(response_text: str, **kwargs):
        if not _enabled() or not response_text:
            return None
        rules = _rules()
        if not rules:
            return None
        try:
            return _note_block(response_text, rules)
        except Exception:
            return None

    def pre_llm(session_id="", is_first_turn=False, **kwargs):
        if not _enabled() or yaml is None:
            return None
        try:
            data = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            return None
        summary = [
            f"- {name}: {spec.get('message', '')[:140]}"
            for name, spec in sorted((data.get("rules") or {}).items())
            if isinstance(spec, dict) and spec.get("severity") != "off"
        ]
        digest = "Daneel style enforcement is active. Current rules in force:\n" + "\n".join(summary)
        return {"context": digest}

    ctx.register_hook("transform_llm_output", transform)
    ctx.register_hook("pre_llm_call", pre_llm)