#!/usr/bin/env python3
"""The prompts behind one study: ``[{session_id, ts, text, origin}]``.

``trace --prompts <KEY>`` runs this. Two sources, merged by time:

- the spec's transcript: ``<state_dir>/specs/<KEY>.spec.json`` carries
  ``_meta.transcript_path``; the transcript JSONL is read and ONLY
  ``user_message`` events are taken (``origin: "transcript"``);
- the workspace manifests: every ``<research_root>/*/.sessions/*.json``
  session record whose ``ticket_keys`` hold the key contributes its
  recorded last user message (``origin: "manifest"``).

Output: the JSON list printed to stdout verbatim, sorted by ``ts``. No
transcript path and no manifests: ``[]``. No argument: usage on stderr,
exit 2. Never invents a prompt: only recorded text is printed.

Usage::

    python scripts/trace_prompts.py ABC-237
    echo 42 | ...            # not supported; pass the key as an argument
    python scripts/trace_prompts.py --selftest
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

SESSIONS_DIR = ".sessions"
ENV_RESEARCH_DIRS = "UXR_RESEARCH_DIRS"


def _load_config() -> dict | None:
    """Load the plugin config through the one loader; None on any failure."""
    try:
        from lib.config import load_config

        return load_config()
    except Exception:
        return None


def normalize_key(key: str, config: dict | None) -> str:
    """A bare number becomes ``<bare_number_prefix>-<n>``; a key passes through."""
    text = str(key or "").strip()
    prefix = ""
    if isinstance(config, dict):
        tracker = config.get("tracker", {})
        if isinstance(tracker, dict):
            prefix = str(tracker.get("bare_number_prefix") or "").strip()
    if re.fullmatch(r"\d+", text) and prefix:
        return "%s-%s" % (prefix, text)
    return text


def spec_prompts(spec_path, session_id: str) -> list[dict]:
    """User-message prompts from one transcript JSONL, origin ``transcript``."""
    prompts: list[dict] = []
    if not spec_path:
        return prompts
    try:
        with open(spec_path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict) or obj.get("type") != "user" or obj.get("isMeta"):
                    continue
                message = obj.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                texts: list[str] = []
                if isinstance(content, str):
                    texts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text" \
                                and isinstance(block.get("text"), str):
                            texts.append(block["text"])
                text = "\n".join(texts).strip()
                if not text:
                    continue
                prompts.append({
                    "session_id": session_id,
                    "ts": str(obj.get("timestamp") or ""),
                    "text": text,
                    "origin": "transcript",
                })
    except OSError:
        return []
    return prompts


def manifest_prompts(research_roots: list[str], key: str) -> list[dict]:
    """Recorded last-user-message snippets from matching session records."""
    prompts: list[dict] = []
    for root in research_roots:
        base = Path(root)
        if not base.is_dir():
            continue
        try:
            candidates = sorted(base.glob("*/%s/*.json" % SESSIONS_DIR))
        except OSError:
            continue
        for path in candidates:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict):
                continue
            if "ticket_keys" not in record or "last_user_at" not in record:
                continue  # not a session record (markers, gate state)
            keys = [str(item) for item in record.get("ticket_keys") or []]
            if key not in keys:
                continue
            text = str(record.get("last_user_snippet") or "").strip()
            if not text:
                continue
            prompts.append({
                "session_id": str(record.get("session_id") or ""),
                "ts": str(record.get("last_user_at") or ""),
                "text": text,
                "origin": "manifest",
            })
    return prompts


def research_roots(config: dict | None, environ=None) -> list[str]:
    """UXR_RESEARCH_DIRS entries, then ``paths.research_root`` from the config."""
    environ = os.environ if environ is None else environ
    roots: list[str] = []
    for part in str(environ.get(ENV_RESEARCH_DIRS) or "").split(os.pathsep):
        if part.strip():
            roots.append(part.strip())
    if isinstance(config, dict):
        paths = config.get("paths", {})
        if isinstance(paths, dict):
            root = paths.get("research_root")
            if isinstance(root, str) and root.strip():
                roots.append(root)
    return roots


# --- W2: the RQ-to-hypothesis map + the drop rule (new phase 6) ---

RQ_STOPWORDS = frozenset(
    "what when where does with from that this than more they their have into "
    "before after during about while whose which will would could should look "
    "plan want makes like over under also each most many some such very".split())


def _content_words(text: str) -> list[str]:
    """Content words, lowercase; hyphenated compounds count double; a trailing
    plural s folds (managers -> manager)."""
    words: list[str] = []
    for raw in re.split(r"[^a-z0-9-]+", str(text).lower()):
        raw = raw.strip("-")
        if not raw or raw in RQ_STOPWORDS:
            continue
        if len(raw) < 4 and "-" not in raw:
            continue
        folded = raw[:-1] if len(raw) > 4 and raw.endswith("s") and not raw.endswith("ss") else raw
        words.append(folded)
        if "-" in raw:
            words.append(folded)  # compounds carry twice the weight
    return words


def rq_map(spec: dict) -> dict:
    """Mechanical RQ-to-hypothesis trace: two or more content words shared
    with a hypothesis (label or text) means the RQ traces to it. An RQ that
    traces to nothing is listed under ``unmapped`` - the phase 6 drop rule
    says drop it and say why. No inference involved."""
    hypotheses = spec.get("hypotheses") or []
    questions = spec.get("research_questions") or []
    label_words: dict[str, set[str]] = {}
    for index, hypothesis in enumerate(hypotheses, 1):
        if not isinstance(hypothesis, dict):
            continue
        label = str(hypothesis.get("label") or "H%d" % index)
        label_words[label] = set(_content_words(str(hypothesis.get("text") or ""))
                                 + _content_words(label))
    mapping: list[dict] = []
    unmapped: list[str] = []
    for index, question in enumerate(questions, 1):
        words = set(_content_words(str(question)))
        traces = [label for label, candidate in label_words.items()
                  if len(words & candidate) >= 2]
        mapping.append({"rq": "RQ%d" % index, "text": str(question), "traces_to": traces})
        if not traces:
            unmapped.append("RQ%d" % index)
    return {"map": mapping, "unmapped": unmapped,
            "drop_rule": "an RQ tracing to no hypothesis is dropped; say you dropped it and why"}


def collect(key: str, config: dict | None, environ=None) -> list[dict]:
    """The merged, deduped, time-sorted prompt list for one key."""
    key = normalize_key(key, config)
    prompts: list[dict] = []
    spec_path = None
    session_id = ""
    state_dir = None
    environ = os.environ if environ is None else environ
    override = str(environ.get("UXR_STATE_DIR") or "").strip()
    if isinstance(config, dict):
        paths = config.get("paths", {})
        if isinstance(paths, dict):
            state_dir = paths.get("state_dir")
    if override:
        state_dir = override
    if state_dir and isinstance(state_dir, str) and "${" not in state_dir:
        spec_path = Path(state_dir) / "specs" / ("%s.spec.json" % key)
        if spec_path.is_file():
            try:
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
                meta = spec.get("_meta") if isinstance(spec, dict) else None
                if isinstance(meta, dict):
                    spec_path = meta.get("transcript_path") or None
                    session_id = str(meta.get("session_id") or "")
            except (OSError, ValueError):
                spec_path = None
        else:
            spec_path = None
    if spec_path and Path(spec_path).is_file():
        prompts.extend(spec_prompts(spec_path, session_id))
    prompts.extend(manifest_prompts(research_roots(config, environ), key))
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict] = []
    for prompt in prompts:
        marker = (prompt["session_id"], prompt["ts"], prompt["text"])
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(prompt)
    unique.sort(key=lambda item: item["ts"])
    return unique


def main(argv: list[str] | None = None, environ=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "selftest" in args or "--selftest" in args:
        return _selftest()
    if "--rq-map" in args:
        index = args.index("--rq-map")
        if index + 1 >= len(args):
            print("usage: trace_prompts.py --rq-map <spec.json>", file=sys.stderr)
            return 2
        path = Path(args[index + 1]).expanduser()
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print("trace_prompts: unreadable spec: %s" % exc, file=sys.stderr)
            return 2
        print(json.dumps(rq_map(spec if isinstance(spec, dict) else {}), ensure_ascii=False, indent=2))
        return 0
    if len(args) != 1 or not args[0].strip() or args[0].startswith("-"):
        print("usage: trace_prompts.py <KEY> | --rq-map <spec.json>", file=sys.stderr)
        return 2
    config = _load_config()
    prompts = collect(args[0].strip(), config, environ=environ)
    print(json.dumps(prompts, ensure_ascii=False, indent=2))
    return 0


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
    raise SystemExit(main())
