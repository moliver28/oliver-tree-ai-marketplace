"""Checklist content self-test: the shipped 66-item set parses and carries the
confirmed ids, tags, optional markers, and registry references (issue 53).

Offline, zero LLM, zero dispatches. The bar: the shipped loader finds
exactly 5 / 29 / 32 items with the exact id sets; the tag counts are
exactly 42 ``[llm]`` / 15 ``[draft]`` / 9 ``[human]`` (the A4.2 tweak
applied); the optional markers are exactly {A1.6, A1.10, A5.3, A6.4,
A7.1, B5.6, B6.4}; every writing-rules registry id named by an item
resolves in ``references/writing-rules.md``; and the MO-banned artifact
word appears nowhere in the three checklist files, the registry, or the
survey skill. Not enrolled in the parity SELFTESTS; rides the smoke
selftest glob.

Run: ``python tests/uxr_selftests/checklist_content.py``. Exit 0 on pass,
1 on fail.
"""
from _harness import bind

bind("lib.checklist_gate", globals())

import re  # selftest-only import

CHECKLISTS = PLUGIN_ROOT / "references" / "checklists"

WANT_COUNTS = {"method-selection.md": 5, "qual-interviews.md": 29,
               "quant-surveys.md": 32}

WANT_IDS = {
    "method-selection.md": [f"A0.{i}" for i in range(1, 6)],
    "qual-interviews.md": (
        [f"A1.{i}" for i in range(1, 11)]
        + [f"A2.{i}" for i in range(1, 4)]
        + ["A6.1", "A6.2", "A6.3", "A6.4"]
        + ["A7.1"]
        + [f"A3.{i}" for i in range(1, 4)]
        + ["A4.0", "A4.1", "A4.2", "A4.3"]
        + [f"A5.{i}" for i in range(1, 5)]
    ),
    "quant-surveys.md": (
        [f"B1.{i}" for i in range(1, 5)]
        + [f"B2.{i}" for i in range(1, 3)]
        + [f"B3.{i}" for i in range(1, 13)]
        + [f"B6.{i}" for i in range(1, 5)]
        + ["B7.1"]
        + ["B4.1", "B4.2"]
        + [f"B5.{i}" for i in range(1, 8)]
    ),
}

WANT_TAGS = {"llm": 42, "draft": 15, "human": 9}
WANT_OPTIONAL = {"A1.6", "A1.10", "A5.3", "A6.4", "A7.1", "B5.6", "B6.4"}
RULE_ID_RE = re.compile(r"\b([RX]-[UISHA]\d)\b")
RULE_LINE_RE = re.compile(r"^- ([RX]-[UISHA]\d): ", re.MULTILINE)
PIPELINE_RE = re.compile(r"^Pipeline: (.+)$")
WANT_PIPELINES = {
    "method-selection.md": "A0",
    "qual-interviews.md": "A1 \u2192 A2 \u2192 A6 \u2192 A7 \u2192 A3 \u2192 A4 \u2192 A5",
    "quant-surveys.md": "B1 \u2192 B2 \u2192 B3 \u2192 B6 \u2192 B7 \u2192 B4 \u2192 B5",
}

#: The MO-banned artifact word (the terminology law): the plugin says
#: script and survey; the banned word never appears in new content.
BANNED_WORD = "guide"
BANNED_FILES = [
    CHECKLISTS / "method-selection.md",
    CHECKLISTS / "qual-interviews.md",
    CHECKLISTS / "quant-surveys.md",
    PLUGIN_ROOT / "references" / "writing-rules.md",
    PLUGIN_ROOT / "skills" / "survey-script" / "SKILL.md",
]


def _selftest() -> int:
    failures: list[str] = []

    def check(name, condition, detail=""):
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("checklist_content self-test")

    all_items: dict[str, list] = {}
    for name, want in WANT_COUNTS.items():
        path = CHECKLISTS / name
        check(f"{name} ships", path.is_file())
        items = load_items(path)
        all_items[name] = items
        ids = [item["id"] for item in items]
        check(f"{name}: the loader parses exactly {want} items",
              len(items) == want, f"found {len(items)}")
        check(f"{name}: the id set is exact and in pipeline order",
              ids == WANT_IDS[name],
              f"got {ids[:6]}... vs want {WANT_IDS[name][:6]}...")
        check(f"{name}: ids are unique", len(set(ids)) == len(ids), "duplicate id")
        # three-layer format: ## heading, one Pipeline line, ### groups with Executor
        lines = path.read_text(encoding="utf-8").splitlines()
        check(f"{name}: opens with the ## Checklist heading",
              bool(lines) and lines[0].startswith("## Checklist"), lines[0][:40])
        pipelines = [PIPELINE_RE.match(ln).group(1).strip()
                     for ln in lines if PIPELINE_RE.match(ln)]
        check(f"{name}: exactly one Pipeline line with the confirmed order",
              pipelines == [WANT_PIPELINES[name]], repr(pipelines))
        groups = [ln[4:].strip() for ln in lines if ln.startswith("### ")]
        executors = sum(1 for ln in lines if ln.startswith("Executor:"))
        check(f"{name}: every group carries an Executor default",
              len(groups) > 0 and executors == len(groups),
              f"{len(groups)} groups, {executors} Executor lines")
        pipeline_groups = [part.strip() for part in pipelines[0].split("\u2192")] \
            if pipelines else []
        head_groups = [g.split(" ")[0] for g in groups]
        if pipelines[0] != "A0":
            check(f"{name}: the Pipeline ids match the ### groups in order",
                  pipeline_groups == head_groups,
                  f"{pipeline_groups} vs {head_groups}")

    # --- tags: exactly 42 [llm] / 15 [draft] / 9 [human]; one tag per item ----
    tags = {"llm": 0, "draft": 0, "human": 0}
    tagless = []
    for name, items in all_items.items():
        for item in items:
            match = re.match(r"^\[(llm|draft|human)\] ", item["item"])
            if match:
                tags[match.group(1)] += 1
            else:
                tagless.append(item["id"])
    check("the tag counts are exactly 42 llm / 15 draft / 9 human (A4.2 draft)",
          tags == WANT_TAGS, repr(tags))
    check("every item carries one executor tag", not tagless, repr(tagless[:6]))

    # --- optional markers: the exact confirmed set -----------------------------
    optional = set()
    for name, items in all_items.items():
        raw = (CHECKLISTS / name).read_text(encoding="utf-8")
        for item in items:
            line = next((ln for ln in raw.splitlines() if f"- [ ] {item['id']} " in ln), "")
            if ") (optional" in line:
                optional.add(item["id"])
    check("the optional markers are exactly the confirmed set",
          optional == WANT_OPTIONAL, repr(sorted(optional)))

    # --- registry ids named by items resolve in writing-rules.md ----------------
    registry = PLUGIN_ROOT / "references" / "writing-rules.md"
    check("writing-rules.md ships", registry.is_file())
    registry_ids = set(RULE_LINE_RE.findall(registry.read_text(encoding="utf-8")))
    named = set()
    for items in all_items.values():
        for item in items:
            named.update(RULE_ID_RE.findall(item["item"]))
            named.update(RULE_ID_RE.findall(item["source"]))
    unresolved = sorted(named - registry_ids)
    check("every registry id an item names resolves in writing-rules.md",
          bool(named) and not unresolved,
          f"{len(named)} named, unresolved {unresolved}")
    check("the registry seeds 26 rules across the five families",
          len(registry_ids) == 26, f"{len(registry_ids)} rules")

    # --- the MO-banned artifact word never appears in new content --------------
    offenders = []
    for path in BANNED_FILES:
        if not path.is_file():
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            if re.search(r"\b" + BANNED_WORD + r"\b", line, re.IGNORECASE):
                offenders.append(f"{path.name}:{number}")
    check("the banned artifact word has zero hits in new content",
          not offenders, repr(offenders[:6]))

    # --- the A1.4 append-only ruling is present --------------------------------
    qual_raw = (CHECKLISTS / "qual-interviews.md").read_text(encoding="utf-8")
    a14 = next((ln for ln in qual_raw.splitlines() if ln.startswith("- [ ] A1.4 ")), "")
    check("A1.4 keeps the confirmed words and carries the appended Source clause",
          "No source needed (plugin law). (Source: plugin law.)" in a14,
          a14[-80:])

    if failures:
        print(f"checklist_content FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 1
    print("checklist_content: all checks green")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
