#!/usr/bin/env python3
"""Contract tests for the coverage-contract drift check (issue #162).

Run: python3 tests/humanizer/test_coverage_contract.py
Exit 0 = every contract gate green.

Sections:
A. Real-file green: the shipped humanizer/COVERAGE.md passes the full
   drift check against the shipped compiled state (voice_tells register,
   battery core gate markers), and every evidence pointer in the file
   resolves to an existing file:line.
B. Mutation determinism: on a temp-root copy of the real file, removing
   a catalog row, removing a register-family row, flipping a mirrored
   status, editing a count, breaking a pointer, renaming a family,
   removing an STE row, and removing a battery row each fail the check
   with the expected message, and the failure list is byte-identical
   across repeated runs (deterministic, never flaky).
C. Missing file: a root without the contract file fails with the defined
   message.
D. Stdlib-only import pin for the checker module (ast-scanned), plus the
   unit-law pins: the checker reuses the shipped _family() classifier
   output, never its own grouping.

Every mutation operates on temp copies; the real repo file is never
modified.
"""
import ast
import importlib.util
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent      # tests/humanizer/
REPO_ROOT = HERE.parent.parent                     # the repository root
PLUGIN_DIR = REPO_ROOT / "humanizer"               # humanizer/
COVERAGE = PLUGIN_DIR / "COVERAGE.md"
CHECKER = HERE / "coverage_contract_check.py"

fails = []


def ck(cond, name, detail=""):
    if cond:
        print(f"OK   {name}")
    else:
        print(f"FAIL {name}" + (f" ({detail})" if detail else ""))
        fails.append(name)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cc = load_module("coverage_contract_check_test", CHECKER)
vt = cc.load_voice_tells(REPO_ROOT)
battery_core = cc.load_battery_core(REPO_ROOT)

# --- A. the real file is green against the shipped compiled state ------------
real_fails = cc.check_coverage_contract(REPO_ROOT, vt=vt, battery_core=battery_core)
ck(not real_fails, "real COVERAGE.md passes the full drift check",
   "; ".join(real_fails[:3]))

text = COVERAGE.read_text(encoding="utf-8")
pointers = cc.POINTER_RE.findall(text)
resolved = 0
for path, start, end in pointers:
    p = REPO_ROOT / path
    if p.is_file() and int(start) >= 1 and (int(end) if end else int(start)) <= len(p.read_text(encoding="utf-8").splitlines()):
        resolved += 1
ck(resolved == len(pointers) and len(pointers) >= 40,
   f"every evidence pointer resolves to shipped code ({resolved}/{len(pointers)})")

# --- B. mutation determinism on a temp-root copy -----------------------------
fams = cc.compiled_families(vt)
ck(len(fams) == 31 and sum(fams.values()) == len(vt.PATTERNS),
   f"the checker groups the register with the shipped _family() classifier "
   f"({len(fams)} families, {sum(fams.values())} patterns)")


def _expected_messages(tag, needles, failures):
    joined = "\n".join(failures)
    return all(needle in joined for needle in needles), joined


def _mutation(tag, old, new, needles, line_anchored=True):
    """Apply one whole-line mutation to the temp copy and prove the check
    fails with the expected messages, deterministically across runs."""
    lines = fixture_text.splitlines()
    hits = [i for i, l in enumerate(lines) if (l.strip() == old.strip() if line_anchored else old in l)]
    if not hits:
        ck(False, f"mutation {tag}: anchor line not found in the fixture copy", old[:70])
        return
    mutated = list(lines)
    if new is None:
        del mutated[hits[0]]
    else:
        mutated[hits[0]] = mutated[hits[0]].replace(old.strip(), new.strip())
    mutated_text = "\n".join(mutated) + "\n"
    if mutated_text == fixture_text:
        ck(False, f"mutation {tag}: the edit changed nothing", old[:70])
        return
    (fixture_root / "humanizer" / "COVERAGE.md").write_text(mutated_text, encoding="utf-8")
    f1 = cc.check_coverage_contract(fixture_root, vt=vt, battery_core=battery_core)
    f2 = cc.check_coverage_contract(fixture_root, vt=vt, battery_core=battery_core)
    deterministic = f1 == f2
    ck(bool(f1) and deterministic,
       f"mutation {tag}: the check fails deterministically ({len(f1)} failures)",
       "empty or nondeterministic" if not (f1 and deterministic) else "")
    hit, joined = _expected_messages(tag, needles, f1)
    ck(hit, f"mutation {tag}: the failure names the broken law",
       joined.splitlines()[0][:110] if joined and not hit else "")


with tempfile.TemporaryDirectory() as td:
    fixture_root = pathlib.Path(td)
    (fixture_root / "humanizer" / "hooks").mkdir(parents=True)
    (fixture_root / "humanizer" / "learn").mkdir(parents=True)
    shutil.copyfile(PLUGIN_DIR / "hooks" / "voice_tells.py",
                    fixture_root / "humanizer" / "hooks" / "voice_tells.py")
    shutil.copyfile(PLUGIN_DIR / "hooks" / "gate.py",
                    fixture_root / "humanizer" / "hooks" / "gate.py")
    shutil.copyfile(PLUGIN_DIR / "SKILL.md",
                    fixture_root / "humanizer" / "SKILL.md")
    shutil.copyfile(PLUGIN_DIR / "learn" / "voice_battery_core.py",
                    fixture_root / "humanizer" / "learn" / "voice_battery_core.py")
    shutil.copyfile(COVERAGE, fixture_root / "humanizer" / "COVERAGE.md")
    fixture_text = (fixture_root / "humanizer" / "COVERAGE.md").read_text(encoding="utf-8")
    base = cc.check_coverage_contract(fixture_root, vt=vt, battery_core=battery_core)
    ck(not base, "the unmutated temp copy passes (mutations alone cause the failures)",
       "; ".join(base[:3]))

    _mutation(
        "row-removal",
        "| 17. Title case in headings | humanizer 17 | implemented "
        "| humanizer/hooks/voice_tells.py:204 |",
        None,
        ["coverage rows do not cover catalog pattern 17",
         "compiled register family 'humanizer 17' has no implemented catalog row"])

    _mutation(
        "family-removal",
        "| banned | implemented | humanizer/hooks/voice_tells.py:140-157 |",
        None,
        ["compiled register family missing from the contract: 'banned'"])

    _mutation(
        "status-flip",
        "| 22. Sycophantic or servile tone | humanizer 22 | implemented | "
        "humanizer/hooks/voice_tells.py:170-174 |",
        "| 22. Sycophantic or servile tone | humanizer 22 | contextual-only "
        "| humanizer/hooks/voice_tells.py:170-174 |",
        ["compiled register family 'humanizer 22' has no implemented catalog row"])

    _mutation(
        "count-drift",
        "- Compiled register patterns: 98 (ninety-eight)",
        "- Compiled register patterns: 97 (ninety-seven)",
        ["coverage contract count drift: Compiled register patterns says 97, "
         "compiled state is 98"])

    _mutation(
        "pointer-break",
        "| 17. Title case in headings | humanizer 17 | implemented "
        "| humanizer/hooks/voice_tells.py:204 |",
        "| 17. Title case in headings | humanizer 17 | implemented "
        "| humanizer/hooks/voice_tells.py:9999 |",
        ["evidence pointer out of range: humanizer/hooks/voice_tells.py:9999"])

    _mutation(
        "stale-family-name",
        "| chatbot | implemented | humanizer/hooks/voice_tells.py:164-166 |",
        "| chatbot residue | implemented | humanizer/hooks/voice_tells.py:164-166 |",
        ["register-families row is not a compiled family: 'chatbot residue'",
         "compiled register family missing from the contract: 'chatbot'"])

    _mutation(
        "ste-row-removal",
        "| S3. Passive voice | ASD-STE100 | implemented "
        "| humanizer/hooks/gate.py:84; humanizer/hooks/gate.py:130-137 |",
        None,
        ["STE table must carry exactly ('S1', 'S2', 'S3', 'S4', 'S5', 'S6')"])

    _mutation(
        "battery-row-removal",
        "| L10-18. Chunk-pair divergence (the family-11 signal) | contextual-only "
        "| humanizer/hooks/voice_tells.py:905-936; humanizer/hooks/gate.py:280-287 |",
        None,
        ["battery table must carry exactly ('L10-1', 'L10-18', 'L10-19', 'L10-20')"])

# --- C. missing file ----------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    empty_root = pathlib.Path(td)
    (empty_root / "humanizer" / "hooks").mkdir(parents=True)
    shutil.copyfile(PLUGIN_DIR / "hooks" / "voice_tells.py",
                    empty_root / "humanizer" / "hooks" / "voice_tells.py")
    missing = cc.check_coverage_contract(empty_root, battery_core=battery_core)
    ck(missing == ["coverage contract file missing: humanizer/COVERAGE.md"],
       "a root without the contract file fails with the defined message",
       str(missing[:1]))

# --- D. stdlib-only checker imports + reuse of the shipped classifier ---------
tree = ast.parse(CHECKER.read_text(encoding="utf-8"))
mods = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        mods.update(a.name.split(".")[0] for a in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        mods.add(node.module.split(".")[0])
stdlib_roots = set(sys.stdlib_module_names)
ck(mods <= stdlib_roots,
   f"coverage_contract_check.py imports stdlib modules only ({sorted(mods)})",
   str(sorted(mods - stdlib_roots)))

grouped = cc.compiled_families(vt)
sample_label = vt.PATTERNS[-1][1]
ck(grouped.get(vt._family(sample_label + " (near: x)"), 0) >= 1
   and vt._family(sample_label + " (near: x)") in grouped,
   "the checker's family grouping rides the shipped _family() output verbatim")

print(f"\ncoverage contract: {len(fails)} failure(s)")
sys.exit(1 if fails else 0)
