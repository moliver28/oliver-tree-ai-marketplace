#!/usr/bin/env python3
"""voice_battery_core.py: the gate-path fast core of the measurement battery.

hooks/gate.py lazy-imports THIS module, never the full battery: the full
module builds the closed lists of all 79 measures and its import cost sits
outside the gate's latency budget (D6a). This file holds only what the fast
core needs, so a cold import stays near the 3 ms bar:

- the shared tokenizer constants (byte-identical to build_voice_profile.py,
  which stays the single source of truth; a sync pin lives in
  tests/humanizer/test_voice_battery.py),
- the marker words of L10-1 (Reinhart et al. 2024, Table 1; "tapestry" stays
  out: the pattern register already bans it, and two families must not name
  the same word in one repair contract),
- fast_core(): one shared pass over token loop, sentence block, paragraph
  block, and character counts (no diversity index, no profile distance).

Wave H-C (2026-11-27) adds the three detection-method signal functions of
the method menu, next to the fast core: chunk_content_sets() (method A1,
the content-word side of the chunk-pair divergence for family 11),
aphorism_shapes() + aphorism_budget_hits() (method B4, the mechanical
enforcement of the skill's own kicker budget for family 35), and
compression_profile() (method B2, advisory). Detector thresholds and
bands are never constants here: they load from the learned-state chain
at scan time (issue #5 data contract; absent state = advisory only).

The gate reads the marker hits only. A battery finding may occupy one of the
at most 5 family-deduped fail lines; it never adds a sixth, and the pass line
stays byte-identical (token law, MAINTENANCE.md). Standard library only.
"""
import re
import zlib

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


# ---- wave H-C signal methods (2026-11-27, method menu A1 / B4 / B2) ----
# The gate consumes these through hooks/gate.py and the report through
# voice_battery_report.py. Thresholds and bands are never constants here:
# they load from the learned-state chain at scan time (issue #5 data
# contract; absent state = advisory only, no fail line).

# Content-word stop list: byte-identical copy of build_voice_profile.py
# STOPWORDS (the single source of truth; the sync pin in
# tests/humanizer/test_voice_battery.py fails the build if the two drift).
STOPWORDS = frozenset("""a an the and or but nor so yet if then than that this these those there
here of in on at by for with from to into over under between against before after during
is are was were be been being am do does did have has had will would can could should may
might must not no nor as it its it's they them their you your we our us he she his her
i me my mine what which who whom whose when where why how all any both each few more most
other some such only own same too very just also about above below up down out off again
once because while until unless since after before""".split())

# Verb frame list for the imperative shape: byte-identical copy of
# voice_battery.py VERBS (103 words; R1 list with its own PROVENANCE row).
VERBS = ("is are was were be been being am do does did has have had shows show uses use needs need gives give takes "
         "take makes make finds find keeps keep holds hold moves move reads read writes write tests test tracks "
         "track cuts cut adds add opens open closes close checks check compares compare measures measure covers "
         "cover limits limit reduces reduce raises raise drives drive supports support explains explain records "
         "record avoids avoid runs run builds build sends send brings bring kept gets get puts put sees "
         "see says said tells tell thinks think knows know wants want goes go comes come").split()

# Imperative frame list (owned selection, R0): the common bare-form verbs a
# short kicker imperative opens with ("Ship it.", "Trust the reader."). The
# determiner rule does the precision work ("Set the timeout." names its
# object with a determiner and never counts); this closed list only has to
# cover the frame words. Not copied from any shipped list; PROVENANCE row
# documents it.
IMPERATIVE_VERBS = ("act add ask be become begin believe build buy choose come cut decide do "
                    "drop end expect fail feel fight find finish fix focus follow forget get give "
                    "go grow handle hear help hold hope keep know launch lead learn leave let "
                    "listen live look lose make manage mark measure meet move need notice offer "
                    "open pay pick plan play point practice prefer prepare present press "
                    "produce protect prove provide pull push raise reach realize receive "
                    "reduce refuse remember remove repeat replace reply report require rest "
                    "return review risk run save say seek sell send serve set settle share "
                    "ship show simplify sit sleep solve speak spend split spread stand start "
                    "stay step stop study succeed support suppose survive take talk teach "
                    "tell tend test think throw track train transform travel treat trust try "
                    "turn understand use value view wait walk want warn watch welcome win "
                    "wish work worry write").split()

VERB_FRAMES = frozenset(VERBS) | frozenset(IMPERATIVE_VERBS)

CHUNK_SIZE = 1200   # vector_pass chunk size (hooks/voice_tells.py _chunks default)
CHUNK_CAP = 12      # vector_pass chunk cap (same module)

ZLIB_LEVEL = 6                  # method menu B2: per-paragraph zlib level 6
APHORISM_MAX_WORDS = 12         # the short-kicker word cap (about 12 words)
APHORISM_MAX_PER_SECTION = 1    # README: max one kicker per section
APHORISM_MAX_PER_PIECE = 3      # README: two to three per piece

_FRAG_AUX = frozenset(
    "is are was were be been being am do does did has have had will would can "
    "could should may might must shall".split())
_SUBJ_OPENERS = frozenset(
    "the a an this that these those my our your his her its their i we you it "
    "they he she one some any every each another both".split())
_DETERMINERS = re.compile(
    r"\b(?:the|a|an|my|our|your|his|her|its|their|this|that|these|those)\b", re.IGNORECASE)
_COPULA_RX = re.compile(r"\b(?:is|are|was|were|am|been|being|be)\b", re.IGNORECASE)
_COLON_KICKER = re.compile(r":\s*[^.:!?\n]{2,80}[.!?]*\s*$")
_PAST_FORM = re.compile(r"\w+ed\b", re.IGNORECASE)
_APH_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+", re.UNICODE)
_APH_HEAD = re.compile(r"^#{1,6}\s+", re.UNICODE)
_APH_LABEL = re.compile(r"^[A-Z][\w ]+:", re.UNICODE)
_APH_CONJ = frozenset("and or but so because which that while when if then since "
                      "although though whereas".split())


def _chunks(text, size=CHUNK_SIZE, cap=CHUNK_CAP):
    """Byte-identical mirror of hooks/voice_tells.py _chunks (paragraph-
    boundary chunks), so chunk_content_sets aligns exactly with the
    vector_pass chunk boundaries; the sync pin in
    tests/humanizer/test_hc_methods.py compares the two on fixture texts."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    paras = [p for p in text.split("\n\n") if p.strip()]
    out, cur = [], ""
    for p in paras:
        if len(cur) + len(p) > size and cur:
            out.append(cur)
            cur = ""
        cur += ("\n\n" if cur else "") + p
    if cur:
        out.append(cur)
    return out[:cap]


def chunk_content_sets(text):
    """Per-chunk frozenset of content words (tokens outside the shared stop
    list), aligned exactly with the vector_pass chunk boundaries (the
    mirrored _chunks above). Rides the fast-core tokenizer constants: no
    new pass, no new embed calls (method menu A1)."""
    return [frozenset(w for w in (t.lower() for t in WORD_RE.findall(chunk))
                      if w not in STOPWORDS)
            for chunk in _chunks(text)]


def compression_profile(text):
    """Per-paragraph zlib compression profile (method menu B2): ratio =
    compressed/plain bytes at zlib level 6, reported as the whole-text
    ratio plus the sample standard deviation of the per-paragraph ratios.
    Advisory only: the gate carries it as an advisory field when the
    learned state has compression bands, never as a fail line."""
    paras = [p for p in PARA_SPLIT.split(text) if p.strip()]
    ratios = []
    plain_total = 0
    comp_total = 0
    for p in paras:
        raw = p.encode("utf-8", "replace")
        packed = zlib.compress(raw, ZLIB_LEVEL)
        plain_total += len(raw)
        comp_total += len(packed)
        if raw:
            ratios.append(len(packed) / float(len(raw)))
    mu = sum(ratios) / len(ratios) if ratios else 0.0
    sd = (sum((x - mu) ** 2 for x in ratios) / (len(ratios) - 1)) ** 0.5 if len(ratios) > 1 else 0.0
    return {"ratio": round(comp_total / float(plain_total), 4) if plain_total else 0.0,
            "sd": round(sd, 4), "paragraphs": len(paras)}


def _aph_units(text, profile):
    """Section split for the aphorism budget: markdown headings name the
    sections; the text before the first heading is one section. Heading
    lines and bullet or numbered list items stay out of the sentence
    units (they are structure, not prose); under the resume profile the
    labeled category lines stay out too (the existing ATS exemption)."""
    sections = []
    name, units = ("(opening)", [])
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _APH_HEAD.match(stripped):
            if units:
                sections.append((name, units))
            name, units = (re.sub(r"^#{1,6}\s+", "", stripped)[:40], [])
            continue
        if _APH_ITEM.match(stripped):
            continue
        if profile == "resume" and _APH_LABEL.match(stripped):
            continue
        units.extend(s.strip() for s in SENT_SPLIT.split(stripped) if s.strip())
    if units or not sections:
        sections.append((name, units))
    return sections


def _aph_shape(s):
    """The one shape hit of a sentence, checked colon-kicker first, then
    imperative, copular definition, fragment; None when none matches.
    Heuristics, precision first: the budget rule (at most one kicker per
    section) absorbs the single-shape false positives that remain.
    Antithesis ("not X but Y") is never counted here: the pattern register
    already carries it as negative parallelism, and two families must not
    name the same tell in one repair contract (the tapestry precedent)."""
    words = [w.lower() for w in WORD_RE.findall(s)]
    wc = len(words)
    if not wc or wc > APHORISM_MAX_WORDS:
        return None
    first = words[0]
    if _COLON_KICKER.search(s) and "," not in s.split(":")[-1]:
        return "colon-kicker"
    if first in VERB_FRAMES and first not in _SUBJ_OPENERS and not _DETERMINERS.search(s):
        return "imperative"
    copulas = _COPULA_RX.findall(s)
    head = s.split(copulas[0] if copulas else "", 1)[0] if copulas else ""
    if len(copulas) == 1 and len(head.split()) <= 3 and not _DETERMINERS.search(head):
        return "copular-definition"
    if (first not in VERB_FRAMES and first not in _APH_CONJ and first not in _SUBJ_OPENERS
            and not any(w in _FRAG_AUX for w in words) and not _PAST_FORM.search(s)
            and s.rstrip().endswith(".")):
        return "fragment"
    return None


def aphorism_shapes(sents):
    """The kicker-shape hits of a sentence list (method menu B4): returns
    [(index, shape)] with at most one shape per sentence."""
    return [(i, shape) for i, s in enumerate(sents) if (shape := _aph_shape(s))]


def aphorism_section_counts(text, profile="public"):
    """[(section name, kicker count)] per section of the piece, for the
    budget check and the report row."""
    return [(name, len(aphorism_shapes(sents))) for name, sents in _aph_units(text, profile)]


def aphorism_budget_hits(text, profile="public"):
    """Family-35 budget fail lines: one line per over-budget section, then
    the piece line when the total passes the per-piece budget. The lines
    name the section and the count, never an AI accusation. Exemptions
    follow the existing precedents: --profile resume (labeled lines and
    list items stay out of the count) and the situational table (the
    'humanizer 35' family is off in the chat and email situations)."""
    hits = []
    total = 0
    for name, sents in _aph_units(text, profile):
        n = len(aphorism_shapes(sents))
        total += n
        if n > APHORISM_MAX_PER_SECTION:
            hits.append("humanizer 35 aphorism budget: section '%s' carries %d kicker shapes "
                        "(budget: at most %d per section)"
                        % (name, n, APHORISM_MAX_PER_SECTION))
    if total > APHORISM_MAX_PER_PIECE:
        hits.append("humanizer 35 aphorism budget: the piece carries %d kicker shapes "
                    "(budget: at most %d per piece)" % (total, APHORISM_MAX_PER_PIECE))
    return hits
