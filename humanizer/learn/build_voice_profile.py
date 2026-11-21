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
- gate_pattern_hits: per-label hit counts and per-1000-sentence rates from the
  hooks/voice_tells.py regex layer (the machine register)

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
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for mark, name in PUNCT_MARKS:
            punct[name] += text.count(mark)
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
    }
    return stats, sents


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
    stats, sents = analyze(files)
    vt = load_voice_tells()
    stats["gate_pattern_hits"] = gate_pattern_hits(sents, vt)
    out = Path(a.out).expanduser()
    if out.parent and str(out.parent):
        out.parent.mkdir(parents=True, exist_ok=True)
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
