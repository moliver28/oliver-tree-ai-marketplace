from _harness import bind

bind("lib.prompts", globals())
#: selftest fixtures live at repo level in a checkout; absent in an installed plugin
FIXTURES_DIR = (PLUGIN_ROOT if (PLUGIN_ROOT / "tests").is_dir() else PLUGIN_ROOT.parent) / "tests" / "fixtures" / "prompts"


def _selftest() -> int:
    """Every asset renders under its fixture condition matrix; each fragment
    fires somewhere; the over-budget case fails; the metering line formats."""
    print("lib/prompts.py selftest")
    if not FIXTURES_DIR.is_dir():
        print("skip: fixtures not shipped (repo-level tests/)")
        return 0
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    assets = sorted(PROMPTS_DIR.glob("*/prompt.md"))
    check("assets exist", bool(assets))
    for path in assets:
        meta = _parse_asset(path)
        name = meta["id"]
        cases = sorted((FIXTURES_DIR / name).glob("case-*.json"))
        check(f"{name}: fixture cases", bool(cases))
        seen_fired: set[str] = set()
        for case_path in cases:
            case = json.loads(case_path.read_text(encoding="utf-8"))
            label = f"{name}:{case_path.stem}"
            try:
                text = render(name, case["fields"])
            except PromptError as exc:
                check(label, bool(case.get("expect_error")), str(exc))
                continue
            check(f"{label}: no error expected", not case.get("expect_error"))
            now = load(name)
            variant = select_variant(now, case["fields"])
            fired = [f.get("id") for f in select_fragments(now, case["fields"])]
            seen_fired.update(fired)
            check(f"{label}: variant", variant == case.get("variant", variant))
            check(f"{label}: fragments", fired == case.get("fragments", fired),
                  f"{fired} != {case.get('fragments')}")
            for line in case.get("expect_lines") or []:
                check(f"{label}: line", line in text, f"missing {line!r}")
        all_frags = {f.get("id") for f in meta.get("fragments") or []}
        check(f"{name}: condition matrix", all_frags <= seen_fired,
              f"never fired: {sorted(all_frags - seen_fired)}")
        over = FIXTURES_DIR / name / "over-budget.json"
        if over.is_file():
            try:
                render(name, json.loads(over.read_text(encoding="utf-8"))["fields"])
                check(f"{name}: over budget fails", False, "rendered anyway")
            except PromptError:
                check(f"{name}: over budget fails", True)
        try:
            probe = {v: "x" for v in meta.get("vars") or []}
            check(f"{name}: metering line",
                  bool(_METER_RE.fullmatch(metering_line(name, probe))))
        except PromptError as exc:
            check(f"{name}: metering line", False, str(exc))
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
