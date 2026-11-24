#!/usr/bin/env python3
"""Walkthrough completion record for onboarding (issue 114, section 3).

The onboarding walkthrough makes the operator use every critical feature
once: create an issue, move a checklist, run the prioritization
calculator, sync a change. This script is the deterministic gate behind
that law: the completion record it keeps is written by the record
command after each feature is used, and the check command exits 0 only
when all four features carry a record. The gate is a script check, never
readable text only: the onboarding command cannot print its walkthrough
completion line until this check exits 0, so finishing the walkthrough
requires the four features to have been used.

Record shape (``<state_dir>/walkthrough.json``, deterministic JSON)::

    {"format": 1, "features": {"create": {"key": "UX-42"}, ...}}

One entry per used feature, in the shipped feature order; ``key`` is the
study ticket the feature ran on, recorded verbatim (empty when the
feature needs no ticket). The record carries no timestamps and no
free text, so it stays a plain deterministic artifact.

State dir: ``--state-dir`` wins, then the researcher state law
(``UXR_STATE_DIR`` wins, then ``paths.state_dir`` from config; an
unexpanded ``${VAR}`` placeholder resolves to nothing). With no state
dir the record command exits 3 and the check command fails closed
(exit 1): the gate never passes on an unresolvable state path.

A record file that cannot parse is treated as empty: the check fails
closed with a named line, and a record write repairs the file from a
fresh record with only the new feature. Concurrent writes take the
provenance file lock, so two writers serialize instead of forking the
file; a lock timeout proceeds unlocked rather than losing a write.

Exit codes: 0 ok (record written, or check complete, or clear done),
1 check incomplete, 2 usage, 3 named error (no state dir, unwritable).

Usage::

    python scripts/walkthrough.py record --feature create --key UX-42
    python scripts/walkthrough.py check [--json]
    python scripts/walkthrough.py clear
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

try:
    from scripts.researcher_state import state_dir as _resolve_state_dir
except ImportError:  # direct execution: python scripts/walkthrough.py
    from researcher_state import state_dir as _resolve_state_dir  # type: ignore

from lib.config import load_config  # noqa: E402  (plugin root on sys.path)

#: The four walkthrough features (issue 114 section 3), in gate order.
#: The order is the record order and the missing-list order.
FEATURES = ("create", "move", "calculator", "sync")

RECORD_NAME = "walkthrough.json"
RECORD_FORMAT = 1

USAGE = (
    "usage:\n"
    "  python scripts/walkthrough.py record --feature <create|move|calculator|sync>"
    " [--key <KEY>] [--state-dir <dir>]\n"
    "  python scripts/walkthrough.py check [--json] [--state-dir <dir>]\n"
    "  python scripts/walkthrough.py clear [--state-dir <dir>]\n"
    "\n"
    "exit codes: 0 ok, 1 check incomplete, 2 usage, 3 named error."
)


def record_path(explicit: str | None, config: dict | None = None, environ=None) -> Path | None:
    """The record file path, or None when no state dir resolves.

    ``--state-dir`` wins; otherwise the researcher state law applies
    (``UXR_STATE_DIR``, then ``paths.state_dir``; an unexpanded placeholder
    is no state dir).
    """
    base = str(explicit or "").strip()
    if base:
        return Path(os.path.expandvars(os.path.expanduser(base))) / RECORD_NAME
    resolved = _resolve_state_dir(config or {}, environ=environ)
    return None if resolved is None else resolved / RECORD_NAME


def _load(path: Path | None) -> dict:
    """The parsed record, or an empty record when absent or unreadable."""
    if path is None or not path.is_file():
        return {"format": RECORD_FORMAT, "features": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"format": RECORD_FORMAT, "features": {}}
    if not isinstance(data, dict) or not isinstance(data.get("features"), dict):
        return {"format": RECORD_FORMAT, "features": {}}
    features = {
        str(name): entry if isinstance(entry, dict) else {"key": str(entry)}
        for name, entry in data["features"].items()
        if str(name) in FEATURES
    }
    return {"format": RECORD_FORMAT, "features": features}


def _save(path: Path, record: dict) -> bool:
    """Write the record under the provenance file lock; True when written.

    Two writers serialize on the lock; a lock failure proceeds unlocked
    rather than losing the write. The file keeps its own newline style
    (one trailing newline, LF).
    """
    try:
        hooks_dir = PLUGIN_ROOT / "hooks"
        if str(hooks_dir) not in sys.path:
            sys.path.insert(0, str(hooks_dir))
        from provenance import file_lock  # noqa: E402  (hooks/ sibling, lazy)
    except Exception:
        file_lock = None
    ordered = {"format": RECORD_FORMAT, "features": {}}
    for name in FEATURES:
        if name in record["features"]:
            entry = record["features"][name]
            ordered["features"][name] = {"key": str(entry.get("key") or "")}
    text = json.dumps(ordered, ensure_ascii=False) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if file_lock is not None:
            with file_lock(path.with_name(path.name + ".lock")):
                path.write_text(text, encoding="utf-8", newline="\n")
        else:
            path.write_text(text, encoding="utf-8", newline="\n")
        return True
    except OSError:
        return False


def missing_features(path: Path | None) -> list[str]:
    """The feature names with no record yet, in gate order."""
    features = _load(path)["features"]
    return [name for name in FEATURES if name not in features]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if args else 2
    command, rest = args[0], args[1:]
    if command not in ("record", "check", "clear"):
        print(f"unknown command {command!r}\n\n{USAGE}", file=sys.stderr)
        return 2
    feature = ""
    key = ""
    state_flag: str | None = None
    as_json = False
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg == "--feature":
            index += 1
            if index >= len(rest):
                print("--feature needs a value", file=sys.stderr)
                return 2
            feature = rest[index]
        elif arg == "--key":
            index += 1
            if index >= len(rest):
                print("--key needs a value", file=sys.stderr)
                return 2
            key = rest[index]
        elif arg == "--state-dir":
            index += 1
            if index >= len(rest):
                print("--state-dir needs a value", file=sys.stderr)
                return 2
            state_flag = rest[index]
        elif arg == "--json":
            as_json = True
        else:
            print(f"unknown argument {arg!r}\n\n{USAGE}", file=sys.stderr)
            return 2
        index += 1
    if command == "record":
        if not feature:
            print("record needs --feature <create|move|calculator|sync>", file=sys.stderr)
            return 2
        if feature not in FEATURES:
            print(
                f"unknown feature {feature!r}; the four features: {', '.join(FEATURES)}",
                file=sys.stderr,
            )
            return 2
        try:
            config = load_config()
        except Exception:
            config = {}
        path = record_path(state_flag, config)
        if path is None:
            print(
                "walkthrough: no state dir resolves (UXR_STATE_DIR, then "
                "paths.state_dir); pass --state-dir to record explicitly",
                file=sys.stderr,
            )
            return 3
        record = _load(path)
        record["features"][feature] = {"key": str(key).strip()}
        if not _save(path, record):
            print(f"walkthrough: cannot write the record at {path}", file=sys.stderr)
            return 3
        recorded = [name for name in FEATURES if name in record["features"]]
        still = [name for name in FEATURES if name not in record["features"]]
        print(f"walkthrough: recorded {feature} ({len(recorded)}/4 used)")
        if still:
            print(f"walkthrough: still to use: {', '.join(still)}")
        return 0
    if command == "clear":
        try:
            config = load_config()
        except Exception:
            config = {}
        path = record_path(state_flag, config)
        if path is not None and path.is_file():
            try:
                path.unlink()
            except OSError as exc:
                print(f"walkthrough: cannot remove {path} ({exc})", file=sys.stderr)
                return 3
        print("walkthrough: record cleared")
        return 0
    # check
    try:
        config = load_config()
    except Exception:
        config = {}
    path = record_path(state_flag, config)
    missing = missing_features(path)
    if as_json:
        print(json.dumps({"complete": not missing, "missing": missing}, ensure_ascii=False))
    if not missing:
        if not as_json:
            print("walkthrough complete: all four features used")
        return 0
    reason = (
        "no state dir resolves (UXR_STATE_DIR, then paths.state_dir); pass "
        "--state-dir to check explicitly"
        if path is None
        else f"missing: {', '.join(missing)}"
    )
    if not as_json:
        print(f"walkthrough incomplete ({reason})")
    else:
        print(f"walkthrough incomplete ({reason})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
