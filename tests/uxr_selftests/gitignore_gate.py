from _harness import bind

bind("scripts.gitignore_gate", globals())
def _selftest() -> int:
    """Cover ignored, not-ignored, git-error fail-closed, and usage."""
    import tempfile

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/gitignore_gate.py --selftest")

    if not _git_available():
        print("  [SKIP] git is not available; selftest cannot run meaningfully")
        print("selftest: all checks passed (1 skipped)")
        return EXIT_OK

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "ws"
        repo.mkdir()
        (repo / ".gitignore").write_text(
            "interviews/participant-key.md\ninterviews/raw-transcripts/\n", encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q", str(repo)], check=True, timeout=30)
        (repo / "interviews").mkdir()
        (repo / "interviews" / "raw-transcripts").mkdir()

        # 1. Ignored paths pass (exit 0).
        code, blocked = check_ignored(
            repo, ["interviews/raw-transcripts/x.txt", "interviews/participant-key.md"]
        )
        check("ignored paths return exit 0", code == EXIT_OK and not blocked, f"{code} {blocked}")

        # 2. A path outside the ignore rules is blocked (exit 3).
        code, blocked = check_ignored(repo, ["interviews/summary.md"])
        check(
            "not-ignored path fails closed with exit 3",
            code == EXIT_ASSERT and blocked == ["interviews/summary.md"],
            f"{code} {blocked}",
        )
        code, blocked = check_ignored(
            repo, ["interviews/raw-transcripts/a.txt", "interviews/summary.md"]
        )
        check(
            "mixed list is blocked when any path is not ignored",
            code == EXIT_ASSERT and blocked == ["interviews/summary.md"],
            f"{code} {blocked}",
        )

        # 3. A directory that is not a git repo fails closed (exit 3).
        plain = Path(td) / "plain"
        plain.mkdir()
        code, _blocked = check_ignored(plain, ["interviews/participant-key.md"])
        check("non-repo directory fails closed with exit 3", code == EXIT_ASSERT, str(code))

        # 4. A missing repo directory fails closed (exit 3).
        code, _blocked = check_ignored(Path(td) / "absent", ["x.md"])
        check("missing repo directory fails closed with exit 3", code == EXIT_ASSERT, str(code))

    # 5. Usage errors are exit 2.
    check("no --repo is a usage error", cmd_assert_ignored(["a.md"]) == EXIT_USAGE)
    check("no paths is a usage error", cmd_assert_ignored(["--repo", "."]) == EXIT_USAGE)
    check("unknown flag is a usage error", cmd_assert_ignored(["--repo", ".", "--bogus"]) == EXIT_USAGE)
    check("no subcommand handled by main", main(["assert-ignored", "--repo", "."]) == EXIT_USAGE)

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
