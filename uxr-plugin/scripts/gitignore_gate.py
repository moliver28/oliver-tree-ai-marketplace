#!/usr/bin/env python3
"""Gitignore gate: assert that participant-data paths are ignored (issue 08).

The people-protecting check that runs before any participant data or
deliverable is written. ``init`` runs it right after scaffolding a
workspace; ``debrief`` and ``report`` run it before they write raw
transcripts, the participant key, or deliverable files. It fails closed:
any git error is exit 3, never a pass.

Usage::

    python scripts/gitignore_gate.py assert-ignored --repo <dir> <paths...>

For each path the gate runs ``git -C <dir> check-ignore -q <path>``
(exit 0 means the path is ignored). Exit codes:

- 0: every path is ignored; writes may proceed.
- 2: usage error (no subcommand, no ``--repo``, no paths, unknown flag).
- 3: at least one path is not ignored, or git itself failed. Never
  proceed past a 3.

Output: one ``[ok] <path>`` / ``[BLOCKED] <path>`` line per path, then a
summary line on stdout. Errors go to stderr. The gate computes and
prints; it never edits ``.gitignore`` itself.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_ASSERT = 3


def _git_available() -> bool:
    try:
        proc = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def check_ignored(repo: Path, paths: list[str]) -> tuple[int, list[str]]:
    """Check every path; return ``(exit_code, blocked_paths)``.

    Runs ``git -C <repo> check-ignore -q <path>`` once per path: exit 0
    means ignored, exit 1 means not ignored, anything else is a git
    failure. A git failure (missing git, missing repo, bad option) fails
    closed as ``EXIT_ASSERT``.
    """
    blocked: list[str] = []
    git_error = ""
    for path in paths:
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo), "check-ignore", "-q", path],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            git_error = f"git check-ignore failed for {path}: {exc}"
            break
        if proc.returncode == 0:
            continue
        if proc.returncode == 1:
            blocked.append(path)
            continue
        git_error = (
            f"git check-ignore failed for {path} with exit {proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
        break
    if git_error:
        print(f"gitignore_gate: {git_error}", file=sys.stderr)
        if not _git_available():
            print("gitignore_gate: git is not runnable on this machine", file=sys.stderr)
        return EXIT_ASSERT, paths
    return (EXIT_OK if not blocked else EXIT_ASSERT), blocked


def _repo_is_git_dir(repo: Path) -> bool:
    if not repo.is_dir():
        return False
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def cmd_assert_ignored(args: list[str]) -> int:
    repo_value = ""
    paths: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--repo":
            index += 1
            if index >= len(args):
                print("gitignore_gate: --repo needs a value", file=sys.stderr)
                return EXIT_USAGE
            repo_value = args[index]
        elif token.startswith("--repo="):
            repo_value = token[len("--repo="):]
        elif token.startswith("-"):
            print(f"gitignore_gate: unknown flag {token!r}", file=sys.stderr)
            return EXIT_USAGE
        else:
            paths.append(token)
        index += 1
    if not repo_value:
        print("gitignore_gate: --repo <dir> is required", file=sys.stderr)
        return EXIT_USAGE
    if not paths:
        print("gitignore_gate: at least one path to check is required", file=sys.stderr)
        return EXIT_USAGE
    repo = Path(repo_value).expanduser()
    if not repo.is_dir():
        print(f"gitignore_gate: repo directory not found: {repo}", file=sys.stderr)
        return EXIT_ASSERT
    code, blocked = check_ignored(repo, paths)
    for path in paths:
        mark = "BLOCKED" if path in blocked else "ok"
        print(f"  [{mark}] {path}")
    if code == EXIT_OK:
        print("gitignore gate: all paths are ignored; writes may proceed")
    else:
        print(
            "gitignore gate: BLOCKED - the paths above are not ignored. "
            "Fix <workspace>/.gitignore before writing participant data.",
            file=sys.stderr,
        )
    if code == EXIT_ASSERT and blocked and not _repo_is_git_dir(repo):
        print(
            f"gitignore_gate: {repo} is not a git repository, so check-ignore "
            "cannot pass; init the repository first",
            file=sys.stderr,
        )
    return code


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__.strip().splitlines()[0])  # terse bare-run pointer; -h prints the full doc
        return EXIT_OK
    if args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_USAGE
    if args[0] == "assert-ignored":
        return cmd_assert_ignored(args[1:])
    print(f"gitignore_gate: unknown subcommand {args[0]!r}", file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
