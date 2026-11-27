#!/usr/bin/env python3
"""voice_battery_core.py: the gate-path fast core of the measurement battery.

hooks/gate.py lazy-imports THIS module, never the full battery: the full
module builds the closed lists of all 79 measures and its import cost sits
outside the gate's latency budget (D6a). This file holds only what the fast
core needs, so a cold import stays near the 3 ms bar:

- the shared tokenizer constants (byte-identical to build_voice_profile.py,
  which stays the single source of truth; a sync pin lives in
  humanizer/tests/test_voice_battery.py),
- the marker words of L10-1 (Reinhart et al. 2024, Table 1; "tapestry" stays
  out: the pattern register already bans it, and two families must not name
  the same word in one repair contract),
- fast_core(): one shared pass over token loop, sentence block, paragraph
  block, and character counts (no diversity index, no profile distance).

The gate reads the marker hits only. A battery finding may occupy one of the
at most 5 family-deduped fail lines; it never adds a sixth, and the pass line
stays byte-identical (token law, MAINTENANCE.md). Standard library only.
"""
import re

# Tokenizer constants: byte-identical copies of build_voice_profile.py (the
# single source of truth). The sync pin in test_voice_battery.py fails the
# build if the two drift.
WORD_RE = re.compile(r"[A-Za-z0-9']+", re.UNICODE)
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
PARA_SPLIT = re.compile(r"\n\s*\n")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
ITEM_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.*)$")
PASSIVE_RE = re.compile(r"\b(is|are|was|were|be|been|being)\s+\w+(?:ed|en)\b", re.IGNORECASE)

MACHINE = ("amidst cacophony camaraderie continuation fleeting grapple ignite intricate palpable pang prioritize "
           "reminder rut shoutout solace tapestry unease unravel vibrant waft underscore").split()
GATE_MARKERS = frozenset(w for w in MACHINE if w != "tapestry")


def fast_core(text):
    """The fast core in one pass: token loop (marker words), sentence block,
    paragraph block, character counts. Returns raw counters; the gate turns
    the marker hits into at most one family-deduped fail line."""
    toks = [w.lower() for w in WORD_RE.findall(text)]
    present = sorted(set(w for w in toks if w in GATE_MARKERS))
    n_long_sent = 0
    n_pass = 0
    n_sents = 0
    n_long_para = 0
    n_paras = 0
    for p in PARA_SPLIT.split(text):
        p = p.strip()
        if not p:
            continue
        n_paras += 1
        para_units = 0
        for line in p.split("\n"):
            line = line.strip()
            if not line:
                continue
            if HEADING_RE.match(line) or ITEM_RE.match(line):
                para_units += 1
                continue
            for s in SENT_SPLIT.split(line):
                if not s.strip():
                    continue
                n_sents += 1
                para_units += 1
                wc = len(WORD_RE.findall(s))
                if wc > 20:
                    n_long_sent += 1
                if PASSIVE_RE.search(s):
                    n_pass += 1
        if para_units > 3:
            n_long_para += 1
    chars = {}
    for mark in ("\u2014", "\u2013", "--", "?", "!", ";", ":", "(", "..."):
        chars[mark] = text.count(mark)
    return {
        "marker_counts": dict((w, toks.count(w)) for w in present),
        "n": len(toks), "ns": n_sents, "np": n_paras,
        "long_sentences": n_long_sent,
        "long_paragraphs": n_long_para,
        "passive_sentences": n_pass,
        "chars": chars,
    }
