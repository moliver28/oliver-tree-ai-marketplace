from _harness import bind

bind("hooks.session_logger", globals())

from provenance import selftest_fixture_dir  # moved home (tests/uxr_selftests/provenance.py); selftest body stays verbatim

def _selftest() -> int:
    """Cover the acceptance items: the same session id twice yields one row,
    an old ``processed: true`` survives a rewrite, a second fire emits no
    duplicate analytics, and a non-research session writes nothing."""
    import tempfile

    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append(name)

    print("hooks/session_logger.py selftest")

    with tempfile.TemporaryDirectory(dir=str(selftest_fixture_dir())) as td:
        tmp = Path(td)
        HOME = tmp / "home"
        (HOME / ".claude").mkdir(parents=True)
        research = tmp / "research"
        workspace = research / "permissions-study"
        (workspace / ".sessions").mkdir(parents=True)
        (workspace / "00-overview.md").write_text(
            "# Permissions study\n\nTicket: ABC-274\n", encoding="utf-8")
        outside = tmp / "plain"
        outside.mkdir()
        state = tmp / "state"
        commands = tmp / "commands"
        commands.mkdir()
        for stem in ("uxr-eod", "uxr-new"):
            (commands / (stem + ".md")).write_text("---\n---\n", encoding="utf-8")
        config = {
            "tracker": {"kind": "jira", "ticket_regex": r"\bABC-\d+\b",
                        "base_url": "https://example.atlassian.net"},
            "paths": {"research_root": str(research)},
            "analytics": {"enabled": True, "endpoint": "", "api_key": ""},
            "sync": {"enabled": False},
        }
        study_file = tmp / "notes.md"
        study_file.write_text("notes", encoding="utf-8")
        transcript = tmp / "transcript.jsonl"
        drive_hash = __import__("provenance").hash12("permissions research")
        lines = [
            {"type": "user", "timestamp": "2026-11-09T10:00:00.000Z",
             "message": {"role": "user",
                         "content": "Check ABC-274 and refresh the summary, then /uxr-eod --dry-run"}},
            {"type": "user", "timestamp": "2026-11-09T10:00:01.000Z",
             "message": {"role": "user",
                         "content": "<command-name>/uxr-plugin:uxr-eod</command-name>"}},
            {"type": "assistant", "timestamp": "2026-11-09T10:00:05.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t1", "name": "mcp__jira__getJiraIssue",
                  "input": {"key": "ABC-274"}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:06.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1", "content": "issue"}]}},
            {"type": "assistant", "timestamp": "2026-11-09T10:00:07.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t2",
                  "name": "mcp__04b27de0-5b5d-4d1e-9f3a-a1b2c3d4e5f6__searchDrive",
                  "input": {"query": "permissions research"}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:08.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t2", "content": "hits"}]}},
            {"type": "assistant", "timestamp": "2026-11-09T10:00:09.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t3", "name": "Read",
                  "input": {"file_path": str(study_file)}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:10.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t3", "content": "text"}]}},
            {"type": "assistant", "timestamp": "2026-11-09T10:00:11.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t4", "name": "Write",
                  "input": {"file_path": str(workspace / "deliverables" / "summary.md")}},
                 {"type": "tool_use", "id": "t5", "name": "Task",
                  "input": {"subagent_type": "hcd-researcher"}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:12.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t4", "content": "ok"},
                 {"type": "tool_result", "tool_use_id": "t5", "content": "done"}]}},
        ]
        transcript.write_text("".join(json.dumps(line) + "\n" for line in lines)
                              + "not json at all\n", encoding="utf-8")

        def run(session_id, cwd, name="SessionEnd", now="2026-11-09T12:00:00-05:00"):
            return handle_event(
                {"hook_event_name": name, "cwd": str(cwd),
                 "transcript_path": str(transcript), "session_id": session_id},
                config=config, state_dir=state, environ={}, home=HOME,
                commands_dir=commands, now=now)

        def journal_rows():
            path = state / "work-log-2026-11-09.jsonl"
            rows = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        rows.append(line)
            return rows

        # 1. A research session writes one row with the contract fields.
        run("s1", workspace)
        rows = journal_rows()
        check("one journal row after the first fire", len(rows) == 1, repr(rows))
        row = rows[0] if rows and isinstance(rows[0], dict) else {}
        expected_keys = ["session_id", "ended_at", "cwd", "in_research_dir",
                         "ticket_keys", "commands_used", "files_edited",
                         "files_edited_count", "tracker_tool_calls",
                         "user_message_count", "first_user_at", "last_user_at",
                         "last_user_snippet", "transcript_path", "provenance",
                         "processed"]
        check("the row carries the contract keys in order",
              list(row.keys()) == expected_keys, repr(list(row.keys())))
        check("ticket keys come from user text and tracker inputs",
              row.get("ticket_keys") == ["ABC-274"], repr(row.get("ticket_keys")))
        check("commands come from prompts and command-name tags",
              row.get("commands_used") == ["/uxr-eod"], repr(row.get("commands_used")))
        check("files edited are collected from the edit tools",
              row.get("files_edited") == [str(workspace / "deliverables" / "summary.md")],
              repr(row.get("files_edited")))
        check("tracker tool calls are counted",
              row.get("tracker_tool_calls") == 1, repr(row.get("tracker_tool_calls")))
        check("user message facts are kept",
              row.get("user_message_count") == 2
              and row.get("first_user_at") == "2026-11-09T10:00:00.000Z"
              and row.get("last_user_at") == "2026-11-09T10:00:01.000Z",
              repr(row))
        check("the row is not processed and ended_at is local ISO",
              row.get("processed") is False and row.get("ended_at")
              == "2026-11-09T12:00:00-05:00", repr(row.get("ended_at")))
        check("the provenance summary counts the walk",
              row.get("provenance", {}).get("source_count") == 3
              and row.get("provenance", {}).get("output_count") == 1
              and row.get("provenance", {}).get("files_read_count") == 1
              and row.get("provenance", {}).get("relationship_count") == 3,
              repr(row.get("provenance")))

        # 1b. An anchored tracker.ticket_regex still attributes keys (F3):
        # the documented validator shape must not empty the journal row.
        anchored_transcript = tmp / "anchored.jsonl"
        anchored_transcript.write_text("".join(json.dumps(line) + "\n" for line in [
            {"type": "user", "timestamp": "2026-11-09T10:00:00.000Z",
             "message": {"role": "user",
                         "content": "Check ABC-274 and refresh the summary"}},
            {"type": "assistant", "timestamp": "2026-11-09T10:00:05.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "a1", "name": "mcp__jira__getJiraIssue",
                  "input": {"key": "ABC-274"}}]}},
        ]), encoding="utf-8")
        anchored_config = {
            "tracker": {"kind": "jira", "ticket_regex": r"^ABC-\d+$",
                        "base_url": "https://example.atlassian.net"},
        }
        anchored_stats = collect_stats(
            {"transcript_path": str(anchored_transcript)}, anchored_config,
            TranscriptWalk(config=anchored_config),
            commands_dir=commands, environ={}, home=HOME)
        check("an anchored ticket_regex still attributes journal keys",
              anchored_stats["ticket_keys"] == ["ABC-274"],
              repr(anchored_stats["ticket_keys"]))

        # 2. The workspace manifests were written.
        manifests = sorted(item.name for item in
                           (workspace / ".sessions").iterdir())
        check("session record, provenance lines, and the sources index exist",
              "2026-11-09T12-00-00-05-00.json" in manifests
              and "provenance.jsonl" in manifests
              and "sources-index.json" in manifests, repr(manifests))
        record = json.loads((workspace / ".sessions"
                             / "2026-11-09T12-00-00-05-00.json").read_text(encoding="utf-8"))
        check("the session record holds the detailed provenance",
              record.get("session_id") == "s1"
              and len(record.get("provenance", {}).get("sources", [])) == 3,
              repr(record.get("provenance", {})))
        check("the drive search source id is stable",
              any(source.get("id") == "drive:search:%s" % drive_hash
                  for source in record.get("provenance", {}).get("sources", [])),
              repr([s.get("id") for s in record.get("provenance", {}).get("sources", [])]))

        # 3. Analytics: exactly one session_summary on the new row.
        buffer_rows = [json.loads(line) for line in
                       (analytics_common.buffer_path(state)).read_text(
                           encoding="utf-8").splitlines() if line.strip()]
        check("one analytics event on the new row",
              len(buffer_rows) == 1
              and buffer_rows[0].get("event") == "session_summary",
              repr(buffer_rows))
        check("the payload maps each field to its own stat",
              buffer_rows[0].get("user_messages") == 2
              and buffer_rows[0].get("tracker_calls") == 1
              and buffer_rows[0].get("files_edited") == 1
              and buffer_rows[0].get("commands") == 1,
              repr(buffer_rows[0]))

        # 4. Same session twice: one row; processed survives; malformed kept.
        rows[0]["processed"] = True
        path = state / "work-log-2026-11-09.jsonl"
        path.write_text("not json at all\n"
                        + json.dumps(rows[0], ensure_ascii=False) + "\n",
                        encoding="utf-8")
        run("s1", workspace)
        rows = journal_rows()
        kept = [r for r in rows if isinstance(r, dict)]
        check("the same session id twice still yields one row", len(kept) == 1, repr(len(kept)))
        check("processed: true survives the rewrite",
              kept and kept[0].get("processed") is True, repr(kept))
        check("the malformed line was preserved verbatim",
              any(isinstance(r, str) and r.strip() == "not json at all" for r in rows),
              repr(rows))
        buffer_rows = [json.loads(line) for line in
                       analytics_common.buffer_path(state).read_text(
                           encoding="utf-8").splitlines() if line.strip()]
        check("a second fire emits no duplicate analytics",
              len(buffer_rows) == 1, repr(len(buffer_rows)))

        # 5. A non-research session (plain cwd, no ticket, no command) writes nothing.
        plain_transcript = tmp / "plain.jsonl"
        plain_transcript.write_text(json.dumps(
            {"type": "user", "timestamp": "2026-11-09T09:00:00.000Z",
             "message": {"role": "user", "content": "what is the weather"}}) + "\n",
            encoding="utf-8")
        handle_event({"hook_event_name": "SessionEnd", "cwd": str(outside),
                      "transcript_path": str(plain_transcript), "session_id": "s2"},
                     config=config, state_dir=state, environ={}, home=HOME,
                     commands_dir=commands, now="2026-11-09T12:02:00-05:00")
        rows = journal_rows()
        check("a non-research session adds no row",
              len([r for r in rows if isinstance(r, dict)]) == 1, repr(rows))
        check("a non-research session writes no analytics",
              len([json.loads(l) for l in analytics_common.buffer_path(state)
                   .read_text(encoding="utf-8").splitlines() if l.strip()]) == 1)
        check("a non-research session writes no workspace manifests",
              not (outside / ".sessions").exists(), "")

        # 6. A research cwd alone (no ticket, no command) still journals.
        run("s3", research / "second-study")
        rows = journal_rows()
        check("a research-cwd session journals",
              len([r for r in rows if isinstance(r, dict)]) == 2, repr(rows))

        # 7. The last-user snippet is capped at 280 characters.
        long_text = "x" * 400
        long_transcript = tmp / "long.jsonl"
        long_transcript.write_text(json.dumps(
            {"type": "user", "timestamp": "2026-11-09T11:00:00.000Z",
             "message": {"role": "user", "content": long_text}}) + "\n", encoding="utf-8")
        handle_event({"hook_event_name": "SessionEnd", "cwd": str(workspace),
                      "transcript_path": str(long_transcript), "session_id": "s4"},
                     config=config, state_dir=state, environ={}, home=HOME,
                     commands_dir=commands, now="2026-11-09T12:05:00-05:00")
        rows = journal_rows()
        row4 = [r for r in rows if isinstance(r, dict) and r.get("session_id") == "s4"]
        check("the snippet is capped at 280 characters",
              bool(row4) and len(row4[0].get("last_user_snippet", "")) == 280,
              repr(len(row4[0].get("last_user_snippet", "")) if row4 else -1))

        # 8. Wrong event names and missing session ids are silent.
        check("a non-SessionEnd event writes nothing",
              handle_event({"hook_event_name": "SessionStart", "cwd": str(workspace),
                            "session_id": "s9"}, config=config, state_dir=state,
                           environ={}, home=HOME) .get("research") is False, "")
        check("a missing session id writes nothing",
              handle_event({"hook_event_name": "SessionEnd", "cwd": str(workspace),
                            "transcript_path": str(transcript)},
                           config=config, state_dir=state, environ={}, home=HOME,
                           commands_dir=commands)["row_written"] is False, "")

        # 9. Stop behaves like SessionEnd for the row upsert, and the
        # Stop -> SessionEnd double fire stays one row with one summary.
        def dict_rows():
            return [r for r in journal_rows() if isinstance(r, dict)]

        def buffer_count():
            return len([line for line in analytics_common.buffer_path(state)
                        .read_text(encoding="utf-8").splitlines() if line.strip()])

        summary = run("s10", workspace, name="Stop",
                      now="2026-11-09T12:10:00-05:00")
        check("a Stop fire journals the session",
              summary.get("row_written") is True and summary.get("row_is_new") is True,
              repr(summary))
        check("a Stop fire writes no workspace manifests",
              not (workspace / ".sessions" / "2026-11-09T12-10-00-05-00.json").exists(), "")
        rows_after_stop = buffer_count()
        check("a Stop fire emits the session summary once",
              rows_after_stop == 4, repr(rows_after_stop))
        run("s10", workspace, name="Stop", now="2026-11-09T12:11:00-05:00")
        kept = [r for r in dict_rows() if r.get("session_id") == "s10"]
        check("repeated Stop fires keep one row",
              len(kept) == 1, repr(len(kept)))
        check("the repeated Stop fire refreshes ended_at in place",
              kept and kept[0].get("ended_at") == "2026-11-09T12:11:00-05:00",
              repr(kept[0].get("ended_at") if kept else None))
        check("the repeated Stop fire emits no duplicate analytics",
              buffer_count() == rows_after_stop, repr(buffer_count()))
        summary = run("s10", workspace, name="SessionEnd",
                      now="2026-11-09T12:12:00-05:00")
        kept = [r for r in dict_rows() if r.get("session_id") == "s10"]
        check("the Stop then SessionEnd double fire still holds one row",
              summary.get("row_is_new") is False and len(kept) == 1,
              repr((summary, len(kept))))
        check("the double fire adds no duplicate analytics",
              buffer_count() == rows_after_stop, repr(buffer_count()))
        check("SessionEnd alone writes the workspace manifests",
              (workspace / ".sessions" / "2026-11-09T12-12-00-05-00.json").exists(), "")
        edges = [json.loads(line) for line in
                 (workspace / ".sessions" / "provenance.jsonl")
                 .read_text(encoding="utf-8").splitlines() if line.strip()]
        check("the double fire appends the edge set once",
              len([e for e in edges if e.get("session_id") == "s10"]) == 3,
              repr(len([e for e in edges if e.get("session_id") == "s10"])))
        check("an unrelated event name is silent",
              handle_event({"hook_event_name": "PreToolUse", "cwd": str(workspace),
                            "session_id": "s11"}, config=config, state_dir=state,
                           environ={}, home=HOME).get("row_written") is False, "")

    if failures:
        print("selftest FAILED (%d check(s))" % len(failures))
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
