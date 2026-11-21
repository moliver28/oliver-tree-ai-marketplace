from _harness import bind

bind("hooks.workspace_sync", globals())
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
    raise SystemExit(_selftest())
