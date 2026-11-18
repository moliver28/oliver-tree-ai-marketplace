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
    python scripts/parse_shorthand.py --selftest
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


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in args or (args and args[0] == "selftest"):
        return _selftest()
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


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/parse_shorthand.py --selftest")

    # the acceptance example, byte for byte
    code, stdout, stderr = run(_ACCEPTANCE_REQUEST)
    check(
        "roster+= acceptance request prints the exact delta",
        code == 0 and stdout.strip() == _ACCEPTANCE_OUTPUT and stderr == "",
        f"code={code} stdout={stdout!r} stderr={stderr!r}",
    )
    if code == 0:
        parsed = json.loads(stdout)
        check(
            "roster+= delta round-trips as the expected object",
            parsed == {
                "name": "Ada",
                "email": "ada@x.io",
                "slack": "",
                "reason": "",
                "status": "Scheduled",
                "channel": "internal",
            },
            repr(parsed),
        )
        check(
            "delta keys keep the roster field order",
            list(parsed.keys()) == ["name", "email", "slack", "reason", "status", "channel"],
            repr(list(parsed.keys())),
        )

    # resources url remap (acceptance)
    code, stdout, _ = run('{"kind":"resources","op":"+=","arg":"Plan|https://x|shared|"}')
    delta = json.loads(stdout) if code == 0 else {}
    check(
        "resources+= writes url, never url_or_text",
        code == 0
        and delta.get("url") == "https://x"
        and "url_or_text" not in delta
        and delta.get("share_status") == "shared",
        f"code={code} delta={delta}",
    )

    # list and patch shapes
    cases = (
        (
            "resources+= non-http value lands in text",
            '{"kind":"resources","op":"+=","arg":"Notes|plain context|"}',
            0,
            {"label": "Notes", "text": "plain context", "share_status": "", "share_note": ""},
        ),
        (
            "hypotheses+= yields label and text",
            '{"kind":"hypotheses","op":"+=","arg":"H3|Export is findable."}',
            0,
            {"label": "H3", "text": "Export is findable."},
        ),
        (
            "assumptions+= yields label and text",
            '{"kind":"assumptions","op":"+=","arg":"A2|Surveys skew to power users"}',
            0,
            {"label": "A2", "text": "Surveys skew to power users"},
        ),
        (
            "roster~= returns match and one-field patch",
            '{"kind":"roster","op":"~=","arg":"ada|status=Data Collected"}',
            0,
            {"match": "ada", "set": {"status": "Data Collected"}},
        ),
        (
            "roster-= returns the match name",
            '{"kind":"roster","op":"-=","arg":"Ada Example"}',
            0,
            {"match": "Ada Example"},
        ),
        (
            "resources~= maps url_or_text in the patch",
            '{"kind":"resources","op":"~=","arg":"Plan|url_or_text=https://y"}',
            0,
            {"match": "Plan", "set": {"url": "https://y"}},
        ),
        (
            "hypotheses-= returns the match label",
            '{"kind":"hypotheses","op":"-=","arg":"H3"}',
            0,
            {"match": "H3"},
        ),
    )
    for name, request, want_code, want_delta in cases:
        code, stdout, stderr = run(request)
        try:
            got = json.loads(stdout) if stdout.strip() else None
        except ValueError:
            got = None
        check(name, code == want_code and got == want_delta, f"code={code} stdout={stdout!r} stderr={stderr!r}")

    # rejections
    rejections = (
        (
            "malformed request JSON exits 2",
            "{oops",
            2,
        ),
        (
            "unknown kind exits 2",
            '{"kind":"milestones","op":"+=","arg":"x"}',
            2,
        ),
        (
            "non-string arg exits 2",
            '{"kind":"roster","op":"+=","arg":42}',
            2,
        ),
        (
            "non-object request exits 2",
            '["roster"]',
            2,
        ),
        (
            "unknown op exits 3",
            '{"kind":"roster","op":"=","arg":"Ada"}',
            3,
        ),
        (
            "roster+= without a name exits 3",
            '{"kind":"roster","op":"+=","arg":"|a@b"}',
            3,
        ),
        (
            "roster~= with an unknown field exits 3",
            '{"kind":"roster","op":"~=","arg":"Ada|bogus=1"}',
            3,
        ),
        (
            "resources+= with too many parts exits 3",
            '{"kind":"resources","op":"+=","arg":"a|b|c|d|e"}',
            3,
        ),
    )
    for name, request, want_code in rejections:
        code, stdout, _ = run(request)
        check(name, code == want_code and stdout == "", f"code={code} stdout={stdout!r}")

    # the acceptance command through the real CLI
    try:
        proc = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "parse_shorthand.py")],
            input=_ACCEPTANCE_REQUEST,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            cwd=str(PLUGIN_ROOT),
        )
        check(
            "CLI prints the exact acceptance delta and exits 0",
            proc.returncode == 0 and proc.stdout.strip() == _ACCEPTANCE_OUTPUT,
            f"code={proc.returncode} stdout={proc.stdout!r}",
        )
    except OSError as exc:
        check("CLI subprocess check ran", False, str(exc))

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
