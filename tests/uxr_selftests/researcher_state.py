"""Researcher journal self-test: the digest read path and the hook's append duty (issue 120).

Binds ``scripts/researcher_state.py`` (the digest CLI and journal helpers)
and drives ``hooks/review_gate.py`` end to end on a synthetic subagent
transcript: the full facts line, the pointer-only fallback line, the Stop
no-append law, the digest window and open p0 count, and the fail-open
behavior when no state dir resolves.
"""
from _harness import bind

bind("scripts.researcher_state", globals())

import contextlib  # selftest-only import
import importlib  # selftest-only import
import io  # selftest-only import
import os  # selftest-only import (env override law)
import tempfile  # selftest-only import

review_gate = importlib.import_module("hooks.review_gate")

REVIEW_TEXT = (
    "Summary\n"
    "The draft traces to the decision but one claim lacks a source.\n"
    "\n"
    "Strengths\n"
    "- Clear decision trace\n"
    "\n"
    "Risks\n"
    "- The toolbar claim has no cited source\n"
    "\n"
    "What to change\n"
    "- Add a source for the toolbar claim\n"
    "\n"
    "findings:\n"
    "- {claim: The toolbar claim lacks a cited source, source: draft spec H1, confidence: high}\n"
    "\n"
    'verdict: {"result": "p0", "p0": ["toolbar claim"]}\n'
)
FULL_LINE_KEYS = ["agent_id", "artifact_kind", "findings", "ran_at", "session_id", "summary", "verdict"]
POINTER_KEYS = ["agent_id", "ran_at", "session_id", "transcript_path"]


def _write_transcript(path, kind, review_text) -> None:
    """One synthetic subagent transcript: the labeled dispatch head, then the review tail."""
    dispatch = (
        '{"type":"user","message":{"content":"Review the artifact. '
        "Artifact kind: %s\\n<study context>\"}}" % kind
    )
    lines = [dispatch]
    if review_text:
        lines.append(
            json.dumps(
                {"type": "assistant", "message": {"content": [{"type": "text", "text": review_text}]}}
            )
        )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _digest(*args) -> tuple[int, list[str]]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(list(args))
    return code, buffer.getvalue().splitlines()


def _selftest() -> int:
    failures: list[str] = []

    def check(name, condition, detail=""):
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/researcher_state.py self-test (with the hooks/review_gate.py journal duty)")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        state = tmp / "state"
        config = {"paths": {"state_dir": str(state)}}
        os.environ["UXR_STATE_DIR"] = str(state)
        workspace = tmp / "research" / "admin-permissions-study"
        (workspace / review_gate.SESSIONS_DIRNAME).mkdir(parents=True)
        (workspace / review_gate.OVERVIEW_MARKER).write_text(
            "# Admin permissions study\n\nTicket: ABC-237\n", encoding="utf-8"
        )
        journal = state / "researcher" / "ABC-237.journal.jsonl"

        code, lines = _digest("digest", "--key", "ABC-237")
        check(
            "digest with no journal prints 'no prior reviews' and exits 0",
            code == 0 and lines == ["no prior reviews"],
            f"code={code} out={lines!r}",
        )
        check("digest without --key exits 2", main(["digest"]) == 2, "expected usage exit 2")
        check("digest with a bad --last exits 2", main(["digest", "--key", "K", "--last", "x"]) == 2, "expected usage exit 2")

        transcript = tmp / "ts.jsonl"
        _write_transcript(transcript, "draft", REVIEW_TEXT)
        event = {
            "hook_event_name": "SubagentStop",
            "agent_type": "hcd-researcher",
            "agent_id": "agent-9",
            "session_id": "s1",
            "cwd": str(workspace),
            "transcript_path": str(transcript),
        }
        check(
            "SubagentStop prints nothing and writes the marker",
            review_gate.handle_subagent_stop(event, config=config) == ""
            and review_gate.marker_path(workspace, "ABC-237").is_file(),
            "expected silence plus a marker",
        )
        rows = read_rows(journal)
        check("one journal line appended", len(rows) == 1, repr(rows)[:160])
        row = rows[0] if rows else {}
        check("the full line carries exactly the seven contract keys", sorted(row) == FULL_LINE_KEYS, sorted(row))
        check("artifact kind comes from the dispatch head", row.get("artifact_kind") == "draft", repr(row.get("artifact_kind")))
        check(
            "the verdict line parses",
            isinstance(row.get("verdict"), dict)
            and row["verdict"].get("result") == "p0"
            and row["verdict"].get("p0") == ["toolbar claim"],
            repr(row.get("verdict")),
        )
        finding = (row.get("findings") or [{}])[0]
        check(
            "the findings entry parses with all three keys",
            "toolbar claim" in str(finding.get("claim"))
            and finding.get("source") == "draft spec H1"
            and finding.get("confidence") == "high",
            repr(row.get("findings")),
        )
        check("the summary section is carried", "decision" in str(row.get("summary")), repr(row.get("summary")))

        before = journal.read_text(encoding="utf-8")
        review_gate.handle_subagent_stop(
            {
                "hook_event_name": "Stop",
                "cwd": str(workspace),
                "session_id": "s2",
                "transcript_path": str(transcript),
            },
            config=config,
        )
        check("a Stop fire appends nothing", journal.read_text(encoding="utf-8") == before, "journal moved")

        review_gate.handle_subagent_stop(
            {
                "hook_event_name": "SubagentStop",
                "agent_type": "novice-participant",
                "cwd": str(workspace),
                "session_id": "s3",
                "transcript_path": str(transcript),
            },
            config=config,
        )
        check("another agent's SubagentStop appends nothing", len(read_rows(journal)) == 1, "journal moved")

        bare = tmp / "bare.jsonl"
        _write_transcript(bare, "draft", "")
        review_gate.handle_subagent_stop(
            {
                "hook_event_name": "SubagentStop",
                "agent_type": "hcd-researcher",
                "agent_id": "agent-10",
                "session_id": "s4",
                "cwd": str(workspace),
                "transcript_path": str(bare),
            },
            config=config,
        )
        rows = read_rows(journal)
        check(
            "a review with no parseable shape appends the pointer-only line",
            len(rows) == 2 and sorted(rows[1]) == POINTER_KEYS and rows[1].get("agent_id") == "agent-10",
            repr(rows[1:])[:160],
        )

        code, lines = _digest("digest", "--key", "ABC-237")
        check(
            "digest prints the window header, two rows, and the open p0 count",
            code == 0
            and lines[0] == "prior reviews (last 2 of 2):"
            and lines[2].split(" ")[1] == "unparsed"
            and lines[-1] == "open p0 items: 1",
            repr(lines),
        )
        check(
            "the digest row carries date, kind, verdict, and the summary sentence",
            lines[1].startswith("20") and " draft p0 " in lines[1] and "decision" in lines[1],
            repr(lines[1]),
        )
        code, lines = _digest("digest", "--key", "ABC-237", "--last", "1")
        check(
            "--last 1 bounds the window to the newest row",
            lines[0] == "prior reviews (last 1 of 2):" and "unparsed" in lines[1] and lines[-1] == "open p0 items: 0",
            repr(lines),
        )

        with open(journal, "a", encoding="utf-8") as handle:
            handle.write("{not json\n")
        code, lines = _digest("digest", "--key", "ABC-237", "--last", "2")
        check(
            "a malformed journal line stays out of the digest",
            code == 0 and len(lines) == 4 and lines[0] == "prior reviews (last 2 of 2):",
            repr(lines),
        )

        facts = review_gate._review_facts(str(transcript))
        check(
            "review facts parse the verdict, summary, and findings from the tail",
            facts.get("summary") and facts.get("verdict") and len(facts.get("findings") or []) == 1,
            repr(facts)[:160],
        )
        strict = tmp / "strict.jsonl"
        _write_transcript(
            strict,
            "report",
            'findings:\n- {"claim": "Quoted claim", "source": "report", "confidence": "low"}\n',
        )
        facts = review_gate._review_facts(str(strict))
        check(
            "a strict-JSON findings entry parses too",
            (facts.get("findings") or [{}])[0].get("claim") == "Quoted claim",
            repr(facts),
        )
        junk = tmp / "junk.jsonl"
        junk.write_text("not json at all\n", encoding="utf-8")
        check("a garbage transcript yields no facts", review_gate._review_facts(str(junk)) == {}, "expected empty facts")

        os.environ.pop("UXR_STATE_DIR", None)
        other = tmp / "research" / "other-study"
        (other / review_gate.SESSIONS_DIRNAME).mkdir(parents=True)
        (other / review_gate.OVERVIEW_MARKER).write_text("# Other\n\nTicket: ABC-300\n", encoding="utf-8")
        check(
            "SubagentStop without a resolvable state dir writes the marker and no journal",
            review_gate.handle_subagent_stop(
                {
                    "hook_event_name": "SubagentStop",
                    "agent_type": "hcd-researcher",
                    "agent_id": "a2",
                    "session_id": "s5",
                    "cwd": str(other),
                    "transcript_path": str(transcript),
                },
                config=None,
            )
            == ""
            and review_gate.marker_path(other, "ABC-300").is_file()
            and not (state / "researcher" / "ABC-300.journal.jsonl").exists(),
            "expected the fail-open path",
        )
        check("journal_path without a state dir is None", journal_path("ABC-300", None) is None, "expected None")
        check("append_line without a journal returns False", append_line(None, {"ran_at": "x"}) is False, "expected False")

        keyless = tmp / "research" / "no ticket yet"
        (keyless / review_gate.SESSIONS_DIRNAME).mkdir(parents=True)
        (keyless / review_gate.OVERVIEW_MARKER).write_text("# Draft study\n", encoding="utf-8")
        os.environ["UXR_STATE_DIR"] = str(state)
        review_gate.handle_subagent_stop(
            {
                "hook_event_name": "SubagentStop",
                "agent_type": "hcd-researcher",
                "agent_id": "a3",
                "session_id": "s6",
                "cwd": str(keyless),
                "transcript_path": str(bare),
            },
            config=None,
        )
        os.environ.pop("UXR_STATE_DIR", None)
        check(
            "the workspace-name key fallback journals under the sanitized folder name",
            (state / "researcher" / "no-ticket-yet.journal.jsonl").is_file(),
            "journal missing",
        )

    if failures:
        print(f"self-test FAILED ({len(failures)} check(s))")
        return 4
    print("self-test: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
