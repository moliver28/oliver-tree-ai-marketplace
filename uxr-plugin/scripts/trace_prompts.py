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

from lib.util import load_config as _load_config, research_roots  # noqa: E402  (shared plumbing)

SESSIONS_DIR = ".sessions"


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
        # read_text one-shot form: the scanner-mandated shape for file reads
        # (no long-lived file handle on a spec-sourced path).
        for line in Path(spec_path).read_text(encoding="utf-8", errors="replace").splitlines():
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
    roots = research_roots(config, environ)
    if spec_path and Path(spec_path).is_file():
        prompts.extend(spec_prompts(spec_path, session_id))
    prompts.extend(manifest_prompts(roots, key))
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
    if "--rq-map" in args:
        index = args.index("--rq-map")
        if index + 1 >= len(args):
            print("usage: trace_prompts.py --rq-map <spec.json>", file=sys.stderr)
            return 2
        path = Path(args[index + 1]).expanduser().resolve()
        if not path.is_file():
            print("trace_prompts: spec not found: %s" % args[index + 1], file=sys.stderr)
            return 2
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


if __name__ == "__main__":
    raise SystemExit(main())
