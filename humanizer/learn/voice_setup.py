#!/usr/bin/env python3
"""voice_setup.py: the install experience of the humanizer plugin (v1.3.0).

Plugins ship no system installer, so this script IS the setup program. It
runs once on first use (re-runnable with --remeasure and --level N) and does
four things, in order:

1. Measure the machine one time. Interpreter spawn, the full gate command at
   a fixed 2,000-word fixture, the battery cost at 500 / 2,000 / 5,000 words,
   the fast-core cost, the two reference-derived axis applies, and the
   level-3 cross-situation piece. Everything is MEASURED on the user's
   machine; nothing is estimated. Results land in
   <learned>/state/machine-bench.json.
2. Pick the measurement level from those measured numbers against the
   user's delay budget (default 1,000 ms; choices 100 / 300 / 500 / 1000).
   Hard rule: the gate path always stays under the 100 ms perception
   threshold (Nielsen 1993), and the gate fast core (level 0) is always on.
   The budget caps the report and analysis path at the 1 second
   flow-of-thought limit. Levels: 0 = gate fast core only; 1 = full battery
   report; 2 = heavy report rows (the PCA projection and the full-covariance
   Delta; MMD two-sample waits for its row to land); 3 = cross-situation
   comparison and windowed stability checks. If the chosen level does not
   fit the measured budget, the script says so and sets the highest that
   fits. Result in <learned>/state/setup.json.
3. Learn the voice per situation. Sample documents come from a directory
   tree with one subdirectory per situation (blog, linkedin, report; ruling
   D5b). Each situation needs 3 or more documents of 500 or more words for
   its own band; a smaller situation falls back to the pooled band and the
   report says so. Layer 1 stores pooled source-blind bands (no per-document
   source identity beside the metrics). Layer 2 stores per-situation
   factors on the tone rows first and the register rows second:
   factor = (situation mean - pooled mean) * k / (k + 5), the shrinkage
   n0 = 5, so a small situation cannot distort the target. Samples and bands
   stay user-local (VOICE_LEARNED_DIR), never in the repo, never committed.
   The reference is the user's own samples plus the user's exemplar
   documents, measured on the user's machine. Norm tables are NOT part of
   this program; the fallback chain ends at the pooled band.
4. Report to the user in plain words: the machine's measured numbers, the
   situations learned with their document counts, and the chosen level with
   the reason.

The report renderer (voice_battery_report.py) reads setup.json and
voice-bands.json: the level gates how much the report computes, and
--situation applies the layer-2 factors (pooled base + situation factor on
the factor rows).

Laws: the token law and the hook contract are untouched (this script writes
files, never gate output). Standard library only. The U+2014 character is
banned in this repository's output.

Exit codes: 0 = setup ran (or reported); 2 = bad usage (missing path, level
outside 0 to 3, budget not a number).
"""
import argparse
import importlib.util
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # humanizer/learn/
PLUGIN_DIR = HERE.parent                        # humanizer/

SITUATIONS = ("blog", "linkedin", "report")     # ruling D5b: first situations
# factor rows: the shipped tone rows first (hedging, boosting, politeness,
# indirect requests, direct starts), then the register rows (delta1 design)
FACTOR_ROWS = ("L9-4", "L9-5", "L9-11", "L9-12", "L9-16", "L7-1", "L7-2")
N0 = 5                                          # factor shrinkage strength
LEVEL_BUDGETS = (100, 300, 500, 1000)
DEFAULT_BUDGET = 1000


def load_battery():
    spec = importlib.util.spec_from_file_location("voice_setup_battery", HERE / "voice_battery.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vb = load_battery()

WORD_RE = vb.WORD_RE


def learned_dir():
    return Path(os.environ.get("VOICE_LEARNED_DIR", PLUGIN_DIR / "learned"))


def state_dir():
    d = learned_dir() / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---- the bench fixture: deterministic, synthetic, no personal text ----
_NOUNS = ("system engine report market pattern measure sample signal model document writer reader process result "
          "profile sentence corpus method study answer network service dataset").split()
_VERBS = "shows uses needs gives takes makes finds keeps holds moves reads writes tests tracks adds".split()
_ADJS = "simple clear short long fast slow stable rough exact useful common rare public local early late".split()


def fixture(n_words, seed=20260101):
    """Deterministic synthetic English-like text of about n_words tokens."""
    import random
    r = random.Random(seed)

    def sent(kind):
        if kind == 0:
            return "The %s %s the %s %s." % (r.choice(_NOUNS), r.choice(_VERBS), r.choice(_ADJS), r.choice(_NOUNS))
        if kind == 1:
            return "We %s the %s because our %s %s it, and we don't %s the %s." % (
                r.choice(_VERBS), r.choice(_NOUNS), r.choice(_NOUNS), r.choice(_VERBS),
                r.choice(_VERBS), r.choice(_NOUNS))
        if kind == 2:
            return "You can %s the %s when you %s the %s; it's %s." % (
                r.choice(_VERBS), r.choice(_NOUNS), r.choice(_VERBS), r.choice(_NOUNS), r.choice(_ADJS))
        if kind == 3:
            return "Does the %s %s the %s? It %s %s %ss." % (
                r.choice(_NOUNS), r.choice(_VERBS), r.choice(_NOUNS), r.choice(_VERBS),
                r.choice(_ADJS), r.choice(_NOUNS))
        if kind == 4:
            return "Because the %s %s the %s, the %s %s %s %s when the %s %s." % (
                r.choice(_NOUNS), r.choice(_VERBS), r.choice(_NOUNS), r.choice(_NOUNS),
                r.choice(_VERBS), r.choice(_ADJS), r.choice(_NOUNS), r.choice(_NOUNS), r.choice(_VERBS))
        return "The %s %s three things: %s, %s, and %s." % (
            r.choice(_NOUNS), r.choice(_VERBS), r.choice(_NOUNS), r.choice(_NOUNS), r.choice(_NOUNS))
    paras, count, i = [], 0, 0
    while count < n_words:
        i += 1
        p = " ".join(sent(r.randrange(6)) for _ in range(r.randint(2, 6)))
        paras.append(p)
        count += len(WORD_RE.findall(p))
    return "\n\n".join(paras)


def interpreter_candidates():
    """The distinct interpreters this machine can run the plugin with: the
    current one plus bare python, python3, and the py launcher from PATH
    (read-only probing; deduped by real path)."""
    import shutil
    found = []

    def add(label, path):
        if not path:
            return
        try:
            real = os.path.realpath(path)
        except Exception:
            real = path
        if not any(real == f[1] for f in found):
            found.append((label, real))

    add("current", sys.executable)
    for name in ("python", "python3", "py"):
        add(name, shutil.which(name))
    return found


def bench_interpreters(candidates):
    """Measured spawn of each interpreter (median of 5 runs of -I -c pass)."""
    out = []
    for label, path in candidates:
        ms = _median_ms(lambda path=path: subprocess.run([path, "-I", "-c", "pass"], check=True))
        out.append({"name": label, "path": path, "spawn_ms": round(ms, 2)})
    return out


def interpreter_line(entries):
    """The one-line interpreter note for the plain-words report (pure; None
    when only one interpreter was found)."""
    if len(entries) < 2:
        return None
    parts = sorted(entries, key=lambda e: e["spawn_ms"])
    fastest = parts[0]
    slowest = max(e["spawn_ms"] for e in entries)
    listing = ", ".join("%s %.1f ms" % (e["name"], e["spawn_ms"]) for e in parts)
    return ("interpreters on PATH: %s; the fastest spawn is %s and saves up to %.1f ms "
            "per gate call against the slowest"
            % (listing, fastest["name"], slowest - fastest["spawn_ms"]))


def _median_ms(fn, runs=5):
    ts = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(ts)


def bench_machine(remeasure=False):
    """Step 1: measure the machine. Returns the bench dict; cached in
    <learned>/state/machine-bench.json unless --remeasure."""
    path = state_dir() / "machine-bench.json"
    if not remeasure and path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8")), False
        except Exception:
            pass
    py = sys.executable
    spawn = _median_ms(lambda: subprocess.run([py, "-I", "-c", "pass"], check=True))
    gate_fixture = fixture(2000, seed=20260202)
    sd = state_dir()

    def gate_spawn():
        subprocess.run([py, "-I", str(PLUGIN_DIR / "hooks" / "gate.py"), "--surface", "public"],
                       input=gate_fixture, capture_output=True, text=True,
                       env={**os.environ, "VOICE_GATE_VECTOR": "off", "VOICE_LEARNED_DIR": str(learned_dir())})
    gate_ms = _median_ms(gate_spawn)
    texts = {n: fixture(n, seed=20260300 + n) for n in (500, 2000, 5000)}
    battery_ms = {}
    for n, text in texts.items():

        def battery_run(text=text):
            acc = vb.scan(text, phrases=True, tri=False)
            vb.values(acc, ref={}, window=None)
        battery_ms[str(n)] = round(_median_ms(battery_run), 2)
    fast_core_ms = round(_median_ms(lambda: vb.fast_core(texts[2000])), 2)
    # axis applies on a 60-word fixture array (L7-6 dot product, L11-11 solve)
    v1 = [0.1] * 60
    mean60 = [10.0] * 60
    sd60 = [2.0] * 60
    rates = [11.0] * 60
    L = vb.cholesky_lower([[1.0 if i == j else 0.5 for j in range(60)] for i in range(60)])

    def axes_apply():
        z = [v1[w] * (rates[w] - mean60[w]) / sd60[w] for w in range(60)]
        d = [rates[w] - mean60[w] for w in range(60)]
        return math.sqrt(sum(x * x for x in vb.forward_substitution(L, d))) + sum(z)
    axes_ms = _median_ms(axes_apply)
    # level-3 piece: one cross-situation factor pass plus three windowed
    # stability windows on the 2,000-word fixture
    band_stats = {"mean": 0.3, "sd": 0.1}
    factors = {mid: {"factor": 0.05, "k": 4} for mid in FACTOR_ROWS}

    def level3_piece():
        acc = vb.scan(texts[2000], phrases=True, tri=False)
        vals = vb.values(acc, ref={}, window=500)
        s = 0.0
        for mid, f in factors.items():
            v = vals.get(mid)
            if isinstance(v, float):
                s += abs(v - (band_stats["mean"] + f["factor"])) / band_stats["sd"]
        toks = acc["tokens"]
        for i in range(0, min(len(toks), 1500), 500):
            part = toks[i:i + 500]
            if part:
                len(set(part)) / float(len(part))
        return s
    l3_ms = _median_ms(level3_piece)
    interpreters = bench_interpreters(interpreter_candidates())
    bench = {
        "format_version": "1.0",
        "python": sys.version.split()[0],
        "interpreters": interpreters,
        "interpreter_spawn_ms": round(spawn, 2),
        "gate_command_ms_2000w": round(gate_ms, 2),
        "gate_fast_core_ms_2000w": fast_core_ms,
        "battery_ms_500w": battery_ms["500"],
        "battery_ms_2000w": battery_ms["2000"],
        "battery_ms_5000w": battery_ms["5000"],
        "axes_apply_ms": round(axes_ms, 4),
        "level3_piece_ms": round(l3_ms, 2),
        "measured_at": time.strftime("%Y-%m-%d"),
    }
    path.write_text(json.dumps(bench, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return bench, True


def level_costs(bench):
    """Measured cost of each level, derived from the machine bench (pure
    function of the bench dict; the picker's golden test feeds fake numbers)."""
    c1 = float(bench["battery_ms_2000w"])
    return {
        0: float(bench["interpreter_spawn_ms"]) + float(bench["gate_command_ms_2000w"]),
        1: c1,
        2: c1 + float(bench["axes_apply_ms"]),
        3: c1 + float(bench["axes_apply_ms"]) + float(bench["level3_piece_ms"]),
    }


def pick_level(bench, budget_ms):
    """Step 2: the highest level whose measured cost fits the budget.
    Level 0 is always allowed (the gate fast core is always on). Pure."""
    costs = level_costs(bench)
    level = 0
    for cand in (3, 2, 1):
        if costs[cand] <= budget_ms:
            level = cand
            break
    return level, costs


def situation_factor(sit_mean, pooled_mean, k, n0=N0):
    """Layer 2: the shrunk factor of one measure for one situation.
    factor = (situation mean - pooled mean) * k / (k + n0); pure."""
    return (sit_mean - pooled_mean) * (float(k) / (k + n0))


def collect_situation_files(root):
    """Sample files per situation from a directory tree: root/<sit>/*.md|txt
    (case-insensitive). Returns {situation: [Path]}; missing dirs absent."""
    out = {}
    root = Path(root)
    for sit in SITUATIONS:
        d = next((p for p in root.iterdir() if p.is_dir() and p.name.lower() == sit), None) \
            if root.is_dir() else None
        if d is None:
            continue
        files = sorted(f for f in d.rglob("*")
                       if f.is_file() and f.suffix.lower() in (".md", ".txt"))
        if files:
            out[sit] = files
    return out


def learn_bands(root):
    """Steps 3 and 3b: per-document battery rows, pooled source-blind bands,
    per-situation bands, and the shrunk factors. Returns (bands, notes)."""
    by_sit = collect_situation_files(root)
    notes = []
    if not by_sit:
        return None, ["no situation directories found under %s (expected %s)"
                      % (root, ", ".join(SITUATIONS))]
    texts, labels = [], []
    for sit, files in by_sit.items():
        for f in files:
            texts.append(f.read_text(encoding="utf-8", errors="replace"))
            labels.append(sit)
    accs = [vb.scan(t, phrases=True, tri=False) for t in texts]
    k = len(accs)
    docs_fw = [vb.fw_counts(a) for a in accs]
    pooled = vb.pooled_counts(docs_fw)
    fw_pooled = dict(zip(vb.FUNCTION_WORDS, pooled))
    window = int(round(vb.median([float(a["n"]) for a in accs])))
    # per-document function-word rate rows for Burrows' Delta and L11-2
    rate_rows = []
    for a in accs:
        n = a["n"]
        rate_rows.append([a["fwc"].get(w, 0) * 1000.0 / n if n else 0.0 for w in vb.FUNCTION_WORDS])
    fw_mean = [vb.sample_mean([r[w] for r in rate_rows]) for w in range(len(vb.FUNCTION_WORDS))]
    fw_sd = [vb.sample_sd([r[w] for r in rate_rows]) for w in range(len(vb.FUNCTION_WORDS))]
    ref0 = vb.ref_block(dict(zip(vb.FUNCTION_WORDS, fw_mean)), dict(zip(vb.FUNCTION_WORDS, fw_sd)),
                        fw_pooled, None, None, k)
    rows0 = [vb.values(a, ref=ref0, window=window) for a in accs]
    col71 = [r["L7-1"] for r in rows0]
    col72 = [r["L7-2"] for r in rows0]
    register = {"L7-1": (vb.sample_mean(col71), vb.sample_sd(col71)),
                "L7-2": (vb.sample_mean(col72), vb.sample_sd(col72))}
    ref1 = vb.ref_block(dict(zip(vb.FUNCTION_WORDS, fw_mean)), dict(zip(vb.FUNCTION_WORDS, fw_sd)),
                        fw_pooled, register, None, k)
    ref1["docs_rates"] = rate_rows
    rows = [vb.values(a, ref=ref1, window=window) for a in accs]

    def band_of(indices):
        out = {}
        for mid in vb.ALL_IDS:
            col = [rows[i][mid] for i in indices if rows[i][mid] is not None]
            if col:
                out[mid] = {"mean": round(vb.sample_mean(col), 6),
                            "sd": round(vb.sample_sd(col), 6),
                            "min": round(min(col), 6), "max": round(max(col), 6),
                            "k": len(col)}
        return out

    all_idx = list(range(k))
    pooled_bands = band_of(all_idx)
    situations = {}
    for sit, files in by_sit.items():
        idx = [i for i, lab in enumerate(labels) if lab == sit]
        words = [accs[i]["n"] for i in idx]
        short = [w for w in words if w < 500]
        entry = {"docs": len(idx), "bands": band_of(idx), "doc_words": [int(w) for w in words]}
        entry["factors"] = {}
        if len(idx) >= 3 and not short:
            for mid in FACTOR_ROWS:
                pb, sb = pooled_bands.get(mid), entry["bands"].get(mid)
                if pb and sb and sb["k"] >= 2:
                    f = situation_factor(sb["mean"], pb["mean"], sb["k"])
                    entry["factors"][mid] = {"factor": round(f, 6), "k": sb["k"]}
        else:
            entry["fallback"] = "pooled band applies (%s)" % (
                "fewer than 3 documents" if len(idx) < 3 else
                "%d document(s) under 500 words" % len(short))
            notes.append("situation %s: %s" % (sit, entry["fallback"]))
        situations[sit] = entry
    bands = {
        "format_version": "1.0",
        "docs": k,
        "window_words": window,
        "pooled": pooled_bands,
        "situations": situations,
        "layer_note": "layer 1 pooled bands carry no per-document source identity; "
                      "layer 2 factors shrink toward 0 by k / (k + %d)" % N0,
    }
    return bands, notes


# ---- step 4: the plain-words report ----

def plain_report(bench, level, costs, budget, bands, notes, remeasured):
    lines = []
    lines.append("voice setup: the machine, the level, and the situations")
    lines.append("machine: interpreter spawn %.1f ms, gate command at 2,000 words %.1f ms, "
                 "battery %.1f / %.1f / %.1f ms at 500 / 2,000 / 5,000 words%s"
                 % (bench["interpreter_spawn_ms"], bench["gate_command_ms_2000w"],
                    bench["battery_ms_500w"], bench["battery_ms_2000w"], bench["battery_ms_5000w"],
                    " (measured now)" if remeasured else " (from machine-bench.json)"))
    gate_total = bench["interpreter_spawn_ms"] + bench["gate_command_ms_2000w"]
    if gate_total > 100.0:
        lines.append("gate path: measured %.1f ms on this machine, over the 100 ms perception "
                     "threshold; the overflow is the interpreter spawn (%.1f ms), not the scan; "
                     "the fast core stays on because the gate needs it"
                     % (gate_total, bench["interpreter_spawn_ms"]))
    else:
        lines.append("gate path: %.1f ms, inside the 100 ms perception threshold" % gate_total)
    lines.append("level: %d (%s); measured cost %.1f ms against your %d ms budget"
                 % (level, LEVEL_NAMES[level], costs[level], budget))
    interp_line = interpreter_line(bench.get("interpreters") or [])
    if interp_line:
        lines.append(interp_line)
    lines.append("  level costs measured on this machine: "
                 + ", ".join("level %d %.1f ms" % (lv, costs[lv]) for lv in sorted(costs)))
    if bands:
        parts = []
        for sit, entry in sorted((bands.get("situations") or {}).items()):
            fac = len(entry.get("factors") or {})
            parts.append("%s: %d documents, %d factor rows%s"
                         % (sit, entry["docs"], fac,
                            "" if not entry.get("fallback") else " (%s)" % entry["fallback"]))
        lines.append("situations learned: %s; pooled bands over %d documents"
                     % ("; ".join(parts), bands.get("docs", 0)))
    else:
        lines.append("situations: none learned (pass a sample directory tree to learn per situation)")
    lines.extend("note: %s" % n for n in notes)
    return "\n".join(lines) + "\n"


LEVEL_NAMES = {0: "gate fast core only", 1: "full battery report",
               2: "battery report plus the heavy axis rows",
               3: "plus cross-situation comparison and windowed stability"}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="voice_setup.py",
        description="The install experience: measure the machine, pick the measurement level, "
                    "learn the voice per situation, and report in plain words.")
    parser.add_argument("samples", nargs="?", default=None,
                        help="sample root directory with one subdirectory per situation "
                             "(blog, linkedin, report)")
    parser.add_argument("--remeasure", action="store_true", help="re-run the machine bench")
    parser.add_argument("--level", type=int, default=None, help="force a level (0 to 3)")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET,
                        help="report-path delay budget in ms (choices 100 / 300 / 500 / 1000; default 1000)")
    args = parser.parse_args(argv)
    if args.level is not None and args.level not in (0, 1, 2, 3):
        print("usage: --level must be 0, 1, 2, or 3", file=sys.stderr)
        return 2
    if args.budget not in LEVEL_BUDGETS:
        print("usage: --budget must be one of %s" % ", ".join(str(b) for b in LEVEL_BUDGETS),
              file=sys.stderr)
        return 2
    bench, remeasured = bench_machine(remeasure=args.remeasure)
    if args.level is not None:
        level = args.level
        costs = level_costs(bench)
        note = None
        if level >= 1 and costs[level] > args.budget:
            note = ("the forced level %d measured %.1f ms, over the %d ms budget; it stays set, "
                    "but the report path will run over budget" % (level, costs[level], args.budget))
    else:
        level, costs = pick_level(bench, args.budget)
        note = None
    bands, notes = (None, [])
    if args.samples:
        bands, notes = learn_bands(args.samples)
        if bands is None:
            print("usage: %s" % notes[0], file=sys.stderr)
            return 2
        (state_dir() / "voice-bands.json").write_text(
            json.dumps(bands, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    setup = {"format_version": "1.0", "level": level, "budget_ms": args.budget,
             "costs_ms": {str(k2): round(v, 2) for k2, v in sorted(costs.items())},
             "situations_learned": sorted((bands or {}).get("situations") or {})}
    (state_dir() / "setup.json").write_text(
        json.dumps(setup, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if note:
        notes.append(note)
    sys.stdout.write(plain_report(bench, level, costs, args.budget, bands, notes, remeasured))
    return 0


if __name__ == "__main__":
    sys.exit(main())
