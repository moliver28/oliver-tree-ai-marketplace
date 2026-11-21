from _harness import bind

bind("scripts.evidence_sweep", globals())
FIXTURES = (PLUGIN_ROOT if (PLUGIN_ROOT / "tests").is_dir() else PLUGIN_ROOT.parent) / "tests" / "fixtures" / "evidence"


def _selftest() -> int:
    print("scripts/evidence_sweep.py selftest")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    config = {"tracker": {"kind": "jira", "project_key": "UXR"},
              "evidence": {"sources": ["tracker_recent", "tracker_topic", "drive", "feedback",
                                       "chat", "wiki", "jtbd", "personas", "chat_discovery"],
                           "chat_channels": ["#support-first-week"]},
              "ssot": {"jtbd_url": "", "personas_url": ""}}
    plan = build_plan(config, "timeline discoverability", tactical=False,
                      current_user="5f1a", today=date(2026, 11, 17))
    check("plan covers 9 sources", len(plan) == 9, str(sorted(plan)))
    check("plan tracker_recent window", plan["tracker_recent"]["window_days"] == 90)
    check("plan jql not-project", "NOT project = UXR" in plan["tracker_recent"]["query"])
    check("plan tool name", plan["tracker_recent"]["tool"] == "searchJiraIssuesUsingJql")
    plan_t = build_plan(config, "ship the export button", tactical=True)
    check("plan tactical wiki skip", plan_t["wiki"].get("skip") is not None)

    golden_path = FIXTURES / "digest-empty.json"
    if golden_path.is_file():
        case = json.loads(golden_path.read_text(encoding="utf-8"))
        out = digest(case["results"], case["topic"], False, case.get("topic_class", ""))
        expected_head = "\n".join(case["expect_block_head"])
        check("digest empty-sweep table", out["synthesis_block"].startswith(expected_head),
              out["synthesis_block"][:200])
        check("digest feedback gap line", "the study carries a gap" in out["synthesis_block"])
        check("digest feedback_gap flag", out["digest"]["feedback_gap"] is True)
        check("digest evidence_total", out["digest"]["evidence_total"] == 0)
        populated = digest({"tracker_recent": {"hits": 6, "titles": ["t"]}, "feedback": {"hits": 41}},
                           "topic", False)
        check("digest populated counts", populated["digest"]["evidence_total"] == 47)
    else:
        check("digest fixture", False, "tests/fixtures/evidence/digest-empty.json missing")
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
