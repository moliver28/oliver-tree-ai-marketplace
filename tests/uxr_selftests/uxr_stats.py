from _harness import bind

bind("scripts.uxr_stats", globals())
def _selftest() -> int:
    """Cover the acceptance items: ``--json`` is valid JSON and duplicate
    rows count once, plus the --days window and the never-joined rule."""
    import tempfile

    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append(name)

    print("scripts/uxr_stats.py selftest")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        state = tmp / "state"
        state.mkdir()
        journal = state / "work-log-2026-11-08.jsonl"
        rows = [
            # Duplicate session: same id, older and newer ended_at.
            {"session_id": "s1", "ended_at": "2026-11-08T09:00:00-05:00",
             "commands_used": ["/uxr-new"], "files_edited_count": 2,
             "tracker_tool_calls": 1, "processed": False},
            {"session_id": "s1", "ended_at": "2026-11-08T17:00:00-05:00",
             "commands_used": ["/uxr-new", "/uxr-eod"], "files_edited_count": 3,
             "tracker_tool_calls": 2, "processed": False},
            {"session_id": "s2", "ended_at": "2026-11-08T10:00:00-05:00",
             "commands_used": ["/uxr-eod"], "files_edited_count": 0,
             "tracker_tool_calls": 0, "processed": True},
            {"session_id": "s3", "ended_at": "2026-11-08T11:00:00-05:00",
             "commands_used": [], "files_edited_count": 1,
             "tracker_tool_calls": 0, "processed": True},
        ]
        journal.write_text("".join(json.dumps(r) + "\n" for r in rows)
                           + "not json at all\n", encoding="utf-8")
        old = state / "work-log-2026-10-01.jsonl"
        old.write_text(json.dumps(
            {"session_id": "s9", "ended_at": "2026-10-01T09:00:00-05:00",
             "commands_used": ["/uxr-new"], "files_edited_count": 4,
             "tracker_tool_calls": 3, "processed": False}) + "\n", encoding="utf-8")
        events = state / "events-2026-11.jsonl"
        lines = []
        for index in range(4):
            lines.append({"v": 1, "event": "command_invoked"})
        for index in range(2):
            lines.append({"v": 1, "event": "tool_failed", "kind": "tool_error"})
        lines.append({"v": 1, "event": "tool_failed", "kind": "user_rejection"})
        lines.append({"v": 1, "event": "agent_dispatched"})
        lines.append("broken line")
        events.write_text("".join(
            (line if isinstance(line, str) else json.dumps(line)) + "\n"
            for line in lines), encoding="utf-8")
        old_events = state / "events-2026-01.jsonl"
        old_events.write_text(json.dumps({"v": 1, "event": "command_invoked"}) + "\n",
                              encoding="utf-8")
        today = date(2026, 11, 9)

        code, out = run(state, None, False, today=today)
        check("all files roll up without --days",
              code == 0 and "distinct_sessions: 4" in out, repr(out[:80]))
        check("duplicate rows count once (latest ended_at kept)",
              "distinct_sessions: 4" in out and "files_edited_total: 8" in out
              and "tracker_tool_calls_total: 5" in out, repr(out))
        check("command adoption counts distinct sessions per command",
              "/uxr-eod: 2" in out and "/uxr-new: 2" in out, repr(out))
        check("the unprocessed count uses the kept rows",
              "unprocessed_count: 2" in out, repr(out))

        code, out = run(state, 7, False, today=today)
        check("--days excludes the old journal month",
              code == 0 and "distinct_sessions: 3" in out, repr(out))
        check("--days keeps only overlapping event months",
              "total_events: 8" in out, repr(out))

        code, out = run(state, None, True, today=today)
        try:
            payload = json.loads(out)
            valid = True
        except ValueError:
            payload, valid = {}, False
        check("--json is valid JSON", code == 0 and valid, repr(out[:60]))
        check("the two rollups stay separate (never joined)",
              set(payload.get("journal", {}).get("command_adoption", {}).keys()).isdisjoint(
                  set(payload.get("analytics", {}).get("event_type_counts", {}).keys())),
              repr(payload))
        check("the json payload carries the contract keys",
              payload.get("journal", {}).get("distinct_sessions") == 4
              and payload.get("analytics", {}).get("total_events") == 9
              and payload.get("analytics", {}).get("tool_failed_by_kind", {})
              .get("tool_error") == 2
              and payload.get("analytics", {}).get("tool_failed_by_kind", {})
              .get("user_rejection") == 1,
              repr(payload.get("analytics")))

        check("malformed lines are skipped silently",
              payload.get("analytics", {}).get("total_events") == 9,
              repr(payload.get("analytics", {}).get("total_events")))

    if failures:
        print("selftest FAILED (%d check(s))" % len(failures))
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
