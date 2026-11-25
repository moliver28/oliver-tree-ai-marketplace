"""Shared CLI dispatch plumbing for ``scripts/*.py``.

One implementation of the per-script ``main`` boilerplate (the ``-h``
banner, the ``--print-mcp-surface`` branch, the flag/switch ``while``
loop, the ``_Usage`` report), so each ``main`` states only its own
grammar. Every helper reproduces the retired per-script blocks
verbatim: the surface is a byte contract, and ``UsageError`` messages
carry exactly the text the script's existing ``except`` prints.
Import shape (after the PLUGIN_ROOT bootstrap)::

    from lib import cli as _cli  # noqa: E402  (shared plumbing)
"""

from __future__ import annotations

import json
import sys
from typing import Callable

from lib.util import force_utf8_stdio  # noqa: E402  (sibling module; caller bootstrapped PLUGIN_ROOT)


class UsageError(Exception):
    """A usage problem whose ``str`` is exactly the line the script prints."""


def parse_flags(
    args: list[str], flag_names: dict[str, str], switches: dict[str, str] | None = None,
) -> dict[str, str]:
    """The shared flag/switch ``while`` loop: ``flag_names`` maps ``--flag``
    to the result key (the next argv token is its value), ``switches`` maps
    ``--switch`` to the key and stores ``"1"``; another token, or a flag
    with no following token, raises ``UsageError`` (message unprefixed:
    the caller adds its ``prog: `` prefix when reporting)."""
    switches = switches or {}
    flags: dict[str, str] = {}
    index = 0
    while index < len(args):
        token = args[index]
        if token in flag_names:
            if index + 1 >= len(args):
                raise UsageError(f"{token} needs a value")
            flags[flag_names[token]] = args[index + 1]
            index += 2
            continue
        if token in switches:
            flags[switches[token]] = "1"
            index += 1
            continue
        raise UsageError(f"unknown argument {token!r}")
    return flags


def run_stdin(argv: list[str] | None, doc: str, mcp_surface: dict,
              run: Callable[[str], tuple[int, str, str]]) -> int:
    """The stdin-script ``main``: ``--print-mcp-surface``, ``-h``, then one
    ``run(sys.stdin.read())`` reported as ``(code, stdout, stderr)``."""
    force_utf8_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--print-mcp-surface":
        print(json.dumps(mcp_surface))
        return 0
    if args and args[0] in ("-h", "--help"):
        print(doc.strip())
        return 0
    code, stdout, stderr = run(sys.stdin.read())
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    return code


def run_main(argv: list[str] | None, prog: str, doc: str,
             run: Callable[[dict[str, str]], tuple[int, str]],
             flag_names: dict[str, str], switches: dict[str, str] | None = None,
             mcp_surface: dict | None = None) -> int:
    """The flag-script ``main``: ``--print-mcp-surface`` (when the script
    publishes one), ``-h``, ``parse_flags``, one ``run(flags)`` whose usage
    problems print ``prog: <message>`` and exit 2, and the ``(code, output)``
    stdout write."""
    force_utf8_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if mcp_surface is not None and args and args[0] == "--print-mcp-surface":
        print(json.dumps(mcp_surface))
        return 0
    if args and args[0] in ("-h", "--help"):
        print(doc.strip())
        return 0
    try:
        flags = parse_flags(args, flag_names, switches)
        code, output = run(flags)
    except UsageError as exc:
        print(f"{prog}: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(output)
    return code
