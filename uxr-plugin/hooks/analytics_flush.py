#!/usr/bin/env python3
"""SessionStart flush: send buffered usage counts when consent allows.

Fires on SessionStart (see hooks/hooks.json). With consent off, nothing
runs at all: no network, no notice, no offset change -- verified in the
self-test with a mocked opener. With consent on:

1. Flush: for every ``events-YYYY-MM.jsonl`` in the state dir, send at
   most 100 complete lines per file past a saved line offset, to
   ``analytics.endpoint``. Each request gets a 2.5 second timeout; the
   whole flush shares a 3 second budget. The offset advances only on
   HTTP 200. The buffer is never rewritten.
2. Notice: the first time analytics run, print one SessionStart
   additionalContext message that states the real behavior -- if the
   flush sends data, the notice says so; if no endpoint is configured,
   the notice says events stay local. The notice is shown once.

Offsets live in ``<state_dir>/flush-offsets.json`` (``{file: next_line}``).
A trailing partial line (no newline yet) is never read and never counted.

Usage::

    python hooks/analytics_flush.py selftest     # run the self-test
    python hooks/analytics_flush.py --selftest   # same, flag form
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
import urllib.request
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import analytics_common  # noqa: E402

BATCH_LINES = 100
REQUEST_TIMEOUT = 2.5
TOTAL_BUDGET = 3.0
OFFSET_FILE = "flush-offsets.json"
NOTICE_FILE = "analytics-notice"


def _load_config() -> dict | None:
    """Load the plugin config through the one loader; None on any failure."""
    try:
        from lib.config import load_config

        return load_config()
    except Exception:
        return None


def _open(request, timeout):
    """One network call, isolated so tests can mock it."""
    return urllib.request.urlopen(request, timeout=timeout)


def load_offsets(state_dir) -> dict:
    """Saved offsets ``{filename: next_line}``; {} on any failure."""
    path = Path(state_dir) / OFFSET_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_offsets(state_dir, offsets: dict) -> bool:
    """Persist offsets atomically; best effort."""
    try:
        path = Path(state_dir) / OFFSET_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(offsets, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        return True
    except OSError:
        return False


def flush(state_dir, endpoint: str, api_key: str = "", offsets: dict | None = None,
          open_fn=None, budget: float = TOTAL_BUDGET,
          request_timeout: float = REQUEST_TIMEOUT) -> dict:
    """Send buffered lines; return ``{"sent", "calls", "advanced", "done"}``.

    Never raises. Without an endpoint nothing is sent, and non-``https://``
    endpoints are refused (never POST over plaintext http). Offsets advance
    only on HTTP 200; failed batches stay pending for the next flush.
    """
    summary = {"sent": 0, "calls": 0, "advanced": [], "done": False}
    if not endpoint:
        return summary
    if not endpoint.startswith("https://"):
        return summary  # refuse plaintext-http endpoints
    state_dir = Path(state_dir)
    if offsets is None:
        offsets = load_offsets(state_dir)
    saved = dict(offsets)
    send = open_fn if open_fn is not None else _open
    deadline = time.monotonic() + budget
    try:
        buffers = sorted(state_dir.glob("events-*.jsonl"))
    except OSError:
        return summary
    for path in buffers:
        if time.monotonic() >= deadline:
            break
        key = path.name
        while time.monotonic() < deadline:
            offset = int(saved.get(key, 0) or 0)
            lines, next_offset = analytics_common.read_buffer_lines(
                path, offset=offset, limit=BATCH_LINES)
            if not lines:
                break
            events = []
            for line in lines:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue  # a malformed complete line is consumed, not sent
            summary["calls"] += 1
            if not events:
                saved[key] = next_offset
                continue
            payload = json.dumps({"events": events}, ensure_ascii=False).encode("utf-8")
            request = urllib.request.Request(
                endpoint, data=payload,
                headers={"Content-Type": "application/json",
                         **({"Authorization": "Bearer " + api_key} if api_key else {})},
                method="POST")
            try:
                with send(request, timeout=request_timeout) as reply:
                    status = getattr(reply, "status", None) or reply.getcode()
            except Exception:
                break  # a failed batch stays pending; move to the next file
            if status != 200:
                break
            saved[key] = next_offset
            summary["sent"] += len(events)
            summary["advanced"].append(key)
            break  # at most one batch of BATCH_LINES per file per flush
    if saved != dict(offsets or {}):
        save_offsets(state_dir, saved)
    summary["done"] = True
    return summary


def notice_text(endpoint: str) -> str:
    """The one-time notice; it states what really happens to the data."""
    if endpoint:
        return (
            "UXR plugin usage analytics are on. At each session start the plugin sends "
            "anonymous usage counts (commands, agents, skills, failures - never prompt "
            "text, file paths, or content) to " + endpoint + ". Turn it off in "
            "config/org.yaml with analytics.enabled: false, or with a "
            "~/.claude/.uxr-analytics-off file, DO_NOT_TRACK=1, or UXR_ANALYTICS=off."
        )
    return (
        "UXR plugin usage analytics are on. Usage counts (commands, agents, skills, "
        "failures - never prompt text, file paths, or content) are recorded locally in "
        "this plugin's data directory; no endpoint is configured, so nothing is sent "
        "over the network. Configure analytics.endpoint to enable sending, or turn "
        "analytics off with analytics.enabled: false."
    )


def notice_pending(state_dir) -> bool:
    """True until the one-time notice has been shown."""
    if state_dir is None:
        return False
    return not (Path(state_dir) / NOTICE_FILE).is_file()


def mark_notice(state_dir) -> None:
    """Record that the notice was shown; best effort."""
    if state_dir is None:
        return
    try:
        path = Path(state_dir) / NOTICE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("shown\n", encoding="utf-8")
    except OSError:
        return


def handle_start(event=None, config=None, environ=None, home=None,
                 state_dir=None, open_fn=None) -> str:
    """SessionStart entry: flush, then the one-time notice; print nothing else."""
    try:
        if not analytics_common.analytics_enabled(config, environ=environ, home=home):
            return ""
        state = Path(state_dir) if state_dir is not None \
            else analytics_common.resolve_state_dir(config, environ=environ)
        if state is not None:
            tracker = config.get("analytics", {}) if isinstance(config, dict) else {}
            endpoint = str(tracker.get("endpoint") or "")
            api_key = str(tracker.get("api_key") or "")
            flush(state, endpoint, api_key=api_key, open_fn=open_fn)
        if notice_pending(state):
            mark_notice(state)
            payload = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": notice_text(endpoint),
                }
            }
            return json.dumps(payload)
        return ""
    except Exception:
        return ""


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "selftest" in args or "--selftest" in args:
        return _selftest()
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    with contextlib.suppress(Exception):
        output = handle_start(event, config=_load_config())
    if output:
        print(output)
    return 0


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
        with open(analytics_common.buffer_path(state), "w", encoding="utf-8",
                  newline="\n") as handle:
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

        with open(analytics_common.buffer_path(state), "a", encoding="utf-8",
                  newline="\n") as handle:
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
        with open(analytics_common.buffer_path(state), "a", encoding="utf-8",
                  newline="\n") as handle:
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
    raise SystemExit(main())
