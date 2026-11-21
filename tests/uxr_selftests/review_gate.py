from _harness import bind

bind("hooks.review_gate", globals())

import tempfile  # selftest-only import (moved from hooks/review_gate.py)

def _selftest() -> int:
    """Cover the acceptance items: reminder shape, session silence, overview
    silence, marker silence, plus the opt-out and the never-list."""
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("hooks/review_gate.py selftest")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        HOME = tmp / "home"
        (HOME / ".claude").mkdir(parents=True)
        workspace = tmp / "research" / "admin-permissions-study"
        (workspace / SESSIONS_DIRNAME).mkdir(parents=True)
        (workspace / OVERVIEW_MARKER).write_text(
            "# Admin permissions study\n\nTicket: ABC-237\n", encoding="utf-8"
        )
        config = None

        def pre_event(path, session_id="s1", tool="Write"):
            return {
                "hook_event_name": "PreToolUse",
                "tool_name": tool,
                "tool_input": {"file_path": str(path)},
                "cwd": str(workspace),
                "session_id": session_id,
            }

        def run(event, **kwargs):
            kwargs.setdefault("environ", {})
            kwargs.setdefault("home", HOME)
            return handle_event(event, config=config, **kwargs)

        deliverable = workspace / "deliverables" / "report.md"

        # 1. First write on a reviewable path: one reminder, correct shape.
        output = run(pre_event(deliverable))
        check("first reviewable write prints one reminder", bool(output), "output was empty")
        try:
            payload = json.loads(output)
        except ValueError:
            payload = {}
        check(
            "reminder carries systemMessage and additionalContext",
            bool(payload.get("systemMessage"))
            and isinstance(payload.get("hookSpecificOutput"), dict)
            and bool(payload["hookSpecificOutput"].get("additionalContext")),
            repr(output[:160]),
        )
        check(
            "reminder has no permissionDecision key",
            "permissionDecision" not in output and "permission_decision" not in output,
            "found a permission decision key",
        )
        check(
            "reminder text says what the marker proves and does not",
            "proves the agent ran" in output and "does not prove" in output,
            "reminder text missing the marker caveat",
        )
        state = _load_state(workspace / SESSIONS_DIRNAME / STATE_FILENAME)
        check(
            "reminder is recorded per session and study",
            bool(state.get("studies", {}).get("ABC-237", {}).get("sessions", {}).get("s1")),
            repr(state)[:160],
        )

        # 2. A second write in the same session is silent.
        check(
            "second write in the same session is silent",
            run(pre_event(deliverable, session_id="s1")) == "",
            "expected empty output",
        )

        # 3. 00-overview.md is never reviewable, even in a fresh session.
        check(
            "00-overview.md is silent",
            run(pre_event(workspace / OVERVIEW_MARKER, session_id="s2")) == "",
            "expected empty output",
        )
        for relative in ("README.md", "interviews/summary.md", "sources/index.md", "recruitment/plan.md"):
            check(
                f"{relative} is silent",
                run(pre_event(workspace / relative, session_id="s3")) == "",
                "expected empty output",
            )

        # 4. A numbered root artifact is reviewable for a new session.
        findings = workspace / "09-findings.md"
        output = run(pre_event(findings, session_id="s4"))
        check("numbered root artifact reminds in a new session", bool(output), "output was empty")

        # 5. SubagentStop writes the marker; then writes are silent forever.
        transcript = tmp / "transcript.jsonl"
        transcript.write_text(
            '{"type":"assistant"}\n{"tool":"Task","subagent_type":"hcd-researcher"}\n',
            encoding="utf-8",
        )
        stop_event = {
            "hook_event_name": "SubagentStop",
            "cwd": str(workspace),
            "session_id": "s5",
            "agent_id": "agent-9",
            "transcript_path": str(transcript),
        }
        check(
            "SubagentStop for hcd-researcher prints nothing",
            run(stop_event) == "",
            "expected empty output",
        )
        marker = marker_path(workspace, "ABC-237")
        marker_ok = False
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            marker_ok = (
                bool(data.get("ran_at"))
                and data.get("agent_id") == "agent-9"
                and data.get("session_id") == "s5"
            )
        except (OSError, ValueError):
            marker_ok = False
        check(
            "marker file holds ran_at, agent_id, session_id",
            marker_ok,
            f"marker at {marker}",
        )
        check(
            "after the marker the write is silent (fresh session)",
            run(pre_event(deliverable, session_id="s6")) == "",
            "expected empty output",
        )

        # 6. A different agent's SubagentStop writes no marker.
        other_workspace = tmp / "research" / "other-study"
        (other_workspace / SESSIONS_DIRNAME).mkdir(parents=True)
        (other_workspace / OVERVIEW_MARKER).write_text("# Other\n\nTicket: ABC-300\n", encoding="utf-8")
        other_transcript = tmp / "other-transcript.jsonl"
        other_transcript.write_text('{"tool":"Task","subagent_type":"novice-participant"}\n', encoding="utf-8")
        before = marker_path(other_workspace, "ABC-300")
        check(
            "SubagentStop for another agent writes no marker",
            run(
                {
                    "hook_event_name": "SubagentStop",
                    "cwd": str(other_workspace),
                    "session_id": "s7",
                    "agent_type": "novice-participant",
                    "transcript_path": str(other_transcript),
                }
            )
            == ""
            and not before.is_file(),
            "marker written for the wrong agent",
        )

        # 7. The opt-out file silences every reminder.
        (HOME / ".claude" / ".uxr-hcd-gate-off").write_text("", encoding="utf-8")
        fresh_workspace = tmp / "research" / "fresh-study"
        (fresh_workspace / SESSIONS_DIRNAME).mkdir(parents=True)
        (fresh_workspace / OVERVIEW_MARKER).write_text("# Fresh\n\nTicket: ABC-310\n", encoding="utf-8")
        check(
            "the opt-out file silences the reminder",
            run(
                pre_event(fresh_workspace / "deliverables" / "deck.md", session_id="s8"),
                home=HOME,
            )
            == "",
            "expected empty output",
        )
        (HOME / ".claude" / ".uxr-hcd-gate-off").unlink()

        # 8. Unknown events and malformed input print nothing.
        check(
            "SessionStart prints nothing",
            run({"hook_event_name": "SessionStart", "cwd": str(workspace)}) == "",
            "expected empty output",
        )
        check(
            "malformed event prints nothing",
            run({"hook_event_name": "PreToolUse"}) == "",
            "expected empty output",
        )

        # 9. Study key falls back to the workspace name when no ticket exists.
        keyless = tmp / "research" / "no ticket yet"
        (keyless / SESSIONS_DIRNAME).mkdir(parents=True)
        (keyless / OVERVIEW_MARKER).write_text("# Draft study\n", encoding="utf-8")
        check(
            "study key falls back to the workspace name",
            study_key(keyless, config) == "no-ticket-yet",
            study_key(keyless, config),
        )

        # 9b. An anchored validator regex still resolves the study key (F3).
        anchored_ws = tmp / "research" / "anchored-study"
        (anchored_ws / SESSIONS_DIRNAME).mkdir(parents=True)
        (anchored_ws / OVERVIEW_MARKER).write_text(
            "# Anchored study\n\nTicket: ABC-505\n", encoding="utf-8"
        )
        anchored_config = {"tracker": {"kind": "jira", "ticket_regex": r"^ABC-\d+$"}}
        check(
            "an anchored ticket_regex still resolves the study key",
            study_key(anchored_ws, anchored_config) == "ABC-505",
            study_key(anchored_ws, anchored_config),
        )

        # 10. Stop is the marker-check backstop: it writes the marker when
        # none exists and never degrades one a SubagentStop wrote.
        marker_before = json.loads(marker.read_text(encoding="utf-8"))
        check(
            "a Stop fire after SubagentStop leaves the marker untouched",
            run(
                {
                    "hook_event_name": "Stop",
                    "cwd": str(workspace),
                    "session_id": "s9",
                    "transcript_path": str(transcript),
                }
            )
            == ""
            and json.loads(marker.read_text(encoding="utf-8")) == marker_before,
            repr(marker.read_text(encoding="utf-8")),
        )
        stop_workspace = tmp / "research" / "stop-marker-study"
        (stop_workspace / SESSIONS_DIRNAME).mkdir(parents=True)
        (stop_workspace / OVERVIEW_MARKER).write_text(
            "# Stop marker study\n\nTicket: ABC-401\n", encoding="utf-8"
        )
        check(
            "a Stop fire writes the marker when none exists",
            run(
                {
                    "hook_event_name": "Stop",
                    "cwd": str(stop_workspace),
                    "session_id": "s10",
                    "transcript_path": str(transcript),
                }
            )
            == ""
            and marker_path(stop_workspace, "ABC-401").is_file(),
            "marker missing after Stop",
        )
        stop_marker = json.loads(
            marker_path(stop_workspace, "ABC-401").read_text(encoding="utf-8")
        )
        check(
            "the Stop-written marker carries the fallback agent id",
            stop_marker.get("agent_id") == AGENT_NAME
            and stop_marker.get("session_id") == "s10"
            and bool(stop_marker.get("ran_at")),
            repr(stop_marker),
        )
        quiet_transcript = tmp / "quiet-transcript.jsonl"
        quiet_transcript.write_text(
            '{"tool":"Task","subagent_type":"novice-participant"}\n', encoding="utf-8"
        )
        no_marker_workspace = tmp / "research" / "no-dispatch-study"
        (no_marker_workspace / SESSIONS_DIRNAME).mkdir(parents=True)
        (no_marker_workspace / OVERVIEW_MARKER).write_text(
            "# No dispatch\n\nTicket: ABC-402\n", encoding="utf-8"
        )
        check(
            "a Stop fire without a dispatch names no marker",
            run(
                {
                    "hook_event_name": "Stop",
                    "cwd": str(no_marker_workspace),
                    "session_id": "s11",
                    "transcript_path": str(quiet_transcript),
                }
            )
            == ""
            and not marker_path(no_marker_workspace, "ABC-402").is_file(),
            "marker written without a dispatch",
        )
        check(
            "unrelated events print nothing",
            run({"hook_event_name": "UserPromptSubmit", "cwd": str(workspace),
                 "prompt": "/uxr-eod", "session_id": "s12"})
            == ""
            and run({"hook_event_name": "SessionEnd", "cwd": str(workspace),
                     "session_id": "s13"})
            == "",
            "expected empty output",
        )

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
