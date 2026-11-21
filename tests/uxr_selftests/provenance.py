from _harness import bind

bind("hooks.provenance", globals())

import tempfile  # selftest-only import (moved from hooks/provenance.py)

def selftest_fixture_dir() -> Path:
    """Selftest fixture root outside the OS temp dir.

    Reads under ``/tmp`` are never sources (``is_excluded_path``), so a
    fixture tree under the OS temp dir would fall outside provenance on
    Linux; a HOME subdirectory keeps fixture reads tracked on every OS.
    """
    root = Path.home() / ".uxr-plugin-selftests"
    root.mkdir(parents=True, exist_ok=True)
    return root


def extract_provenance(transcript_path, research_dirs=None, config: dict | None = None,
                       home=None) -> dict:
    """Walk one transcript file and return its provenance record.

    Missing or unreadable transcript: an empty record (no sources, no
    outputs, no relationships, no failures). Never raises.
    """
    if not transcript_path:
        return {"sources": [], "outputs": [], "files_read": [],
                "relationships": [], "tool_failures": []}
    walk = TranscriptWalk(config=config, home=home)
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                walk.feed(obj)
    except OSError:
        pass
    return walk.result(research_dirs=research_dirs)


def _selftest() -> int:
    """Cover the acceptance items: a fake transcript yields the expected
    sources, outputs, edges, and failure kinds; excluded paths never become
    sources; the manifest files round-trip under the locks."""
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("hooks/provenance.py selftest")

    with tempfile.TemporaryDirectory(dir=str(selftest_fixture_dir())) as td:
        tmp = Path(td)
        HOME = tmp / "home"
        (HOME / ".claude").mkdir(parents=True)
        research = tmp / "research"
        research.mkdir()
        study_file = tmp / "notes.md"
        study_file.write_text("notes", encoding="utf-8")
        config = {"tracker": {"kind": "jira", "ticket_regex": r"\bABC-\d+\b",
                              "base_url": "https://example.atlassian.net"}}

        drive_hash = hash12("onboarding research")
        slack_hash = hash12("launch feedback")
        transcript = tmp / "transcript.jsonl"
        lines = [
            {"type": "user", "timestamp": "2026-11-09T10:00:00.000Z",
             "message": {"role": "user",
                         "content": "Check ABC-274 and refresh the summary doc"}},
            {"type": "assistant", "timestamp": "2026-11-09T10:00:05.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t1", "name": "mcp__jira__getJiraIssue",
                  "input": {"key": "ABC-274"}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:06.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t1", "content": "issue body"}]}},
            # A UUID-named server: the operation keyword classifies it.
            {"type": "assistant", "timestamp": "2026-11-09T10:00:07.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t2",
                  "name": "mcp__04b27de0-5b5d-4d1e-9f3a-a1b2c3d4e5f6__searchGoogleDrive",
                  "input": {"query": "onboarding research"}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:08.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t2", "content": "10 results"}]}},
            {"type": "assistant", "timestamp": "2026-11-09T10:00:09.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t3", "name": "Read",
                  "input": {"file_path": str(study_file)}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:10.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t3", "content": "text"}]}},
            {"type": "assistant", "timestamp": "2026-11-09T10:00:11.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t4", "name": "mcp__slack__search",
                  "input": {"query": "launch feedback"}},
                 {"type": "tool_use", "id": "t5", "name": "Write",
                  "input": {"file_path": str(tmp / "summary.md")}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:12.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t4", "content": "messages"},
                 {"type": "tool_result", "tool_use_id": "t5", "is_error": True,
                  "content": "The user doesn't want to proceed with this write."}]}},
            {"type": "assistant", "timestamp": "2026-11-09T10:00:13.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t6", "name": "mcp__jira__getJiraIssue",
                  "input": {"key": "AB-12"}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:14.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t6", "is_error": True,
                  "content": "connection reset"}]}},
            # Excluded paths are never sources.
            {"type": "assistant", "timestamp": "2026-11-09T10:00:15.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t7", "name": "Read",
                  "input": {"file_path": str(HOME / ".claude" / "settings.json")}},
                 {"type": "tool_use", "id": "t8", "name": "Read",
                  "input": {"file_path": "/tmp/scratch.md"}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:16.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t7", "content": "x"},
                 {"type": "tool_result", "tool_use_id": "t8", "content": "y"}]}},
            # A tracker create whose key only appears in the result text.
            {"type": "assistant", "timestamp": "2026-11-09T10:00:17.000Z",
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "t9", "name": "mcp__jira__createJiraIssue",
                  "input": {"summary": "new study"}}]}},
            {"type": "user", "timestamp": "2026-11-09T10:00:18.000Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "t9",
                  "content": "created ABC-300"}]}},
        ]
        transcript.write_text(
            "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
        )

        walk = TranscriptWalk(config=config, home=HOME)
        user_events = []
        with open(transcript, "r", encoding="utf-8") as handle:
            for line in handle:
                user_events.extend(walk.feed(json.loads(line)))
        provenance = walk.result(research_dirs=[research])
        source_ids = [s["id"] for s in provenance["sources"]]

        # 1. The walk events feed the collector in the same single pass.
        user_texts = [e[1] for e in user_events if e[0] == "user"]
        check("user events exclude tool results and carry text",
              len(user_texts) == 1 and "ABC-274" in user_texts[0], repr(user_texts))
        tool_events = [e for e in user_events if e[0] == "tool"]
        check("tool events carry the operation after the last __",
              any(e[1] == "mcp__04b27de0-5b5d-4d1e-9f3a-a1b2c3d4e5f6__searchGoogleDrive"
                  and e[2] == "searchGoogleDrive" for e in tool_events),
              repr(tool_events))

        # 2. Expected sources, classified by operation name.
        check("tracker source id uses the tracker prefix",
              "jira:ABC-274" in source_ids, repr(source_ids))
        check("drive search id hashes the query (UUID server ignored)",
              f"drive:search:{drive_hash}" in source_ids, repr(source_ids))
        check("slack search id hashes the query",
              f"slack:search:{slack_hash}" in source_ids, repr(source_ids))
        check("local file read is a file: source typed local_file",
              f"file:{study_file}" in source_ids
              and next(s for s in provenance["sources"]
                       if s["id"] == f"file:{study_file}")["type"] == "local_file",
              repr(source_ids))
        check("files under ~/.claude are not sources",
              not any(str(HOME / ".claude") in s for s in source_ids), repr(source_ids))
        check("files under /tmp are not sources",
              not any(s.startswith("file:/tmp") for s in source_ids), repr(source_ids))

        # 3. Outputs carry informed_by = sources read earlier in the session.
        outputs = provenance["outputs"]
        write_output = next((o for o in outputs if o["type"] == "file_edit"
                             and o["path"] == str(tmp / "summary.md")), None)
        create_output = next((o for o in outputs if o["type"] == "tracker_create"), None)
        check("file edit is an output", write_output is not None, repr(outputs))
        check("tracker create takes its key from the result text",
              create_output is not None and create_output["id"] == "ABC-300",
              repr(create_output))
        if write_output:
            expected = ["jira:ABC-274", f"drive:search:{drive_hash}",
                        f"file:{study_file}", f"slack:search:{slack_hash}"]
            check("informed_by holds every earlier source, in order",
                  write_output["informed_by"] == expected,
                  repr(write_output["informed_by"]))

        # 4. Relationships: one edge per output x source pair, across all outputs.
        expected_edges = sum(len(o["informed_by"]) for o in outputs)
        write_edges = len(write_output["informed_by"]) if write_output else 0
        check("relationship count matches informed_by pairs",
              len(provenance["relationships"]) == expected_edges
              and expected_edges >= write_edges,
              repr(provenance["relationships"]))

        # 5. Failure kinds: rejection phrase vs plain error.
        kinds = sorted(f["kind"] for f in provenance["tool_failures"])
        check("rejection phrase yields user_rejection, other errors tool_error",
              kinds == ["tool_error", "user_rejection"],
              repr(provenance["tool_failures"]))
        rejection = next((f for f in provenance["tool_failures"]
                          if f["kind"] == "user_rejection"), {})
        check("rejection names the failing tool",
              rejection.get("tool") == "Write", repr(rejection))

        # 6. research_dirs tags local sources inside research dirs.
        file_source = next((s for s in provenance["sources"]
                            if s["id"] == f"file:{study_file}"), {})
        check("in_research is False outside research dirs",
              file_source.get("in_research") is False, repr(file_source))

        # 7. Workspace manifests round-trip.
        workspace = tmp / "research" / "study-a"
        (workspace / SESSIONS_DIRNAME).mkdir(parents=True)
        record = {"session_id": "s1", "ended_at": "2026-11-09T12:00:00-05:00",
                  "ticket_keys": ["ABC-274"]}
        written = write_workspace_manifests(workspace, record, provenance, config=config)
        manifest = session_manifest_path(workspace, "2026-11-09T12:00:00-05:00")
        check("session record written with colons to hyphens",
              manifest.is_file() and "session_record" in written, repr(written))
        edge_lines = [json.loads(l) for l in
                      (workspace / SESSIONS_DIRNAME / PROVENANCE_FILE)
                      .read_text(encoding="utf-8").splitlines() if l.strip()]
        check("one provenance line per edge with the contract fields",
              len(edge_lines) == expected_edges
              and sum(1 for e in edge_lines if e["output"] == str(tmp / "summary.md"))
              == write_edges
              and all(e["relationship"] == "informed_by"
                      and e["session_id"] == "s1"
                      and e["timestamp"] == "2026-11-09T12:00:00-05:00"
                      and all(k in e for k in ("source_id", "source_url",
                                               "output_type", "output_url"))
                      for e in edge_lines),
              repr(edge_lines[:1]))
        tracker_edge = next((e for e in edge_lines
                             if e["output_type"] == "tracker_create"), None)
        check("tracker edge builds the browse URL from config",
              tracker_edge is not None
              and tracker_edge["output_url"] == "https://example.atlassian.net/browse/ABC-300",
              repr(tracker_edge))
        index = json.loads((workspace / SESSIONS_DIRNAME / SOURCES_INDEX_FILE)
                           .read_text(encoding="utf-8"))
        check("sources index dedupes by id with first_seen/last_seen/times_consulted",
              len(index) == len(source_ids)
              and all(e["times_consulted"] == 1 and e["first_seen"] and e["last_seen"]
                      for e in index.values()),
              repr(index))
        first_seen = index["jira:ABC-274"]["first_seen"]
        # A second session consults the same sources without duplicating ids.
        update_sources_index(workspace, provenance["sources"], now="2026-11-10T09:00:00Z")
        index2 = json.loads((workspace / SESSIONS_DIRNAME / SOURCES_INDEX_FILE)
                            .read_text(encoding="utf-8"))
        check("second consult bumps times_consulted and keeps first_seen",
              len(index2) == len(source_ids)
              and index2["jira:ABC-274"]["times_consulted"] == 2
              and index2["jira:ABC-274"]["first_seen"] == first_seen
              and index2["jira:ABC-274"]["last_seen"] == "2026-11-10T09:00:00Z",
              repr(index2.get("jira:ABC-274")))

        # 8. A missing transcript yields the empty record.
        empty = {"sources": [], "outputs": [], "files_read": [],
                 "relationships": [], "tool_failures": []}
        check("missing transcript yields empty record",
              extract_provenance(tmp / "absent.jsonl") == empty,
              repr(extract_provenance(tmp / "absent.jsonl")))

        # 9. hash12 is stable and 12 hex characters.
        check("hash12 is stable and 12 hex",
              hash12("x") == hash12("x") and len(hash12("x")) == 12
              and all(c in "0123456789abcdef" for c in hash12("x")),
              hash12("x"))

        # 9b. An anchored validator regex still matches free text (F3).
        anchored = ticket_regex({"tracker": {"kind": "jira",
                                             "ticket_regex": r"^UXR-[0-9]+$"}})
        found = anchored.search("plan UXR-101 for onboarding")
        check("an anchored ticket_regex compiles for search",
              found is not None and found.group(0) == "UXR-101", repr(found))
        check("a non-anchored ticket_regex is unchanged",
              ticket_regex({"tracker": {"kind": "jira",
                                        "ticket_regex": r"\bUXR-\d+\b"}})
              .search("plan UXR-101") is not None)
        check("an anchors-only ticket_regex falls back to the generic pattern",
              ticket_regex({"tracker": {"kind": "jira", "ticket_regex": "^$"}})
              is FALLBACK_KEY_RE)
        walk_anchored = TranscriptWalk(config={"tracker": {"kind": "jira",
                                                           "ticket_regex": r"^ABC-\d+$"}})
        walk_anchored.feed({"type": "assistant", "timestamp": "t",
                            "message": {"role": "assistant", "content": [
                                {"type": "tool_use", "id": "t10",
                                 "name": "mcp__jira__createJiraIssue",
                                 "input": {"summary": "new study"}}]}})
        walk_anchored.feed({"type": "user", "timestamp": "t",
                            "message": {"role": "user", "content": [
                                {"type": "tool_result", "tool_use_id": "t10",
                                 "content": "created ABC-300"}]}})
        anchored_outputs = walk_anchored.result()["outputs"]
        check("an anchored regex takes the create key from the result text",
              bool(anchored_outputs) and anchored_outputs[0].get("id") == "ABC-300",
              repr(anchored_outputs))

        # 10. The locks release (no leftover lock files).
        leftovers = list((workspace / SESSIONS_DIRNAME).glob("*.lock"))
        check("file locks release", not leftovers, repr(leftovers))

        # 11. Hook-mode stdin is recognized; CLI stdin is not.
        check("a hook event on stdin is recognized",
              stdin_names_hook_event(io.StringIO('{"hook_event_name": "Stop"}')) is True,
              "")
        check("plain piped stdin stays CLI mode",
              stdin_names_hook_event(io.StringIO("hello world")) is False, "")
        check("empty stdin stays CLI mode",
              stdin_names_hook_event(io.StringIO()) is False, "")

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 1
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
