from _harness import bind

bind("scripts.trace_prompts", globals())
def _selftest() -> int:
    """Cover the acceptance items: no argument exits 2; a spec with no
    transcript_path and no manifests returns []; only user_message events
    are read; manifests contribute the recorded snippet."""
    import tempfile

    failures = []

    def check(name, condition, detail=""):
        print("  [%s] %s" % ("ok" if condition else "FAIL", name))
        if not condition:
            failures.append(name)

    print("scripts/trace_prompts.py selftest")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        state = tmp / "state" / "specs"
        state.mkdir(parents=True)
        research = tmp / "research" / "study-a" / ".sessions"
        research.mkdir(parents=True)
        environ = {"UXR_STATE_DIR": str(tmp / "state"),
                   "UXR_RESEARCH_DIRS": str(tmp / "research")}
        config = {"tracker": {"bare_number_prefix": "ABC"},
                  "paths": {"research_root": str(tmp / "research")}}

        # A spec with a transcript holding three events; only user messages count.
        transcript = tmp / "transcript.jsonl"
        lines = [
            {"type": "user", "timestamp": "2026-11-08T09:00:00.000Z",
             "message": {"role": "user", "content": "Plan the permissions study"}},
            {"type": "assistant", "timestamp": "2026-11-08T09:00:01.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t1", "name": "Read",
                  "input": {"file_path": "/x"}}]}},
            {"type": "user", "timestamp": "2026-11-08T09:00:02.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1", "content": "leaked?"}]}},
            {"type": "user", "timestamp": "2026-11-08T09:00:03.000Z", "isMeta": True,
             "message": {"role": "user", "content": "meta line"}},
            {"type": "user", "timestamp": "2026-11-08T09:00:04.000Z",
             "message": {"role": "user", "content": "Second question about ABC-237"}},
        ]
        transcript.write_text("".join(json.dumps(l) + "\n" for l in lines),
                              encoding="utf-8")
        spec = {"_meta": {"created_at": "2026-11-08T09:00:00Z",
                          "last_edited_at": "2026-11-08T09:00:00Z",
                          "last_edited_by_command": "new",
                          "tracker_updated_at": None,
                          "session_id": "sA",
                          "transcript_path": str(transcript)}}
        (state / "ABC-237.spec.json").write_text(json.dumps(spec), encoding="utf-8")

        # A manifest whose record names the same key.
        manifest = {"session_id": "sB", "ended_at": "2026-11-08T18:00:00Z",
                    "ticket_keys": ["ABC-237"],
                    "last_user_at": "2026-11-08T17:30:00.000Z",
                    "last_user_snippet": "Follow up on the pilot findings"}
        (research / "2026-11-08T18-00-00Z.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        # An unrelated record that must be skipped.
        (research / "gate-state.json").write_text('{"studies": {}}', encoding="utf-8")

        prompts = collect("ABC-237", config, environ=environ)
        check("two transcript prompts and one manifest prompt",
              len(prompts) == 3, repr([p["origin"] for p in prompts]))
        check("only user_message events are read (no tool results, no meta)",
              all("leaked" not in p["text"] and "meta line" not in p["text"]
                  for p in prompts), repr(prompts))
        check("origins are transcript and manifest",
              [p["origin"] for p in prompts]
              == ["transcript", "transcript", "manifest"], repr(prompts))
        check("prompts are time-sorted",
              prompts == sorted(prompts, key=lambda p: p["ts"]), repr(prompts))
        check("the manifest prompt carries the recorded snippet",
              prompts[-1]["text"] == "Follow up on the pilot findings"
              and prompts[-1]["session_id"] == "sB", repr(prompts[-1]))
        check("a bare number normalizes to the prefixed key",
              collect("237", config, environ=environ) == prompts,
              repr(len(collect("237", config, environ=environ))))

        # A key with nothing anywhere: [].
        check("an unknown key returns []",
              collect("ABC-999", config, environ=environ) == [],
              repr(collect("ABC-999", config, environ=environ)))

        # A spec whose _meta has no transcript_path and no manifests: [].
        empty_spec = {"_meta": {"session_id": "sC", "transcript_path": None}}
        (state / "ABC-500.spec.json").write_text(json.dumps(empty_spec), encoding="utf-8")
        check("a spec with no transcript_path and no manifests returns []",
              collect("ABC-500", config, environ=environ) == [],
              repr(collect("ABC-500", config, environ=environ)))

        # main(): no argument exits 2; output is verbatim JSON.
        import io
        from contextlib import redirect_stderr

        err = io.StringIO()
        with redirect_stderr(err):
            code = main([])
        check("no argument exits 2", code == 2, repr(code))
        check("no argument prints usage on stderr",
              "usage" in err.getvalue(), repr(err.getvalue()[:60]))
        import contextlib

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["ABC-999"], environ=environ)
        check("an empty result prints [] and exits 0",
              code == 0 and out.getvalue().strip() == "[]", repr(out.getvalue()))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["ABC-237"], environ=environ)
        parsed = json.loads(out.getvalue())
        check("stdout is the verbatim JSON list", isinstance(parsed, list)
              and len(parsed) == 3, repr(len(parsed)))

    # W2 rq-map: the phase 6 map is mechanical and matches the baseline map.
    golden_spec = {
        "research_questions": [
            "Where do first-week users look for the timeline when they want to plan?",
            "What does a first-session planning attempt look like for a new project manager?",
            "What makes the timeline entry discoverable in the left navigation vs the header toolbar?",
        ],
        "hypotheses": [
            {"label": "H1", "text": "First-week users look for planning features in the header toolbar before the left navigation."},
            {"label": "H2", "text": "New project managers who find the timeline in their first session build a plan in that session."},
            {"label": "H3", "text": "A navigation change increases first-session timeline discovery more than a guided tour."},
        ],
    }
    mapped = rq_map(golden_spec)
    check("rq map traces like the baseline",
          [entry["traces_to"] for entry in mapped["map"]] == [["H1"], ["H2"], ["H1", "H3"]],
          json.dumps(mapped["map"]))
    orphaned = rq_map({"research_questions": ["What color should the button be?"],
                       "hypotheses": golden_spec["hypotheses"][:1]})
    check("rq map lists unmapped RQs under the drop rule",
          orphaned["unmapped"] == ["RQ1"], json.dumps(orphaned["unmapped"]))

    if failures:
        print("selftest FAILED (%d check(s))" % len(failures))
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
