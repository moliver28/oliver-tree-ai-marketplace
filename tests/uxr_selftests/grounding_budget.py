"""Grounding budget self-test: the byte budgets that quantify design decision 7 (build item 13).

Offline, zero LLM, zero dispatches. Asserts the shipped files against the
ruled values (MO gate 2026-11-22: row cap 120, central file 16,000 bytes)
and the per-surface budgets from the Grounding-adherence acceptance-test
section: pointer line 256, law line 256, workspace CLAUDE.md paragraph
1,000, hook text 256, condition-index row 120, entry file 3,000, leaf
line 200, combined worst case 1,768 bytes per workspace turn. Also
asserts the LOC law for the content wave: ``references/sources/`` holds
only markdown entry files (zero payload LOC), and the eval scaffolding
lives under ``tests/`` with a runner that imports the hcd-researcher
runner (no copy).

Run: ``python tests/uxr_selftests/grounding_budget.py`` (bare module; the
smoke gate discovers it by the repo-level selftest convention). Exit 0 on
pass, 1 on fail.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "uxr-plugin"

POINTER_MAX = 256
LAW_LINE_MAX = 256
CLAUDE_MAX = 1000
HOOK_MAX = 256
ROW_MAX_BYTES = 120
ROW_CAP = 120
CENTRAL_MAX = 16000
ENTRY_MAX = 3000
LEAF_MAX = 200
COMBINED_MAX = 1768


def _grounding_lines(path: Path) -> list[str]:
    try:
        return [ln for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.startswith("Grounding:")]
    except OSError:
        return []


def _selftest() -> int:
    failures: list[str] = []

    def check(name, condition, detail=""):
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("grounding_budget self-test")

    # --- pointers: every skill and command surface carries one line, <=256 bytes
    surfaces: list[tuple[str, str]] = []
    cmds = PLUGIN_ROOT / "commands"
    if cmds.is_dir():
        for path in sorted(cmds.glob("*.md")):
            lines = _grounding_lines(path)
            check(f"pointer present: commands/{path.name}", len(lines) == 1,
                  f"{len(lines)} Grounding lines")
            for ln in lines:
                surfaces.append((f"commands/{path.name}", ln))
    skills = PLUGIN_ROOT / "skills"
    if skills.is_dir():
        for path in sorted(skills.glob("*/SKILL.md")):
            lines = _grounding_lines(path)
            check(f"pointer present: {path.relative_to(PLUGIN_ROOT).as_posix()}",
                  len(lines) == 1, f"{len(lines)} Grounding lines")
            for ln in lines:
                surfaces.append((path.relative_to(PLUGIN_ROOT).as_posix(), ln))
    max_pointer = max((len(ln.encode("utf-8")) for _, ln in surfaces), default=0)
    check("pointer line <= 256 bytes", max_pointer <= POINTER_MAX, f"max {max_pointer}")

    # --- hook text: the web-tool nudge line, <=256 bytes, and its behavior
    hook_path = PLUGIN_ROOT / "hooks" / "web_nudge.py"
    hook_ok = hook_path.is_file()
    check("web_nudge hook ships", hook_ok)
    nudge = ""
    if hook_ok:
        sys.path.insert(0, str(hook_path.parent))
        import web_nudge  # noqa: E402  (selftest-only import)
        nudge = web_nudge.NUDGE_LINE
        check("hook text <= 256 bytes", len(nudge.encode("utf-8")) <= HOOK_MAX,
              f"{len(nudge.encode('utf-8'))} bytes")
        with tempfile.TemporaryDirectory() as tmp:
            open_ws = Path(tmp) / "ws"
            open_ws.mkdir()
            (open_ws / "00-overview.md").write_text("x", encoding="utf-8")
            open_event = {"hook_event_name": "PreToolUse", "tool_name": "WebSearch",
                          "cwd": str(open_ws)}
            out = web_nudge.handle_event(open_event)
            check("hook fires inside a uxr workspace", "additionalContext" in out, out[:60])
            closed = web_nudge.handle_event({"hook_event_name": "PreToolUse",
                                             "tool_name": "WebSearch", "cwd": tmp})
            check("hook silent outside a uxr workspace", closed == "", closed[:60])
            other = web_nudge.handle_event({"hook_event_name": "PreToolUse",
                                            "tool_name": "Bash", "cwd": str(open_ws)})
            check("hook silent on non-web tools", other == "", other[:60])
            broken = web_nudge.handle_event(None)
            check("hook silent on a broken event", broken == "", broken[:60])
        # the catch-every-exception, exit-0 contract: garbage stdin never fails
        proc = subprocess.run([sys.executable, str(hook_path)], input="{not json",
                              capture_output=True, text=True, timeout=30)
        check("hook exits 0 on garbage stdin", proc.returncode == 0,
              f"exit {proc.returncode}")

    # --- the law one-line form rides the pointer lines (<=256 covered above);
    #     the CLAUDE.md law paragraph is <=1000 bytes
    claude_path = PLUGIN_ROOT / "templates" / "workspace" / "CLAUDE.md"
    claude_text = claude_path.read_text(encoding="utf-8") if claude_path.is_file() else ""
    match = re.search(r"Grounding law: .*?(?=\n\n|\Z)", claude_text, re.DOTALL)
    law_bytes = len(match.group(0).encode("utf-8")) if match else -1
    check("CLAUDE.md law paragraph present", law_bytes > 0, "no Grounding law paragraph")
    check("CLAUDE.md law paragraph <= 1000 bytes", 0 < law_bytes <= CLAUDE_MAX,
          f"{law_bytes} bytes")
    check("CLAUDE.md law names the index and the store",
          "references/research-sources.md" in claude_text
          and "references/sources/" in claude_text)

    # --- combined worst case per turn (review F4), measured, <=1768 bytes
    combined = (min(law_bytes if law_bytes > 0 else CLAUDE_MAX, CLAUDE_MAX)
                + max_pointer + len(nudge.encode("utf-8")))
    check("combined worst case <= 1768 bytes", combined <= COMBINED_MAX,
          f"{combined} bytes (law {law_bytes} + pointer {max_pointer} + hook "
          f"{len(nudge.encode('utf-8'))})")

    # --- the central file: law + condition index only, ruled values
    central = PLUGIN_ROOT / "references" / "research-sources.md"
    check("central file ships", central.is_file())
    cb = central.read_bytes() if central.is_file() else b""
    check(f"central file <= {CENTRAL_MAX} bytes", 0 < len(cb) <= CENTRAL_MAX,
          f"{len(cb)} bytes")
    ct = cb.decode("utf-8")
    rows = [ln for ln in ct.splitlines() if re.match(r"^- R-\d+ \|", ln)]
    check(f"index rows <= {ROW_CAP}", 0 < len(rows) <= ROW_CAP, f"{len(rows)} rows")
    row_over = [ln for ln in rows if len(ln.encode("utf-8")) > ROW_MAX_BYTES]
    check(f"index rows <= {ROW_MAX_BYTES} bytes", not row_over,
          f"{len(row_over)} over")
    ids = sorted(int(m.group(1)) for m in
                 (re.match(r"^- R-(\d+) \|", ln) for ln in rows) if m)
    check("everyday ids contiguous, no gaps", ids == list(range(1, len(ids) + 1)),
          f"{len(ids)} rows")
    check("no appendix rows in the central file",
          not re.search(r"^- A-\d+ \|", ct, re.MULTILINE))
    check("no markdown tables in the central file", "|---" not in ct)
    check("no YAML frontmatter in the central file", not ct.startswith("---"))

    # --- the store: one file per entry, byte budgets, markdown only (LOC law)
    sources = PLUGIN_ROOT / "references" / "sources"
    check("sources/ directory ships", sources.is_dir())
    files = sorted(sources.glob("*")) if sources.is_dir() else []
    md_files = [p for p in files if p.is_file()]
    check("sources/ holds only markdown (content wave, zero payload LOC)",
          all(p.suffix == ".md" for p in md_files) and len(md_files) == len(files),
          f"{len(files)} entries")
    r_files = sorted(p.stem for p in md_files if p.stem.startswith("R-"))
    a_files = sorted(p.stem for p in md_files if p.stem.startswith("A-"))
    r_nums = sorted(int(s[2:]) for s in r_files)
    a_nums = sorted(int(s[2:]) for s in a_files)
    check(f"R-01..R-{r_nums[-1] if r_nums else 0} contiguous, everyday set complete",
          r_nums == list(range(1, 110)), f"{len(r_nums)} R files")
    check("A-01..A-52 contiguous, appendix set complete",
          a_nums == list(range(1, 53)), f"{len(a_nums)} A files")
    over_files = [(p.name, p.stat().st_size) for p in md_files
                  if p.stat().st_size > ENTRY_MAX]
    check(f"entry files <= {ENTRY_MAX} bytes", not over_files, f"{over_files[:3]}")
    leaf_over = []
    header_bad = []
    for p in md_files:
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if not re.match(r"^[RA]-\d+ \| .+ \| .+ \| WHEN: ", lines[0]):
            header_bad.append(p.name)
        for ln in lines:
            if ln.startswith("- ") and len(ln.encode("utf-8")) > LEAF_MAX:
                leaf_over.append((p.name, len(ln.encode("utf-8"))))
    check("entry header shape (id | name | tier | WHEN:)", not header_bad,
          f"{header_bad[:3]}")
    check(f"leaf lines <= {LEAF_MAX} bytes", not leaf_over, f"{leaf_over[:3]}")

    # --- pointer coverage: every id named in a pointer line exists in the store
    store_ids = {p.stem for p in md_files}
    orphans = []
    for surface, ln in surfaces:
        for m in re.finditer(r"\b([RA]-\d{1,3})\b", ln):
            if m.group(1) not in store_ids:
                orphans.append((surface, m.group(1)))
    check("pointer-coverage: no orphan ids", not orphans, f"{orphans[:5]}")
    for surface, ln in surfaces:
        name = surface.split("/")[-1]
        if name in ("uxr-report.md", "uxr-deck.md"):
            ids_in_line = set(re.findall(r"\b([RA]-\d{1,3})\b", ln))
            check(f"F6: {name} names R-20 and R-21",
                  {"R-20", "R-21"} <= ids_in_line, str(sorted(ids_in_line)))

    # --- the acceptance scaffolding lives under tests/ and imports the base
    evals_dir = REPO_ROOT / "tests" / "evals" / "grounding"
    check("evals.json ships under tests/evals/grounding/",
          (evals_dir / "evals.json").is_file())
    runner = evals_dir / "run_evals.py"
    check("grounding runner ships", runner.is_file())
    if runner.is_file():
        runner_text = runner.read_text(encoding="utf-8")
        check("runner imports the hcd-researcher runner (no copy)",
              "hcd-researcher" in runner_text and "importlib" in runner_text)
    check("this selftest lives under tests/ (LOC law)",
          Path(__file__).resolve().is_relative_to(REPO_ROOT / "tests"))

    if failures:
        print(f"grounding_budget FAILED ({len(failures)} check(s))")
        for item in failures:
            print(f"  [FAIL] {item}")
        return 1
    print("grounding_budget: all checks green")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
