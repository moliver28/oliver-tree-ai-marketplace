#!/usr/bin/env python3
"""Optional post-session workspace commit (off by default).

Called by ``hooks/session_logger.py`` only when ``sync.enabled`` is true.
The reference plugin committed with ``git add -A`` over the whole
monorepo, shipped sync on by default, and pushed without asking; this
module fixes all three:

1. Opt-in: without ``sync.enabled: true`` in the config, nothing runs.
2. Staged scope: the commit stages exactly the workspace path --
   ``git add -- <workspace>`` from the repository toplevel -- never the
   whole repository, never a sibling folder.
3. No automatic push: a push is never performed by the hook. When
   ``sync.remote`` is set and unpushed commits exist, the result carries
   ``push_pending: true`` and the reason ``ask the user before the first
   push``; the next interactive command surfaces the question. The hook
   itself cannot ask, so it never pushes.

Anything that goes wrong is reported in ``reason`` and never raises.

Usage::

"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

GIT_TIMEOUT = 30


def _git(*args: str, cwd=None) -> tuple[int, str, str]:
    """One git call; never raises."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(cwd) if cwd else None, capture_output=True,
            text=True, timeout=GIT_TIMEOUT, encoding="utf-8", errors="replace")
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


def sync_workspace(workspace, config, ended_at: str | None = None) -> dict:
    """Commit the workspace's own changes; never push. Returns a summary."""
    summary = {"committed": False, "push_pending": False, "pushed": False,
               "reason": ""}
    try:
        sync = config.get("sync") if isinstance(config, dict) else None
        if not (isinstance(sync, dict) and sync.get("enabled")):
            summary["reason"] = "sync disabled"
            return summary
        workspace = Path(workspace)
        if not workspace.is_dir():
            summary["reason"] = "workspace missing"
            return summary
        code, toplevel, git_err = _git("rev-parse", "--show-toplevel", cwd=workspace)
        if code != 0:
            summary["reason"] = "not a git repository"
            return summary
        toplevel = Path(toplevel.strip())
        # Stage exactly the workspace path -- never -A, never the repo root.
        code, _out, stage_err = _git("add", "--", str(workspace), cwd=toplevel)
        if code != 0:
            summary["reason"] = (stage_err or "git add failed").strip()[:200]
            return summary
        code, staged, _ = _git("diff", "--cached", "--name-only", cwd=toplevel)
        if code != 0:
            summary["reason"] = "git diff --cached failed"
            return summary
        if not staged.strip():
            summary["reason"] = "nothing to commit"
            return summary
        stamp = ended_at or datetime.now().astimezone().isoformat(timespec="seconds")
        code, _out, commit_err = _git(
            "-c", "user.name=UXR session sync",
            "-c", "user.email=uxr-sync@localhost.invalid",
            "commit", "-m", "Session sync %s" % stamp, cwd=toplevel)
        if code != 0:
            summary["reason"] = (commit_err or "git commit failed").strip()[:200]
            return summary
        summary["committed"] = True
        summary["reason"] = "workspace committed"
        remote = str(sync.get("remote") or "").strip()
        if not remote:
            return summary
        code, ahead, _ = _git("rev-list", "--count", "%s..HEAD" % remote,
                              cwd=toplevel)
        if code == 0 and ahead.strip() not in ("", "0"):
            # The user is asked before the first push; the hook never pushes.
            summary["push_pending"] = True
            summary["reason"] = "ask the user before the first push"
        return summary
    except Exception as exc:
        summary["reason"] = str(exc)[:200]
        return summary


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    print(__doc__.strip().splitlines()[0])  # terse CLI pointer; full doc in this file
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
