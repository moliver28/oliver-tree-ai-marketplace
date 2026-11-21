from _harness import bind

bind("hooks.analytics_common", globals())

import tempfile  # selftest-only import (moved from hooks/analytics_common.py)

def _selftest() -> int:
    """Cover the consent matrix, the salted ids, the envelope scrub, and the
    buffer behavior. This module never imports a network function; the
    flush-level no-network test lives in analytics_flush.py."""
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("hooks/analytics_common.py selftest")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        HOME = tmp / "home"
        (HOME / ".claude").mkdir(parents=True)
        state = tmp / "state"
        enabled = {"analytics": {"enabled": True, "endpoint": "", "api_key": ""}}
        disabled = {"analytics": {"enabled": False, "endpoint": "", "api_key": ""}}

        # 1. The consent matrix.
        check("analytics.enabled false means off",
              not analytics_enabled(disabled, environ={}, home=HOME))
        check("analytics.enabled true means on",
              analytics_enabled(enabled, environ={}, home=HOME))
        check("UXR_ANALYTICS=off overrides the config",
              not analytics_enabled(enabled, environ={"UXR_ANALYTICS": "off"}, home=HOME))
        check("DO_NOT_TRACK=1 means off",
              not analytics_enabled(enabled, environ={"DO_NOT_TRACK": "1"}, home=HOME))
        (HOME / ".claude" / OFF_FILE).write_text("", encoding="utf-8")
        check("the off file means off",
              not analytics_enabled(enabled, environ={}, home=HOME))
        (HOME / ".claude" / OFF_FILE).unlink()
        check("a missing config means off",
              not analytics_enabled(None, environ={}, home=HOME))
        check("an error during the check means off",
              not analytics_enabled(enabled, environ={}, home=123))

        # 2. Salted identity: 12 hex, stable, salt-dependent.
        salt = load_or_create_salt(state)
        check("salt file created and non-empty", bool(salt), repr(salt))
        if os.name == "posix":
            check("salt file mode is 0600",
                  (state / SALT_FILE).stat().st_mode & 0o777 == 0o600,
                  oct((state / SALT_FILE).stat().st_mode & 0o777))
        else:
            check("salt file created (POSIX modes not enforced on this OS)",
                  (state / SALT_FILE).is_file())
        check("load_or_create_salt is stable", load_or_create_salt(state) == salt)
        uid = pseudonymous_id(salt, "sess-1")
        check("pseudonymous id is 12 hex",
              len(uid) == 12 and all(c in "0123456789abcdef" for c in uid), uid)
        check("same value keeps one id, different value differs",
              pseudonymous_id(salt, "sess-1") == uid
              and pseudonymous_id(salt, "sess-2") != uid)
        check("a different salt changes the id",
              pseudonymous_id("other", "sess-1") != uid)
        check("no salt means no id", pseudonymous_id("", "sess-1") == "")

        # 3. Envelope: shape, salted session id, deep scrub.
        envelope = build_envelope(
            "command_invoked",
            {"command": "/uxr-eod", "prompt": "secret", "nested":
             {"text": "secret", "command": "/uxr-show"}},
            "sess-1", salt, now="2026-11-09T12:00:00-05:00", uid_value="researcher")
        check("envelope carries v, ts, event, plugin_version",
              envelope["v"] == 1 and envelope["event"] == "command_invoked"
              and envelope["ts"] == "2026-11-09T12:00:00-05:00"
              and envelope["plugin_version"] == plugin_version(), repr(envelope))
        check("session_id and uid are salted, never raw",
              envelope["session_id"] == pseudonymous_id(salt, "sess-1")
              and envelope["uid"] == pseudonymous_id(salt, "researcher")
              and "sess-1" not in json.dumps(envelope), repr(envelope))
        check("prompt/text/content are dropped silently",
              "prompt" not in envelope and "text" not in envelope.get("nested", {})
              and envelope.get("nested", {}).get("command") == "/uxr-show",
              repr(envelope))

        # 4. record_event: consent gates the buffer; no network here.
        check("consent off writes nothing",
              not record_event("session_summary", {}, "s", config=disabled,
                               state_dir=state, environ={}, home=HOME)
              and not any(state.glob("events-*.jsonl")))
        check("consent on writes one buffer line",
              record_event("session_summary", {"user_messages": 4}, "s1",
                           config=enabled, state_dir=state, environ={}, home=HOME,
                           now="2026-11-09T12:00:01-05:00")
              and record_event("session_summary", {"user_messages": 2}, "s2",
                               config=enabled, state_dir=state, environ={}, home=HOME,
                               now="2026-11-09T12:00:02-05:00"))
        buffer = buffer_path(state, "2026-11")
        rows = [json.loads(line) for line in
                buffer.read_text(encoding="utf-8").splitlines() if line.strip()]
        check("buffer is one JSON line per event with scrubbed payload",
              len(rows) == 2 and rows[0]["event"] == "session_summary"
              and rows[0]["session_id"] == pseudonymous_id(salt, "s1")
              and "prompt" not in json.dumps(rows) and "text" not in json.dumps(rows),
              repr(rows))

        # 5. read_buffer_lines: offsets, limits, partial lines.
        lines, next_offset = read_buffer_lines(buffer, 0, limit=1)
        check("limit reads at most N complete lines",
              len(lines) == 1 and next_offset == 1, repr((lines, next_offset)))
        rest, rest_offset = read_buffer_lines(buffer, next_offset)
        check("the remainder resumes at the offset",
              len(rest) == 1 and rest_offset == 2, repr((rest, rest_offset)))
        with open(buffer, "a", encoding="utf-8") as handle:
            handle.write('{"v":1,"event":"partial"}')  # no trailing newline
        partial_lines, partial_offset = read_buffer_lines(buffer, 0)
        check("a trailing partial line is never read",
              len(partial_lines) == 2 and partial_offset == 2,
              repr((partial_lines, partial_offset)))

        # 6. resolve_state_dir: env override and unexpanded placeholder.
        check("UXR_STATE_DIR overrides config",
              str(resolve_state_dir(None, environ={ENV_STATE_DIR: str(tmp / "other")}))
              == str((tmp / "other").resolve())
              or str(resolve_state_dir(None, environ={ENV_STATE_DIR: str(tmp / "other")}))
              == str(tmp / "other"))
        check("an unexpanded ${VAR} resolves to None",
              resolve_state_dir({"paths": {"state_dir": "${UNSET_VAR_X}/state"}},
                                environ={}) is None)

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
