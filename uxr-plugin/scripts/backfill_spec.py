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


def save_spec(key: str, draft_path: Path, command: str = "new") -> int:
    """Save a draft spec with the six ``_meta`` keys to
    ``<state_dir>/specs/<KEY>.spec.json`` (the ``new`` build block, scripted)."""
    try:
        spec = json.loads(draft_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"backfill_spec: unreadable draft: {exc}", file=sys.stderr)
        return 2
    if not isinstance(spec, dict):
        print("backfill_spec: the draft is not a JSON object", file=sys.stderr)
        return 2
    spec["_meta"] = spec_blocks.make_meta(command)
    try:
        from lib.config import load_config
        path = spec_blocks.spec_path(key, load_config())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:  # config or write failure: report, save nothing
        print(f"backfill_spec: spec not saved ({exc}); the ticket may exist but the spec is missing", file=sys.stderr)
        return 3
    print(path)
    return 0


def check_readback(body_path: Path) -> int:
    """Verify node counts on the read-back body (markdown/html text or an
    ADF JSON document) and print the counts plus ``counts OK`` or the
    problems (the ``new`` read-back step, scripted)."""
    from lib import spec_blocks
    text = body_path.read_text(encoding="utf-8")
    body: object = text
    if text.lstrip().startswith("{"):
        try:
            body = json.loads(text)
        except ValueError:
            pass
    ok, problems = spec_blocks.assert_full_document(body)
    print(json.dumps(spec_blocks.document_counts(body)))
    print("counts OK" if ok else "\n".join(problems))
    return 0 if ok else 4


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
    def value_of(name: str) -> str:
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else ""

    if args and args[0] == "save-spec":
        key, draft = value_of("--key"), value_of("--file")
        if key and draft:
            return save_spec(key, Path(draft).expanduser())
        print("usage: backfill_spec.py save-spec --key <KEY> --file <draft.json> [--command new]", file=sys.stderr)
        return 2
    if args and args[0] == "check-readback":
        if value_of("--file"):
            return check_readback(Path(value_of("--file")).expanduser())
        print("usage: backfill_spec.py check-readback --file <body.md>", file=sys.stderr)
        return 2
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

    # W2 build-block helpers: save-spec writes _meta; check-readback counts.
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        draft = Path(td) / "draft.json"
        draft.write_text(json.dumps({"study_title": "T", "hypotheses": [
            {"label": "H1", "text": "Falsifiable."}], "research_questions": ["Why?"]}),
            encoding="utf-8")
        os.environ["UXR_CONFIG__PATHS__STATE_DIR"] = str(Path(td) / "state")
        try:
            code = save_spec("T-1", draft)
            saved = Path(td) / "state" / "specs" / "T-1.spec.json"
            meta = json.loads(saved.read_text(encoding="utf-8")).get("_meta", {}) if saved.is_file() else {}
            check("save-spec writes the spec with six _meta keys",
                  code == 0 and len(meta) == 6, f"code={code} meta={sorted(meta)}")
            readback = Path(td) / "readback.md"
            readback.write_text(spec_blocks.build_document(
                json.loads(draft.read_text(encoding="utf-8")),
                config=spec_blocks.selftest_config("markdown")), encoding="utf-8")
            check("check-readback passes a full document", check_readback(readback) == 0)
        finally:
            os.environ.pop("UXR_CONFIG__PATHS__STATE_DIR", None)

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
