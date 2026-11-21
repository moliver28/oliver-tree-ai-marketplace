from _harness import bind

bind("scripts.publish_artifact", globals())
def _selftest() -> int:
    """Offline checks with a throwaway git repo and a bare remote."""
    import tempfile

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        suffix = f" ({detail})" if detail else ""
        print(f"  [{'ok' if condition else 'FAIL'}] {name}{suffix}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/publish_artifact.py selftest")

    module_source = Path(__file__).read_text(encoding="utf-8")
    quote = chr(34)
    needles = (
        quote + "push" + quote + ", " + quote + "--for" + "ce" + quote,
        quote + "sta" + "sh" + quote,
        quote + "re" + "set" + quote,
    )
    check(
        "no force-push, stash, or reset git calls in this module",
        all(needle not in module_source for needle in needles),
    )

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        repo = tmp / "gallery"
        repo.mkdir()
        for args in (
            ("git", "init", "-b", "main", str(repo)),
            ("git", "-C", str(repo), "config", "user.name", "Gallery Bot"),
            ("git", "-C", str(repo), "config", "user.email", "gallery@example.invalid"),
        ):
            subprocess.run(args, capture_output=True, text=True, check=True)
        (repo / "README.md").write_text("# Gallery\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"],
                       capture_output=True, text=True, check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"],
                       capture_output=True, text=True, check=True)
        bare = tmp / "remote.git"
        subprocess.run(["git", "init", "--bare", str(bare)],
                       capture_output=True, text=True, check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(bare)],
                       capture_output=True, text=True, check=True)

        source = tmp / "report.html"
        source.write_text(
            "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<title>report</title></head><body>report body</body></html>\n",
            encoding="utf-8",
        )
        common = {
            "ticket": "ABC-237", "pod": "Governance", "tier": "strategic",
            "audience": "leadership", "date_text": "2026-11-09",
            "title": "Governance Import redesign 2026-11",
            "repo_path": repo, "pages_url": "https://example.invalid/reports",
        }

        ok, reason = check_repo_state(repo)
        check("clean main repo passes the state check", ok, reason)
        (repo / "scratch.txt").write_text("dirty", encoding="utf-8")
        ok, reason = check_repo_state(repo)
        check("a dirty tree fails the state check",
              not ok and "dirty" in reason, reason)
        code = publish(html_path=source, slug="report-1", force=False, **common)
        check("publish refuses a dirty tree and makes no commit", code == EXIT_FAIL)
        commits = subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        check("no commit was made by the refused publish", commits == "1", commits)
        (repo / "scratch.txt").unlink()

        code = publish(html_path=source, slug="Report 1", force=False, **common)
        check("a malformed slug refuses", code == EXIT_FAIL)

        # the foreign-file rule needs a clean tree: commit the leftover first
        (repo / "report-x").mkdir()
        (repo / "report-x" / "leftover.txt").write_text("foreign", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "report-x/leftover.txt"],
                       capture_output=True, text=True, check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "leftover"],
                       capture_output=True, text=True, check=True)
        code = publish(html_path=source, slug="report-x", force=False, **common)
        check("foreign files in the slug folder refuse without --force",
              code == EXIT_FAIL)
        code = publish(html_path=source, slug="report-x", force=True, **common)
        check("foreign files pass with --force", code == EXIT_OK)
        check("index.html lands in the slug folder",
              (repo / "report-x" / "index.html").is_file())

        manifest = json.loads((repo / "manifest.json").read_text(encoding="utf-8"))
        check(
            "manifest holds the published entry",
            len(manifest) == 1 and manifest[0]["slug"] == "report-x"
            and manifest[0]["title"] == "Governance Import redesign 2026-11",
            repr(manifest),
        )
        gallery = (repo / "index.html").read_text(encoding="utf-8")
        check(
            "gallery ships search, chips, and the escaped card",
            "<input id=\"q\"" in gallery and 'class="chip"' in gallery
            and "Governance Import redesign 2026-11" in gallery,
        )
        readme = (repo / "README.md").read_text(encoding="utf-8")
        check(
            "readme gains the markers and one row",
            README_START in readme and README_END in readme
            and readme.count("(ABC-237, strategic)") == 1,
            repr(readme),
        )

        source2 = tmp / "report2.html"
        source2.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        second = dict(common)
        second.update({"ticket": "ABC-240", "tier": "standard", "audience": "internal",
                       "date_text": "2026-11-01", "title": "Second report",
                       "pod": "Platform"})
        code = publish(html_path=source2, slug="report-2", force=False, **second)
        check("second publish succeeds", code == EXIT_OK)
        manifest = json.loads((repo / "manifest.json").read_text(encoding="utf-8"))
        check(
            "manifest upsert keeps one entry per slug",
            [item["slug"] for item in manifest] == ["report-x", "report-2"],
            repr(manifest),
        )
        readme = (repo / "README.md").read_text(encoding="utf-8")
        check(
            "readme list holds both rows sorted inside the markers",
            readme.count("- 2026-") == 2
            and readme.index("- 2026-11-01") < readme.index("- 2026-11-09"),
            repr(readme),
        )

        code = publish(html_path=source, slug="report-1", force=False, **common)
        check("republishing identical output succeeds idempotently", code == EXIT_OK)
        commits = subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        check("republish makes no extra commit", commits == "5", commits)
        pushed = subprocess.run(
            ["git", "-C", str(bare), "rev-parse", "--verify", "refs/heads/main"],
            capture_output=True, text=True,
        )
        check("publishes pushed main to the origin remote",
              pushed.returncode == 0, pushed.stderr)

        check(
            "missing flags are usage",
            main(["publish", str(source), "--slug=report-x"]) == EXIT_USAGE,
        )
        check(
            "unknown subcommand is usage",
            main(["retract"]) == EXIT_USAGE,
        )

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
