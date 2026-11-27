#!/usr/bin/env python3
"""Contract tests for learn/voice_setup.py (the install experience, v1.3.0).

Run: python3 tests/humanizer/test_voice_setup.py
Exit 0 = every contract gate green.

The contract this file pins:

1. Level picker goldens: fake machine-bench numbers in, a documented level
   out. The picker never exceeds the user's budget; level 0 is always
   allowed; a forced level that measures over budget is reported, not
   silently dropped.
2. Per-situation bands: 3 documents in one situation pin the pooled band
   values (mean and sample deviation of named measures).
3. Two-layer factor: pooled base in, situation factor out; the shrinkage
   k / (k + 5) pins at k = 3 and k = 10.
4. CLI: --remeasure re-runs the bench; --level N accepts 0 to 3 and exits 2
   outside; --budget accepts the four choices and exits 2 outside; the
   state files (machine-bench.json, setup.json, voice-bands.json) land in
   the user-local learned/state directory and nowhere in the repo.
"""
import importlib.util
import json
import math
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent      # tests/humanizer/
REPO_ROOT = HERE.parent.parent                     # the repository root
PLUGIN_DIR = REPO_ROOT / "humanizer"               # humanizer/

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


vs = load_module("voice_setup_contract", PLUGIN_DIR / "learn" / "voice_setup.py")

# 1. Level picker goldens -------------------------------------------------------
FAST = {"interpreter_spawn_ms": 20.0, "gate_command_ms_2000w": 70.0, "battery_ms_2000w": 5.0,
        "axes_apply_ms": 0.1, "level3_piece_ms": 10.0}
MID = {"interpreter_spawn_ms": 20.0, "gate_command_ms_2000w": 70.0, "battery_ms_2000w": 150.0,
       "axes_apply_ms": 5.0, "level3_piece_ms": 200.0}
SLOW = {"interpreter_spawn_ms": 20.0, "gate_command_ms_2000w": 70.0, "battery_ms_2000w": 400.0,
        "axes_apply_ms": 5.0, "level3_piece_ms": 700.0, "battery_ms_500w": 100.0,
        "battery_ms_5000w": 1000.0, "gate_fast_core_ms_2000w": 1.0,
        "python": "3.11.15", "measured_at": "2026-01-01", "format_version": "1.0"}
VERY_SLOW = {"interpreter_spawn_ms": 20.0, "gate_command_ms_2000w": 70.0, "battery_ms_2000w": 1200.0,
             "axes_apply_ms": 10.0, "level3_piece_ms": 300.0}
lv, costs = vs.pick_level(FAST, 1000)
ck(lv == 3 and abs(costs[3] - 15.1) < 1.0e-6,
   "picker: a fast machine at a 1,000 ms budget picks level 3 (cost 15.1 ms)",
   "%s %s" % (lv, costs))
lv1, _ = vs.pick_level(FAST, 100)
ck(lv1 == 3, "picker: a 15 ms report fits a 100 ms budget at level 3", str(lv1))
lv2, costs_mid = vs.pick_level(MID, 300)
ck(lv2 == 2 and abs(costs_mid[2] - 155.0) < 1.0e-6,
   "picker: a 150 ms battery fits a 300 ms budget at level 2 (155 ms)", str(lv2))
lv2b, costs_mid = vs.pick_level(MID, 1000)
ck(lv2b == 3 and abs(costs_mid[3] - 355.0) < 1.0e-6,
   "picker: the middle machine reaches level 3 at a 1,000 ms budget", str(lv2b))
lv3, costs3 = vs.pick_level(SLOW, 1000)
ck(lv3 == 2 and costs3[2] <= 1000 and costs3[3] > 1000,
   "picker: a slow level-3 piece drops level 3 and keeps level 2 inside the budget",
   "%s %s" % (lv3, costs3))
lv4, _ = vs.pick_level(VERY_SLOW, 1000)
ck(lv4 == 0, "picker: a 1,200 ms battery keeps only level 0")
ck(vs.pick_level(SLOW, 300)[0] == 0 and vs.pick_level(SLOW, 500)[0] == 2,
   "picker: budget 300 keeps level 0 (400 ms does not fit) and budget 500 keeps level 2 (405 ms fits)")
ck(set(vs.LEVEL_BUDGETS) == {100, 300, 500, 1000},
   "picker: the four budget choices are 100 / 300 / 500 / 1000 ms")

# 2. Per-situation bands + 3. two-layer factor ----------------------------------
ck(abs(vs.situation_factor(10.0, 8.0, 3) - 2.0 * 3.0 / 8.0) < 1.0e-12,
   "factor: the shrinkage pins at k = 3 (factor = delta * 3/8 = 0.75 for delta 2)")
ck(abs(vs.situation_factor(10.0, 8.0, 10) - 2.0 * 10.0 / 15.0) < 1.0e-12,
   "factor: the shrinkage pins at k = 10 (factor = delta * 2/3)")
ck(vs.situation_factor(10.0, 8.0, 0) == 0.0,
   "factor: a situation without documents contributes no factor")
ck(len(vs.FACTOR_ROWS) == 7 and vs.FACTOR_ROWS[:5] == ("L9-4", "L9-5", "L9-11", "L9-12", "L9-16")
   and vs.FACTOR_ROWS[5:] == ("L7-1", "L7-2"),
   "factor: the factor rows are the five shipped tone rows then the two register rows")

with tempfile.TemporaryDirectory() as td:
    tdp = pathlib.Path(td)
    env = {**os.environ, "VOICE_LEARNED_DIR": str(tdp / "learned")}
    samples = tdp / "samples"
    for i, sit in enumerate(("blog", "linkedin", "report")):
        for d in range(1 if sit == "report" else 3):
            p = samples / sit / ("doc%d.md" % d)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(vs.fixture(520, seed=7000 + i * 100 + d), encoding="utf-8")
    bands, notes = vs.learn_bands(samples)
    ck(bands is not None and bands["docs"] == 7,
       "bands: the tree learns 7 documents over the three situations", str(bands and bands["docs"]))
    ck(set(bands["situations"]) == {"blog", "linkedin", "report"},
       "bands: the three situation directories are learned", str(sorted(bands["situations"])))
    pooled = bands["pooled"]
    ck("L4-1" in pooled and pooled["L4-1"]["k"] == 7,
       "bands: the pooled band carries mean, sd, min, max, and k per measure")
    ck(bands["situations"]["report"].get("fallback") == "pooled band applies (fewer than 3 documents)",
       "bands: a one-document situation records the pooled fallback")
    ck(bands["situations"]["blog"]["factors"] and bands["situations"]["linkedin"]["factors"],
       "bands: the 3-document situations carry factor rows")
    ck(not bands["situations"]["report"].get("factors"),
       "bands: the fallback situation contributes no factor")
    f94 = bands["situations"]["blog"]["factors"].get("L9-4")
    manual = (bands["situations"]["blog"]["bands"]["L9-4"]["mean"] - pooled["L9-4"]["mean"]) \
        * 3.0 / 8.0
    ck(f94 is not None and abs(f94["factor"] - manual) < 1.0e-6 and f94["k"] == 3,
       "bands: the L9-4 factor equals the shrunk situation offset (k / (k + 5))")
    ck("no per-document source identity" in bands.get("layer_note", ""),
       "bands: the layer note states the source-blind pooled base")

    # CLI: full run, exit codes, state files
    r = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_setup.py"),
                        str(samples), "--level", "3", "--remeasure"],
                       capture_output=True, text=True, env=env)
    ck(r.returncode == 0 and "level: 3" in r.stdout and "situations learned" in r.stdout,
       "cli: a full run exits 0 and reports the level and the situations")
    ck((tdp / "learned" / "state" / "machine-bench.json").is_file()
       and (tdp / "learned" / "state" / "setup.json").is_file()
       and (tdp / "learned" / "state" / "voice-bands.json").is_file(),
       "cli: machine-bench.json, setup.json, and voice-bands.json land in learned/state")
    setup = json.loads((tdp / "learned" / "state" / "setup.json").read_text(encoding="utf-8"))
    ck(setup["level"] == 3 and setup["budget_ms"] == 1000,
       "cli: setup.json records the forced level and the budget")
    # --remeasure reuse: a second run without --remeasure reuses the bench
    r2 = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_setup.py"),
                         str(samples), "--level", "3"],
                        capture_output=True, text=True, env=env)
    ck(r2.returncode == 0 and "from machine-bench.json" in r2.stdout,
       "cli: without --remeasure the bench numbers are reused")
    # forced level over budget is reported, not dropped (fake bench numbers
    # make the check deterministic on any machine)
    state = tdp / "learned" / "state"
    (state / "machine-bench.json").write_text(json.dumps(SLOW), encoding="utf-8")
    r3 = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_setup.py"),
                         str(samples), "--level", "3", "--budget", "100"],
                        capture_output=True, text=True, env=env)
    ck(r3.returncode == 0 and "over the 100 ms budget" in r3.stdout,
       "cli: a forced level over the budget says so and stays set")
    # usage errors
    for bad in (["--level", "9"], ["--budget", "250"], [str(tdp / "absent-root")]):
        rb = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_setup.py")] + bad,
                            capture_output=True, text=True, env=env)
        ck(rb.returncode == 2, "cli: %s exits 2 (bad usage)" % " ".join(bad), str(rb.returncode))
    # the renderer reads the state: level 3 adds the two extra lines, --situation applies
    cand = tdp / "cand.md"
    cand.write_text(vs.fixture(1000, seed=777), encoding="utf-8")
    prof_root = tdp / "learned"
    (prof_root / "profile.json").write_text(json.dumps({"battery": {"docs": 3, "window_words": 500}}), encoding="utf-8")
    rr = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_battery_report.py"),
                         str(cand), "--situation", "blog"],
                        capture_output=True, text=True, env=env)
    ck(rr.returncode == 0 and "bands read at situation blog" in rr.stdout,
       "renderer: --situation applies the learned factor with the defined note")
    ck("cross-situation fit:" in rr.stdout and "windowed stability:" in rr.stdout,
       "renderer: level 3 adds the cross-situation fit and the windowed stability lines")
    setup_path = tdp / "learned" / "state" / "setup.json"
    setup_path.write_text(json.dumps({"level": 0, "budget_ms": 1000}), encoding="utf-8")
    rl = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_battery_report.py"),
                         str(cand)], capture_output=True, text=True, env=env)
    ck(rl.returncode == 0 and "setup level 0 keeps the battery report off" in rl.stdout,
       "renderer: setup level 0 turns the report bands off with the defined note")
    setup_path.unlink()

# interpreter probe (owner question 2026-11-27: what can be done about the
# +42 ms spawn floor; the floor belongs to the interpreter build) ---------------
cands = vs.interpreter_candidates()
ck(any(name == "current" for name, _path in cands) and len(cands) >= 1,
   "interpreters: the probe always finds the current interpreter",
   str([c[0] for c in cands]))
measured = vs.bench_interpreters(cands)
ck(all(e["spawn_ms"] > 0 for e in measured) and len(measured) == len(cands),
   "interpreters: every found interpreter carries a measured spawn")
line_one = vs.interpreter_line(measured[:1])
ck(line_one is None,
   "interpreters: one interpreter prints no note")
fake = [{"name": "current", "path": "x", "spawn_ms": 40.0},
        {"name": "python", "path": "y", "spawn_ms": 20.5},
        {"name": "py", "path": "z", "spawn_ms": 41.0}]
line = vs.interpreter_line(fake)
ck(line is not None and line.startswith("interpreters on PATH: python 20.5 ms, current 40.0 ms, py 41.0 ms; "
                                        "the fastest spawn is python and saves up to 20.5 ms per gate call"),
   "interpreters: the report line pins the fastest-first order and the saving", str(line))
ck(vs.interpreter_line([]) is None, "interpreters: an empty probe prints no note")

# stdlib-only pin ----------------------------------------------------------------
import ast  # noqa: E402
tree = ast.parse((PLUGIN_DIR / "learn" / "voice_setup.py").read_text(encoding="utf-8"))
imported = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imported.update(a.name.split(".")[0] for a in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        imported.add(node.module.split(".")[0])
ck(imported <= {"argparse", "importlib", "json", "math", "os", "random", "shutil",
                "statistics", "subprocess", "sys", "time", "pathlib"},
   "stdlib-only: voice_setup imports stay in the pinned set", str(sorted(imported)))

print(f"\nvoice_setup contract: {len(fails)} failure(s)")
sys.exit(1 if fails else 0)
