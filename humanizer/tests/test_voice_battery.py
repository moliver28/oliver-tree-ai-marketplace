#!/usr/bin/env python3
"""Contract tests for learn/voice_battery.py, learn/voice_battery_core.py,
learn/voice_battery_report.py, and the battery sections of
learn/build_voice_profile.py and hooks/gate.py (v1.2.0).

Run: python3 humanizer/tests/test_voice_battery.py
Exit 0 = every contract gate green.

The contract this file pins:

1. Spec: the 79 Tier A rows (the 74 rows of the measures map section 3a plus the
   5 rows of the re-tier pass delta1), with
   the per-level counts, and every row carries a unit, a minimum rule, and
   a count-floor rule; the renderer carries an edit reading for every row.
2. Closed-list sizes (deterministic; the payload contract of decision D1b):
   5.6 KB of R0/R1 lists in total, never more.
3. Tokenizer sync: voice_battery_core.py mirrors build_voice_profile.py
   byte for byte on the five tokenizer constants (the core module exists
   for the gate's latency budget and must never drift from the source of
   truth). No timing asserts in CI: list sizes and pattern strings only.
4. Band math: t quantiles by degrees of freedom (df = k - 1), the map's
   prediction factors, and the verdict thresholds.
5. Battery goldens: one deterministic synthetic corpus (built in-process,
   seeded; no personal text) measured on the shipped code; the full value
   row pins as a rounded-JSON SHA-256 plus named floats. Golden run on
   Python 3.11.15.
6. Profile battery section: per-measure mean / sample deviation / min /
   max / k (AM-04), the pooled reference rows, the per-level holdout
   outside counts, and the rank vector.
7. Gate fast core: a marker word produces at most ONE family-deduped fail
   line; the clean pass line stays byte-identical; fast_core is
   deterministic.
8. Report: the section-6 shape (11 level blocks, overall band, length
   confidence note, no decimal fit score), byte-deterministic, fail-open
   without a profile.
9. stdlib-only: the three new modules never leave the stdlib set.
"""
import ast
import hashlib
import importlib.util
import json
import math
import os
import pathlib
import random
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent      # humanizer/tests/
PLUGIN_DIR = HERE.parent                            # humanizer/
REPO_ROOT = PLUGIN_DIR.parent
ALLOWED_IMPORTS = {"importlib", "math", "os", "re"}
ALLOWED_IMPORTS_REPORT = {"argparse", "importlib", "json", "math", "os", "sys", "pathlib"}

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


vb = load_module("voice_battery_contract", PLUGIN_DIR / "learn" / "voice_battery.py")
core = load_module("voice_battery_core_contract", PLUGIN_DIR / "learn" / "voice_battery_core.py")
bvp = load_module("voice_profile_contract", PLUGIN_DIR / "learn" / "build_voice_profile.py")

# 1. Spec pins -----------------------------------------------------------------
PER_LEVEL = {"L1": 13, "L2": 9, "L3": 6, "L4": 12, "L5": 8, "L6": 1,
             "L7": 4, "L8": 2, "L9": 11, "L10": 7, "L11": 6}
got_levels = {}
for mid in vb.ALL_IDS:
    lv = vb.SPEC[mid][0]
    got_levels[lv] = got_levels.get(lv, 0) + 1
ck(len(vb.ALL_IDS) == 79 and got_levels == PER_LEVEL,
   "spec: the 79 Tier A rows (74 at dispatch plus the 5 re-tier rows) with the per-level counts",
   str(got_levels))
ck(all(vb.SPEC[mid][2] in vb.UNIT_TEXT for mid in vb.ALL_IDS),
   "spec: every row carries a known unit")
ck(all(vb.SPEC[mid][4] is not None for mid in vb.ALL_IDS if vb.SPEC[mid][3] != "win"),
   "spec: every row carries a minimum rule (L2-1 reads in windows only, no word floor)")
report_mod = load_module("voice_battery_report_contract", PLUGIN_DIR / "learn" / "voice_battery_report.py")
missing_readings = [mid for mid in vb.ALL_IDS if mid not in report_mod.EDIT_READINGS]
ck(not missing_readings, "spec: the renderer carries an edit reading for every row", str(missing_readings[:4]))
ck(all(r[2] in ("sentence length", "word choice", "punctuation", "structure", "links",
                "tone", "machine patterns", "no edit")
       for r in report_mod.EDIT_READINGS.values()),
   "spec: every reading maps to one of the eight edit classes")

# 2. Closed-list sizes ---------------------------------------------------------
sizes = {
    "function words": (len(set(bvp.FUNCTION_WORDS)), 60),
    "stop words": (len(bvp.STOPWORDS), 119),
    "prepositions": (len(set(vb.PREPOSITIONS)), 54),
    "subordinators": (len(set(vb.SUBORDINATORS)), 21),
    "coordinators": (len(set(vb.COORDINATORS)), 6),
    "pronouns": (len(set(vb.PRON_I + vb.PRON_WE + vb.PRON_YOU + vb.PRON_P3 + vb.PRON_OTHER)), 47),
    "hedges": (len(set(vb.HEDGES)), 58),
    "boosters": (len(set(vb.BOOSTERS)), 26),
    "intensifiers": (len(set(vb.INTENSIFIERS)), 7),
    "politeness words": (len(set(vb.POLITE)), 6),
    "machine markers": (len(set(vb.MACHINE)), 21),
    "verbs": (len(set(vb.VERBS)), 103),
    "gate markers": (len(core.GATE_MARKERS), 20),
}
bad = {k: v for k, v in sizes.items() if v[0] != v[1]}
ck(not bad, "sizes: the closed lists match their pinned entry counts", str(bad))
ck(len(vb.PHRASE_FAMILIES) == 3
   and [len(vb.PHRASE_FAMILIES[k]) for k in ("L10-2", "L9-12", "L5-10")] == [15, 5, 15],
   "sizes: the three Tier A phrase families carry their pinned alternative counts")
ck(all(w in vb.MACHINE for w in ("tapestry",)) and "tapestry" not in core.GATE_MARKERS,
   "sizes: tapestry stays in the L10-1 measure but out of the gate rule (one family per word)")

# 3. Tokenizer sync pins -------------------------------------------------------
drift = []
BVP_CONSTS = ("WORD_RE", "SENT_SPLIT", "PASSIVE_RE")       # defined by the source of truth
CORE_ONLY = ("PARA_SPLIT", "HEADING_RE", "ITEM_RE")        # core and battery share
for name in BVP_CONSTS:
    if getattr(core, name).pattern != getattr(bvp, name).pattern:
        drift.append(name)
    if getattr(core, name).pattern != getattr(vb, name).pattern:
        drift.append(name + " (battery)")
for name in CORE_ONLY:
    if getattr(core, name).pattern != getattr(vb, name).pattern:
        drift.append(name + " (battery)")
ck(not drift, "sync: voice_battery_core tokenizer constants are byte-identical across the modules",
   str(drift))

# 4. Band math pins ------------------------------------------------------------
t_pins = {(3, 4.3027), (5, 2.7764), (10, 2.2622), (20, 2.0930), (50, 2.0096)}
ck(all(abs(vb.t_value(k) - want) < 5.0e-5 for k, want in t_pins),
   "band: t quantiles match the map values (df = k - 1)")
ck(abs(vb.band_factor(5) - 3.042) < 1.0e-3 and abs(vb.band_factor(3) - 4.969) < 1.0e-3,
   "band: prediction factors match the map's worked values (3.042 at k 5, 4.969 at k 3)")
ck(vb.t_value(2) is None and vb.t_value(51) == vb.t_value(50),
   "band: k under 3 has no t value; k above 50 holds the df 49 value")
ck(vb.verdict(0.9, 2.7764) == "inside" and vb.verdict(3.5, 2.7764) == "near the edge"
   and vb.verdict(4.5, 2.7764) == "outside",
   "band: verdict thresholds sit at t and 1.5 t")
ck(abs(vb.eff_sd(2.0, 5.4) - math.sqrt(4.0 + 5.4)) < 1.0e-12,
   "band: s_eff = sqrt(s^2 + floor), the AM-06 count floor")

# 4b. Reference-derived axis goldens (delta1 rows L7-6 and L11-11) --------------
R3 = [[1.0, 0.9, 0.9], [0.9, 1.0, 0.9], [0.9, 0.9, 1.0]]
v1, lam = vb.power_iteration(R3)
want_v = 1.0 / math.sqrt(3.0)
ck(all(abs(x - want_v) < 1.0e-9 for x in v1) and abs(lam - 2.8) < 1.0e-9,
   "pca: power iteration pins the eigenvector (1,1,1)/sqrt(3) and lambda 2.8 of the fixed matrix",
   "%s %.6f" % (["%.9f" % x for x in v1], lam))
PC_ROWS = [[2.0, 1.0, 0.5], [1.0, 2.0, 1.5], [3.0, 2.5, 2.0], [1.5, 1.0, 0.5], [2.5, 3.0, 2.5]]
pc_v1, pc_mean, pc_sd, pc_projs = vb.first_pca(PC_ROWS)
PC_V1_GOLDEN = [0.471858, 0.623438, 0.623438]
PC_PROJ_GOLDEN = -1.035107
ck(all(abs(a - b) < 1.0e-6 for a, b in zip(pc_v1, PC_V1_GOLDEN)),
   "pca: the fixed rate rows pin the first eigenvector", str(["%.6f" % x for x in pc_v1]))
proj_row = [1.2, 1.4, 1.1]
z_row = [(proj_row[w] - pc_mean[w]) / pc_sd[w] if pc_sd[w] > 0 else 0.0 for w in range(3)]
proj = sum(pc_v1[w] * z_row[w] for w in range(3))
ck(abs(proj - PC_PROJ_GOLDEN) < 1.0e-6,
   "pca: the fixed candidate pins its projection score", "%.6f" % proj)
L2x2 = vb.cholesky_lower([[4.0, 2.0], [2.0, 3.0]])
ck(abs(L2x2[0][0] - 2.0) < 1.0e-12 and L2x2[0][1] == 0.0
   and abs(L2x2[1][0] - 1.0) < 1.0e-12 and abs(L2x2[1][1] - math.sqrt(2.0)) < 1.0e-12,
   "chol: the fixed 2x2 covariance pins its Cholesky factor",
   str([("%.9f" % x) for row in L2x2 for x in row]))
dist = vb.mahalanobis_distance([2.0, 2.0], [1.0, 1.0], L2x2)
ck(abs(dist - math.sqrt(0.375)) < 1.0e-12,
   "chol: the fixed difference pins the full-covariance distance (sqrt(0.375))", "%.9f" % dist)
# shrinkage fallback at k = 30: word 3 = word 0 + word 1 makes the covariance
# singular, so the unshrunk solve fails and the shrunk solve stays stable
rows30 = [[1.0 + 0.1 * (i % 5), 2.0 + 0.2 * (i % 3), 0.5 + 0.05 * ((i + 1) % 4),
           3.0 + 0.1 * (i % 5) + 0.2 * (i % 3)] for i in range(30)]
S_raw, _ = vb.shrunk_covariance(rows30, alpha=0.0)
raw_failed = False
try:
    vb.cholesky_lower(S_raw)
except ValueError:
    raw_failed = True
S_shr, mean30 = vb.shrunk_covariance(rows30, alpha=0.1)
shr_ok = False
try:
    L30 = vb.cholesky_lower(S_shr)
    d30 = vb.mahalanobis_distance(rows30[7], mean30, L30)
    shr_ok = d30 >= 0.0
except ValueError:
    shr_ok = False
ck(raw_failed and shr_ok,
   "chol: shrinkage fallback at k = 30 (unshrunk solve fails on the singular matrix, shrunk solve is stable)")

# 4c. MATTR window pin (Kendro et al. 2025: window 50; the prototype's 100 is
# superseded) and the excess-vocabulary list (Kobak et al. 2025, figure S6) ----
ck(vb.MATTR_WINDOW == 50 and len(set(vb.EXCESS_WORDS)) == 291,
   "rows: MATTR window pins at 50 and the excess list pins at 291 words (Kobak figure S6)")
toks_m = ["w%d" % (i % 13) for i in range(200)]
manual = vb.sample_mean([len(set(toks_m[i:i + 50])) / 50.0 for i in range(151)])
ck(abs(vb._mattr(toks_m) - manual) < 1.0e-12,
   "rows: MATTR equals the mean type-token ratio over consecutive 50-token windows")
excess_text = " ".join(["plain"] * 1998 + ["delve", "intricate"])
excess_vals = vb.values(vb.scan(excess_text), ref={})
ck(excess_vals["L10-15"] == 1.0,
   "rows: two excess words in 2,000 tokens read 1.0 per 1,000 words", str(excess_vals["L10-15"]))

# 5. Battery goldens on a synthetic corpus -------------------------------------
NOUNS = ("system engine report market pattern measure sample signal model document writer reader "
         "process result profile sentence corpus method study answer network service dataset").split()
VERBS = "shows uses needs gives takes makes finds keeps holds moves reads writes tests tracks adds".split()
ADJS = "simple clear short long fast slow stable rough exact useful common rare public local early late".split()
PP = "shown used needed given taken made found kept held moved read written tested tracked".split()


def sent(r):
    kind = r.randrange(12)
    if kind == 0:
        return "The %s %s the %s %s." % (r.choice(NOUNS), r.choice(VERBS), r.choice(ADJS), r.choice(NOUNS))
    if kind == 1:
        return "We %s the %s because our %s %s it, and we don't %s the %s." % (
            r.choice(VERBS), r.choice(NOUNS), r.choice(NOUNS), r.choice(VERBS), r.choice(VERBS), r.choice(NOUNS))
    if kind == 2:
        return "You can %s the %s when you %s the %s; it's %s." % (
            r.choice(VERBS), r.choice(NOUNS), r.choice(VERBS), r.choice(NOUNS), r.choice(ADJS))
    if kind == 3:
        return "Does the %s %s the %s? It %s %s %ss." % (
            r.choice(NOUNS), r.choice(VERBS), r.choice(NOUNS), r.choice(VERBS), r.choice(ADJS), r.choice(NOUNS))
    if kind == 4:
        return "The %s may %s the %s, but it might not %s the %s." % (
            r.choice(NOUNS), r.choice(VERBS), r.choice(NOUNS), r.choice(VERBS), r.choice(NOUNS))
    if kind == 5:
        return "Because the %s %s the %s, the %s %s %s %s when the %s %s." % (
            r.choice(NOUNS), r.choice(VERBS), r.choice(NOUNS), r.choice(NOUNS), r.choice(VERBS),
            r.choice(ADJS), r.choice(NOUNS), r.choice(NOUNS), r.choice(VERBS))
    if kind == 6:
        return "The %s %s three things: %s, %s, and %s." % (
            r.choice(NOUNS), r.choice(VERBS), r.choice(NOUNS), r.choice(NOUNS), r.choice(NOUNS))
    if kind == 7:
        return "The %s was %s by the %s, and the %s was %s in the %s." % (
            r.choice(NOUNS), r.choice(PP), r.choice(NOUNS), r.choice(NOUNS), r.choice(PP), r.choice(NOUNS))
    if kind == 8:
        return "The %s %s the %s; the %s %s it (see the %s)." % (
            r.choice(NOUNS), r.choice(VERBS), r.choice(NOUNS), r.choice(NOUNS), r.choice(VERBS), r.choice(NOUNS))
    if kind == 9:
        return "If the %s %s the %s, it %s the %s until the %s %s the %s." % (
            r.choice(NOUNS), r.choice(VERBS), r.choice(NOUNS), r.choice(VERBS), r.choice(NOUNS),
            r.choice(NOUNS), r.choice(VERBS), r.choice(NOUNS))
    if kind == 10:
        return "The %s %s %s the %s--the %s %s it." % (
            r.choice(NOUNS), r.choice(VERBS), r.choice(ADJS), r.choice(NOUNS), r.choice(NOUNS), r.choice(VERBS))
    return "- The %s %s the %s." % (r.choice(NOUNS).title(), r.choice(VERBS), r.choice(NOUNS))


def build_synthetic(n_words, seed):
    r = random.Random(seed)
    paras, count, i = [], 0, 0
    while count < n_words:
        i += 1
        if i % 8 == 0:
            p = "## %s %s" % (r.choice(NOUNS).title(), r.choice(NOUNS).title())
        elif i % 5 == 0:
            p = "\n".join(sent(r) for _ in range(r.randint(2, 4)))
        else:
            p = " ".join(sent(r) for _ in range(r.randint(2, 6)))
        paras.append(p)
        count += len(bvp.WORD_RE.findall(p))
    return "\n\n".join(paras)


DOC_TEXTS = [build_synthetic(1000, 900 + i) for i in range(5)]
CAND_TEXT = build_synthetic(1000, 777)
accs = [vb.scan(t, phrases=True, tri=True) for t in DOC_TEXTS]
docs_fw = [vb.fw_counts(a) for a in accs]
pooled = vb.pooled_counts(docs_fw)
fw_pooled = dict(zip(vb.FUNCTION_WORDS, pooled))
tri_pooled = vb.tri_merge([a["tri"] for a in accs])
window = int(round(vb.median([float(a["n"]) for a in accs])))
fw_rows = []
for t in DOC_TEXTS:
    toks = [w.lower() for w in bvp.WORD_RE.findall(t)]
    counts = {w: 0 for w in bvp.FUNCTION_WORDS}
    for w in toks:
        if w in counts:
            counts[w] += 1
    base = len(toks)
    fw_rows.append({w: counts[w] * 1000.0 / base for w in bvp.FUNCTION_WORDS})
mean = {w: sum(row[w] for row in fw_rows) / len(fw_rows) for w in bvp.FUNCTION_WORDS}
sd = {w: vb.sample_sd([row[w] for row in fw_rows]) for w in bvp.FUNCTION_WORDS}
rows0 = [vb.values(a, ref=vb.ref_block(mean, sd, fw_pooled, None, tri_pooled, 5), window=window)
         for a in accs]
col71 = [r["L7-1"] for r in rows0]
col72 = [r["L7-2"] for r in rows0]
reg = {"L7-1": (vb.sample_mean(col71), vb.sample_sd(col71)),
       "L7-2": (vb.sample_mean(col72), vb.sample_sd(col72)),
       "range": vb.sample_sd(col71)}
full_rows = [vb.values(a, ref=vb.ref_block(mean, sd, fw_pooled, reg, tri_pooled, 5), window=window)
             for a in accs]
cand_vals = vb.run(CAND_TEXT, ref=vb.ref_block(mean, sd, fw_pooled, reg, tri_pooled, 5), window=window)
golden_payload = json.dumps({mid: (round(v, 6) if isinstance(v, float) else v)
                             for mid, v in sorted(cand_vals.items())}, sort_keys=True)
GOLDEN_SHA = "1044b725ce634e4ee01db410b27251978b54837fbdcc6f6cd3e4e5b027c66aa7"
got_sha = hashlib.sha256(golden_payload.encode("utf-8")).hexdigest()
ck(got_sha == GOLDEN_SHA,
   "goldens: the candidate battery row pins its SHA-256 (79 rounded values, Python 3.11.15 run)",
   got_sha)
ck(abs(cand_vals["L4-1"] - 11.010870) < 1.0e-6 and abs(cand_vals["L11-4"] - 0.511455) < 1.0e-6,
   "goldens: named floats (mean sentence length 11.010870, Jensen-Shannon 0.511455)",
   "%.6f / %.6f" % (cand_vals["L4-1"], cand_vals["L11-4"]))
det2 = vb.run(CAND_TEXT, ref=vb.ref_block(mean, sd, fw_pooled, reg, tri_pooled, 5), window=window)
ck(det2 == cand_vals, "goldens: two battery runs on the same text agree exactly")
ck(vb.values(vb.scan(CAND_TEXT), ref={})["L11-4"] is None,
   "goldens: L11 distances read None without a reference (never a made-up 0)")

# 6. Profile battery section ---------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    tdp = pathlib.Path(td)
    env = {**os.environ, "VOICE_LEARNED_DIR": str(tdp / "learned")}
    (tdp / "learned").mkdir()
    samples = tdp / "samples"
    samples.mkdir()
    for i, text in enumerate(DOC_TEXTS):
        (samples / ("s%d.md" % (i + 1))).write_text(text, encoding="utf-8")
    cand = tdp / "cand.md"
    cand.write_text(CAND_TEXT, encoding="utf-8")
    rbp = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "build_voice_profile.py"),
                          str(samples), "--out", str(tdp / "learned" / "profile.json")],
                         capture_output=True, text=True, env=env)
    prof = json.loads((tdp / "learned" / "profile.json").read_text(encoding="utf-8"))
    batt = prof.get("battery") or {}
    ck(rbp.returncode == 0 and batt.get("docs") == 5 and isinstance(batt.get("window_words"), int),
       "profile: the battery section carries the document count and the window size")
    meas = batt.get("measures") or {}
    shape_bad = [mid for mid, st in meas.items()
                 if not ({"mean", "sd", "min", "max", "k"} <= set(st) and st["k"] >= 2)]
    ck(len(meas) >= 55 and not shape_bad,
       "profile: per-measure mean, sample deviation, min, max, and k are stored",
       "%d stored, bad %s" % (len(meas), shape_bad[:3]))
    sd_bad = []
    for w, v in prof["function_words"]["stddev"].items():
        col = [row[w] for row in fw_rows]
        mu = sum(col) / len(col)
        want = math.sqrt(sum((x - mu) ** 2 for x in col) / (len(col) - 1))
        if abs(v - want) > 1.0e-6:
            sd_bad.append(w)
    ck(not sd_bad, "profile: function_words stores the SAMPLE deviation, divide by k - 1 (AM-04)",
       str(sd_bad[:3]))
    lh = batt.get("levels_holdout") or {}
    ck(sorted(lh.keys()) == sorted(vb.LEVELS) and all(isinstance(v, int) for v in lh.values()),
       "profile: per-level holdout outside counts are stored", str(lh))
    rank = batt.get("rank") or {}
    ck(rank.get("measure") == "L11-4" and len(rank.get("d") or []) == 5,
       "profile: the rank vector holds one leave-one-out distance per document")
    pca_side = json.loads((tdp / "learned" / "profile-pca.json").read_text(encoding="utf-8"))
    chol_side = json.loads((tdp / "learned" / "profile-covariance.json").read_text(encoding="utf-8"))
    ck(pca_side.get("k") == 5 and len(pca_side.get("v1") or []) == 60
       and isinstance(pca_side.get("proj_sd"), float),
       "profile: profile-pca.json carries the eigenvector and the projection band (5 documents)")
    ck(chol_side.get("k") == 5 and 2 <= len(chol_side.get("words") or []) <= 60
       and len((chol_side.get("band") or {}).get("distances") or []) == 5
       and chol_side.get("alpha") == 0.1,
       "profile: profile-covariance.json carries the shrinkage factor and the leave-one-out band",
       "words kept %d" % len(chol_side.get("words") or []))
    ck("L7-6" in meas and "L11-11" in meas and "L2-5" in meas,
       "profile: the axes and MATTR store per-measure bands like every other row")
    refw = (batt.get("reference") or {})
    ck(len(refw.get("fw_pooled") or []) == 60 and len(refw.get("docs_fw")) == 5
       and len(refw.get("docs_words")) == 5
       and sum(refw.get("fw_pooled") or []) == sum(sum(r) for r in refw.get("docs_fw") or []),
       "profile: the pooled reference rows carry 60-word counts per document and pooled")
    # report renderer against the built profile
    rrep = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_battery_report.py"),
                           str(cand), "--profile", str(tdp / "learned" / "profile.json")],
                          capture_output=True, text=True, env=env)
    out1 = rrep.stdout
    level_lines = [l for l in out1.splitlines() if re.match(r"^L\d+ ", l)]
    ck(rrep.returncode == 0 and len(level_lines) == 11,
       "report: eleven level blocks print, exit 0", str(len(level_lines)))
    ck(out1.startswith("voice fit  (reference: 5 documents)")
       and out1.rstrip().endswith("rank false alarm 1 of 6"),
       "report: the header names the reference and the length note closes with the false alarm")
    ck("overall: " in out1 and "length: " in out1 and not re.search(r"\bfit [0-9]+\.[0-9]", out1),
       "report: overall band and length note present, no decimal fit score")
    rrep2 = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_battery_report.py"),
                            str(cand), "--profile", str(tdp / "learned" / "profile.json")],
                           capture_output=True, text=True, env=env)
    ck(rrep2.returncode == 0 and rrep2.stdout == out1,
       "report: two runs print byte-identical text")
    ck("L7-6 function-word PCA projection" in out1 and "L11-11 full-covariance Delta" in out1
       and "by the stored leave-one-out distances" in out1,
       "report: the two axis rows print, L11-11 with its leave-one-out rank line")
    rj = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_battery_report.py"),
                         str(cand), "--profile", str(tdp / "learned" / "profile.json"), "--json"],
                        capture_output=True, text=True, env=env)
    jrep = json.loads(rj.stdout)
    ck(rj.returncode == 0 and jrep.get("overall") in ("inside", "near the edge", "outside")
       and "L11-8" in " ".join(jrep.get("suppressed") or []),
       "report: --json carries the overall band and lists L11-8 as suppressed without --samples")
    # fail-open: no profile at all
    env_np = {**os.environ, "VOICE_LEARNED_DIR": str(tdp / "absent")}
    rnp = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_battery_report.py"),
                          str(cand)], capture_output=True, text=True, env=env_np)
    ck(rnp.returncode == 0 and "no profile at" in rnp.stdout and "overall: n/a" in rnp.stdout,
       "report: fail-open with no profile, exit 0, defined note, overall n/a")
    # usage errors
    rerr = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "learn" / "voice_battery_report.py"),
                           str(tdp / "missing.md")], capture_output=True, text=True, env=env)
    ck(rerr.returncode == 2, "report: a missing candidate file exits 2 (bad usage)")

# 7. Gate fast core ------------------------------------------------------------
MARKER_TEXT = ("The team will unravel the intricate process.\n\n"
               "We prioritize the solace of the reader, and the palpable result stays.\n\n"
               "The scanner loads the rules from the shared module, so the hook and the checker cannot drift.")
CLEAN_TEXT = "The scanner loads the rules from the shared module, so the hook and the checker cannot drift."
fc1 = core.fast_core(MARKER_TEXT)
fc2 = core.fast_core(MARKER_TEXT)
ck(fc1 == fc2 and fc1["marker_counts"].get("unravel") == 1 and fc1["marker_counts"].get("intricate") == 1
   and "tapestry" not in fc1["marker_counts"],
   "gate core: fast_core is deterministic and counts the marker words (tapestry excluded)")
with tempfile.TemporaryDirectory() as td:
    env = {**os.environ, "VOICE_LEARNED_DIR": td, "VOICE_GATE_LOG": str(pathlib.Path(td, "gate.log")),
           "VOICE_GATE_VECTOR": "off"}
    r = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "hooks" / "gate.py"), "--surface", "public"],
                       input=MARKER_TEXT, capture_output=True, text=True, env=env)
    j = json.loads(r.stdout)
    battery_lines = [ln for ln in j.get("instruction", "").splitlines() if "battery marker" in ln]
    ck(r.returncode == 4 and j["status"] == "fail" and len(battery_lines) == 1
       and j.get("reported", 0) <= 5,
       "gate: a marker text fails with at most ONE battery marker line inside the 5-line cap")
    ck("unravel" in battery_lines[0] if battery_lines else False,
       "gate: the battery marker line names the marker word")
    r2 = subprocess.run([sys.executable, "-I", str(PLUGIN_DIR / "hooks" / "gate.py"), "--surface", "public"],
                        input=CLEAN_TEXT, capture_output=True, text=True, env=env)
    ck(r2.returncode == 0 and r2.stdout.strip() == '{"status": "pass", "surface": "public", "tokens_to_model": 0}',
       "gate: the clean pass line stays byte-identical with the battery core loaded")

# 8 + 9. stdlib-only import pins ------------------------------------------------
for name, path, allowed in (
        ("voice_battery", PLUGIN_DIR / "learn" / "voice_battery.py", ALLOWED_IMPORTS),
        ("voice_battery_core", PLUGIN_DIR / "learn" / "voice_battery_core.py", {"re"}),
        ("voice_battery_report", PLUGIN_DIR / "learn" / "voice_battery_report.py", ALLOWED_IMPORTS_REPORT)):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    ck(imported <= allowed, f"stdlib-only: {name} imports stay in the pinned set", str(sorted(imported)))

print(f"\nvoice_battery contract: {len(fails)} failure(s)")
sys.exit(1 if fails else 0)
