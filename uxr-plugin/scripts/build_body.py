#!/usr/bin/env python3
"""Render a study spec into the tracker ticket body (issue 04).

The deterministic half of every write command: spec JSON on stdin, rendered
body on stdout. Rendering never talks to a tracker and never writes files --
the command that calls this script previews the body and pushes it through
the tracker adapter (``references/tracker.md``).

Exit codes:

- 0: body rendered; it is on stdout as text (markdown, html) or pretty
  JSON (adf, per ``tracker.body_format``).
- 2: stdin was not valid JSON, or a configuration error.
- 3: ``validate_spec`` failed; every error is on stderr as ``  - <error>``
  and stdout stays empty. A validation failure means zero tracker calls
  and zero file writes.
- 4: the rendered document failed ``assert_full_document`` (missing or
  duplicated template blocks); problems are on stderr, stdout stays empty.

Usage::

    python scripts/build_body.py < spec.json > body.txt
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib import config as _config  # noqa: E402
from lib import spec_blocks  # noqa: E402
from lib import cli as _cli  # noqa: E402  (shared plumbing)


def _dump(body: dict | str) -> str:
    """Serialize the body for stdout: text as-is, ADF as pretty JSON."""
    if isinstance(body, str):
        return body + "\n"
    return json.dumps(body, ensure_ascii=False, indent=2) + "\n"


def run(spec_text: str, config: dict | None = None) -> tuple[int, str, str]:
    """Render one spec text; return ``(exit_code, stdout, stderr)``."""
    try:
        spec = json.loads(spec_text)
    except ValueError as exc:
        return 2, "", f"build_body: spec is not valid JSON: {exc}\n"
    if config is None:
        try:
            config = _config.load_config()
        except _config.ConfigError as exc:
            return 2, "", f"build_body: config error: {exc}\n"
    ok, errors = spec_blocks.validate_spec(spec, config=config)
    if not ok:
        return 3, "", "".join(f"  - {error}\n" for error in errors)
    try:
        body = spec_blocks.build_document(spec, config=config)
    except ValueError as exc:
        return 2, "", f"build_body: {exc}\n"
    complete, problems = spec_blocks.assert_full_document(body)
    if not complete:
        return 4, "", "".join(f"  - {problem}\n" for problem in problems)
    return 0, _dump(body), ""


MCP_SURFACE = {
    "description": (
        "build_body.py: render a study spec into the tracker ticket body. Pass "
        "the spec JSON in 'stdin'; the rendered body comes back on stdout "
        "(markdown, html, or ADF JSON). Exit 3 means the spec failed "
        "validation; a validation failure makes zero tracker calls."),
    "flags": [],
    "stdin": {"name": "stdin", "required": True, "help": "the study spec JSON document"},
}


def main(argv: list[str] | None = None) -> int:
    return _cli.run_stdin(argv, doc=__doc__, mcp_surface=MCP_SURFACE, run=run)


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    raise SystemExit(main())
