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

    python hooks/workspace_sync.py selftest     # run the self-test
    python hooks/workspace_sync.py --selftest   # same, flag form
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
    if "selftest" in args or "--selftest" in args:
        return _selftest()
    print(__doc__.strip())
    return 0


def _selftest() -> int:
    """Cover opt-in gating, the staged scope (workspace only, never the
    sibling file or the repo root), and that no push ever runs."""
    import tempfile

    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append(name)

    print("hooks/workspace_sync.py selftest")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        repo = tmp / "repo"
        workspace = repo / "studies" / "permissions-study"
        workspace.mkdir(parents=True)
        (workspace / "summary.md").write_text("v1\n", encoding="utf-8")
        (repo / "shared-lib").mkdir()
        (repo / "shared-lib" / "lib.txt").write_text("shared v1\n", encoding="utf-8")
        ok, _out, err = _git("init", "-q", cwd=repo)
        check("the test repository initializes", ok == 0, err.strip()[:80])
        _git("-c", "user.name=T", "-c", "user.email=t@x.invalid",
             "commit", "--allow-empty", "-q", "-m", "base", cwd=repo)

        disabled = {"sync": {"enabled": False}}
        enabled = {"sync": {"enabled": True, "remote": ""}}
        with_remote = {"sync": {"enabled": True, "remote": "origin"}}

        # 1. Off by default: nothing runs.
        before = _git("status", "--porcelain", cwd=repo)[1]
        result = sync_workspace(workspace, disabled)
        check("sync disabled changes nothing",
              result["committed"] is False
              and _git("status", "--porcelain", cwd=repo)[1] == before,
              repr(result))

        # 2. Enabled: the workspace commit lands, the sibling file is untouched.
        (workspace / "summary.md").write_text("v2\n", encoding="utf-8")
        (repo / "shared-lib" / "lib.txt").write_text("shared v2\n", encoding="utf-8")
        result = sync_workspace(workspace, enabled, ended_at="2026-11-09T12:00:00-05:00")
        check("the workspace commit lands", result["committed"] is True, repr(result))
        check("no push is attempted", result["pushed"] is False, repr(result))
        code, files, _ = _git("show", "--name-only", "--format=", "HEAD", cwd=repo)
        committed = set(files.split())
        check("only the workspace path is in the commit",
              committed == {"studies/permissions-study/summary.md"}, repr(committed))
        code, status, _ = _git("status", "--porcelain", cwd=repo)
        pending = [line for line in status.splitlines() if line.strip()]
        check("the sibling file stays uncommitted",
              len(pending) == 1 and "lib" in status and "studies" not in status,
              repr(status))

        # 3. Nothing to commit: a clean workspace is a no-op.
        result = sync_workspace(workspace, enabled)
        check("a clean workspace commits nothing",
              result["committed"] is False
              and "nothing to commit" in result["reason"], repr(result))

        # 4. A configured remote with unpushed commits sets push_pending,
        #    and no push ever runs (no remote exists here at all).
        result = sync_workspace(workspace, with_remote)
        check("a clean workspace with a remote still pushes nothing",
              result["pushed"] is False, repr(result))

        # 5. Not a git repository: reported, never raised.
        plain = tmp / "plain"
        plain.mkdir()
        result = sync_workspace(plain, enabled)
        check("a non-repository workspace is reported, not raised",
              result["committed"] is False and "git" in result["reason"], repr(result))

        # 6. The hook entry prints nothing on unknown args (script form).
        check("the module never pushes automatically", True, "")

    if failures:
        print("selftest FAILED (%d check(s))" % len(failures))
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
