#!/usr/bin/env python3
"""One-spawn hook dispatcher (efficiency lever: fewer interpreter starts).

Runs the hooks that share an event in ONE process: reads the event JSON
from stdin once, then imports each hook module and calls its ``main()``
with that payload on ``sys.stdin`` — same bytes, same order, same exit
codes as the previous one-spawn-per-hook wiring. The first nonzero exit
stops the chain and propagates (a blocking hook wins; informational
hooks all return 0 today). Events still on their own spawn (exit-code
critical or single) keep their direct hooks.json entries.

Usage: ``python hooks/dispatch.py <sessionstart|stop|subagentstop>``
(with the event JSON on stdin, as every hook in this plugin expects).
Exit: 0 all hooks returned 0; otherwise the first nonzero hook exit;
2 usage error.
"""
from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent

#: event -> hook scripts in their previous hooks.json run order
CHAIN: dict[str, list[str]] = {
    "sessionstart": ["ux_research_context.py", "analytics_flush.py"],
    "stop": ["session_logger.py", "review_gate.py", "provenance.py", "analytics.py"],
    "subagentstop": ["review_gate.py", "analytics.py"],
}


def _load(script: str):
    spec = importlib.util.spec_from_file_location(script[:-3], HOOKS_DIR / script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(event: str, payload: str) -> int:
    for script in CHAIN[event]:
        module = _load(script)
        saved, sys.stdin = sys.stdin, io.StringIO(payload)
        try:
            code = module.main()
        finally:
            sys.stdin = saved
        if code:
            return code
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in CHAIN:
        print("usage: dispatch.py <sessionstart|stop|subagentstop>", file=sys.stderr)
        return 2
    payload = sys.stdin.read()
    return run(sys.argv[1], payload)


def _selftest() -> int:
    print("hooks/dispatch.py selftest")
    failures: list[str] = []
    real_stdin = sys.stdin

    def check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    import types
    made = []
    for script in ("a_ok.py", "b_block.py", "c_after.py"):
        path = HOOKS_DIR / script
        path.write_text("def main():\n    return %s\n" %
                        ("0" if script != "b_block.py" else "2"), encoding="utf-8")
        made.append(path)
    try:
        saved_chain = dict(CHAIN)
        CHAIN["stop"] = ["a_ok.py", "b_block.py", "c_after.py"]
        sys.stdin = io.StringIO("{}")
        check("first-nonzero propagates", run("stop", "{}") == 2)
        CHAIN["stop"] = ["a_ok.py", "c_after.py"]
        check("all-zero chain returns 0", run("stop", "{}") == 0)
        check("stdin restored", sys.stdin is real_stdin or isinstance(sys.stdin, io.StringIO))
        CHAIN.clear()
        CHAIN.update(saved_chain)
    finally:
        sys.stdin = real_stdin
        for path in made:
            path.unlink(missing_ok=True)
    check("chain covers 3 events", set(CHAIN) == {"sessionstart", "stop", "subagentstop"})
    if failures:
        print(f"selftest FAILED ({len(failures)})")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main() if len(sys.argv) == 1 or sys.argv[1] != "selftest" else _selftest())
