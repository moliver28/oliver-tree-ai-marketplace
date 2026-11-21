from _harness import bind

bind("hooks.analytics_flush", globals())
def _selftest() -> int:
    """Cover the acceptance item - with analytics off no network call occurs
    (the opener is mocked and counted) - plus offsets, budgets, batching,
    partial lines, and the honest one-time notice."""
    import tempfile

    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append(name)

    print("hooks/analytics_flush.py selftest")

    class Reply:
        def __init__(self, status):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        HOME = tmp / "home"
        (HOME / ".claude").mkdir(parents=True)
        state = tmp / "state"
        endpoint = "https://telemetry.example.invalid/ingest"
        enabled = {"analytics": {"enabled": True, "endpoint": endpoint, "api_key": "k"}}
        no_endpoint = {"analytics": {"enabled": True, "endpoint": "", "api_key": ""}}
        disabled = {"analytics": {"enabled": False, "endpoint": endpoint, "api_key": ""}}

        calls = []

        def mock_open(request, timeout):
            calls.append((request.full_url, timeout))
            return Reply(200)

        # 1. Consent off: no network call, no notice.
        out = handle_start({}, config=disabled, state_dir=state,
                           environ={}, home=HOME, open_fn=mock_open)
        check("consent off sends nothing", not calls, repr(calls))
        check("consent off prints nothing", out == "", repr(out[:80]))

        # 2. Consent on but no endpoint: still no network call.
        calls.clear()
        out = handle_start({}, config=no_endpoint, state_dir=state,
                           environ={}, home=HOME, open_fn=mock_open)
        check("no endpoint sends nothing", not calls, repr(calls))
        check("the no-endpoint notice says data stays local",
              "nothing is sent" in out and "locally" in out, repr(out[:120]))
        check("the notice is SessionStart additionalContext",
              json.loads(out).get("hookSpecificOutput", {}).get("hookEventName")
              == "SessionStart", repr(out[:80]))
        check("the notice shows once (marker written)",
              handle_start({}, config=no_endpoint, state_dir=state,
                           environ={}, home=HOME, open_fn=mock_open) == "")

        # 3. A 200 flush advances the offset by exactly the sent lines.
        calls.clear()
        (state / NOTICE_FILE).unlink(missing_ok=True)
        buffer = analytics_common.buffer_path(state)
        with buffer.open("w", encoding="utf-8", newline="\n") as handle:
            for index in range(3):
                handle.write(json.dumps({"v": 1, "event": "e%d" % index}) + "\n")
        summary = flush(state, endpoint, api_key="k", open_fn=mock_open)
        check("all lines sent on HTTP 200", summary["sent"] == 3, repr(summary))
        check("one request made", len(calls) == 1 and calls[0][1] == 2.5, repr(calls))
        saved = load_offsets(state)
        check("the offset advanced to 3", saved.get(analytics_common.buffer_path(state).name) == 3,
              repr(saved))
        calls.clear()
        summary = flush(state, endpoint, api_key="k", open_fn=mock_open)
        check("a second flush sends nothing new", summary["sent"] == 0 and not calls,
              repr((summary, calls)))

        # 4. A failed flush leaves the batch pending and the offset unchanged.
        def failing_open(request, timeout):
            calls.append(request.full_url)
            return Reply(500)

        buffer = analytics_common.buffer_path(state)
        with buffer.open("a", encoding="utf-8", newline="\n") as handle:
            for index in range(2):
                handle.write(json.dumps({"v": 1, "event": "f%d" % index}) + "\n")
        calls.clear()
        summary = flush(state, endpoint, open_fn=failing_open)
        check("a non-200 response sends nothing through and keeps the offset",
              summary["sent"] == 0
              and load_offsets(state).get(analytics_common.buffer_path(state).name) == 3,
              repr((summary, load_offsets(state))))
        calls.clear()
        summary = flush(state, endpoint, open_fn=mock_open)
        check("the pending batch is retried on the next flush",
              summary["sent"] == 2
              and load_offsets(state).get(analytics_common.buffer_path(state).name) == 5,
              repr(summary))

        # 5. Batching: at most 100 complete lines per request.
        calls.clear()
        (state / "events-2000-01.jsonl").write_text(
            "".join(json.dumps({"v": 1, "event": "bulk%d" % index}) + "\n"
                    for index in range(250)), encoding="utf-8")
        summary = flush(state, endpoint, open_fn=mock_open)
        check("the first batch stops at 100 lines", summary["sent"] == 100, repr(summary))
        check("the offset counts only what was sent",
              load_offsets(state).get("events-2000-01.jsonl") == 100, repr(load_offsets(state)))
        summary = flush(state, endpoint, open_fn=mock_open)
        check("the second batch takes the next 100", summary["sent"] == 100, repr(summary))

        # 6. A trailing partial line is never read or counted.
        (state / "events-2000-02.jsonl").write_text(
            json.dumps({"v": 1, "event": "whole"}) + "\n" + '{"v":1,"event":"half',
            encoding="utf-8")
        calls.clear()
        summary = flush(state, endpoint, open_fn=mock_open)
        check("the partial trailing line is not sent",
              summary["sent"] >= 1
              and load_offsets(state).get("events-2000-02.jsonl") == 1,
              repr(summary))
        lines, next_offset = analytics_common.read_buffer_lines(
            state / "events-2000-02.jsonl", 0)
        check("the partial line stays pending in place",
              len(lines) == 1 and next_offset == 1, repr((lines, next_offset)))

        # 7. The budget stops the flush after the deadline.
        calls.clear()
        buffer = analytics_common.buffer_path(state)
        with buffer.open("a", encoding="utf-8", newline="\n") as handle:
            for index in range(30):
                handle.write(json.dumps({"v": 1, "event": "budget%d" % index}) + "\n")

        def slow_open(request, timeout):
            calls.append(request.full_url)
            time.sleep(0.05)
            return Reply(200)

        summary = flush(state, endpoint, open_fn=slow_open, budget=0.12)
        check("the flush stops at the total budget",
              summary["sent"] > 0 and len(calls) < 6, repr((summary, len(calls))))

        # 8. The endpoint notice is honest about sending.
        text = notice_text(endpoint)
        check("the sending notice names the endpoint and the opt-outs",
              endpoint in text and "analytics.enabled" in text
              and "UXR_ANALYTICS" in text, repr(text[:120]))

    if failures:
        print("selftest FAILED (%d check(s))" % len(failures))
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
