#!/usr/bin/env python3
"""voice_battery_report.py: the on-demand gestalt report of the measurement
battery (map section 6; the /voice-fit command surface).

One block per level L1 to L11. Each block opens with one line: the measures
with a reading, the inside / near the edge / outside counts, and the level
band. Each measure row carries five parts: identifier and name; the observed
value with its unit; the reference band with the seen range; the band
verdict; and one reading sentence that names the edit class. Rows outside
the band print first, then near the edge, then inside; rows with the same
verdict keep identifier order, so the first rows are the edits that matter
most. The last two lines give the overall band and the length confidence
note. The report is plain text. It has no decimal fit score (a decimal such
as "fit 0.73" suggests a precision the band does not have).

Bands (map sections 4.1, 4.2, 4.8) come from the user's own profile
(learned/profile.json, battery section, written by build_voice_profile.py).
No public norm exists: L11 rows and every band read the user's profile.
- Measure band: z = (c - mean) / (s_eff * sqrt(1 + 1/k)) with the sample
  deviation and the count floor s_eff = sqrt(s^2 + floor); inside when
  |z| <= t(0.975, k - 1), near the edge up to 1.5 t, outside beyond.
  A measure whose own interval is wider than one half of the band gets the
  mark "short" in place of a reading (map 4.3, normal approximation).
- Level band: the candidate's outside count against the largest outside
  count of the author's own held-out documents (o*), stored at build time.
- L11 band: the paired rank rule of map 4.5 on the Jensen-Shannon distance,
  the first-line distance of map 4.4. Inside when the candidate ranks at
  most k of k + 1; at rank k + 1 outside from 19 reference documents (the
  false alarm 1 / (k + 1) is then at most 5 percent), near the edge below.
  The candidate outside 0.5 to 2 times the median reference length is read
  in windows of that median length and the median window distance ranks.
- Overall: inside when no level is outside and L11 is inside; near the edge
  with one level outside or L11 near the edge; outside with two or more
  levels outside or L11 outside.

L11-8 needs the pooled character 3-gram rows of the samples; the profile
does not carry them. Pass --samples DIR for that one row (it reads n/a with
a note otherwise).

The reading sentences and edit classes come from the map section 6 table.
The three distance rows the table does not list (L11-4, L11-5, L11-8) reuse
the L11-1 class: a distance above the band reads as a function-word or
character-habit difference, an edit of word choice.

Advisory only, human-only surface: the model never receives this report, so
the token law holds (map section 6, report paths). It never gates, never
rewrites, never enters the delivery gate.

Exit codes: 0 = report printed (fail-open, also with no profile: the
candidate values print without bands and a defined note); 2 = bad usage.
"""
import argparse
import importlib.util
import json
import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # humanizer/learn/
PLUGIN_DIR = HERE.parent                        # humanizer/


def load_battery():
    spec = importlib.util.spec_from_file_location("voice_battery_report_mod", HERE / "voice_battery.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vb = load_battery()

# Reading sentences and edit classes (map section 6). (below, above, class);
# below/above describe the position against the reference band.
EDIT_READINGS = {
    "L1-1": ("fewer dashes than the author", "more dashes than the author: replace some by a comma or a period", "punctuation"),
    "L1-2": ("fewer exclamation marks than the author", "more exclamation marks than the author: remove some", "punctuation"),
    "L1-3": ("fewer question marks than the author", "more question marks than the author: turn some into statements", "punctuation"),
    "L1-4": ("fewer semicolons than the author", "more semicolons than the author: remove some", "punctuation"),
    "L1-5": ("fewer colons than the author", "more colons than the author: remove some", "punctuation"),
    "L1-6": ("fewer open parentheses than the author", "more open parentheses than the author: remove some", "punctuation"),
    "L1-7": ("fewer double dashes than the author", "more double dashes than the author: replace some by a comma or a period", "punctuation"),
    "L1-8": ("fewer commas per sentence than the author", "more commas per sentence than the author: split the long sentences", "sentence length"),
    "L1-9": ("quote characters sit closer to straight than the author's", "quote characters sit closer to curly than the author's", "punctuation"),
    "L1-11": ("fewer emoji than the author", "more emoji than the author: remove some", "punctuation"),
    "L1-12": ("fewer headings and lists than the author", "more headings and lists than the author: write running text", "structure"),
    "L1-13": ("fewer lower-case sentence starts than the author", "sentences that start in lower case: capitalize", "punctuation"),
    "L1-14": ("fewer ellipses than the author", "more ellipses than the author: remove some", "punctuation"),
    "L2-1": ("the words repeat sooner than the author's: replace a repeated word (read at equal length only)", "the words repeat later than the author's", "word choice"),
    "L2-4": ("the vocabulary repeats sooner than the author's: replace a repeated word", "the vocabulary repeats later than the author's", "word choice"),
    "L2-5": ("the words repeat sooner than the author's over 50-word windows: replace a repeated word", "the words repeat later than the author's over 50-word windows", "word choice"),
    "L2-6": ("shorter words than the author", "longer words than the author: use the shorter word", "word choice"),
    "L2-7": ("fewer long words than the author", "more long words than the author: use the shorter word", "word choice"),
    "L2-9": ("the top content word repeats less than the author's", "one content word repeats more than the author's: replace some of its occurrences", "word choice"),
    "L2-10": ("fewer content words than the author", "more content words than the author: remove filler nouns", "word choice"),
    "L2-11": ("fewer vague intensifiers than the author", "more vague intensifiers than the author: remove some or state the degree", "tone"),
    "L2-12": ("fewer numbers than the author", "more numbers than the author: remove some", "word choice"),
    "L3-1": ("fewer nominalizations than the author", "more words of this form than the author: use the plain word or the verb", "word choice"),
    "L3-2": ("fewer adjective-suffix words than the author", "more words of this form than the author: use the plain word or the verb", "word choice"),
    "L3-3": ("fewer adverbs in -ly than the author", "more words of this form than the author: use the plain word or the verb", "word choice"),
    "L3-4": ("fewer forms in -ing than the author", "more forms in -ing than the author: use a main verb", "sentence length"),
    "L3-5": ("less past tense than the author", "more past tense than the author", "word choice"),
    "L3-6": ("fewer prefixed words than the author", "more words of this form than the author: use the plain word or the verb", "word choice"),
    "L4-1": ("shorter sentences than the author", "longer sentences than the author: split some", "sentence length"),
    "L4-2": ("lower median sentence length than the author", "higher median sentence length than the author: split some", "sentence length"),
    "L4-3": ("lower 95th-percentile sentence length than the author", "higher 95th-percentile sentence length than the author: split the longest sentences", "sentence length"),
    "L4-4": ("sentence length is more even than the reference: vary sentence length", "sentence length varies more than the reference", "sentence length"),
    "L4-5": ("fewer sentences over 20 words than the author", "more sentences over 20 words than the author: split some", "sentence length"),
    "L4-6": ("fewer short sentences than the author: add short ones", "more short sentences than the author: join some", "sentence length"),
    "L4-7": ("fewer subordinators than the author", "more complex structures than the author: make clauses into sentences", "sentence length"),
    "L4-8": ("fewer connectives than the author", "more connectives than the author: remove some or start a new sentence", "links"),
    "L4-9": ("fewer of these small words than the author", "more of them than the author: use a full verb or name the thing", "word choice"),
    "L4-10": ("fewer passive markers than the author", "more passive markers than the author: name the actor as the subject", "sentence length"),
    "L4-11": ("fewer copula forms than the author", "more of them than the author: use a full verb", "word choice"),
    "L4-16": ("fewer words of stance than the author", "more words of certainty than the author: state the fact", "tone"),
    "L5-1": ("fewer connectives than the author", "more connectives than the author: remove some or start a new sentence", "links"),
    "L5-2": ("fewer additive connectives than the author", "more connectives than the author: remove some or start a new sentence", "links"),
    "L5-3": ("fewer adversative connectives than the author", "more connectives than the author: remove some or start a new sentence", "links"),
    "L5-4": ("fewer causal connectives than the author", "more connectives than the author: remove some or start a new sentence", "links"),
    "L5-5": ("fewer temporal connectives than the author", "more connectives than the author: remove some or start a new sentence", "links"),
    "L5-6": ("sentences share fewer words than the author's: repeat a key word or name the topic", "sentences share more words than the author's: replace a repeated word", "links"),
    "L5-9": ("fewer pronouns than the author", "more pronouns than the author: remove some or start a new sentence", "links"),
    "L5-10": ("fewer multiword connectives than the author", "more connectives than the author: remove some or start a new sentence", "links"),
    "L6-11": ("fewer marked sentences (question, exclamation, ellipsis, negation) than the author", "more of this tone: remove some", "tone"),
    "L7-1": ("the register sits more informational than the author's", "the register sits more involved than the author's: add the words of that side (pronouns and verbs, or nouns)", "word choice"),
    "L7-2": ("the register sits more expository than the author's", "the register sits more narrative than the author's", "word choice"),
    "L7-4": ("a property of the reference, not of the candidate", "a property of the reference, not of the candidate", "no edit"),
    "L7-6": ("the candidate sits below the author's main function-word axis position", "the candidate sits above the author's main function-word axis position: look at the word rates that stand out", "word choice"),
    "L8-1": ("more verbs than a text of the situation", "more nouns than a text of the situation: use a verb at some places", "word choice"),
    "L8-2": ("fewer content words per sentence than the author", "more content words per sentence than the author: split the sentence", "sentence length"),
    "L9-1": ("less of this tone (reader address) than the author", "more of this tone: remove some", "tone"),
    "L9-2": ("fewer first-person singular forms than the author", "more of this tone: remove some", "tone"),
    "L9-3": ("fewer first-person plural forms than the author", "more of this tone: remove some", "tone"),
    "L9-4": ("fewer hedges than the author: state the limit of a claim", "more hedges than the author: remove some", "tone"),
    "L9-5": ("fewer words of certainty than the author", "more words of certainty than the author: state the fact", "tone"),
    "L9-6": ("fewer possibility modals than the author", "more words of certainty than the author: state the fact", "tone"),
    "L9-7": ("fewer necessity modals than the author", "more words of certainty than the author: state the fact", "tone"),
    "L9-8": ("fewer prediction modals than the author", "more words of certainty than the author: state the fact", "tone"),
    "L9-11": ("fewer politeness markers than the author", "more of this tone: remove some", "tone"),
    "L9-12": ("fewer indirect requests than the author", "more of this tone: remove some", "tone"),
    "L9-16": ("fewer direct starts than the author", "more direct starts than the author: start the sentence with another word", "tone"),
    "L10-1": ("no marker word", "marker words present: delete them", "machine patterns"),
    "L10-2": ("fewer banned words and phrases than the author", "more banned words and phrases than the author: delete them", "machine patterns"),
    "L10-9": ("fewer noun-heavy constructions than the author", "more noun-heavy constructions than the author: use a verb at some places", "machine patterns"),
    "L10-11": ("sentence length more uniform than the author's: vary sentence length", "sentence length less uniform than the author's", "sentence length"),
    "L10-13": ("less variety of vocabulary than the author's: vary the words", "more variety of vocabulary than the author's", "word choice"),
    "L10-14": ("the register position differs from the reference in one direction", "the register position differs from the reference in the other direction", "word choice"),
    "L10-15": ("no excess style word", "excess style words present: delete them or use the plain word", "machine patterns"),
    "L11-1": ("no edit (closer than a typical own document)", "the function-word profile differs: look at the word rates that stand out", "word choice"),
    "L11-2": ("no edit (closer than a typical own document)", "the z-scored function-word profile differs in direction: look at the word rates that stand out", "word choice"),
    "L11-4": ("no edit (closer than a typical own document)", "the function-word distribution differs: look at the word rates that stand out", "word choice"),
    "L11-5": ("no edit (closer than a typical own document)", "the candidate reads less like the reference distribution: look at the word rates that stand out", "word choice"),
    "L11-8": ("no edit (character habits closer than typical)", "the character-level habits differ: check dashes, quotes, and word endings", "word choice"),
    "L11-11": ("no edit (the correlated profile matches)", "the correlated pattern of word rates differs: look at word pairs that move together", "word choice"),
}

SUPPRESS_TEXT = {
    "w": "needs %s words", "s": "needs %s sentences", "q": "needs %s quotes",
    "wc10": "needs 2,000 words or 10 counts", "pairs": "needs 10 sentence pairs",
    "win": "needs windows of the reference length", "docs": "needs 5 reference documents",
    "ref": "needs a reference and %s words",
}

SIDE_FILE_REASON = {
    "L7-6": "needs profile-pca.json beside the profile (built from 5 or more sample documents)",
    "L11-11": "needs profile-covariance.json beside the profile (built from the sample documents)",
}


def _suppress_reason(mk, mv, mid=None):
    if mid in SIDE_FILE_REASON:
        return SIDE_FILE_REASON[mid]
    if mk in ("w", "s", "q"):
        return SUPPRESS_TEXT[mk] % format(mv, ",")
    if mk == "ref":
        return SUPPRESS_TEXT["ref"] % format(mv, ",")
    return SUPPRESS_TEXT.get(mk, "below its minimum")


def learned_profile_path():
    return Path(os.environ.get("VOICE_LEARNED_DIR", PLUGIN_DIR / "learned")) / "profile.json"


def load_profile(path):
    """Read profile.json; fail-open like voice_fit: an absent or unreadable
    profile degrades the report, it never fails the run."""
    p = Path(path).expanduser()
    if not p.is_file():
        return None, f"note: no profile at {p}; bands read n/a (run learn/build_voice_profile.py)."
    try:
        prof = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return None, f"note: profile at {p} unreadable ({e!r}); bands read n/a."
    if not isinstance(prof, dict) or not isinstance(prof.get("battery"), dict):
        return None, (f"note: profile at {p} has no battery section; bands read n/a "
                      "(rebuild it with learn/build_voice_profile.py).")
    return prof, None


def load_samples(path):
    """Expand --samples to a sorted list of .md/.txt files (same input
    contract as build_voice_profile.py). Empty result -> SystemExit(2)."""
    p = Path(path).expanduser()
    files = []
    if p.is_dir():
        for cand in sorted(p.rglob("*")):
            if cand.is_file() and cand.suffix.lower() in (".md", ".txt"):
                files.append(cand)
    elif p.is_file() and p.suffix.lower() in (".md", ".txt"):
        files.append(p)
    if not files:
        print(f'usage: --samples path "{path}" is missing or holds no .md/.txt files', file=sys.stderr)
        raise SystemExit(2)
    return files


def load_state():
    """The setup state files (learned/state/setup.json, voice-bands.json)
    written by voice_setup.py; ({}, {}) when absent (fail-open)."""
    base = Path(os.environ.get("VOICE_LEARNED_DIR", PLUGIN_DIR / "learned")) / "state"
    out = {}
    for name in ("setup.json", "voice-bands.json"):
        try:
            data = json.loads((base / name).read_text(encoding="utf-8"))
            out[name.split(".")[0]] = data if isinstance(data, dict) else {}
        except Exception:
            out[name.split(".")[0]] = {}
    return out["setup"], out["voice-bands"]


def _fw2(value):
    return "%.2f" % value if isinstance(value, (int, float)) else "n/a"


def row_reading(mid, val, mean):
    """The reading sentence for one row: the map direction for outside and
    near the edge, the neutral sentence inside."""
    below, above, cls = EDIT_READINGS[mid]
    if val >= mean:
        return above, cls
    return below, cls


def measure_row_state(mid, val, stats, n, ns, quotes):
    """Band state of one measure row: (verdict, low, high, seen_low,
    seen_high, short, k_used). The printed band is the map 4.1 prediction
    band mean +- t * s * sqrt(1 + 1/k); the count floor lives only in the
    z of the verdict (map 4.2). verdict None = no band (k under 3 or no
    spread); short marks a candidate interval wider than half the band
    (map 4.3, normal approximation of the candidate's own interval)."""
    sd = stats.get("sd", 0.0)
    k = int(stats.get("k", 0))
    t = vb.t_value(k)
    low, high, short = None, None, False
    verdict = None
    if t is not None and sd > 0:
        stretch = math.sqrt(1.0 + 1.0 / k)
        half = t * sd * stretch
        low, high = stats["mean"] - half, stats["mean"] + half
        fv = vb.floor_variance(vb.SPEC[mid][5], stats["mean"], n, ns, quotes)
        se = vb.eff_sd(sd, fv)
        z = (val - stats["mean"]) / (se * stretch)
        verdict = vb.verdict(z, t)
        short = 1.96 * math.sqrt(fv) > 0.5 * half
    return verdict, low, high, stats.get("min"), stats.get("max"), short, k


def jsd_counts(ca, cb, keys):
    return vb._js(ca, cb, keys)


def rank_rule(acc, battery, ref_fw_pooled, total_words):
    """The paired rank rule of map 4.5 on L11-4 (Jensen-Shannon distance).
    Returns (rank r, k, false_alarm_text) or None when the stored data is
    too small (k under 3 or a missing holdout vector)."""
    rank = battery.get("rank") or {}
    d_vec = rank.get("d") or []
    docs_fw = ((battery.get("reference") or {}).get("docs_fw")) or []
    docs_words = ((battery.get("reference") or {}).get("docs_words")) or []
    k = len(d_vec)
    if k < 3 or len(docs_fw) != k or not ref_fw_pooled:
        return None
    fwc = acc["fwc"]
    cand_all = dict((w, fwc.get(w, 0)) for w in vb.FUNCTION_WORDS)
    keys = list(vb.FUNCTION_WORDS) + ["(other)"]

    def jsd_vs(pooled_counts, counts, n_words):
        cb = dict(zip(vb.FUNCTION_WORDS, pooled_counts))
        cb["(other)"] = max(total_words - sum(pooled_counts), 0)
        cc = dict(counts)
        cc["(other)"] = max(n_words - sum(counts.values()), 0)
        return jsd_counts(cc, cb, keys)

    n = acc["n"]
    c_vals = []
    window = None
    if docs_words:
        w_med = int(round(vb.median([float(w) for w in docs_words])))
        if w_med and (n < 0.5 * w_med or n > 2.0 * w_med):
            window = w_med
    wins = None
    if window:
        toks = acc["tokens"]
        wins = []
        for i in range(0, n - window + 1, window):
            part = toks[i:i + window]
            wc = {}
            for w in part:
                if w in vb.FUNCSET:
                    wc[w] = wc.get(w, 0) + 1
            wins.append(wc)
        if not wins:
            return None
    for i in range(k):
        loo = [ref_fw_pooled[j] - docs_fw[i][j] for j in range(len(vb.FUNCTION_WORDS))]
        if window:
            c_vals.append(vb.median([jsd_vs(loo, wcount, window) for wcount in wins]))
        else:
            c_vals.append(jsd_vs(loo, cand_all, n))
    r = 1 + sum(1 for c, d in zip(c_vals, d_vec) if c > d)
    return r, k, c_vals


def _load_side_file(profile_path, suffix):
    """Read one profile-side artifact (-pca.json, -covariance.json), named
    after the profile's stem (profile-fit.json -> profile-fit-pca.json) with
    the plain profile-pca.json as the fallback. None when absent or
    unreadable (fail-open; the rows read n/a)."""
    if not profile_path:
        return None
    p = Path(profile_path).expanduser()
    for name in (p.stem + suffix, "profile" + suffix):
        try:
            data = json.loads((p.parent / name).read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return None


def build_report(candidate_text, profile, profile_note=None, sample_files=None, profile_path=None,
                 setup=None, bands=None, situation=None):
    """Render the section-6 report text (and the JSON dict). profile_path
    locates the side artifacts written by build_voice_profile.py. setup and
    bands carry the voice_setup.py state; situation applies the layer-2
    factors (pooled base + situation factor on the factor rows)."""
    lines = []
    report = {"levels": {}, "notes": []}
    notes = [profile_note] if profile_note else []
    battery = (profile or {}).get("battery") or {}
    fw_profile = (profile or {}).get("function_words") or {}
    stats = battery.get("measures") or {}
    ref = battery.get("reference") or {}
    k_docs = int(battery.get("docs", 0) or 0)
    fw_pooled = ref.get("fw_pooled") or []
    total_words = int(ref.get("total_words", 0) or 0)
    level = (setup or {}).get("level")

    tri_pooled = None
    if sample_files:
        texts = [f.read_text(encoding="utf-8", errors="replace") for f in sample_files]
        tri_pooled = vb.tri_merge([vb.scan(t, phrases=False, tri=True)["tri"] for t in texts])
    ref_full = None
    pca = chol = None
    if level is not None and level < 1:
        notes.append("note: setup level 0 keeps the battery report off (the gate fast core only); "
                     "run learn/voice_setup.py --level 1 to enable the report path.")
        stats = {}
    if fw_pooled and fw_profile.get("mean") and fw_profile.get("stddev"):
        ref_full = vb.ref_block(fw_profile["mean"], fw_profile["stddev"],
                                dict(zip(vb.FUNCTION_WORDS, fw_pooled)), None, tri_pooled, k_docs)
        reg = {}
        for key in ("L7-1", "L7-2"):
            st = stats.get(key)
            if st:
                reg[key] = (st["mean"], st["sd"])
        st71 = stats.get("L7-1")
        if st71:
            reg["range"] = st71["sd"]
        if reg:
            ref_full["register"] = reg
        # the reference-derived axes (delta1 rows): per-document rates from the
        # stored pooled rows, plus the two side artifacts beside the profile
        docs_fw = ref.get("docs_fw") or []
        docs_words = ref.get("docs_words") or []
        if docs_fw and docs_words and len(docs_fw) == len(docs_words):
            ref_full["docs_rates"] = [[row[w] * 1000.0 / docs_words[i]
                                       for w in range(len(vb.FUNCTION_WORDS))]
                                      for i, row in enumerate(docs_fw)]
        if level is None or level >= 2:
            pca = _load_side_file(profile_path, "-pca.json")
            if pca and {"v1", "mean", "sd"} <= set(pca):
                ref_full["pca"] = pca
            chol = _load_side_file(profile_path, "-covariance.json")
            if chol and {"mean", "chol_lower"} <= set(chol):
                ref_full["chol"] = chol
    elif battery:
        notes.append("note: the profile carries no function_words section; the L11 distances read n/a.")

    # layer 2: the situation factors shift the band mean on the factor rows
    sit_entry = None
    if situation and bands:
        sit_entry = (bands.get("situations") or {}).get(situation)
        if sit_entry and sit_entry.get("factors") and not sit_entry.get("fallback"):
            shifted = dict(stats)
            for mid, f in sit_entry["factors"].items():
                st = shifted.get(mid)
                if st:
                    st2 = dict(st)
                    st2["mean"] = st["mean"] + f["factor"]
                    shifted[mid] = st2
            stats = shifted
            notes.append("note: bands read at situation %s: pooled base + situation factor "
                         "(k %d)" % (situation, sit_entry["docs"]))
        else:
            notes.append("note: no learned factor for situation %s; the pooled base applies"
                         % situation)
    elif situation:
        notes.append("note: no setup bands found; run learn/voice_setup.py to learn per situation.")

    acc = vb.scan(candidate_text, phrases=True, tri=tri_pooled is not None)
    vals = vb.values(acc, ref=ref_full or {}, window=battery.get("window_words"))
    n, ns, npar = acc["n"], acc["ns"], acc["np"]
    report["words"], report["sentences"], report["paragraphs"] = n, ns, npar

    acc = vb.scan(candidate_text, phrases=True, tri=tri_pooled is not None)
    vals = vb.values(acc, ref=ref_full or {}, window=battery.get("window_words"))
    n, ns, npar = acc["n"], acc["ns"], acc["np"]
    report["words"], report["sentences"], report["paragraphs"] = n, ns, npar

    quotes = acc["curly"] + acc["chars"]["straight"]
    suppressed = []
    heavy_note = ("setup level %d keeps the heavy rows off (run learn/voice_setup.py --level 2)" % level
                  if level is not None and level < 2 else None)
    for mid in vb.ALL_IDS:
        if vals[mid] is None:
            _lv, _name, _unit, mk, mv, _fl, _cm = vb.SPEC[mid]
            if mk == "ref" and not battery:
                suppressed.append("%s (needs a profile reference)" % mid)
            elif mk == "ref" and mid == "L11-8" and battery:
                suppressed.append("%s (needs --samples for the pooled character 3-gram rows)" % mid)
            elif mid in SIDE_FILE_REASON and heavy_note:
                suppressed.append("%s (%s)" % (mid, heavy_note))
            else:
                suppressed.append("%s (%s)" % (mid, _suppress_reason(mk, mv, mid)))

    rank = None
    if fw_pooled and battery:
        rank = rank_rule(acc, battery, fw_pooled, total_words)

    lines.append("voice fit  (reference: %s)" % ("%d documents" % k_docs if k_docs else "n/a"))

    overall_levels = {}
    for lvl in vb.LEVELS:
        ids = sorted(mid for mid in vb.ALL_IDS if vb.SPEC[mid][0] == lvl)
        rows = []
        counts = {"inside": 0, "near the edge": 0, "outside": 0, "short": 0, "unbanded": 0}
        for mid in ids:
            val = vals[mid]
            if val is None:
                continue
            st = stats.get(mid)
            if st is None:
                verdict, low, high, slow, shigh, short, ku = None, None, None, None, None, False, 0
            else:
                verdict, low, high, slow, shigh, short, ku = measure_row_state(mid, val, st, n, ns, quotes)
            if short and verdict:
                counts["short"] += 1
                state = "short"
            elif verdict:
                counts[verdict] += 1
                state = verdict
            else:
                counts["unbanded"] += 1
                state = "unbanded"
            rows.append((mid, val, state, verdict, low, high, slow, shigh, st or {}))
        order = {"outside": 0, "near the edge": 1, "inside": 2, "short": 3, "unbanded": 4}
        rows.sort(key=lambda r: (order[r[2]], r[0]))
        name = vb.LEVEL_NAMES[lvl]
        readings = len(rows)
        if lvl == "L11":
            if rank:
                r, kk, _c = rank
                if r <= kk:
                    band = "inside"
                elif kk >= 19:
                    band = "outside"
                else:
                    band = "near the edge"
                lines.append("L11 %s  readings %d of %d  rank %d of %d  band: %s"
                             % (name, readings, len(ids), r, kk + 1, band))
                lines.append("  The candidate sits farther from the other documents than the held-out "
                             "document in %d of %d comparisons. A text by the author lands at rank %d of %d "
                             "in 1 of %d cases (the false alarm of the rank reading)."
                             % (r - 1, kk, kk + 1, kk + 1, kk + 1))
            else:
                band = None
                lines.append("L11 %s  readings %d of %d  band: n/a (the rank rule needs 3 or more "
                             "reference documents with spread)" % (name, readings, len(ids)))
            overall_levels[lvl] = band
        else:
            o_star = (battery.get("levels_holdout") or {}).get(lvl)
            o = counts["outside"]
            if o_star is None or not battery:
                band = None
            elif o <= o_star:
                band = "inside"
            elif o == o_star + 1:
                band = "near the edge"
            else:
                band = "outside"
            overall_levels[lvl] = band
            band_text = "band: %s" % band if band else "band: n/a (holdout needs 4 or more reference documents)"
            lines.append("%s %s  readings %d of %d  inside %d  near the edge %d  outside %d  short %d  %s"
                         % (lvl, name, readings, len(ids), counts["inside"],
                            counts["near the edge"], counts["outside"], counts["short"], band_text))
        for mid, val, state, verdict, low, high, slow, shigh, st in rows:
            _lv, mname, unit, _mk, _mv, _fl, _cm = vb.SPEC[mid]
            unit_text = vb.UNIT_TEXT.get(unit, unit)
            seg = "  %s  %s %s  %s %s" % (state, mid, mname, _fw2(val), unit_text)
            if low is not None:
                seg += "  band %s to %s (seen %s to %s)" % (_fw2(low), _fw2(high), _fw2(slow), _fw2(shigh))
            lines.append(seg)
            if state in ("outside", "near the edge"):
                reading, cls = row_reading(mid, val, st.get("mean", val))
                lines.append("    %s [edit: %s]" % (reading, cls))
            elif state == "short":
                lines.append("    too short for this measure at this length (the candidate's own "
                             "interval is wider than half the band)")
            elif state == "inside":
                lines.append("    inside the author's range; no edit [edit: none]")
            else:
                lines.append("    no band from the reference yet (k under 3 or no spread)")
            if mid == "L11-11" and isinstance(vals.get("L11-11"), float):
                band = (chol or {}).get("band") or {}
                dists = band.get("distances") or []
                if dists:
                    r = 1 + sum(1 for d in dists if d < vals["L11-11"])
                    lines.append("    rank %d of %d by the stored leave-one-out distances "
                                 "(a text by the author draws the last rank in 1 of %d cases)"
                                 % (r, len(dists) + 1, len(dists) + 1))
        report["levels"][lvl] = {"readings": readings, "counts": counts, "band": overall_levels[lvl],
                                 "rows": [{"id": r[0], "value": r[1], "state": r[2]} for r in rows]}

    outside_levels = [lv for lv in vb.LEVELS if overall_levels.get(lv) == "outside"]
    l11_band = overall_levels.get("L11")
    banded = [lv for lv in vb.LEVELS if overall_levels.get(lv) is not None]
    if len(outside_levels) >= 2 or l11_band == "outside":
        overall = "outside"
    elif len(outside_levels) == 1 or l11_band == "near the edge":
        overall = "near the edge"
    elif banded:
        overall = "inside"
    else:
        overall = None
    overall_text = overall if overall else "n/a (a full reading needs a profile battery section)"

    # level 3: the cross-situation comparison and the windowed stability check
    if level is not None and level >= 3 and bands:
        sits = (bands.get("situations") or {})
        scored = []
        for sname, entry in sorted(sits.items()):
            factors = entry.get("factors") or {}
            if not factors:
                continue
            zs = []
            for mid, f in factors.items():
                st = stats.get(mid) or (bands.get("pooled") or {}).get(mid)
                v = vals.get(mid)
                if st and isinstance(v, float) and st.get("sd", 0) > 0:
                    zs.append(abs(v - (st["mean"] + f["factor"])) / st["sd"])
            if zs:
                scored.append((vb.sample_mean(zs), sname))
        if scored:
            scored.sort()
            lines.append("cross-situation fit: " + " < ".join("%s (mean |z| %.2f)" % (s, mz)
                                                              for mz, s in scored))
        window = (battery or {}).get("window_words")
        if window and len(acc["tokens"]) >= window:
            toks = acc["tokens"]
            ttrs = [len(set(toks[i:i + window])) / float(window)
                    for i in range(0, len(toks) - window + 1, window)]
            if ttrs:
                lines.append("windowed stability: type-token ratio %.2f to %.2f across %d windows "
                             "of %d words" % (min(ttrs), max(ttrs), len(ttrs), window))
    lines.append("overall: %s" % overall_text)

    readings_total = sum(1 for mid in vb.ALL_IDS if vals[mid] is not None)
    fa_text = "1 of %d" % (k_docs + 1) if k_docs >= 3 else "n/a"
    sup_text = "; ".join(suppressed) if suppressed else "none"
    lines.append("length: %d words, %d sentences, %d paragraphs; readings %d of %d; suppressed: %s; "
                 "reference %d documents; rank false alarm %s"
                 % (n, ns, npar, readings_total, len(vb.ALL_IDS), sup_text, k_docs, fa_text))
    lines.extend(notes)
    text = "\n".join(lines) + "\n"
    report["overall"] = overall
    report["suppressed"] = suppressed
    report["notes"] = notes
    report["rank"] = {"r": rank[0], "k": rank[1]} if rank else None
    return text, report


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    parser = argparse.ArgumentParser(
        prog="voice_battery_report.py",
        description="The on-demand gestalt report of the 79-measure battery: one band per level "
                    "plus the overall band, each row mapped to an edit class (advisory, never gates).")
    parser.add_argument("candidate", help="candidate file path, or '-' for stdin")
    parser.add_argument("--profile", default=None, help="learned/profile.json path (default: the plugin learned dir)")
    parser.add_argument("--samples", default=None,
                        help="sample dir or .md/.txt file; adds the pooled character 3-gram rows for L11-8")
    parser.add_argument("--situation", default=None,
                        help="apply the learned layer-2 factors of this situation to the band step")
    args = parser.parse_args(argv)
    if args.candidate == "-":
        candidate_text = sys.stdin.read()
        if not candidate_text.strip():
            print("usage: pipe text to stdin, or name a candidate file", file=sys.stderr)
            return 2
    else:
        p = Path(args.candidate).expanduser()
        if not p.is_file():
            print(f"usage: candidate file not found: {p}", file=sys.stderr)
            return 2
        candidate_text = p.read_text(encoding="utf-8", errors="replace")
    profile, profile_note = load_profile(args.profile or learned_profile_path())
    profile_path = args.profile or learned_profile_path()
    sample_files = load_samples(args.samples) if args.samples else None
    setup, bands = load_state()
    text, report = build_report(candidate_text, profile, profile_note, sample_files, profile_path,
                                setup=setup, bands=bands, situation=args.situation)
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
