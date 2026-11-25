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

``sync-references --workspace <dir>`` copies the plugin-to-workspace sync
set (``SYNC_SET``: the three checklist files and the writing-rules
registry) into the workspace: absent files copy, identical files stay
unchanged, differing files stay as recorded local overrides.

Usage::

    python hooks/workspace_sync.py sync-references --workspace <dir>
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

#: The plugin-to-workspace sync set (issue 53, design decision 2): the
#: canonical content files every study workspace carries. Plugin canonical
#: wins on create; a workspace edit is a recorded local override, never
#: clobbered by a later sync. The set appends; it never renumbers or drops.
SYNC_SET: tuple[str, ...] = (
    "references/checklists/method-selection.md",
    "references/checklists/qual-interviews.md",
    "references/checklists/quant-surveys.md",
    "references/writing-rules.md",
)


def sync_references(workspace, plugin_root=None) -> dict:
    """Copy the sync set from the plugin into the workspace; record overrides.

    Plugin-to-workspace only. A file absent from the workspace is copied.
    A workspace file identical to the plugin canonical copy is left alone.
    A workspace file that differs is a recorded local override: the
    workspace copy stays and the path lands in the summary's ``overrides``
    list. Never raises; never deletes; never writes outside the workspace.
    """
    summary = {"synced": [], "overrides": [], "unchanged": [], "reason": ""}
    try:
        root = Path(plugin_root) if plugin_root is not None else PLUGIN_ROOT
        workspace = Path(workspace)
        if not workspace.is_dir():
            summary["reason"] = "workspace missing"
            return summary
        for rel in SYNC_SET:
            source = root / rel
            target = workspace / rel
            if not source.is_file():
                continue
            payload = source.read_bytes()
            if target.is_file():
                if target.read_bytes() == payload:
                    summary["unchanged"].append(rel)
                else:
                    summary["overrides"].append(rel)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            summary["synced"].append(rel)
        return summary
    except Exception as exc:
        summary["reason"] = str(exc)[:200]
        return summary


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
        code, toplevel, _err = _git("rev-parse", "--show-toplevel", cwd=workspace)
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
    if len(args) == 3 and args[0] == "sync-references" and args[1] == "--workspace":
        result = sync_references(args[2])
        for rel in result["synced"]:
            print(f"synced: {rel}")
        for rel in result["overrides"]:
            print(f"local override kept: {rel}")
        print(
            f"sync-references: {len(result['synced'])} synced, "
            f"{len(result['overrides'])} local overrides, "
            f"{len(result['unchanged'])} unchanged"
        )
        return 0
    print(__doc__.strip().splitlines()[0])  # terse CLI pointer; full doc in this file
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
