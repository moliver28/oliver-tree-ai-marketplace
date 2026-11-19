#!/usr/bin/env python3
"""Evidence sweep planner and digester (W2). Commands own tracker I/O;
this script never touches the network. ``plan`` prints the per-source
query spec (tool, window, limit, query) from config; ``digest`` compresses
raw results into the evidence digest and renders the synthesis table, so
the signals call consumes the digest ONLY - never raw search JSON. Digest
input: ``{"<key>": {"hits": n, "titles": [...], "owners": [...]}}`` or
``"unavailable"`` per source. Exit: 0 ok, 2 usage/config, 3 selftest.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.config import ConfigError, load_config  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((PLUGIN_ROOT / "prompts" / "evidence" / "sources.json").read_text(encoding="utf-8"))
FIXTURES = (PLUGIN_ROOT if (PLUGIN_ROOT / "tests").is_dir() else PLUGIN_ROOT.parent) / "tests" / "fixtures" / "evidence"


def _dotted(config: dict, path: str, default):
    node = config
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def build_plan(config: dict, topic: str, tactical: bool, current_user: str = "",
               today: date | None = None) -> dict:
    """One query spec per source enabled in ``evidence.sources``. Per-source
    extras live in sources.json ``entry_extra``: a literal value, or
    ``{"config": <dotted path>, "default": ...}`` resolved against ``config``."""
    today = today or date.today()
    enabled = (config.get("evidence") or {}).get("sources") or []
    tracker = (config.get("tracker") or {})
    tool = DATA["search_tools"].get(tracker.get("kind", ""), "search(filter)")
    plan = {}
    for source in DATA["sources"]:
        key = source["key"]
        if key not in enabled:
            continue
        entry: dict = {"label": source["label"], "tool": tool}
        if source.get("skip_if") == "tactical" and tactical:
            entry["skip"] = "tactical study: the wiki source is skipped by rule"
        window = source.get("window_days")
        if window:
            entry["window_days"] = window
            entry["window_start"] = (today - timedelta(days=window)).isoformat()
        if source.get("limit"):
            entry["limit"] = source["limit"]
        template = DATA["jql"].get(key)
        if template:
            entry["query"] = template.format(
                project_key=tracker.get("project_key", ""),
                current_user=current_user or "<current user account id>",
                topic=topic, window_start=entry.get("window_start", ""))
        if source.get("adoption_gap"):
            entry["never_silently_skip"] = "churn, satisfaction, or adoption topics carry the gap clause"
        for field, spec in (DATA.get("entry_extra") or {}).get(key, {}).items():
            entry[field] = (_dotted(config, spec["config"], spec.get("default"))
                            if isinstance(spec, dict) and "config" in spec else spec)
        plan[key] = entry
    return plan


def digest(results: dict, topic: str, tactical: bool = False,
           topic_class: str = "", tracker_tool: str = "searchJiraIssuesUsingJql") -> dict:
    """Compress raw sweep results into the digest + the synthesis block.
    Unavailable lines dedupe by display name: both tracker sources share
    one tool line, and jtbd/personas/chat_discovery log their config keys."""
    sources = DATA["sources"]
    counts: dict[str, int] = {}
    compressed: dict[str, dict] = {}
    unavailable: list[dict] = []
    feedback_gap = False

    def mark(source: dict, note: str = "") -> None:
        display = tracker_tool if source.get("tracker") else source.get("unavailable_as", source["label"])
        if not any(item["label"] == display for item in unavailable):
            unavailable.append({"label": display, "gap": note})

    for source in sources:
        key = source["key"]
        entry = results.get(key)
        if entry is None or entry == "unavailable" or (
            isinstance(entry, dict) and entry.get("skip")
        ):
            mark(source, "gap" if source.get("adoption_gap") else "")
            if source.get("adoption_gap"):
                feedback_gap = True
            continue
        hits = int(entry.get("hits", 0)) if isinstance(entry, dict) else int(entry)
        counts[key] = hits
        titles = [str(t)[:80] for t in (entry.get("titles") or [])][:3] if isinstance(entry, dict) else []
        owners = [str(o) for o in (entry.get("owners") or [])][:5] if isinstance(entry, dict) else []
        compressed[key] = {"hits": hits, "titles": titles, "owners": owners}
    evidence_total = sum(counts.values())
    lines = ["## Evidence sweep", "", "| Source | Hits |", "|---|---|"]
    for source in sources:
        if source.get("table"):
            lines.append(f"| {source['label']} | {counts.get(source['key'], 0)} |")
    lines.append("")
    for item in unavailable:
        line = f"- {item['label']}: unavailable (skipped)"
        if item["gap"]:
            line += (f" \u2014 topic is {topic_class or 'adoption-adjacent'}; the study"
                     " carries a gap: no customer-side pain counts this run")
        lines.append(line)
    block = "\n".join(lines)
    return {
        "digest": {"sources": compressed,
                   "unavailable": [item["label"] for item in unavailable],
                   "feedback_gap": feedback_gap, "evidence_total": evidence_total,
                   "tactical": tactical},
        "synthesis_block": block + "\n\nTop signals\n",
        "metering": f"evidence@{DATA['version']} sources={len(counts)} unavailable={len(unavailable)} evidence_total={evidence_total}",
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("selftest", "--selftest"):
        return _selftest()

    def value_of(name: str) -> str:
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else ""

    tactical = "--tactical" in args
    topic = value_of("--topic")
    if args and args[0] == "plan":
        try:
            config = load_config()
        except ConfigError as exc:
            print(f"evidence_sweep: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(build_plan(config, topic, tactical,
                                    value_of("--current-user")), indent=2))
        return 0
    if args and args[0] == "digest":
        results_path = value_of("--results")
        if not results_path:
            print("evidence_sweep: digest needs --results <file>", file=sys.stderr)
            return 2
        try:
            results = json.loads(Path(results_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"evidence_sweep: unreadable results: {exc}", file=sys.stderr)
            return 2
        out = digest(results, topic, tactical, value_of("--topic-class"))
        print(json.dumps(out["digest"], indent=2))
        print()
        print(out["synthesis_block"])
        print(out["metering"], file=sys.stderr)
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


def _selftest() -> int:
    print("scripts/evidence_sweep.py selftest")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    config = {"tracker": {"kind": "jira", "project_key": "UXR"},
              "evidence": {"sources": ["tracker_recent", "tracker_topic", "drive", "feedback",
                                       "chat", "wiki", "jtbd", "personas", "chat_discovery"],
                           "chat_channels": ["#support-first-week"]},
              "ssot": {"jtbd_url": "", "personas_url": ""}}
    plan = build_plan(config, "timeline discoverability", tactical=False,
                      current_user="5f1a", today=date(2026, 11, 17))
    check("plan covers 9 sources", len(plan) == 9, str(sorted(plan)))
    check("plan tracker_recent window", plan["tracker_recent"]["window_days"] == 90)
    check("plan jql not-project", "NOT project = UXR" in plan["tracker_recent"]["query"])
    check("plan tool name", plan["tracker_recent"]["tool"] == "searchJiraIssuesUsingJql")
    plan_t = build_plan(config, "ship the export button", tactical=True)
    check("plan tactical wiki skip", plan_t["wiki"].get("skip") is not None)

    golden_path = FIXTURES / "digest-empty.json"
    if golden_path.is_file():
        case = json.loads(golden_path.read_text(encoding="utf-8"))
        out = digest(case["results"], case["topic"], False, case.get("topic_class", ""))
        block = out["synthesis_block"] + "\n- Owning group: Onboarding (from the ask alone; no evidence to cluster)\n- Hypotheses in flight: none surfaced (all sources unavailable)\n- Pain strength: low\n- Stakeholders:\n"
        expected_head = "\n".join(case["expect_block_head"])
        check("digest empty-sweep table", out["synthesis_block"].startswith(expected_head),
              out["synthesis_block"][:200])
        check("digest feedback gap line", "the study carries a gap" in out["synthesis_block"])
        check("digest feedback_gap flag", out["digest"]["feedback_gap"] is True)
        check("digest evidence_total", out["digest"]["evidence_total"] == 0)
        populated = digest({"tracker_recent": {"hits": 6, "titles": ["t"]}, "feedback": {"hits": 41}},
                           "topic", False)
        check("digest populated counts", populated["digest"]["evidence_total"] == 47)
    else:
        check("digest fixture", False, "tests/fixtures/evidence/digest-empty.json missing")
    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 3
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
