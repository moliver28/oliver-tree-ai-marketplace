#!/usr/bin/env python3
"""Contract tests for the wave H-C learn-to-gate data contract and the
detection methods (issue #5 ruling clauses 1-4; issues #145/#167; the
method menu at the orchestrator's notes).

Run: python3 tests/humanizer/test_hc_methods.py
Exit 0 = every contract gate green.

Sections (A lands with the data contract commit; B with the methods
commit; the file grows with the wave):

A. Data contract (issue #5, all four clauses)
   1. Detector threshold bands join the state-file loader: sources may
      carry "bands"; numbers load at scan time; absent state -> empty
      bands, embedded defaults unchanged; entry-level invalid numbers
      skip just that entry and log state_skip (fail-open unchanged).
   2. cycling_signals consumes the bands from the loader chain: absent
      bands -> [], qualifying pairs only under present bands, shape
      mismatch -> [], inactive vector pass -> [].
   3. vector_pass exposes the per-chunk vectors it already computes
      (chunk_vecs; no second embedding pass).
   4. Clause 1 proof at the gate level: a pattern that exists only in the
      state file fires in the real gate subprocess; a corrupt state file
      fails open to the embedded register (clean text still passes).
   5. Clause 3: learn/regenerate.py runs the whole rebuild chain in one
      pass, one line per step, fail-open skip lines, exit 0 without any
      corpus; a nonexistent --corpus path is a usage error (exit 2).
   6. Clause 2 audit: no learn tool writes a code file (no write call in
      any learn/*.py targets a .py/.pyc/.yaml/.yml path constant).
"""
import ast
import importlib.util
import json
import os
import pathlib
import re
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


vt = load_module("hc_voice_tells", PLUGIN_DIR / "hooks" / "voice_tells.py")

# A1+A2. bands in the state-file loader chain ----------------------------------
with tempfile.TemporaryDirectory() as td:
    tdp = pathlib.Path(td)
    logf = tdp / "gate.log"
    stf = tdp / "voice-rules.json"
    saved = {k: os.environ.pop(k) for k in ("VOICE_RULES_STATE", "VOICE_GATE_LOG") if k in os.environ}
    try:
        os.environ["VOICE_GATE_LOG"] = str(logf)
        # absent state file: empty bands, embedded defaults, silent
        os.environ["VOICE_RULES_STATE"] = str(tdp / "absent.json")
        eff = vt.effective_rules()
        ck(eff.get("bands") == {} and eff["patterns"] == list(vt.PATTERNS),
           "data contract: absent state -> empty bands, embedded defaults unchanged")
        ck(not logf.exists(), "data contract: absent state stays silent (no log side effects)")
        # valid bands: numbers load at scan time, per-key file order override
        os.environ["VOICE_RULES_STATE"] = str(stf)
        stf.write_text(json.dumps({
            "format": 1,
            "sources": {
                "calibration": {"bands": {"cycling": {"t_sem": 0.62, "t_lex": 0.35}}},
                "owner": {"bands": {"cycling": {"t_sem": 0.7}, "compression": {"sd_hi": 0.09}}},
            }}, indent=2))
        eff = vt.effective_rules()
        ck(eff["bands"].get("cycling") == {"t_sem": 0.7, "t_lex": 0.35},
           "data contract: band numbers load from the state chain, later source overrides per key",
           str(eff.get("bands")))
        ck(eff["bands"].get("compression") == {"sd_hi": 0.09},
           "data contract: a second band name loads beside the first")
        # invalid entries skip per key, valid keys stay, state_skip logged
        if logf.exists():
            logf.unlink()
        stf.write_text(json.dumps({
            "format": 1,
            "sources": {"calibration": {"bands": {
                "cycling": {"t_sem": 0.62, "t_lex": "high"},
                "flat": "not an object"}}}}, indent=2))
        eff = vt.effective_rules()
        ck(eff["bands"].get("cycling") == {"t_sem": 0.62},
           "data contract: a non-number band entry is skipped, valid numbers stand")
        ck("flat" not in eff["bands"],
           "data contract: a non-object band is skipped")
        ck(logf.exists() and "not a number" in logf.read_text(errors="replace"),
           "data contract: invalid band entries log state_skip with the entry named")
        # corrupt state file: full embedded fallback, bands empty
        if logf.exists():
            logf.unlink()
        stf.write_text("{corrupt json here")
        eff = vt.effective_rules()
        ck(eff["bands"] == {} and eff["patterns"] == list(vt.PATTERNS)
           and logf.exists() and '"state_skip"' in logf.read_text(errors="replace"),
           "data contract: corrupt state -> embedded fallback, empty bands, state_skip logged")
    finally:
        for k in ("VOICE_RULES_STATE", "VOICE_GATE_LOG"):
            os.environ.pop(k, None)
        for k, v in saved.items():
            os.environ[k] = v

# A2. cycling_signals consumes the loader chain --------------------------------
with tempfile.TemporaryDirectory() as td:
    tdp = pathlib.Path(td)
    saved = {k: os.environ.pop(k) for k in ("VOICE_RULES_STATE", "VOICE_GATE_LOG") if k in os.environ}
    try:
        os.environ["VOICE_GATE_LOG"] = str(tdp / "gate.log")
        sets = [frozenset({"alpha", "beta"}), frozenset({"gamma", "delta"}),
                frozenset({"alpha", "beta"})]

        def vec(words):
            v = [0.0] * 8
            for w in words:
                v[ord(w[0]) % 8] = 1.0
            n = sum(x * x for x in v) ** 0.5 or 1.0
            return [x / n for x in v]
        # chunks 0 and 1 share the vector direction (cosine 1.0) while their
        # content-word sets are disjoint: the cycling signature
        vp = {"active": True, "chunk_vecs": [vec("ab"), vec("ab"), vec("cd")]}
        ck(vt.cycling_signals(vp, sets) == [],
           "cycling: absent bands -> no pairs (advisory only, never a fail line)")
        os.environ["VOICE_RULES_STATE"] = str(tdp / "voice-rules.json")
        (tdp / "voice-rules.json").write_text(json.dumps({
            "format": 1, "sources": {"calibration": {"bands": {
                "cycling": {"t_sem": 0.9, "t_lex": 0.1}}}}}))
        got = vt.cycling_signals(vp, sets)
        ck(len(got) == 1 and got[0]["pair"] == 0 and got[0]["cosine"] == 1.0
           and got[0]["jaccard"] == 0.0,
           "cycling: bands present -> the high-cosine zero-overlap pair qualifies", str(got))
        (tdp / "voice-rules.json").write_text(json.dumps({
            "format": 1, "sources": {"calibration": {"bands": {
                "cycling": {"t_sem": 0.9, "t_lex": 0.0}}}}}))
        got = vt.cycling_signals(vp, sets)
        ck(len(got) == 1 and got[0]["pair"] == 0,
           "cycling: t_lex 0 keeps the zero-overlap pair only", str(got))
        (tdp / "voice-rules.json").write_text(json.dumps({
            "format": 1, "sources": {"calibration": {"bands": {
                "cycling": {"t_sem": 1.1, "t_lex": 0.1}}}}}))
        ck(vt.cycling_signals(vp, sets) == [],
           "cycling: a cosine band no pair reaches -> no pairs")
        ck(vt.cycling_signals({"active": True, "chunk_vecs": [vec("ab")]}, sets[:1]) == [],
           "cycling: shape mismatch (sets and vectors lengths differ) -> []")
        ck(vt.cycling_signals({"active": False, "chunk_vecs": None}, sets) == [],
           "cycling: inactive vector pass -> []")
    finally:
        for k in ("VOICE_RULES_STATE", "VOICE_GATE_LOG"):
            os.environ.pop(k, None)
        for k, v in saved.items():
            os.environ[k] = v

# A3. vector_pass exposes chunk_vecs, inactive shape included -------------------
off = vt.vector_pass.__doc__ and "chunk_vecs" in vt.vector_pass.__doc__
ck(off, "vector layer: vector_pass documents the chunk_vecs output")
ck(vt.vector_pass("irrelevant")["chunk_vecs"] is None,
   "vector layer: inactive pass carries chunk_vecs None (fail-open shape)")

# A4. clause 1 at the gate level (state rule fires in the real gate) ------------
with tempfile.TemporaryDirectory() as td:
    tdp = pathlib.Path(td)
    stf = tdp / "voice-rules.json"
    saved = {k: os.environ.pop(k) for k in ("VOICE_RULES_STATE", "VOICE_GATE_VECTOR") if k in os.environ}
    try:
        os.environ["VOICE_GATE_VECTOR"] = "off"
        stf.write_text(json.dumps({"format": 1, "sources": {"register": {"patterns": [
            {"pattern": "\\bfrobnicate\\b", "label": "state pattern 'frobnicate' (register)"}]}}}))
        os.environ["VOICE_RULES_STATE"] = str(stf)
        env = {**os.environ}
        r = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "hooks" / "gate.py"),
                            "--surface", "public"],
                           input="Please frobnicate the stack before the audit reads it.",
                           capture_output=True, text=True, env=env)
        ok4 = False
        try:
            j = json.loads(r.stdout)
            ok4 = (r.returncode == 4 and j["status"] == "fail"
                   and "frobnicate" in j.get("instruction", ""))
        except Exception:
            pass
        ck(ok4, "data contract clause 1: a state-file-only pattern fails in the real gate subprocess")
        stf.write_text("{corrupt")
        r2 = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "hooks" / "gate.py"),
                             "--surface", "public"],
                            input="The scanner loads the rules from the shared module first.",
                            capture_output=True, text=True, env=env)
        ck(r2.returncode == 0 and json.loads(r2.stdout)["status"] == "pass",
           "data contract clause 1: corrupt state fails open, clean text passes (exit 0)")
    finally:
        for k in ("VOICE_RULES_STATE", "VOICE_GATE_VECTOR"):
            os.environ.pop(k, None)
        for k, v in saved.items():
            os.environ[k] = v

# A5. clause 3: one scripted regenerate pass ------------------------------------
reg_path = PLUGIN_DIR / "learn" / "regenerate.py"
reg = load_module("hc_regenerate", reg_path)
ck(hasattr(reg, "main"), "regenerate: importable with main()")
with tempfile.TemporaryDirectory() as td:
    tdp = pathlib.Path(td)
    env = {**os.environ, "VOICE_LEARNED_DIR": str(tdp / "learned"),
           "VOICE_GATE_LOG": str(tdp / "gate.log"), "VOICE_GATE_VECTOR": "off"}
    (tdp / "learned").mkdir()
    r = subprocess.run([sys.executable, "-I", str(reg_path)],
                       capture_output=True, text=True, env=env)
    lines = r.stdout.splitlines()
    steps = [ln for ln in lines if ln.startswith("regenerate ")]
    names = [ln.split(":")[0] for ln in steps]
    ck(r.returncode == 0 and len(steps) == 6
       and names == ["regenerate calibrate", "regenerate distill", "regenerate vectors",
                     "regenerate classifier", "regenerate profile", "regenerate pool"],
       "regenerate: the full chain runs in one pass, fixed order, one line per step",
       str(names))
    ck(any("skipped (--corpus not given)" in ln for ln in steps)
       and any("skipped (--samples not given)" in ln for ln in steps),
       "regenerate: missing optional inputs print defined skip lines, exit stays 0")
    ck(any("pool empty" in ln for ln in steps),
       "regenerate: an empty reference pool prints the defined pool line")
    ck((tdp / "learned" / "rules.json").is_file(),
       "regenerate: the distill output lands in the configured learned dir "
       "(VOICE_LEARNED_DIR), never the repo default")
    r2 = subprocess.run([sys.executable, "-I", str(reg_path), "--corpus", str(tdp / "missing")],
                        capture_output=True, text=True, env=env)
    ck(r2.returncode == 2, "regenerate: a nonexistent --corpus path is a usage error (exit 2)")

# A6. clause 2 audit: learn tools write data files only -------------------------
WRITE_FUNCS = {"write_text", "write_bytes", "open"}
CODE_SUFFIX = re.compile(r"\.(py|pyc|pyo|yaml|yml)$", re.IGNORECASE)
violations = []
learn_dir = PLUGIN_DIR / "learn"
for p in sorted(learn_dir.glob("*.py")):
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = node.func
        name = fname.attr if isinstance(fname, ast.Attribute) else (fname.id if isinstance(fname, ast.Name) else "")
        if name not in WRITE_FUNCS:
            continue
        for arg in node.args + [kw.value for kw in node.keywords]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and CODE_SUFFIX.search(arg.value):
                violations.append("%s:%d writes %r" % (p.name, node.lineno, arg.value))
ck(not violations,
   "data contract clause 2: no learn tool writes a code file (audit over learn/*.py)",
   "; ".join(violations[:4]))

# B. Detection methods (method menu A1 / B4 / B2; issue #145) -------------------
core = load_module("hc_battery_core", PLUGIN_DIR / "learn" / "voice_battery_core.py")

# B1. chunk alignment: the core mirror stays byte-identical to vector_pass
_LONG = "\n\n".join(
    ("Paragraph %d carries enough prose to cross the chunk boundary when the "
     "writer keeps going for a while. The scanner reads the words in one "
     "shared pass and the chunks stay aligned with the vector pass.") % i
    for i in range(30))
ck(core._chunks("short text") == vt._chunks("short text")
   and core._chunks(_LONG) == vt._chunks(_LONG),
   "chunk alignment: the core chunk mirror matches voice_tells._chunks exactly "
   "(short and long texts)")
sets_c = core.chunk_content_sets(_LONG)
chunks_c = core._chunks(_LONG)
ck(len(sets_c) == len(chunks_c) and len(sets_c) >= 2,
   "chunk alignment: chunk_content_sets returns one content set per chunk")
ck(all(isinstance(s, frozenset) for s in sets_c)
   and all(w not in core.STOPWORDS for s in sets_c for w in s),
   "chunk alignment: content sets hold content words only (stop words excluded)")

# B2. compression profile: deterministic, level 6, advisory shape
prof1 = core.compression_profile(_LONG)
prof2 = core.compression_profile(_LONG)
ck(prof1 == prof2 and 0.0 < prof1["ratio"] < 1.0 and prof1["paragraphs"] > 0,
   "compression: the profile is deterministic and reports a real ratio",
   str(prof1))
import zlib as _zlib
_para = _LONG.split("\n\n")[0]
ck(len(_zlib.compress(_para.encode("utf-8"), 6))
   == len(_zlib.compress(_para.encode("utf-8"), core.ZLIB_LEVEL)),
   "compression: the shipped zlib level stays pinned at 6")

# B3. aphorism shapes: kickers hit, prose and instructions stay clean
KICKS = [("No pain, no gain.", "fragment"), ("Ship it.", "imperative"),
         ("The rule is simple: cut it.", "colon-kicker"),
         ("Voice is trust.", "copular-definition")]
ck(all(core._aph_shape(s) == want for s, want in KICKS),
   "aphorism: the four countable kicker shapes hit their own shapes",
   str([(s, core._aph_shape(s)) for s, _w in KICKS]))
CLEANS = ["Set the timeout.", "Save the file.",
          "The scanner loads the rules from the shared module, so the hook and the "
          "checker cannot drift.",
          "It is not just about speed, it is about unlocking value at the end of the day.",
          "The report shows three things: numbers, facts, and figures.",
          "No one argued about the deadline."]
ck(all(core._aph_shape(s) is None for s in CLEANS),
   "aphorism: instructions and prose sentences carry no shape hits",
   str([(s, core._aph_shape(s)) for s in CLEANS if core._aph_shape(s)]))
two_kickers = "Ship it.\n\nNo pain, no gain."
hits2 = core.aphorism_budget_hits(two_kickers)
ck(len(hits2) == 1 and "section '(opening)'" in hits2[0] and "2 kicker shapes" in hits2[0],
   "aphorism: two kickers in one section produce the section budget line", str(hits2))
four_sections = ("## One\n\nShip it.\n\n## Two\n\nNo pain, no gain.\n\n"
                 "## Three\n\nVoice is trust.\n\n## Four\n\nMove fast.")
hits4 = core.aphorism_budget_hits(four_sections)
ck(len(hits4) == 1 and "piece carries 4" in hits4[0],
   "aphorism: one kicker per section across four sections trips the piece budget",
   str(hits4))
resume_text = "- Lead the team\n\nSkills:\nShip fast.\n\n## Experience\n\nBuild the pipeline."
ck(core.aphorism_budget_hits(resume_text, profile="resume") == [],
   "aphorism: the resume profile keeps list items and labeled lines out of the count")
ck("humanizer 35" in core.aphorism_budget_hits(four_sections)[0],
   "aphorism: the budget lines carry the humanizer 35 family id for the situational table")

# B4. the gate: budget fail line inside the 5-line cap, clean pass byte-identical
with tempfile.TemporaryDirectory() as td:
    tdp = pathlib.Path(td)
    env = {**os.environ, "VOICE_LEARNED_DIR": str(tdp / "learned"),
           "VOICE_GATE_LOG": str(tdp / "gate.log"), "VOICE_GATE_VECTOR": "off"}
    (tdp / "learned").mkdir()
    r = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "hooks" / "gate.py"),
                        "--surface", "public"],
                       input=four_sections, capture_output=True, text=True, env=env)
    ok_line = False
    try:
        j = json.loads(r.stdout)
        aph_lines = [ln for ln in j.get("instruction", "").splitlines()
                     if "aphorism budget" in ln]
        ok_line = (r.returncode == 4 and j["status"] == "fail" and len(aph_lines) == 1
                   and "piece carries 4" in aph_lines[0]
                   and j.get("reported", 0) <= 5)
    except Exception:
        pass
    ck(ok_line,
       "gate: the aphorism budget fails over-budget text with ONE family-deduped line "
       "inside the 5-line cap, naming the count against the budget")
    clean_ok = ("Set the timeout. The scanner reads the config first. Save the file.\n\n"
                "Ship it.")
    r2 = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "hooks" / "gate.py"),
                         "--surface", "public"],
                        input=clean_ok, capture_output=True, text=True, env=env)
    ck(r2.returncode == 0
       and r2.stdout.strip() == '{"status": "pass", "surface": "public", "tokens_to_model": 0}',
       "gate: a one-kicker instruction text still passes with the byte-identical pass line")
    try:
        j2 = json.loads(r2.stdout)
        ck(not any(k in j2 for k in ("cycling_pairs", "compression_profile")),
           "gate: the band-gated advisory fields stay absent without learned bands")
    except Exception:
        ck(False, "gate: pass JSON parse for the advisory-absent case")
    # band-gated advisory field: compression bands in the learned state
    stf = tdp / "voice-rules.json"
    stf.write_text(json.dumps({"format": 1, "sources": {"calibration": {"bands": {
        "compression": {"sd_hi": 99.0}}}}}))
    env_b = {**env, "VOICE_RULES_STATE": str(stf)}
    r3 = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "hooks" / "gate.py"),
                         "--surface", "public"],
                        input=clean_ok, capture_output=True, text=True, env=env_b)
    try:
        j3 = json.loads(r3.stdout)
        cp = j3.get("compression_profile")
        ck(r3.returncode == 0 and isinstance(cp, dict) and "ratio" in cp and "sd" in cp,
           "gate: compression_profile rides the pass JSON only when the learned state "
           "carries the band", str(cp))
    except Exception as e:
        ck(False, "gate: compression advisory JSON parse: %r" % (e,))

# B5. the report rows L10-18/19/20 ------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    tdp = pathlib.Path(td)
    env = {**os.environ, "VOICE_LEARNED_DIR": str(tdp / "learned"),
           "VOICE_GATE_LOG": str(tdp / "gate.log")}
    (tdp / "learned").mkdir()
    cand = tdp / "cand.md"
    cand.write_text("## Section\n\nShip it.\n\nNo pain, no gain.\n\nVoice is trust.",
                    encoding="utf-8")
    env_nc = {**env, "VOICE_GATE_VECTOR": "off"}
    r = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_battery_report.py"),
                        str(cand)], capture_output=True, text=True, env=env_nc)
    out1 = r.stdout
    ck(r.returncode == 0 and "L10-18" in out1 and "L10-19 aphorism shapes" in out1
       and "L10-20 compression profile" in out1,
       "report: the three method rows print in the L10 block")
    ck("needs calibrated cycling bands" in out1,
       "report: L10-18 reads n/a with the defined note while uncalibrated")
    ck("outside  L10-19" in out1 and "sections over budget" in out1,
       "report: L10-19 reads outside against the budget on over-budget text")
    ck("readings " in out1 and " of 82;" in out1,
       "report: the length note counts the three method rows (82-row total)")
    r2 = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_battery_report.py"),
                         str(cand)], capture_output=True, text=True, env=env_nc)
    ck(r2.returncode == 0 and r2.stdout == out1,
       "report: two runs print byte-identical text (method rows included)")
    rj = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_battery_report.py"),
                         str(cand), "--json"], capture_output=True, text=True, env=env_nc)
    try:
        jrep = json.loads(rj.stdout)
        l10_rows = {row["id"]: row for row in (jrep.get("levels", {}).get("L10", {})
                                               .get("rows") or [])}
        ck("L10-19" in l10_rows and "L10-20" in l10_rows and "L10-18" not in l10_rows,
           "report: --json carries the computed method rows in the L10 block (the "
           "suppressed cycling row stays out, like L11-12)",
           str(sorted(l10_rows)))
    except Exception as e:
        ck(False, "report: --json parse: %r" % (e,))

print(f"\nhc methods + data contract: {len(fails)} failure(s)")
sys.exit(1 if fails else 0)
