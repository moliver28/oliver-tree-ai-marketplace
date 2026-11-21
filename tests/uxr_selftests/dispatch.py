from _harness import bind

bind("hooks.dispatch", globals())
def _selftest() -> int:
    print("hooks/dispatch.py selftest")
    failures: list[str] = []
    real_stdin = sys.stdin

    def check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    import types
    made = []
    for script in ("a_ok.py", "b_block.py", "c_after.py"):
        path = HOOKS_DIR / script
        path.write_text("def main():\n    return %s\n" %
                        ("0" if script != "b_block.py" else "2"), encoding="utf-8")
        made.append(path)
    try:
        saved_chain = dict(CHAIN)
        CHAIN["stop"] = ["a_ok.py", "b_block.py", "c_after.py"]
        sys.stdin = io.StringIO("{}")
        check("first-nonzero propagates", run("stop", "{}") == 2)
        CHAIN["stop"] = ["a_ok.py", "c_after.py"]
        check("all-zero chain returns 0", run("stop", "{}") == 0)
        check("stdin restored", sys.stdin is real_stdin or isinstance(sys.stdin, io.StringIO))
        CHAIN.clear()
        CHAIN.update(saved_chain)
    finally:
        sys.stdin = real_stdin
        for path in made:
            path.unlink(missing_ok=True)
    check("chain covers 3 events", set(CHAIN) == {"sessionstart", "stop", "subagentstop"})
    if failures:
        print(f"selftest FAILED ({len(failures)})")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
