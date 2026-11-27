#!/usr/bin/env python3
"""build_voice_profile.py: deterministic voice-profile builder (zero LLM).

Reads the user's real writing samples (.md/.txt files or directories), computes
surface statistics, writes learned/profile.json, and prints a human-readable
pre-fill draft of the onboarding template's sections 2 (voice DNA), 3 (reader)
and 5 (hard rules) for the user to confirm or correct BY HAND. The draft is an
input to the onboarding conversation, never a replacement for it.

No network access and no model calls: every number is string arithmetic over
the samples. Deterministic: identical inputs produce identical output (every
ordering is count-descending then lexicographic; ties never depend on
iteration order).

Measured values in learned/profile.json:
- sentence_length: mean / median / p95 words per sentence
- paragraph_sentences: mean / median / max sentences per paragraph
- punctuation_per_1000_words: frequency table for . , ; : ? ! em dash -- ( )
- top_ngrams: top content n-grams (1, 2 and 3 words, stopword-filtered)
- openers: most frequent first two words of a sentence
- passive_sentence_share: share of sentences with a passive-voice marker
- intensifiers_per_100_words: vague-intensifier density
- function_words (v1.1.0, issue #127 Tier 3): per-document frequency profile of
  ~60 hardcoded English function words (unit: per-1000-words; per-document
  mean + stddev across the samples). This is the Burrows' Delta reference
  profile consumed by learn/acceptance_check.py --backend delta.
- gate_pattern_hits: per-label hit counts and per-1000-sentence rates from the
  hooks/voice_tells.py regex layer (the machine register)
- battery (v1.2.0, the 74-measure Tier A battery of learn/voice_battery.py):
  run over each sample document. Per measure: mean, sample deviation
  (divide by k - 1), minimum, maximum, and the document count k that has a
  reading. Plus the pooled reference rows the report path reads (function-
  word counts per document and pooled, document word counts, the window
  size for the length-sensitive rows), the per-level holdout outside counts
  (map 4.7), and the leave-one-out distance vector for the rank rule
  (map 4.5). This is the measure-once / apply-cheap core: the report path
  reads bands from here instead of re-measuring the samples.

Exit codes: 0 = profile written (or the defined empty-input case: a clear
message, no file written); 2 = bad arguments (missing path).
"""
import argparse
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # humanizer/learn/
PLUGIN_DIR = HERE.parent                        # humanizer/
DEFAULT_OUT = PLUGIN_DIR / "learned" / "profile.json"

STOPWORDS = frozenset("""a an the and or but nor so yet if then than that this these those there
here of in on at by for with from to into over under between against before after during
is are was were be been being am do does did have has had will would can could should may
might must not no nor as it its it's they them their you your we our us he she his her
i me my mine what which who whom whose when where why how all any both each few more most
other some such only own same too very just also about above below up down out off again
once because while until unless since after before""".split())

WORD_RE = re.compile(r"[A-Za-z0-9']+", re.UNICODE)
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
PASSIVE_RE = re.compile(r"\b(is|are|was|were|be|been|being)\s+\w+(?:ed|en)\b", re.IGNORECASE)
INTENSIFIER_RE = re.compile(r"\b(very|really|basically|actually|literally|definitely|certainly)\b", re.IGNORECASE)
PUNCT_MARKS = [(".", "period"), (",", "comma"), (";", "semicolon"), (":", "colon"),
               ("?", "question"), ("!", "exclamation"), ("\u2014", "em dash"),
               ("--", "double hyphen"), ("(", "open paren"), (")", "close paren")]

# The ~60 hardcoded English function words of the Burrows' Delta profile
# (issue #127 Tier 3). Exactly 60 entries; the single source of truth shared
# with learn/acceptance_check.py (which imports this list).
FUNCTION_WORDS = (
    "the of and a to in is you that it he was for on are as with his they i "
    "at be this have from or one had by word but not what all were we when "
    "your can said there use an each which she do how their if will up other "
    "about out many then them these so"
).split()


def load_voice_tells():
    """Load hooks/voice_tells.py (the shared detection core) from its plugin
    location. Returns the module or None when it cannot be imported (the
    profile is still written, without the gate-pattern section)."""
    try:
        spec = importlib.util.spec_from_file_location(
            "voice_tells_profile", HERE.parent / "hooks" / "voice_tells.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        print(f"note: gate pattern layer unavailable ({e!r}); profile carries surface stats only",
              file=sys.stderr)
        return None


def collect_files(paths):
    """Expand CLI arguments to a deterministic, sorted list of .md/.txt files.
    A missing path raises SystemExit(2) with a clear message; a present path
    with no readable samples contributes nothing (the empty-input case)."""
    files = []
    for arg in paths:
        p = Path(arg).expanduser()
        if not p.exists():
            print(f"missing path: {p}", file=sys.stderr)
            raise SystemExit(2)
        if p.is_file():
            if p.suffix.lower() in (".md", ".txt"):
                files.append(p)
        else:
            for cand in sorted(p.rglob("*")):
                if cand.is_file() and cand.suffix.lower() in (".md", ".txt"):
                    files.append(cand)
    seen, out = set(), []
    for f in sorted(files):  # dedupe overlapping args, keep a stable order
        key = str(f.resolve())
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def split_paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def sentences_of(para):
    return [s for s in SENT_SPLIT.split(para.strip()) if s.strip()]


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return 0.0
    mid = n // 2
    return float(xs[mid]) if n % 2 else (xs[mid - 1] + xs[mid]) / 2.0


def percentile(xs, frac):
    xs = sorted(xs)
    if not xs:
        return 0.0
    idx = min(len(xs) - 1, max(0, math.ceil(frac * len(xs)) - 1))
    return float(xs[idx])


def top_counts(counter, limit):
    """Deterministic ranking: count desc, then key asc."""
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def analyze(files):
    """Single deterministic pass over all samples; returns the stats dict."""
    paras, sents = [], []
    words_total = 0
    punct = {name: 0 for _, name in PUNCT_MARKS}
    fw_rows = []  # per-document function-word frequency rows (Burrows' Delta profile)
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for mark, name in PUNCT_MARKS:
            punct[name] += text.count(mark)
        doc_words = [w.lower() for w in WORD_RE.findall(text)]
        counts = {w: 0 for w in FUNCTION_WORDS}
        for w in doc_words:
            if w in counts:
                counts[w] += 1
        base = len(doc_words)
        fw_rows.append({w: counts[w] * 1000.0 / base if base else 0.0 for w in FUNCTION_WORDS})
        for para in split_paragraphs(text):
            paras.append(para)
            for s in sentences_of(para):
                sents.append(s)
                words_total += len(WORD_RE.findall(s))
    sent_lens = [len(WORD_RE.findall(s)) for s in sents]
    para_counts = [len(sentences_of(p)) for p in paras]

    ngrams = {1: {}, 2: {}, 3: {}}
    openers = {}
    passive = 0
    intensifiers = 0
    you_hits = 0
    for s in sents:
        words = [w.lower() for w in WORD_RE.findall(s)]
        if words:
            openers[" ".join(words[:2])] = openers.get(" ".join(words[:2]), 0) + 1
        content = [w for w in words if w not in STOPWORDS]
        for n in (1, 2, 3):
            for i in range(len(content) - n + 1):
                gram = " ".join(content[i:i + n])
                ngrams[n][gram] = ngrams[n].get(gram, 0) + 1
        if PASSIVE_RE.search(s):
            passive += 1
        intensifiers += len(INTENSIFIER_RE.findall(s))
        if re.search(r"\b(you|your)\b", s, re.IGNORECASE):
            you_hits += 1

    stats = {
        "files": len(files),
        "paragraphs": len(paras),
        "sentences": len(sents),
        "words": words_total,
        "sentence_length": {
            "mean": round(sum(sent_lens) / len(sent_lens), 2) if sent_lens else 0.0,
            "median": round(median(sent_lens), 2),
            "p95": round(percentile(sent_lens, 0.95), 2),
        },
        "paragraph_sentences": {
            "mean": round(sum(para_counts) / len(para_counts), 2) if para_counts else 0.0,
            "median": round(median(para_counts), 2),
            "max": max(para_counts) if para_counts else 0,
        },
        "punctuation_per_1000_words": {
            name: round(count * 1000.0 / words_total, 2) if words_total else 0.0
            for name, count in punct.items()},
        "top_ngrams": {str(n): [[g, c] for g, c in top_counts(ngrams[n], 10)] for n in (1, 2, 3)},
        "openers": [[o, c] for o, c in top_counts(openers, 10)],
        "passive_sentence_share": round(passive / len(sents), 3) if sents else 0.0,
        "intensifiers_per_100_words": round(intensifiers * 100.0 / words_total, 2) if words_total else 0.0,
        "reader_address_share": round(you_hits / len(sents), 3) if sents else 0.0,
        "function_words": function_word_profile(fw_rows),
    }
    return stats, sents, fw_rows


def function_word_profile(fw_rows):
    """Burrows' Delta reference profile: per-word mean + sample stddev of
    the per-1000-words frequencies across the sample documents (divide by
    k - 1, AM-04: the population stddev makes every document score exactly
    1.0 at k = 2 and changes the unit with k). A word constant across
    documents has stddev 0 and contributes 0 to a candidate's Delta; one
    document alone carries no spread (stddev 0 everywhere)."""
    n = len(fw_rows)
    if not n:
        return {"unit": "per-1000-words", "docs": 0, "words": list(FUNCTION_WORDS),
                "mean": {}, "stddev": {}}
    mean = {w: sum(row[w] for row in fw_rows) / n for w in FUNCTION_WORDS}
    if n > 1:
        stddev = {w: math.sqrt(sum((row[w] - mean[w]) ** 2 for row in fw_rows) / (n - 1))
                  for w in FUNCTION_WORDS}
    else:
        stddev = {w: 0.0 for w in FUNCTION_WORDS}
    return {"unit": "per-1000-words", "docs": n, "words": list(FUNCTION_WORDS),
            "mean": {w: round(v, 6) for w, v in mean.items()},
            "stddev": {w: round(v, 6) for w, v in stddev.items()}}


def load_battery():
    """Load learn/voice_battery.py (the 74-measure Tier A battery) from its
    plugin location. Returns the module or None when it cannot be imported
    (the profile is still written, without the battery section)."""
    try:
        spec = importlib.util.spec_from_file_location(
            "voice_battery_profile", HERE / "voice_battery.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        print(f"note: battery layer unavailable ({e!r}); profile carries surface stats only",
              file=sys.stderr)
        return None


def battery_block(texts, fw_profile, fw_rows):
    """Run the battery over each sample document and build the profile's
    battery section: per-measure mean, sample deviation, minimum, maximum,
    and the document count k with a reading (the measure-once / apply-cheap
    core), plus the reference rows, the per-level holdout outside counts
    (map 4.7), and the leave-one-out distance vector for the rank rule
    (map 4.5). Returns (block_or_None, pca_out_or_None, chol_out_or_None):
    the two side payloads are the delta1 reference-derived axes (L7-6 PCA,
    L11-11 full-covariance Delta), user-local R3 data that the caller writes
    beside the profile; nothing ships."""
    vb = load_battery()
    if vb is None or not texts:
        return None, None, None
    accs = [vb.scan(t, phrases=True, tri=True) for t in texts]
    k = len(accs)
    docs_fw = [vb.fw_counts(a) for a in accs]
    pooled = vb.pooled_counts(docs_fw)
    fw_pooled = dict(zip(vb.FUNCTION_WORDS, pooled))
    tri_pooled = vb.tri_merge([a["tri"] for a in accs])
    window = int(round(vb.median([float(a["n"]) for a in accs])))
    mean, sd = fw_profile["mean"], fw_profile["stddev"]

    # base matrix (stored bands); one extra pass carries the register stats
    def _reg_pair(col):
        vals = [v for v in col if v is not None]
        return (vb.sample_mean(vals), vb.sample_sd(vals)) if len(vals) >= 2 else None

    rate_rows = [[row[w] for w in FUNCTION_WORDS] for row in fw_rows]
    # the reference-derived axes (delta1 L7-6, L11-11): R3, user-local,
    # rebuilt by this command, never shipped. PCA needs 5 or more documents;
    # the Cholesky solve needs a positive variance on every word (the
    # shrinkage keeps it stable below k = 61). Fail-open: an unstable solve
    # means no file and the rows read n/a.
    pca_out = chol_out = None
    pca_ref = chol_ref = None
    if k >= 5:
        try:
            v1, pmean, psd, projs = vb.first_pca(rate_rows)
            pca_out = {
                "format_version": "1.0", "words": list(FUNCTION_WORDS),
                "mean": [round(x, 6) for x in pmean], "sd": [round(x, 6) for x in psd],
                "v1": [round(x, 6) for x in v1],
                "proj_mean": round(vb.sample_mean(projs), 6),
                "proj_sd": round(vb.sample_sd(projs), 6),
                "k": k,
            }
            pca_ref = {"v1": list(v1), "mean": list(pmean), "sd": list(psd)}
        except Exception as e:
            print(f"note: PCA projection skipped ({e!r})", file=sys.stderr)
    if k >= 2:
        try:
            # words with zero cross-document variance carry no distance
            # information and would break the positive-definite solve, so
            # they drop out (the delta1 variance-reduction design); the
            # stored words list names the set that the solve covers
            sds = [vb.sample_sd([row[w] for row in rate_rows]) for w in range(len(FUNCTION_WORDS))]
            kept = [w for w in range(len(FUNCTION_WORDS)) if sds[w] > 0]
            if len(kept) >= 2:
                sub_rows = [[row[w] for w in kept] for row in rate_rows]
                S, cmean = vb.shrunk_covariance(sub_rows, alpha=0.1)
                L = vb.cholesky_lower(S)
                loo_d = []
                for i, row in enumerate(sub_rows):
                    rest = sub_rows[:i] + sub_rows[i + 1:]
                    lmean = [vb.sample_mean([r[j] for r in rest]) for j in range(len(kept))]
                    d = [row[j] - lmean[j] for j in range(len(kept))]
                    loo_d.append(math.sqrt(sum(x * x for x in vb.forward_substitution(L, d))))
                chol_out = {
                    "format_version": "1.0",
                    "words": [FUNCTION_WORDS[w] for w in kept],
                    "mean": [round(x, 6) for x in cmean],
                    "chol_lower": [[round(x, 6) for x in L[i][:i + 1]] for i in range(len(kept))],
                    "alpha": 0.1, "k": k,
                    "band": {"mean": round(vb.sample_mean(loo_d), 6),
                             "sd": round(vb.sample_sd(loo_d), 6),
                             "distances": [round(x, 6) for x in loo_d]},
                }
                chol_ref = {"words": [FUNCTION_WORDS[w] for w in kept],
                            "mean": list(cmean), "chol_lower": L}
        except Exception as e:
            print(f"note: full-covariance Delta skipped ({e!r})", file=sys.stderr)

    ref0 = vb.ref_block(mean, sd, fw_pooled, None, tri_pooled, k)
    rows0 = [vb.values(a, ref=ref0, window=window) for a in accs]
    col71 = [r["L7-1"] for r in rows0]
    col72 = [r["L7-2"] for r in rows0]
    register = {}
    pair71, pair72 = _reg_pair(col71), _reg_pair(col72)
    if pair71:
        register["L7-1"] = pair71
        register["range"] = pair71[1]
    if pair72:
        register["L7-2"] = pair72
    ref1 = vb.ref_block(mean, sd, fw_pooled, register, tri_pooled, k)
    ref1["docs_rates"] = rate_rows
    if pca_ref:
        ref1["pca"] = pca_ref
    if chol_ref:
        ref1["chol"] = chol_ref
    rows = [vb.values(a, ref=ref1, window=window) for a in accs]

    measures = {}
    for mid in vb.ALL_IDS:
        col = [r[mid] for r in rows if r[mid] is not None]
        if col:
            measures[mid] = {"mean": round(vb.sample_mean(col), 6),
                             "sd": round(vb.sample_sd(col), 6),
                             "min": round(min(col), 6), "max": round(max(col), 6),
                             "k": len(col)}

    # variability rows L10-16 / L10-17 (delta4): sentence-aligned
    # pseudo-documents, the fixed 20-feature vector, the reference
    # reductions, and the B=200 size-matched split null with the recorded
    # seed. R3 user-local, rebuilt by this command, never shipped. Below the
    # minimum pool (5 documents, 50 segments) the object stores
    # status: insufficient_reference.
    seg_rows_raw, seg_labels, per_doc_segs = [], [], []
    for i, t in enumerate(texts):
        for seg_sents in vb.variability_segments(t):
            seg_text = " ".join(seg_sents)
            a_seg = vb.scan(seg_text, phrases=False, tri=False)
            v_seg = vb.values(a_seg, ref={}, window=None)
            seg_rows_raw.append(vb.var_feature_vector(a_seg, v_seg))
            per_doc_segs.append(i)
    n_seg = len(seg_rows_raw)
    k_docs = len(texts)
    variability = {
        "features": list(vb.VAR_FEATURE_ROWS) + ["contraction_rate", "sentence_length_sd"],
        "seed": vb.VAR_SEED, "splits": vb.VAR_SPLITS,
        "k_docs": k_docs, "n_seg": n_seg,
        "segment_words": vb.VAR_SEGMENT_WORDS,
    }
    if k_docs < vb.VAR_MIN_REF_DOCS or n_seg < vb.VAR_MIN_REF_SEGS:
        variability["status"] = "insufficient_reference"
    else:
        ref_mean = [vb.sample_mean([r[w] for r in seg_rows_raw]) for w in range(20)]
        ref_sd = [vb.sample_sd([r[w] for r in seg_rows_raw]) for w in range(20)]
        z_rows = [[(r[w] - ref_mean[w]) / ref_sd[w] if ref_sd[w] > 0 else 0.0
                   for w in range(20)] for r in seg_rows_raw]
        null = vb.var_null(z_rows, seg_rows_raw)
        sl_ref_sd, ss_ref_sd = vb.var_reduction(seg_rows_raw)
        v_ref = vb.var_v(z_rows)
        variability.update({
            "ref_mean": [round(x, 6) for x in ref_mean],
            "ref_sd": [round(x, 6) for x in ref_sd],
            "v_ref": round(v_ref, 6) if v_ref is not None else None,
            "sl_ratio_ref_sd": round(sl_ref_sd, 6),
            "intra_ref_sd_of_sd": round(ss_ref_sd, 6),
            "status": "ok",
        })
        if null:
            variability.update({
                "v_ci_lo": round(null["v_lo"], 6), "v_ci_hi": round(null["v_hi"], 6),
                "sl_ci_lo": round(null.get("sl_lo", 0.0), 6),
                "sl_ci_hi": round(null.get("sl_hi", 0.0), 6),
                "ss_ci_lo": round(null.get("ss_lo", 0.0), 6),
                "ss_ci_hi": round(null.get("ss_hi", 0.0), 6),
            })

    # holdout matrix (map 4.5 rank rule and map 4.7 level outside counts):
    # each document measured against the other documents' own reference rows.
    # The rank rule needs 3 or more documents and the holdout bands need a
    # t value at k - 1, so a smaller corpus stores no holdout at all.
    hold_rows = []
    d_vec = []
    for i in range(k if k >= 3 else 0):
        loo_fw = dict(zip(vb.FUNCTION_WORDS, [pooled[j] - docs_fw[i][j]
                                              for j in range(len(vb.FUNCTION_WORDS))]))
        loo_tri = dict(tri_pooled)
        for g, c in accs[i]["tri"].items():
            loo_tri[g] -= c
        loo_rows = fw_rows[:i] + fw_rows[i + 1:]
        loo_mean = {w: sum(r[w] for r in loo_rows) / len(loo_rows) for w in FUNCTION_WORDS}
        loo_sd = {w: vb.sample_sd([r[w] for r in loo_rows]) for w in FUNCTION_WORDS}
        loo71 = col71[:i] + col71[i + 1:]
        loo72 = col72[:i] + col72[i + 1:]
        reg_loo = {}
        pair71, pair72 = _reg_pair(loo71), _reg_pair(loo72)
        if pair71:
            reg_loo["L7-1"] = pair71
            reg_loo["range"] = pair71[1]
        if pair72:
            reg_loo["L7-2"] = pair72
        ref_loo = vb.ref_block(loo_mean, loo_sd, loo_fw, reg_loo, loo_tri, k - 1)
        hrow = vb.values(accs[i], ref=ref_loo, window=window)
        hold_rows.append(hrow)
        d_vec.append(hrow["L11-4"])

    levels_holdout = {}
    t_hold = vb.t_value(k - 1)
    if t_hold is not None and k > 1:
        factor = math.sqrt(1.0 + 1.0 / (k - 1))
        per_doc = [dict((lv, 0) for lv in vb.LEVELS) for _ in range(k)]
        for i in range(k):
            others = [hold_rows[j] for j in range(k) if j != i]
            for mid in vb.ALL_IDS:
                v = hold_rows[i][mid]
                if v is None:
                    continue
                col = [o[mid] for o in others if o[mid] is not None]
                if len(col) < 3:
                    continue
                mu = vb.sample_mean(col)
                s = vb.sample_sd(col)
                if s <= 0:
                    continue
                if abs((v - mu) / (s * factor)) > t_hold:
                    per_doc[i][vb.SPEC[mid][0]] += 1
        for lv in vb.LEVELS:
            levels_holdout[lv] = max(p[lv] for p in per_doc)

    rank = None
    if k >= 3 and all(d is not None for d in d_vec):
        rank = {"measure": "L11-4", "d": [round(d, 6) for d in d_vec]}

    return {
        "docs": k,
        "window_words": window,
        "measures": measures,
        "levels_holdout": levels_holdout,
        "rank": rank,
        "variability": variability,
        "measure_set": vb.BATTERY_VERSION,
        "reference": {
            "fw_pooled": [int(c) for c in pooled],
            "docs_fw": [[int(c) for c in row] for row in docs_fw],
            "docs_words": [int(a["n"]) for a in accs],
            "total_words": int(sum(a["n"] for a in accs)),
        },
    }, pca_out, chol_out


def gate_pattern_hits(sents, vt):
    """Per-label hit counts and rates from the voice_tells regex layer.
    Only patterns that fired are listed; patterns_checked carries the total."""
    if vt is None or not sents:
        return {"patterns_checked": 0, "fired": {}}
    eff = vt.effective_rules()
    compiled = [(re.compile(rx, re.IGNORECASE), label) for rx, label in eff["patterns"]]
    counts = {}
    for s in sents:
        for _rx, label in compiled:
            if _rx.search(s):
                counts[label] = counts.get(label, 0) + 1
    n = len(sents)
    fired = {label: {"hits": c, "per_1k_sentences": round(c * 1000.0 / n, 2)}
             for label, c in top_counts(counts, len(counts))}
    return {"patterns_checked": len(compiled), "fired": fired}


def describe_rhythm(sl):
    """Plain-language rhythm line derived from the median and p95 sentence
    length. Thresholds are fixed so the wording is deterministic."""
    med, p95 = sl["median"], sl["p95"]
    if med <= 12 and p95 <= 25:
        return f"short declarative core (median sentence {med} words, p95 {p95}); long sentences are rare"
    if med <= 20:
        return f"mixed rhythm: short evidence sentences carry the piece, p95 reaches {p95} words"
    return f"long-form rhythm (median sentence {med} words, p95 {p95}); split the longest sentences"


def draft_sections(stats, hits):
    """Human-readable pre-fill of onboarding template sections 2, 3 and 5.
    Every line ends with the data it came from; the user confirms by hand."""
    sl, ps = stats["sentence_length"], stats["paragraph_sentences"]
    punct = stats["punctuation_per_1000_words"]
    grams2 = ", ".join(g for g, _c in stats["top_ngrams"]["2"][:5]) or "(none recurring)"
    grams3 = ", ".join(g for g, _c in stats["top_ngrams"]["3"][:5]) or "(none recurring)"
    openers = ", ".join(f'"{o}"' for o, _c in stats["openers"][:4]) or "(no repeated opener)"

    lines = []
    lines.append("## 2. Voice DNA (draft from your samples; confirm or rewrite by hand)")
    lines.append(f"1. Rhythm: {describe_rhythm(sl)}.")
    lines.append(f"2. Paragraph shape: median {ps['median']} sentences per paragraph, longest {ps['max']}.")
    lines.append(f"3. Punctuation habits: semicolons {punct['semicolon']} per 1000 words, "
                 f"colons {punct['colon']}, questions {punct['question']}, "
                 f"em dashes {punct['em dash']}, exclamations {punct['exclamation']}.")
    lines.append(f"4. Sentences often open with: {openers}.")
    lines.append(f"5. Recurring two-word phrases: {grams2}. Longer runs: {grams3}.")
    lines.append("(Name the influences, register and temperament yourself; the numbers only describe the surface.)")
    lines.append("")
    lines.append("## 3. Reader (draft cues; fill the rest by hand)")
    lines.append(f"- Direct address: {stats['reader_address_share'] * 100:.0f}% of sentences use you/your "
                 f"({'write toward a named reader' if stats['reader_address_share'] >= 0.05 else 'mostly third-person; name who reads this'}).")
    lines.append(f"- Question budget: {punct['question']} questions per 1000 words "
                 f"({'questions are part of the voice' if punct['question'] >= 1 else 'questions are rare; close statements, not questions'}).")
    lines.append("- Who reads this: <FILL>")
    lines.append("- What every piece should change for the reader: <FILL>")
    lines.append("")
    lines.append("## 5. Hard rules (draft bans from your samples; confirm each by hand)")
    bans = []
    if punct["em dash"] > 0:
        bans.append("no em dash U+2014 (it appears in your samples)")
    if stats["intensifiers_per_100_words"] >= 1.0:
        bans.append(f"no vague intensifiers (very/really/...; {stats['intensifiers_per_100_words']} per 100 words in your samples)")
    if stats["passive_sentence_share"] >= 0.25:
        bans.append(f"rewrite passive clauses active ({stats['passive_sentence_share'] * 100:.0f}% of your sentences carry a passive marker)")
    for label, d in hits.get("fired", {}).items():
        if d["per_1k_sentences"] >= 5.0:
            base = label.split(" (")[0].lower()
            if base == "em dash (u+2014)" or base.startswith("em dash"):
                continue  # already covered by the em-dash ban above
            bans.append(f"no {label.split(' (')[0]} ({d['per_1k_sentences']} hits per 1000 sentences in clean prose)")
    if not bans:
        bans.append("no em dash U+2014")
    bans.append("no fabricated numbers, sources, or quotes; every claim carries evidence, mechanism, or a labeled first-person observation")
    for b in bans:
        lines.append(f"- {b}")
    lines.append("(Add the bans that matter to you; delete draft lines your voice deliberately keeps.)")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("samples", nargs="+", help="sample files or directories (.md/.txt)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="profile JSON path (default: the plugin's learned/profile.json)")
    a = ap.parse_args()
    files = collect_files(a.samples)
    if not files:
        print("no readable .md/.txt samples in the given paths; nothing profiled (write the onboarding template by hand)")
        return 0
    stats, sents, fw_rows = analyze(files)
    vt = load_voice_tells()
    stats["gate_pattern_hits"] = gate_pattern_hits(sents, vt)
    block, pca_out, chol_out = battery_block(
        [f.read_text(encoding="utf-8", errors="replace") for f in files],
        stats["function_words"], fw_rows)
    if block is not None:
        stats["battery"] = block
    out = Path(a.out).expanduser()
    if out.parent and str(out.parent):
        out.parent.mkdir(parents=True, exist_ok=True)
    for payload, suffix in ((pca_out, "-pca.json"), (chol_out, "-covariance.json")):
        if payload:
            side = out.with_name(out.stem + suffix)
            side.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out.write_text(json.dumps(_ordered_profile(stats, files), indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(draft_sections(stats, stats["gate_pattern_hits"]))
    print(f"\nprofile written: {out} ({stats['files']} files, {stats['sentences']} sentences, "
          f"{stats['words']} words)")
    return 0


def _ordered_profile(stats, files):
    """Profile payload: stats plus provenance of the samples (paths, resolved)."""
    profile = dict(stats)
    profile["samples"] = sorted(str(f) for f in files)
    return profile


if __name__ == "__main__":
    sys.exit(main())
