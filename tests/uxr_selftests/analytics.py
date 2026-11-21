from _harness import bind

bind("hooks.analytics", globals())
def _selftest() -> int:
    """Cover command normalization, the discovered agent allowlist, the
    consent gate, and the failure-kind split. The buffer goes to a temp
    state dir; nothing here touches the network."""
    global COMMANDS_DIR
    import tempfile

    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append(name)

    print("hooks/analytics.py selftest")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        HOME = tmp / "home"
        (HOME / ".claude").mkdir(parents=True)
        state = tmp / "state"
        commands = tmp / "commands"
        commands.mkdir()
        for stem in ("uxr-eod", "uxr-trace", "uxr-stats", "uxr-new"):
            (commands / (stem + ".md")).write_text("---\n---\n", encoding="utf-8")
        COMMANDS_DIR = commands
        agents = tmp / "agents"
        agents.mkdir()
        agent_names = ["expert-participant", "hcd-researcher", "novice-participant",
                       "novice-report-reader", "research-dataviz-designer",
                       "script-writer", "stakeholder-reviewer"]
        for stem in agent_names:
            (agents / (stem + ".md")).write_text("---\n---\n", encoding="utf-8")
        enabled = {"analytics": {"enabled": True, "endpoint": "", "api_key": ""}}
        disabled = {"analytics": {"enabled": False, "endpoint": "", "api_key": ""}}

        def rows():
            path = analytics_common.buffer_path(state)
            if not path.is_file():
                return []
            return [json.loads(line) for line in
                    path.read_text(encoding="utf-8").splitlines() if line.strip()]

        # 1. Command normalization.
        check("installed namespace normalizes",
              normalize_command("/uxr-plugin:uxr-eod --dry-run", commands) == "/uxr-eod")
        check("a bare shipped command counts",
              normalize_command("/uxr-trace", commands) == "/uxr-trace")
        check("an unshipped command does not count",
              normalize_command("/uxr-absent", commands) == "")
        check("a non-slash prompt does not count",
              normalize_command("summarize the study", commands) == "")

        # 2. The allowlist is discovered from agents/.
        check("the allowlist holds every shipped agent",
              plugin_agents(agents) == agent_names, repr(plugin_agents(agents)))

        # 3. Consent off: nothing recorded.
        check("consent off records nothing",
              handle_event({"hook_event_name": "UserPromptExpansion",
                            "prompt": "/uxr-eod", "session_id": "s1"},
                           config=disabled, state_dir=state, environ={}, home=HOME) == ""
              and not rows())

        # 4. command_invoked from a slash-command expansion.
        check("slash-command expansion records command_invoked",
              handle_event({"hook_event_name": "UserPromptExpansion",
                            "expansion_type": "slash_command",
                            "prompt": "/uxr-plugin:uxr-eod", "session_id": "s1"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and any(row.get("event") == "command_invoked"
                      and row.get("command") == "/uxr-eod" for row in rows()))
        salt = analytics_common.load_or_create_salt(state)
        check("recorded session ids are salted, never raw",
              bool(rows())
              and all(row.get("session_id") == analytics_common.pseudonymous_id(salt, "s1")
                      for row in rows()))
        check("a plain prompt expansion records nothing",
              handle_event({"hook_event_name": "UserPromptExpansion",
                            "prompt": "what is on my plate", "session_id": "s1"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and len(rows()) == 1)

        # 5. agent_dispatched from SubagentStop.
        transcript = tmp / "transcript.jsonl"
        transcript.write_text('{"tool": "Task", "subagent_type": "script-writer"}\n',
                              encoding="utf-8")
        check("explicit plugin agent records agent_dispatched",
              handle_event({"hook_event_name": "SubagentStop",
                            "agent_type": "hcd-researcher", "session_id": "s1"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and any(row.get("event") == "agent_dispatched"
                      and row.get("agent") == "hcd-researcher" for row in rows()))
        check("a non-plugin agent is not recorded",
              handle_event({"hook_event_name": "SubagentStop",
                            "agent_type": "general-purpose", "session_id": "s1"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and len([row for row in rows()
                       if row.get("event") == "agent_dispatched"]) == 1)
        check("transcript scan resolves an allowlisted agent",
              transcript_agent({"transcript_path": str(transcript)},
                               plugin_agents(agents)) == "script-writer")
        check("transcript scan with an empty allowlist finds nothing",
              transcript_agent({"transcript_path": str(transcript)}, []) == "")

        # 6. tool_failed kinds; the detail never travels.
        check("a plain failure records tool_failed with kind tool_error",
              handle_event({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                            "tool_response": {"is_error": True,
                                              "content": "exit code 1: boom"},
                            "session_id": "s1"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and any(row.get("event") == "tool_failed"
                      and row.get("tool_name") == "Bash"
                      and row.get("kind") == "tool_error"
                      and "boom" not in json.dumps(row) for row in rows()))
        check("a rejection phrase records kind user_rejection",
              handle_event({"hook_event_name": "PostToolUse", "tool_name": "Write",
                            "tool_response": {"is_error": True,
                                              "content": "The user doesn't want to proceed."},
                            "session_id": "s1"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and any(row.get("event") == "tool_failed"
                      and row.get("kind") == "user_rejection" for row in rows()))
        check("skill use records skill_invoked",
              handle_event({"hook_event_name": "PostToolUse", "tool_name": "Skill",
                            "tool_input": {"skill": "notebooklm"}, "session_id": "s1"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and any(row.get("event") == "skill_invoked"
                      and row.get("skill") == "notebooklm" for row in rows()))

        # 7. Malformed events are silent.
        check("malformed events print nothing and record nothing",
              handle_event(None, config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and handle_event({}, config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and len(rows()) == 5)

        # 8. UserPromptSubmit counts like UserPromptExpansion, and the
        # Claude Code double fire (Submit before the expansion, Expansion
        # at it) stays one command_invoked inside the dedup window.
        base = "2026-11-09T10:30:00-05:00"
        submit = {"hook_event_name": "UserPromptSubmit",
                  "prompt": "/uxr-trace", "session_id": "s9"}
        check("UserPromptSubmit records command_invoked",
              handle_event(submit, config=enabled, state_dir=state,
                           environ={}, home=HOME, now=base) == ""
              and any(row.get("event") == "command_invoked"
                      and row.get("command") == "/uxr-trace" for row in rows())
              and len(rows()) == 6, repr(rows()))
        check("the Submit then Expansion double fire counts once",
              handle_event(dict(submit, hook_event_name="UserPromptExpansion",
                                expansion_type="slash_command"),
                           config=enabled, state_dir=state,
                           environ={}, home=HOME, now=base) == ""
              and len([row for row in rows()
                       if row.get("command") == "/uxr-trace"]) == 1,
              repr(rows()))
        check("the same command counts again outside the window",
              handle_event(dict(submit, prompt="/uxr-trace --json"),
                           config=enabled, state_dir=state,
                           environ={}, home=HOME,
                           now="2026-11-09T10:32:00-05:00") == ""
              and len([row for row in rows()
                       if row.get("command") == "/uxr-trace"]) == 2,
              repr(rows()))
        check("a different session is not deduped away",
              handle_event(dict(submit, session_id="s10"),
                           config=enabled, state_dir=state,
                           environ={}, home=HOME,
                           now="2026-11-09T10:32:30-05:00") == ""
              and len([row for row in rows()
                       if row.get("command") == "/uxr-trace"]) == 3,
              repr(rows()))

        # 9. Stop is wired for the ZCode turn end but records nothing.
        stop_buffer = len(rows())
        check("a Stop fire records nothing",
              handle_event({"hook_event_name": "Stop", "session_id": "s9"},
                           config=enabled, state_dir=state, environ={}, home=HOME) == ""
              and handle_event({"hook_event_name": "Stop", "session_id": "s9",
                                "agent_type": "hcd-researcher",
                                "transcript_path": str(transcript)},
                               config=enabled, state_dir=state, environ={},
                               home=HOME) == ""
              and len(rows()) == stop_buffer, repr(rows()))

    if failures:
        print("selftest FAILED (%d check(s))" % len(failures))
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
