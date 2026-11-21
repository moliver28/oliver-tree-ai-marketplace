#!/usr/bin/env python3
"""distill_phrases.py: fold recurring request phrasings into learned rules (zero LLM).

Input: learned/phrases.log, the append-only sidecar the /voice command writes
after every successful run (one `<date>\\t<verbatim request>` line per run; a
shell append, never a model call). The tool extracts recurring phrasings by
string frequency alone:

- recurring n-grams: word 2-4 grams appearing at least --min-count times
  (stopwords are not filtered here: phrasings like "polish this intro" are
  exactly what the description law wants)
- recurring openers: the first two words of a request
- recurring closers: the last two words of a request

Output: learned/rules.json, merged deterministically. Existing "manual"
entries in a present rules.json are preserved verbatim; the computed sections
are regenerated from the log (same inputs, same bytes). Every list is ordered
count-descending then lexicographic, capped at --top entries.

Empty-input behavior (defined, not an error): a missing or empty log prints a
clear message and still writes rules.json carrying only the preserved manual
entries and zero computed entries; exit code 0.

Exit codes: 0 = rules written; 2 = bad arguments (log path is a directory).
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # humanizer/learn/
PLUGIN_DIR = HERE.parent                        # humanizer/
DEFAULT_LOG = PLUGIN_DIR / "learned" / "phrases.log"
DEFAULT_OUT = PLUGIN_DIR / "learned" / "rules.json"

WORD_RE = re.compile(r"[A-Za-z0-9']+", re.UNICODE)


def read_log(path):
    """Parse the phrase log. Returns (requests, malformed, lines). A malformed
    line (no tab separator, or an empty request part) is skipped and counted;
    that is a defined behavior, never a crash."""
    requests, malformed, total = [], 0, 0
    if not path.is_file():
        return requests, malformed, total
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        total += 1
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            malformed += 1
            continue
        date, text = parts[0].strip(), parts[1].strip()
        if not date or not text:
            malformed += 1
            continue
        requests.append(text)
    return requests, malformed, total


def ngrams_of(text, n):
    words = WORD_RE.findall(text.lower())
    return [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]


def top_counts(counter, limit):
    """Deterministic ranking: count desc, then key asc."""
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def distill(requests, min_count, top):
    grams, openers, closers = {}, {}, {}
    for text in requests:
        for n in (2, 3, 4):
            for g in ngrams_of(text, n):
                grams[g] = grams.get(g, 0) + 1
        words = WORD_RE.findall(text.lower())
        if len(words) >= 2:
            openers[" ".join(words[:2])] = openers.get(" ".join(words[:2]), 0) + 1
            closers[" ".join(words[-2:])] = closers.get(" ".join(words[-2:]), 0) + 1
    def at_floor(counter):
        return [[k, c] for k, c in top_counts(counter, top) if c >= min_count]
    return {
        "recurring_ngrams": at_floor(grams),
        "recurring_openers": at_floor(openers),
        "recurring_closers": at_floor(closers),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log", default=str(DEFAULT_LOG), help="phrases.log path (default: the plugin's learned/phrases.log)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="rules.json path (default: the plugin's learned/rules.json)")
    ap.add_argument("--min-count", type=int, default=2, help="minimum occurrences for a phrasing to count as recurring (default 2)")
    ap.add_argument("--top", type=int, default=15, help="maximum entries per computed section (default 15)")
    a = ap.parse_args()
    log = Path(a.log).expanduser()
    out = Path(a.out).expanduser()
    if log.is_dir():
        print(f"log path is a directory, expected a file: {log}", file=sys.stderr)
        return 2
    requests, malformed, total = read_log(log)
    if out.parent and str(out.parent):
        out.parent.mkdir(parents=True, exist_ok=True)
    manual = []
    if out.is_file():
        try:
            prior = json.loads(out.read_text(encoding="utf-8"))
            if isinstance(prior, dict) and isinstance(prior.get("manual"), list):
                manual = prior["manual"]
        except Exception as e:
            print(f"existing rules.json unreadable, computed merge proceeds without manual entries ({e!r})",
                  file=sys.stderr)
    if not requests:
        print(f"no request lines in {log}"
              + (" (file missing)" if not log.is_file() else f" ({total} lines, {malformed} malformed)")
              + "; rules.json carries only preserved manual entries")
    computed = distill(requests, a.min_count, a.top)
    rules = {
        "format": 1,
        "source": str(log),
        "request_lines": len(requests),
        "malformed_lines": malformed,
        "min_count": a.min_count,
        **computed,
        "manual": manual,
    }
    out.write_text(json.dumps(rules, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if requests:
        print(f"distilled {len(requests)} request lines: "
              f"{len(computed['recurring_ngrams'])} recurring n-grams, "
              f"{len(computed['recurring_openers'])} openers, "
              f"{len(computed['recurring_closers'])} closers -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
