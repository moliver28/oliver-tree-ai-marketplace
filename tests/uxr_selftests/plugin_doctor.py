from _harness import bind

bind("scripts.plugin_doctor", globals())


def _selftest() -> int:
    """Cover the doctor: front matter parsing, the module table, a clean
    check on the full tree, and the repo-clone refusal."""
    import io
    from contextlib import redirect_stdout

    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append(name)

    print("scripts/plugin_doctor.py selftest")

    # front matter parser
    check(
        "front matter parses",
        front_matter('---\ndescription: "x"\nargument-hint: "[all]"\n---\nbody')
        == {"description": "x", "argument-hint": "[all]"},
    )
    check("front matter missing block", front_matter("no block") is None)
    check("front matter malformed", front_matter("---\nno colon here\n---\n") is None)

    # module table and pure helpers
    check("modules declared", set(MODULES) == {"mcp", "scripting"})
    check(
        "module paths resolve in repo",
        all((PLUGIN_ROOT / rel).exists() for rel in all_module_paths(["mcp", "scripting"])),
    )
    check("prune_path on missing path", prune_path(PLUGIN_ROOT / "no-such-path") is None)
    # clean check on the full tree (the repo clone carries no state file)
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = run_check()
    check("run_check green on full tree", code == 0 and "0 problem(s)" in buf.getvalue(), buf.getvalue()[:160])
    check("no state file in the repo tree", load_state() is None)

    # profile apply refuses inside the marketplace clone, before any write
    check("apply refuses in repo clone", apply_profile("scripting") == 3)
    check("state file still absent", not STATE.exists())
    check("unknown profile exits 2", apply_profile("no-such") == 2)

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
