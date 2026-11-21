from _harness import bind

bind("scripts.classify", globals())
#: selftest fixtures live at repo level in a checkout; absent in an installed plugin
FIXTURES = (PLUGIN_ROOT if (PLUGIN_ROOT / "tests").is_dir() else PLUGIN_ROOT.parent) / "tests" / "fixtures" / "classify"


def _selftest() -> int:
    print("scripts/classify.py selftest")
    failures: list[str] = []
    cases = sorted(FIXTURES.glob("*.json"))
    if not cases:
        print("skip: fixtures not shipped (repo-level tests/)")
        return 0
    for case_path in cases:
        case = json.loads(case_path.read_text(encoding="utf-8"))
        try:
            if case["subcommand"] == "intent":
                got = classify_intent(case["input"], case.get("prefix", ""))
            elif case["subcommand"] == "reply":
                got = classify_reply(case["input"])
            elif case["subcommand"] == "method":
                got = classify_method(case["input"])
            elif case["subcommand"] == "decision":
                got = classify_decision(case["input"])
            else:
                got = route_finding(case["input"])
        except ClassifyError as exc:
            got = {"error": str(exc)}
        if got == case["expect"]:
            print(f"  [ok] {case_path.stem}")
        else:
            failures.append(f"{case_path.stem}: {got} != {case['expect']}")
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
