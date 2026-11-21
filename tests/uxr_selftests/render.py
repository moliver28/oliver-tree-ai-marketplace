from _harness import bind

bind("lib.render", globals())
def _selftest() -> int:
    """Byte-compare every tests/fixtures/render case against its expected.txt."""
    cases = sorted(((PLUGIN_ROOT if (PLUGIN_ROOT / "tests").is_dir() else PLUGIN_ROOT.parent)
                    / "tests" / "fixtures" / "render").glob("*.json"))
    print("lib/render.py selftest")
    failures: list[str] = []
    if not cases:
        print("skip: fixtures not shipped (repo-level tests/)")
        return 0
    for case_path in cases:
        expected = case_path.with_suffix(".expected.txt")
        if not expected.is_file():
            failures.append(f"{case_path.name}: no expected.txt")
            continue
        data = json.loads(case_path.read_text(encoding="utf-8"))
        if case_path.name.startswith("mine"):
            got = render_mine(data.get("items") or [], data.get("mode") or "default",
                              data.get("now") or "now", data.get("project_key") or "")
        else:
            got = render_show(data["item"], data.get("now") or "now")
        if got + "\n" != expected.read_text(encoding="utf-8"):
            failures.append(f"{case_path.stem}: differs from expected.txt")
        else:
            print(f"  [ok] {case_path.stem}")
    now = "2026-11-17T21:54:24Z"
    for label, ts, want in (("just now", "2026-11-17T21:54:00Z", "just now"),
                            ("12h", "2026-11-17T09:54:00Z", "12h ago"),
                            ("7d", "2026-11-10T21:30:00Z", "7d ago"),
                            ("1w", "2026-11-08T21:54:00Z", "1w ago"),
                            ("1mo", "2026-10-17T21:00:00Z", "1mo ago")):
        if relative_time(ts, now) != want:
            failures.append(f"ladder {label}: {relative_time(ts, now)} != {want}")
    if convert_emoji("look :eyes:") != "look \U0001f440" or convert_emoji(":nope:") != ":nope:":
        failures.append("emoji conversion")
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
