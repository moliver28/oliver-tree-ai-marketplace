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
    python scripts/build_body.py --selftest
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


def _force_utf8_stdio() -> None:
    """Keep emoji and unicode content intact on every platform pipe."""
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
    spec_text = sys.stdin.read()
    code, stdout, stderr = run(spec_text)
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

    print("scripts/build_body.py --selftest")

    spec_text = json.dumps(spec_blocks.GOLDEN_SPEC, ensure_ascii=False)

    # golden body: exit 0 and byte-identical across two runs
    first = run(spec_text, config=spec_blocks.selftest_config("markdown"))
    second = run(spec_text, config=spec_blocks.selftest_config("markdown"))
    check(
        "golden spec renders exit 0 twice with byte-identical stdout",
        first[0] == 0 and first == second and bool(first[1].strip()),
        f"codes {first[0]}/{second[0]}",
    )

    # the acceptance command: empty hypotheses exits 3 with empty stdout
    code, stdout, stderr = run('{"hypotheses": []}', config=spec_blocks.selftest_config())
    check(
        "empty hypotheses exits 3 with empty stdout and '  - ' stderr lines",
        code == 3 and stdout == "" and stderr.startswith("  - "),
        f"code={code} stdout={stdout!r} stderr={stderr!r}",
    )

    # bad JSON exits 2
    code, stdout, _ = run("{not json", config=spec_blocks.selftest_config())
    check("malformed spec JSON exits 2 with empty stdout", code == 2 and stdout == "", f"code={code}")

    # adf output is a JSON document
    code, stdout, _ = run(spec_text, config=spec_blocks.selftest_config("adf"))
    adf_ok = False
    if code == 0:
        try:
            adf_ok = json.loads(stdout).get("type") == "doc"
        except ValueError:
            adf_ok = False
    check("adf body leaves stdout as a JSON ADF document", adf_ok, f"code={code}")

    # incomplete document exits 4
    patched = spec_blocks.selftest_config()
    original = spec_blocks.assert_full_document
    try:
        spec_blocks.assert_full_document = lambda body: (False, ["injected: missing checklist"])
        code, stdout, stderr = run(spec_text, config=patched)
    finally:
        spec_blocks.assert_full_document = original
    check(
        "failed document check exits 4 with empty stdout",
        code == 4 and stdout == "" and "injected" in stderr,
        f"code={code}",
    )

    # the real CLI: the acceptance command verbatim, in a subprocess
    try:
        proc = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "build_body.py")],
            input='{"hypotheses": []}',
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            cwd=str(PLUGIN_ROOT),
        )
        check(
            "CLI echo of the acceptance command exits 3 with empty stdout",
            proc.returncode == 3 and proc.stdout == "" and proc.stderr.lstrip().startswith("-"),
            f"code={proc.returncode} stdout={proc.stdout!r}",
        )

        golden_twins = [
            subprocess.run(
                [sys.executable, str(PLUGIN_ROOT / "scripts" / "build_body.py")],
                input=spec_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                cwd=str(PLUGIN_ROOT),
            )
            for _ in range(2)
        ]
        check(
            "CLI golden spec renders byte-identical stdout on two runs",
            golden_twins[0].returncode == 0
            and golden_twins[0].stdout == golden_twins[1].stdout
            and bool(golden_twins[0].stdout.strip()),
            f"codes {golden_twins[0].returncode}/{golden_twins[1].returncode}",
        )

        adf_env = {**os.environ, "UXR_CONFIG__TRACKER__BODY_FORMAT": "adf"}
        proc = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "build_body.py")],
            input=spec_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            cwd=str(PLUGIN_ROOT),
            env=adf_env,
        )
        adf_ok = False
        if proc.returncode == 0:
            try:
                adf_ok = json.loads(proc.stdout).get("type") == "doc"
            except ValueError:
                adf_ok = False
        check("CLI honors the tracker.body_format config override", adf_ok, f"code={proc.returncode}")
    except OSError as exc:
        check("CLI subprocess checks ran", False, str(exc))

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
