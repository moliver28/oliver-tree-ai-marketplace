#!/usr/bin/env python3
"""Adapter registry and resolver for the UX research plugin (issue 112).

The plugin splits into two halves. The harness half (commands, references,
deterministic modules) speaks the generic operations language of
``references/tracker.md``: ``current_user``, ``find_user``, ``get_item``,
``search``, ``create_item``, ``update_item``, ``list_state_changes``,
``set_state``, ``add_comment``, ``item_url``, ``normalize_key``. The sync
half is one adapter module per tracker kind: it names those operations and
binds them to the tracker's own tools. This module is the registry between
them: config-driven registration (the ``adapters`` section of the config
contract) and one resolver the harness calls instead of reaching into any
adapter module.

Interface contract. Every adapter module provides four operations; all are
deterministic, network-free, and tool-call-free:

- ``connect(config)``: the connection facts read from ``tracker.*``, with
  the keys still empty listed in ``missing`` and ``ready`` true when
  nothing is missing.
- ``pull(key, config)``: the ``normalize_key`` rule of
  ``references/tracker.md`` in code, one key at a time; returns
  ``{"key": ...}`` or ``{"error": "..."}``, never raises.
- ``push(spec, shorthands, config)``: field payloads through
  ``lib/field_map.py``, the body through ``scripts/build_body.py``;
  returns ``{"exit", "body", "fields", "stderr"}`` and keeps the existing
  exit-code contract (0 ok, 3 validation refused with zero writes, 2/4
  from build_body).
- ``spec_transform(spec, config, body_format=None)``: renders a spec into
  the tracker body format through ``lib/spec_blocks.py``; byte-identical
  to that module's output.

Registration is data, not code. ``adapters.<kind>`` in the config names
``module`` (a file path relative to the plugin root; ``""`` = declared but
not built), ``doc`` (the reference file holding that adapter's parameters;
the registry never duplicates parameter text), ``area`` (``issues`` or
``kb``), and ``capabilities`` (``pull`` / ``push`` / ``spec_transform``
booleans). ``tracker.kind`` selects the entry. A user org.yaml can point
``module`` at any importable file under the plugin root, so a local
adapter registers without code edits; nothing hardcodes a kind.

Absence is a state, not a failure: :func:`resolve` returns ``None``
silently for an empty kind, an unknown kind, and an entry whose ``module``
is empty. Configured-but-broken is a named failure: a ``module`` path that
does not exist, or importing it raises, raises :class:`ConfigError` naming
the path and the exception text. Nothing logs and nothing prints on the
absent path; the harness behaves exactly as with no tracker.

Exit codes for the CLI: 0 ok (the record as one JSON line, or ``null``
when the kind resolves to absent-sync), 2 usage, 3 named error.

Usage::

    python lib/adapters.py describe --kind jira
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Mapping
from typing import Any

try:
    from . import config as _config  # package context: import lib.adapters
except ImportError:  # direct execution: python lib/adapters.py
    import config as _config  # type: ignore

ConfigError = _config.ConfigError
PLUGIN_ROOT = _config.PLUGIN_ROOT
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))  # resolve() imports adapter modules as lib.<name>

#: The shipped registration, mirroring the ``adapters`` section of
#: ``config/org.example.yaml``. Fallback only for a config dict that lacks
#: the section (repo-level tests pass raw dicts); :func:`load_config`
#: output always carries the section, so runtime code never sees this
#: fallback. A section that is present wins: an entry it does not declare
#: is not registered.
ADAPTER_DEFAULTS: dict[str, dict[str, Any]] = {
    "jira": {
        "module": "lib/adapter_jira.py",
        "doc": "references/tracker.md",
        "area": "issues",
        "capabilities": {"pull": True, "push": True, "spec_transform": True},
    },
    "linear": {
        "module": "",
        "doc": "references/trackers-other.md",
        "area": "issues",
        "capabilities": {"pull": True, "push": True, "spec_transform": True},
    },
    "github": {
        "module": "lib/adapter_github.py",
        "doc": "references/tracker-github.md",
        "area": "issues",
        "capabilities": {"pull": True, "push": True, "spec_transform": True},
    },
    "asana": {
        "module": "",
        "doc": "references/trackers-other.md",
        "area": "issues",
        "capabilities": {"pull": True, "push": True, "spec_transform": True},
    },
    "notion": {
        "module": "",
        "doc": "references/onboarding.md",
        "area": "kb",
        "capabilities": {"pull": True, "push": False, "spec_transform": False},
    },
}

#: The three capability bits, in the order the record carries them.
CAPABILITY_NAMES = ("pull", "push", "spec_transform")


def resolve(config: Mapping[str, Any]) -> dict | None:
    """Return the adapter record for ``tracker.kind``, or None (absent-sync).

    Rules, in order:

    1. ``tracker.kind`` empty or missing: return None.
    2. No ``adapters`` mapping in ``config`` (or one that is not a
       mapping): fall back to the shipped defaults. No entry for the kind
       there either: return None.
    3. Entry ``module`` empty: return None (declared, not built).
    4. Module file missing, or importing it raises: raise ConfigError
       naming the path and the exception text.
    5. Otherwise return the plain record:
       ``{"kind", "module", "doc", "area", "capabilities"}``.

    Importing the module is the load check only; the record stays plain
    data and never carries the module object. Capability bits read from
    the entry; an undeclared bit is False (the plugin's off-by-default
    rule).
    """
    tracker = config.get("tracker") if isinstance(config, Mapping) else None
    kind = str(tracker.get("kind") or "").strip() if isinstance(tracker, Mapping) else ""
    if not kind:
        return None
    section = config.get("adapters") if isinstance(config, Mapping) else None
    if isinstance(section, Mapping):
        entry: Any = section.get(kind)
    elif kind in ADAPTER_DEFAULTS:
        entry = ADAPTER_DEFAULTS[kind]
    else:
        entry = None
    if not isinstance(entry, Mapping):
        return None
    module = str(entry.get("module") or "").strip()
    if not module:
        return None
    posix = module.replace("\\", "/")
    path = PLUGIN_ROOT / posix
    if not path.is_file():
        raise ConfigError(
            f"adapters.{kind}.module does not exist: {path} "
            "(the path is relative to the plugin root)"
        )
    module_path = posix[:-3] if posix.endswith(".py") else posix
    module_path = module_path.replace("/", ".")
    try:
        importlib.import_module(module_path)
    except Exception as exc:
        raise ConfigError(
            f"adapters.{kind}.module cannot be imported: {module} ({exc})"
        ) from exc
    bits = entry.get("capabilities")
    bits = bits if isinstance(bits, Mapping) else {}
    return {
        "kind": kind,
        "module": module,
        "doc": str(entry.get("doc") or ""),
        "area": str(entry.get("area") or ""),
        "capabilities": {name: bool(bits.get(name)) for name in CAPABILITY_NAMES},
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

USAGE = """usage:
  python lib/adapters.py describe --kind <kind>
  python lib/adapters.py --help

exit codes: 0 ok, 2 usage, 3 named error."""


def _cli_describe(rest: list[str]) -> int:
    """Handle ``describe --kind ...``; returns the process exit code."""
    kind: str | None = None
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg == "--kind":
            index += 1
            if index >= len(rest):
                print("describe: --kind needs a value", file=sys.stderr)
                return 2
            kind = rest[index]
        elif arg.startswith("--kind="):
            kind = arg[len("--kind="):]
        else:
            print(f"describe: unknown argument {arg!r}", file=sys.stderr)
            return 2
        index += 1
    if kind is None or not kind.strip():
        print("describe: --kind is required", file=sys.stderr)
        return 2
    try:
        config = _config.load_config()
        probe = dict(config)
        tracker = dict(probe.get("tracker") or {})
        tracker["kind"] = kind.strip()
        probe["tracker"] = tracker
        record = resolve(probe)
    except ConfigError as exc:
        print(f"adapters: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(record, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if not args:
        print(USAGE)
        return 2
    if args[0] == "describe":
        return _cli_describe(args[1:])
    print(f"unknown command {args[0]!r}\n\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
