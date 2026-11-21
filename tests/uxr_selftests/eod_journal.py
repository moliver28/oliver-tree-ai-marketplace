from _harness import bind

bind("scripts.eod_journal", globals())
FIXTURES = (PLUGIN_ROOT if (PLUGIN_ROOT / "tests").is_dir() else PLUGIN_ROOT.parent) / "tests" / "fixtures" / "eod"


def _selftest() -> int:
    print("scripts/eod_journal.py selftest")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    footer = "_Posted by Claude Code on behalf of Jordan Reyes._"
    check("check: word count and footer",
          check_draft("[ux-eod 2026-11-17]\n\nOne session today.\n\n" + footer, footer) == "14 True")
    check("check: missing footer is False",
          check_draft("[ux-eod 2026-11-17]\n\nNo footer yet.", footer) == "5 False")

    golden = FIXTURES / "journal-2026-11-17.jsonl"
    if golden.is_file():
        with tempfile.TemporaryDirectory() as td:
            state = Path(td)
            (state / "work-log-2026-11-17.jsonl").write_text(
                golden.read_text(encoding="utf-8"), encoding="utf-8")
            rows = _read_rows(state, ["2026-11-17"])
            grouped = filter_rows(rows)
            check("filter: matches the baseline grouping",
                  grouped == {"active": {"UXR-101": 1}, "readonly_sessions": ["ro-1"],
                              "unlinked_sessions": ["ul-1"]}, json.dumps(grouped))
            draft = draft_auto([row for row in rows if "UXR-101" in (row.get("ticket_keys") or [])],
                               "UXR-101", "2026-11-17", footer)
            check("draft-auto: first line is the heading", draft.startswith("[ux-eod 2026-11-17]"))
            check("draft-auto: facts only, capped, footered",
                  draft.splitlines()[2].startswith("UXR-101: 1 session(s)")
                  and len(draft.split()) < 300 and draft.rstrip().endswith(footer), draft)
            empty = filter_rows([])
            check("filter: empty input", empty == {"active": {}, "readonly_sessions": [],
                                                   "unlinked_sessions": []})
            changed = rewrite_journal(state, ["2026-11-17"], {"UXR-101"}, {"ro-1"})
            after = {row["session_id"]: bool(row.get("processed")) for row in
                     (json.loads(line) for line in
                      (state / "work-log-2026-11-17.jsonl").read_text(encoding="utf-8").splitlines()
                      if line.strip())}
            check("rewrite: flips posted and readonly, leaves unlinked unprocessed",
                  changed == 2 and after.get("baseline-uc8-session") is True
                  and after.get("ro-1") is True and after.get("ul-1") is False,
                  json.dumps(after))
    else:
        check("journal fixture", False, "tests/fixtures/eod/journal fixture missing")
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
