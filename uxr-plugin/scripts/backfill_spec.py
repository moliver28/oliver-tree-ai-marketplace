#!/usr/bin/env python3
"""Recover a partial study spec from a live ticket body (issue 04).

Reads a ticket body on stdin -- rendered text (markdown or html) or an ADF
document as JSON -- and prints the recovered spec JSON on stdout. This is
the best-effort reverse path for tickets that predate their spec file: it
recovers ``history``, ``decision``, ``hypotheses``, ``research_questions``,
and ``roster`` as ``{name, status}`` rows, skipping placeholder content.

It validates nothing and writes nothing. The user reviews the output and
saves it themselves (usually to ``<state_dir>/specs/<KEY>.spec.json``). A
recovered spec has no ``_meta``; the next edit must set
``tracker_updated_at``. Never raise on body content: anything
unrecoverable is simply left out, and a body with nothing recoverable
prints ``{}``.

Exit codes: 0 always (recovery is best effort; empty recovery is a valid
result the user reviews).

Usage::

    python scripts/backfill_spec.py < live-body.md > recovered.spec.json
    python scripts/backfill_spec.py --selftest
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib import spec_blocks  # noqa: E402


def run(body_text: str) -> tuple[int, str, str]:
    """Recover a spec from one body text; return ``(exit_code, stdout, stderr)``."""
    spec = spec_blocks.spec_from_body(body_text)
    stdout = json.dumps(spec, ensure_ascii=False, indent=2) + "\n"
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


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/backfill_spec.py --selftest")

    golden = spec_blocks.GOLDEN_SPEC
    expected_roster = [
        {"name": "Ada Example", "status": "Scheduled"},
        {"name": "Rook Example", "status": "Potential Candidate"},
    ]

    md_body = spec_blocks.build_document(golden, config=spec_blocks.selftest_config("markdown"))
    code, stdout, _ = run(md_body)
    spec = json.loads(stdout) if code == 0 and stdout.strip() else {}
    check(
        "markdown body recovers history, decision, hypotheses, and RQs",
        code == 0
        and spec.get("history") == golden["history"]
        and spec.get("decision") == golden["decision"]
        and spec.get("hypotheses") == golden["hypotheses"]
        and spec.get("research_questions") == golden["research_questions"],
        f"code={code} spec={json.dumps(spec, ensure_ascii=False)[:200]}",
    )
    check(
        "markdown body recovers the roster with names and statuses",
        spec.get("roster") == expected_roster,
        repr(spec.get("roster")),
    )
    check(
        "recovered spec carries no _meta",
        "_meta" not in spec,
    )

    adf_body = spec_blocks.build_document(golden, config=spec_blocks.selftest_config("adf"))
    code, stdout, _ = run(json.dumps(adf_body, ensure_ascii=False))
    adf_spec = json.loads(stdout) if code == 0 and stdout.strip() else {}
    check(
        "ADF JSON body recovers the same fields",
        code == 0
        and adf_spec.get("history") == golden["history"]
        and adf_spec.get("hypotheses") == golden["hypotheses"]
        and adf_spec.get("roster") == expected_roster,
        f"code={code} spec={json.dumps(adf_spec, ensure_ascii=False)[:200]}",
    )

    html_body = spec_blocks.build_document(golden, config=spec_blocks.selftest_config("html"))
    code, stdout, _ = run(html_body)
    html_spec = json.loads(stdout) if code == 0 and stdout.strip() else {}
    check(
        "html body recovers history, hypotheses, and the roster",
        code == 0
        and html_spec.get("history") == golden["history"]
        and html_spec.get("hypotheses") == golden["hypotheses"]
        and html_spec.get("roster") == expected_roster,
        f"code={code} spec={json.dumps(html_spec, ensure_ascii=False)[:200]}",
    )

    code, stdout, _ = run("")
    check("empty input prints {} and exits 0", code == 0 and json.loads(stdout) == {}, f"stdout={stdout!r}")

    placeholder_body = spec_blocks.build_document({}, config=spec_blocks.selftest_config())
    code, stdout, _ = run(placeholder_body)
    check(
        "placeholder-only body recovers nothing",
        code == 0 and json.loads(stdout) == {},
        f"stdout={stdout[:120]!r}",
    )

    for junk in ("}}garbage{{{", "<not html", "plain words only", '{"type": "doc"}'):
        code, stdout, _ = run(junk)
        ok = code == 0 and isinstance(json.loads(stdout), dict)
        check(f"junk input ({junk[:14]!r}) exits 0 with a JSON object", ok, f"code={code}")

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
