#!/usr/bin/env python3
"""Parse an edit shorthand into a JSON delta (issue 04).

Commands read the user's shorthand and hand it here for the deterministic
half: stdin carries ``{"kind": "roster|hypotheses|assumptions|resources",
"op": "+=|~=|-=", "arg": "<pipe string>"}`` and stdout carries one JSON
delta the command applies to the spec. This script never touches the spec
file or the tracker.

Shorthand shapes:

- ``roster+=Name|email|slack|reason|status|channel`` -- missing parts pad
  with ``""``; empty status becomes ``Potential Candidate``, empty channel
  becomes ``internal``.
- ``roster~=Name|field=value`` -- patch one roster field; the command
  matches the name case-insensitively as a substring.
- ``roster-=Name`` -- remove; exact case-insensitive name match.
- ``hypotheses+=Label|Text`` and ``assumptions+=Label|Text`` -- fields are
  ``(label, text)``.
- ``resources+=Label|Url-or-Text|Share-status|Share-note`` -- the second
  part lands in ``url`` when it starts with ``http``, otherwise in
  ``text``; never as ``url_or_text``.
- ``~=`` on lists returns ``{"match": label, "set": {field: value}}``;
  ``-=`` returns ``{"match": label}``.

Exit codes: 0 ok, 2 bad request (invalid JSON, unknown kind, wrong types),
3 rejected shorthand. On any nonzero exit stdout stays empty.

Usage::

    echo '{"kind":"roster","op":"+=","arg":"Ada|ada@x.io|||Scheduled|"}' \\
      | python scripts/parse_shorthand.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib import spec_blocks  # noqa: E402
from lib.util import force_utf8_stdio as _force_utf8_stdio  # noqa: E402  (shared plumbing)

OPERATORS = ("+=", "~=", "-=")


def run(request_text: str) -> tuple[int, str, str]:
    """Parse one shorthand request; return ``(exit_code, stdout, stderr)``."""
    try:
        request = json.loads(request_text)
    except ValueError as exc:
        return 2, "", f"parse_shorthand: request is not valid JSON: {exc}\n"
    if not isinstance(request, dict):
        return 2, "", "parse_shorthand: request must be a JSON object\n"
    kind = request.get("kind")
    op = request.get("op")
    arg = request.get("arg")
    fields = spec_blocks.LIST_SHORTHAND_FIELDS.get(str(kind)) if kind is not None else None
    if kind != "roster" and fields is None:
        known = ", ".join(["roster", *spec_blocks.LIST_SHORTHAND_FIELDS])
        return 2, "", f"parse_shorthand: unknown kind {kind!r}; expected one of {known}\n"
    if not isinstance(arg, str):
        return 2, "", "parse_shorthand: 'arg' must be a string\n"
    if op not in OPERATORS:
        return 3, "", f"parse_shorthand: unknown op {op!r}; use one of {', '.join(OPERATORS)}\n"
    try:
        if kind == "roster":
            delta = spec_blocks.parse_roster_shorthand(op, arg)
        else:
            delta = spec_blocks.parse_list_shorthand(op, arg, fields)
    except ValueError as exc:
        return 3, "", f"parse_shorthand: {exc}\n"
    stdout = json.dumps(delta, ensure_ascii=False, separators=(",", ":")) + "\n"
    return 0, stdout, ""


MCP_SURFACE = {
    "description": (
        "parse_shorthand.py: parse one edit-shorthand request into a JSON "
        "delta. Pass one request JSON object in 'stdin': kind is one of "
        "roster|hypotheses|assumptions|resources, op is one of +=|~=|=, and "
        "arg carries the pipe string."),
    "flags": [],
    "stdin": {"name": "stdin", "required": True, "help": "the shorthand request JSON"},
}


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--print-mcp-surface":
        print(json.dumps(MCP_SURFACE))
        return 0
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    code, stdout, stderr = run(sys.stdin.read())
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    return code


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

_ACCEPTANCE_REQUEST = '{"kind":"roster","op":"+=","arg":"Ada|ada@x.io|||Scheduled|"}'
_ACCEPTANCE_OUTPUT = (
    '{"name":"Ada","email":"ada@x.io","slack":"","reason":"","status":"Scheduled","channel":"internal"}'
)


if __name__ == "__main__":
    raise SystemExit(main())
