#!/usr/bin/env python3
"""voice_battery.py: the 74-row Tier A measurement battery (v1, zero LLM).

One shared pass over a text produces every measure of the battery map
(.zcode/agent-tasks/humanizer-measures-map.out.md, section 3a). The rows are
the spec: 74 measures in the levels L1 to L11, each with a source paper of
status "read in full" and a resource class R0 or R1 (closed lists, 5.6 KB in
all). No packages, corpora, models, or VADER-derived data ship. Standard
library only.

Design (ported from the latency prototype bench.py, athena-measures-bench):
1. Split paragraphs, headings, list items, and sentences one time. Heading
   lines and list items do not count as sentences; they count in L1-12 and in
   the paragraph units.
2. Tokenize one time with the plugin WORD_RE. One dictionary lookup per token
   fills every token-class counter in one loop.
3. One small compiled pattern per phrase alternative, literal first, with the
   left word edge checked in code. v1 carries the three Tier A phrase
   families: L10-2 banned words, L5-10 multiword connectives, L9-12 indirect
   requests.
4. str.count() counts single characters and marks.
5. Ratios, diversity indices, and distances are computed after the loop.

Boundary (unchanged laws):
- Advisory data. This module never gates by itself. hooks/gate.py calls
  fast_core() only, and a battery finding may name at most one of the at most
  5 family-deduped fail lines; the pass line stays byte-identical.
- No public norms: L11 rows and every band read the user's own profile
  (learned/profile.json, battery section). No VADER-derived list ships
  (decision D1b rejected R2).

Minimum words: below its minimum a measure returns None and the report's
length note lists it. Minimums are the estimates of the map section 3a until
the validation run of map section 8 replaces them.

Deviations from the prototype, each per the catalog row (map 3a is the spec):
- Suffix rates carry no exception list (L3-1 to L3-5 count every word with
  the suffix; the row definitions name the known noise words).
- L2-10 lexical density and L8-2 use the plugin stop list of 119 words, not
  the 60-word function list.
- L7-1 involved side uses the form-in-ig class per the catalog row; the
  prototype had swapped in contractions. L7-2 subtracts the modal side per
  the catalog row.
- L9-11 counts please only when it is not the first word of its sentence;
  L9-12 drops "can you" and "may I" (the catalog names both as differences
  to remove before a release).
- L6-11 value = share of sentences with a marked ending (?, !, ellipsis) or
  a negation word; the four parts of the row stay one row.
- L10-13 value = MTLD (the L2-4 value, read against its band).
- L10-11 value = the L4-4 spread; L10-9 value = the L8-1 ratio.

Units and the count floor (map 4.1, 4.2, AM-06): a rate r per 1,000 words in
a candidate of N words carries sampling variance r * 1000 / N. The band step
adds that floor: s_eff = sqrt(s^2 + floor). Shares use p * (1 - p) / n.
Shape measures (medians, ratios, spreads, distances) carry no floor and say
so in the length note.
"""
import importlib.util
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))          # humanizer/learn/

# The tokenizer constants live in voice_battery_core.py (the gate-path fast
# core), byte-identical to build_voice_profile.py (the single source of
# truth). The sync pin in humanizer/tests/test_voice_battery.py fails the
# build if the three files drift.
_core_spec = importlib.util.spec_from_file_location(
    "voice_battery_core_mod", os.path.join(HERE, "voice_battery_core.py"))
core = importlib.util.module_from_spec(_core_spec)
_core_spec.loader.exec_module(core)
WORD_RE = core.WORD_RE
SENT_SPLIT = core.SENT_SPLIT
PARA_SPLIT = core.PARA_SPLIT
HEADING_RE = core.HEADING_RE
ITEM_RE = core.ITEM_RE
PASSIVE_RE = core.PASSIVE_RE

# STOPWORDS (119) and FUNCTION_WORDS (60) come from build_voice_profile.py
# (single source of truth, shared with the STE layer and learn/voice_fit.py).
_bvp_spec = importlib.util.spec_from_file_location(
    "voice_profile_battery", os.path.join(HERE, "build_voice_profile.py"))
bvp = importlib.util.module_from_spec(_bvp_spec)
_bvp_spec.loader.exec_module(bvp)
STOPWORDS = bvp.STOPWORDS
FUNCTION_WORDS = tuple(bvp.FUNCTION_WORDS)

EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u27BF\u2B00-\u2BFF\uFE0F]")
TRI_RE = re.compile(r"(?=([a-z']{3}))")
URL_RE = re.compile(r"(?<!\S)(?:https?://|www\.)\S+")
HASHTAG_RE = re.compile(r"(?<![\w#])#[A-Za-z0-9_]+")
MENTION_RE = re.compile(r"(?<![\w@])@[A-Za-z0-9_]+")

# ---- closed lists (R0/R1). Sources: map section 3a; PROVENANCE.md rows. ----
INTENSIFIERS = "very really basically actually literally definitely certainly".split()
PREPOSITIONS = ("about above across after against along amid among around at before behind below beneath "
                "beside between beyond by despite down during except for from in inside into like near of off "
                "on onto out outside over past per since through throughout till to toward towards under "
                "underneath until up upon via with within without").split()
SUBORDINATORS = ("after although as because before if once since than that though unless until when whenever "
                 "where whereas whether while whilst lest").split()
COORDINATORS = "and or but nor yet so".split()
PRON_I = "i me my mine myself".split()
PRON_WE = "we us our ours ourselves".split()
PRON_YOU = "you your yours yourself yourselves".split()
PRON_P3 = ("he him his himself she her hers herself it its itself they them their theirs themselves "
           "this that these those").split()
PRON_OTHER = "who whom whose which what one someone anyone everyone somebody anybody everybody".split()
MOD_POS = "can may might could".split()
MOD_NEC = "must should ought".split()
MOD_PRED = "will would shall".split()
CONN_ADD = ("and or also too plus furthermore moreover additionally besides likewise similarly further "
            "alternatively").split()
CONN_ADV = ("but yet however nevertheless nonetheless still though although whereas while instead rather anyway "
            "regardless conversely").split()
CONN_CAUS = "because so therefore thus hence consequently accordingly since for otherwise".split()
CONN_TEMP = ("then next afterwards meanwhile finally subsequently later earlier soon until when whenever while "
             "once immediately formerly previously first second third").split()
# Owned selections (map 3a says so for both; the Hyland 2005 lists were not opened).
HEDGES = ("about almost apparently appears approximately argue around assume broadly claim could doubt essentially "
          "estimate fairly feel frequently generally guess indicate infer largely likely mainly may maybe might "
          "mostly often perhaps plausibly possible possibly presumably probably quite rather relatively roughly "
          "seems should sometimes suggest suppose suspect tend typically uncertain unlikely usually would "
          "arguably somewhat nearly partially predominantly rarely seldom").split()
BOOSTERS = ("actually always certainly clearly conclude confidently definitely demonstrate doubtless evidently "
            "incontrovertibly indeed know must never obviously prove realize really show surely think truly "
            "undeniably undoubtedly unquestionably").split()
POLITE = "thanks thank appreciate sorry apologize apologies".split()   # + medial please (sentence block)
MACHINE = ("amidst cacophony camaraderie continuation fleeting grapple ignite intricate palpable pang prioritize "
           "reminder rut shoutout solace tapestry unease unravel vibrant waft underscore").split()  # Reinhart 2024 Table 1
VERBS = ("is are was were be been being am do does did has have had shows show uses use needs need gives give takes "
         "take makes make finds find keeps keep holds hold moves move reads read writes write tests test tracks "
         "track cuts cut adds add opens open closes close checks check compares compare measures measure covers "
         "cover limits limit reduces reduce raises raise drives drive supports support explains explain records "
         "record avoids avoid runs run builds build sends send brings bring kept gets get puts put sees "
         "see says said tells tell thinks think knows know wants want goes go comes come").split()
NEG_SET = frozenset("not no never none nobody nothing neither nor".split())

# token class ids
(C_FUNC, C_PREP, C_SUB, C_COORD, C_PRON, C_I, C_WE, C_YOU, C_P3, C_MODPOS, C_MODNEC, C_MODPRED,
 C_ADD, C_ADV, C_CAUS, C_TEMP, C_HEDGE, C_BOOST, C_POLITE, C_INTENS, C_COPULA, C_THE, C_MACH,
 C_VERB, C_SUFNOM, C_SUFADJ, C_SUFLY, C_SUFING, C_SUFED, C_SUFPREF, C_LONG, C_DIGIT) = range(32)
NCLS = 32


def _lex():
    """One dict: token -> tuple of class ids (one lookup per token)."""
    d = {}

    def put(words, cid):
        for w in words:
            d[w] = d.get(w, ()) + (cid,)
    put(FUNCTION_WORDS, C_FUNC)
    put(PREPOSITIONS, C_PREP)
    put(SUBORDINATORS, C_SUB)
    put(COORDINATORS, C_COORD)
    put(PRON_I + PRON_WE + PRON_YOU + PRON_P3 + PRON_OTHER, C_PRON)
    put(PRON_I, C_I)
    put(PRON_WE, C_WE)
    put(PRON_YOU, C_YOU)
    put(PRON_P3, C_P3)
    put(MOD_POS, C_MODPOS)
    put(MOD_NEC, C_MODNEC)
    put(MOD_PRED, C_MODPRED)
    put(CONN_ADD, C_ADD)
    put(CONN_ADV, C_ADV)
    put(CONN_CAUS, C_CAUS)
    put(CONN_TEMP, C_TEMP)
    put(HEDGES, C_HEDGE)
    put(BOOSTERS, C_BOOST)
    put(POLITE, C_POLITE)
    put(INTENSIFIERS, C_INTENS)
    put("is are was were be been being am".split(), C_COPULA)
    put(("the",), C_THE)
    put(MACHINE, C_MACH)
    put(VERBS, C_VERB)
    return d


LEX = _lex()
FUNCSET = frozenset(FUNCTION_WORDS)
# suffix classes: one search per token; the matched group index picks the class
SUF_RE = re.compile("(?:(tion|sion|ment|ness|ity|ance|ence|ship|hood)|(ful|less|able|ible|ous|ive|al|ic|ary)"
                    "|(ly)|(ing)|(ed))$")
SUF_FIRST = (C_SUFNOM, C_SUFADJ, C_SUFLY, C_SUFING, C_SUFED)
PREFIXES = ("un", "re", "dis", "pre", "non", "over", "under", "mis")

# phrase families (Tier A only). Each alternative keeps its literal first word
# at the start; the left word edge is checked in code (_left_edge).
PHRASE_FAMILIES = {
    # L10-2 banned words and phrases (plugin register; five also in Reinhart 2024 Table 1)
    "L10-2": [
        r"spearhead(?:ed|ing|s)?\b", r"results?[-\s]?driven\b", r"passionate\s+about\b",
        r"proven\s+track\s+record\b", r"game[-\s]?changers?\b", r"best[-\s]?in[-\s]?class\b",
        r"seamless(?:ly)?\b",
        r"delv(?:e|es|ed|ing)\s+(?:deep(?:er|ly)?\s+)?(?:in)?to?\b",
        r"tapestr(?:y|ies)\b", r"supercharg(?:e|es|ed|ing)\b", r"unlocks?(?:ed|ing)?\b",
        r"leverag(?:e|es|ed|ing)\b", r"synerg(?:y|ies|istic)\b", r"cutting[-\s]?edge\b", r"world[-\s]?class\b",
    ],
    # L9-12 indirect requests (Danescu-Niculescu-Mizil et al. 2013, p. 4 and Table 3;
    # "can you" and "may I" removed per the catalog row)
    "L9-12": [
        r"could\s+you\b", r"would\s+you\b", r"would\s+you\s+mind\b",
        r"would\s+it\s+be\s+possible\b", r"by\s+the\s+way\b",
    ],
    # L5-10 multiword connectives (Okulska et al. 2023, p. 8)
    "L5-10": [
        r"in\s+addition\b", r"as\s+a\s+result\b", r"on\s+the\s+other\s+hand\b", r"in\s+contrast\b",
        r"for\s+example\b", r"for\s+instance\b", r"at\s+the\s+same\s+time\b", r"after\s+that\b",
        r"before\s+that\b", r"in\s+the\s+end\b", r"at\s+first\b", r"in\s+summary\b", r"to\s+sum\s+up\b",
        r"above\s+all\b", r"first\s+of\s+all\b",
    ],
}
PHRASE_RX = {}
for _mid, _alts in PHRASE_FAMILIES.items():
    PHRASE_RX[_mid] = [re.compile(a) for a in _alts]

CUR = ("\u201c", "\u201d", "\u2018", "\u2019")   # curly double and single quotes


def _left_edge(low, s):
    return s == 0 or not (low[s - 1].isalnum() or low[s - 1] in "_'-")


# ---- measure spec: id -> (level, name, unit, min_kind, min_val, floor, count_mark) ----
# unit: per1000w | per100w | per1000s | per100s | per1s | share01 | pct100w |
#       ratio | score100w | score1000w | slen | words | spread | zmean |
#       delta | jsd | kl | cosdist
# min_kind: w (words) | s (sentences) | q (quotes) | wc10 (2000 words or 10
#           counts) | pairs | win (windows) | docs | ref (needs a reference)
# floor: the variance floor kind for the band step (map 4.2)
SPEC = {
    "L1-1": ("L1", "em dashes per 1,000 words", "per1000w", "wc10", ("\u2014", 10), "rate1000w", "\u2014"),
    "L1-2": ("L1", "exclamation marks per 1,000 words", "per1000w", "wc10", ("!", 10), "rate1000w", "!"),
    "L1-3": ("L1", "question marks per 1,000 words", "per1000w", "wc10", ("?", 10), "rate1000w", "?"),
    "L1-4": ("L1", "semicolons per 1,000 words", "per1000w", "wc10", (";", 10), "rate1000w", ";"),
    "L1-5": ("L1", "colons per 1,000 words", "per1000w", "wc10", (":", 10), "rate1000w", ":"),
    "L1-6": ("L1", "open parentheses per 1,000 words", "per1000w", "wc10", ("(", 10), "rate1000w", "("),
    "L1-7": ("L1", "other dashes per 1,000 words", "per1000w", "wc10", ("dash", 10), "rate1000w", "dash"),
    "L1-8": ("L1", "commas per sentence", "per1s", "s", 20, "rate1s", ","),
    "L1-9": ("L1", "curly-quote share", "share01", "q", 10, "share_q", None),
    "L1-11": ("L1", "emoji per 1,000 words", "per1000w", "wc10", ("emoji", 10), "rate1000w", "emoji"),
    "L1-12": ("L1", "format marks per 1,000 words", "per1000w", "w", 300, "rate1000w", None),
    "L1-13": ("L1", "lower-case sentence starts per 100 sentences", "per100s", "s", 20, "rate100s", None),
    "L1-14": ("L1", "ellipses per 1,000 words", "per1000w", "wc10", ("ellipsis", 10), "rate1000w", "ellipsis"),
    "L2-1": ("L2", "type-token ratio", "share01", "win", None, "share_t", None),
    "L2-4": ("L2", "MTLD", "words", "w", 100, "none", None),
    "L2-6": ("L2", "mean word length", "ratio", "w", 300, "none", None),
    "L2-7": ("L2", "long-word share", "per100w", "w", 300, "rate100w", None),
    "L2-9": ("L2", "top-word share", "share01", "w", 300, "share_t", None),
    "L2-10": ("L2", "lexical density", "share01", "w", 300, "share_t", None),
    "L2-11": ("L2", "vague intensifier rate", "per100w", "w", 500, "rate100w", None),
    "L2-12": ("L2", "digit share", "per100w", "w", 300, "rate100w", None),
    "L3-1": ("L3", "nominalization rate", "per1000w", "w", 500, "rate1000w", None),
    "L3-2": ("L3", "adjective-suffix rate", "per1000w", "w", 500, "rate1000w", None),
    "L3-3": ("L3", "adverb in -ly rate", "per1000w", "w", 500, "rate1000w", None),
    "L3-4": ("L3", "form in -ing rate", "per1000w", "w", 500, "rate1000w", None),
    "L3-5": ("L3", "past-tense form rate", "per1000w", "w", 500, "rate1000w", None),
    "L3-6": ("L3", "prefix rate", "per1000w", "w", 500, "rate1000w", None),
    "L4-1": ("L4", "mean sentence length", "slen", "s", 20, "none", None),
    "L4-2": ("L4", "median sentence length", "slen", "s", 20, "none", None),
    "L4-3": ("L4", "95th percentile sentence length", "slen", "s", 40, "none", None),
    "L4-4": ("L4", "sentence-length spread", "ratio", "s", 20, "none", None),
    "L4-5": ("L4", "share of sentences over 20 words", "share01", "s", 20, "share_s", None),
    "L4-6": ("L4", "share of sentences of 8 words or fewer", "share01", "s", 20, "share_s", None),
    "L4-7": ("L4", "subordinators per 100 sentences", "per100s", "s", 20, "rate100s", None),
    "L4-8": ("L4", "coordinators per 1,000 words", "per1000w", "w", 300, "rate1000w", None),
    "L4-9": ("L4", "prepositions per 100 words", "per100w", "w", 300, "rate100w", None),
    "L4-10": ("L4", "passive-marker share", "share01", "s", 20, "share_s", None),
    "L4-11": ("L4", "copula rate", "per1000w", "w", 300, "rate1000w", None),
    "L4-16": ("L4", "modal rate", "per1000w", "w", 300, "rate1000w", None),
    "L5-1": ("L5", "connective rate", "per1000w", "w", 500, "rate1000w", None),
    "L5-2": ("L5", "additive connectives", "per1000w", "w", 500, "rate1000w", None),
    "L5-3": ("L5", "adversative connectives", "per1000w", "w", 500, "rate1000w", None),
    "L5-4": ("L5", "causal connectives", "per1000w", "w", 500, "rate1000w", None),
    "L5-5": ("L5", "temporal connectives", "per1000w", "w", 500, "rate1000w", None),
    "L5-6": ("L5", "overlap of adjacent sentences", "share01", "pairs", 10, "share_s", None),
    "L5-9": ("L5", "pronoun rate", "per100w", "w", 300, "rate100w", None),
    "L5-10": ("L5", "multiword connectives", "per1000w", "w", 1000, "rate1000w", None),
    "L6-11": ("L6", "sentence-type profile", "share01", "s", 20, "share_s", None),
    "L7-1": ("L7", "involved-against-informational score", "score100w", "w", 500, "rate100w", None),
    "L7-2": ("L7", "narrative-against-expository score", "score1000w", "w", 500, "rate1000w", None),
    "L7-4": ("L7", "register range of the author", "spread", "docs", 5, "none", None),
    "L8-1": ("L8", "nominal-against-verbal ratio", "ratio", "w", 500, "none", None),
    "L8-2": ("L8", "content words per sentence", "per1s", "s", 20, "rate1s", None),
    "L9-1": ("L9", "reader-address share", "share01", "s", 20, "share_s", None),
    "L9-2": ("L9", "first-person singular rate", "per1000w", "w", 300, "rate1000w", None),
    "L9-3": ("L9", "first-person plural rate", "per1000w", "w", 300, "rate1000w", None),
    "L9-4": ("L9", "hedge rate", "per1000w", "w", 500, "rate1000w", None),
    "L9-5": ("L9", "booster rate", "per1000w", "w", 500, "rate1000w", None),
    "L9-6": ("L9", "possibility modals", "per1000w", "w", 300, "rate1000w", None),
    "L9-7": ("L9", "necessity modals", "per1000w", "w", 300, "rate1000w", None),
    "L9-8": ("L9", "prediction modals", "per1000w", "w", 300, "rate1000w", None),
    "L9-11": ("L9", "politeness markers", "per1000w", "w", 2000, "rate1000w", None),
    "L9-12": ("L9", "indirect requests", "per1000w", "w", 2000, "rate1000w", None),
    "L9-16": ("L9", "direct starts per 100 sentences", "per100s", "s", 20, "rate100s", None),
    "L10-1": ("L10", "marker-word rate", "per1000w", "w", 1000, "rate1000w", None),
    "L10-2": ("L10", "banned words and phrases", "per1000s", "w", 2000, "rate1000s", None),
    "L10-9": ("L10", "noun-heavy marker", "ratio", "w", 500, "none", None),
    "L10-11": ("L10", "sentence-length uniformity", "ratio", "s", 20, "none", None),
    "L10-13": ("L10", "lower lexical diversity", "words", "w", 100, "none", None),
    "L10-14": ("L10", "register-profile mismatch", "zmean", "w", 500, "none", None),
    "L11-1": ("L11", "Burrows' Delta", "delta", "ref", 500, "none", None),
    "L11-4": ("L11", "Jensen-Shannon distance", "jsd", "ref", 500, "none", None),
    "L11-5": ("L11", "Kullback-Leibler divergence", "kl", "ref", 500, "none", None),
    "L11-8": ("L11", "character 3-gram distance", "cosdist", "ref", 500, "none", None),
}
ALL_IDS = tuple(SPEC)                       # definition order = map order
LEVELS = ("L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10", "L11")
LEVEL_NAMES = {
    "L1": "orthography and graphology", "L2": "lexis", "L3": "morphology", "L4": "syntax",
    "L5": "cohesion", "L6": "discourse and rhetoric", "L7": "register dimensions",
    "L8": "information structure", "L9": "pragmatics and tone",
    "L10": "machine-pattern markers", "L11": "distance and authorship",
}
UNIT_TEXT = {
    "per1000w": "per 1,000 words", "per100w": "per 100 words", "per1000s": "per 1,000 sentences",
    "per100s": "per 100 sentences", "per1s": "per sentence", "share01": "share (0 to 1)",
    "ratio": "ratio", "score100w": "score per 100 words", "score1000w": "score per 1,000 words",
    "slen": "words", "words": "words", "spread": "spread", "zmean": "mean z",
    "delta": "delta", "jsd": "distance", "kl": "divergence", "cosdist": "distance",
}

# two-sided 95 percent t quantiles by degrees of freedom, df = 2..49 (k = 3..50).
# Computed by numerical integration of the t CDF (build script in the task
# workspace); cross-checked against the map values at df 2, 3, 4, 5, 9, 19, 49.
T975 = (
    4.3027, 3.1824, 2.7764, 2.5706, 2.4469, 2.3646, 2.3060, 2.2622,
    2.2281, 2.2010, 2.1788, 2.1604, 2.1448, 2.1314, 2.1199, 2.1098,
    2.1009, 2.0930, 2.0860, 2.0796, 2.0739, 2.0687, 2.0639, 2.0595,
    2.0555, 2.0518, 2.0484, 2.0452, 2.0423, 2.0395, 2.0369, 2.0345,
    2.0322, 2.0301, 2.0281, 2.0262, 2.0244, 2.0227, 2.0211, 2.0195,
    2.0181, 2.0167, 2.0154, 2.0141, 2.0129, 2.0117, 2.0106, 2.0096,
)


def t_value(k):
    """t(0.975, k - 1); the df = 49 value serves k above 50; None for k < 3."""
    df = k - 1
    if df < 2:
        return None
    return T975[min(df, 49) - 2]


def band_factor(k):
    """t(0.975, k - 1) * sqrt(1 + 1/k), the 95 percent prediction factor."""
    t = t_value(k)
    if t is None:
        return None
    return t * math.sqrt(1.0 + 1.0 / k)


def sample_sd(xs):
    """Sample standard deviation (divide by k - 1; AM-04). 0.0 below k = 2."""
    k = len(xs)
    if k < 2:
        return 0.0
    mu = sum(xs) / k
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (k - 1))


def sample_mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return 0.0
    mid = n // 2
    return float(xs[mid]) if n % 2 else (xs[mid - 1] + xs[mid]) / 2.0


def verdict(z, t):
    """Band of one standardized distance (map 4.2): inside, near the edge,
    outside. None when z or the t factor is missing."""
    if z is None or t is None:
        return None
    az = abs(z)
    if az <= t:
        return "inside"
    if az <= 1.5 * t:
        return "near the edge"
    return "outside"


def eff_sd(sd, floor_var):
    """s_eff = sqrt(s^2 + floor): the count floor of map 4.2 (AM-06)."""
    return math.sqrt(sd * sd + max(0.0, floor_var))


def floor_variance(unit, mean, n_words, n_sents, quotes=0):
    """Sampling variance floor of one candidate reading, by unit (map 4.1
    length floor). Shape units return 0.0 (no floor; the length note says
    so). Rate floors use the absolute mean: the score rows can sit below
    zero, and a count floor is a magnitude. Share floors clamp the mean to
    the 0 to 1 interval."""
    n = max(0, n_words)
    s = max(0, n_sents)
    if unit == "rate1000w":
        return abs(mean) * 1000.0 / n if n else 0.0
    if unit in ("rate100w", "score100w"):
        return abs(mean) * 100.0 / n if n else 0.0
    if unit == "rate1000s":
        return abs(mean) * 1000.0 / s if s else 0.0
    if unit == "rate100s":
        return abs(mean) * 100.0 / s if s else 0.0
    if unit == "rate1s":
        return abs(mean) / s if s else 0.0
    if unit == "share_s":
        p = min(1.0, max(0.0, mean))
        return p * (1.0 - p) / s if s else 0.0
    if unit == "share_t":
        p = min(1.0, max(0.0, mean))
        return p * (1.0 - p) / n if n else 0.0
    if unit == "share_q":
        p = min(1.0, max(0.0, mean))
        return p * (1.0 - p) / quotes if quotes else 0.0
    return 0.0


def _per(x, n, scale):
    return x * scale / n if n else 0.0


def _mtld(toks, ttr=0.72):
    """MTLD: mean length of the word sequences whose type-token ratio falls
    to 0.72; mean of a forward and a backward pass."""
    def one(seq):
        factors, types, seen = 0.0, {}, 0
        for w in seq:
            seen += 1
            types[w] = types.get(w, 0) + 1
            if len(types) / seen <= ttr:
                factors += 1.0
                types, seen = {}, 0
        if seen:
            factors += (1.0 - len(types) / seen) / (1.0 - ttr)
        return len(seq) / factors if factors else 0.0
    if not toks:
        return 0.0
    return (one(toks) + one(toks[::-1])) / 2.0


def _ttr_windows(toks, window):
    """Type-token ratio over consecutive full windows (map 4.6: compare in
    windows of the reference length only). None without a full window."""
    if not window or len(toks) < window:
        return None
    vals = []
    for i in range(0, len(toks) - window + 1, window):
        part = toks[i:i + window]
        vals.append(len(set(part)) / float(window))
    return sample_mean(vals)


def _js(ca, cb, keys):
    """Jensen-Shannon distance (natural log) between two count rows; 0.5
    count floor on every key."""
    a = [ca.get(k, 0) + 0.5 for k in keys]
    b = [cb.get(k, 0) + 0.5 for k in keys]
    sa, sb, d = float(sum(a)), float(sum(b)), 0.0
    for x, y in zip(a, b):
        p, q, m = x / sa, y / sb, (x / sa + y / sb) / 2.0
        d += 0.5 * (p * math.log(p / m) + q * math.log(q / m))
    return math.sqrt(max(d, 0.0))


def _kl(ca, cb, keys):
    """Kullback-Leibler divergence of the candidate from the reference;
    natural log; 0.5 count floor on every key."""
    a = [ca.get(k, 0) + 0.5 for k in keys]
    b = [cb.get(k, 0) + 0.5 for k in keys]
    sa, sb = float(sum(a)), float(sum(b))
    return sum((x / sa) * math.log((x / sa) / (y / sb)) for x, y in zip(a, b))


def _cos_dist(ca, cb):
    """One minus the cosine between two count dicts."""
    dot = sum(v * cb.get(k, 0) for k, v in ca.items())
    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    return 1.0 - dot / (na * nb) if (na and nb) else 1.0


def _structure(text):
    """Paragraphs, sentences, headings, list items; split one time. Heading
    lines and list items do not produce sentences (they count in L1-12)."""
    sents, heads, items, para_words, para_units, n_paras = [], 0, 0, [], [], 0
    for p in PARA_SPLIT.split(text):
        p = p.strip()
        if not p:
            continue
        n_paras += 1
        nw = nu = 0
        for line in p.split("\n"):
            line = line.strip()
            if not line:
                continue
            nw += len(WORD_RE.findall(line))
            if HEADING_RE.match(line):
                heads += 1
            elif ITEM_RE.match(line):
                items += 1
                nu += 1
            else:
                parts = [s for s in SENT_SPLIT.split(line) if s.strip()]
                sents.extend(parts)
                nu += len(parts)
        para_words.append(nw)
        para_units.append(nu)
    return sents, heads, items, para_words, para_units, n_paras


def scan(text, phrases=True, tri=False):
    """One shared pass. Returns the accumulators every measure reads."""
    toks = [w.lower() for w in WORD_RE.findall(text)]
    n = len(toks)
    sents, heads, items, para_words, para_units, n_paras = _structure(text)
    cnt = [0] * NCLS
    fwc = {}
    lens = []
    n_pass = n_lower = n_you = n_marked = n_direct = n_please_medial = 0
    ov_sum, ov_n = 0.0, 0
    prev_content = None
    for raw in sents:
        ws = [w.lower() for w in WORD_RE.findall(raw)]
        if not ws:
            continue
        lens.append(len(ws))
        if PASSIVE_RE.search(raw):
            n_pass += 1
        if raw[0].islower():
            n_lower += 1
        if "you" in ws or "your" in ws:
            n_you += 1
        if raw.rstrip().endswith(("?", "!", "...", "\u2026")) or not NEG_SET.isdisjoint(ws):
            n_marked += 1
        if ws[0] in ("you", "please"):
            n_direct += 1
        if "please" in ws[1:]:
            n_please_medial += 1
        content = frozenset(w for w in ws if w not in STOPWORDS)
        if prev_content and content:
            ov_sum += len(content & prev_content) / float(len(content))
            ov_n += 1
        prev_content = content
    for w in toks:
        ent = LEX.get(w)
        if ent is not None:
            for c in ent:
                cnt[c] += 1
            if w in FUNCSET:
                fwc[w] = fwc.get(w, 0) + 1
        m = SUF_RE.search(w)
        if m is not None:
            cnt[SUF_FIRST[m.lastindex - 1]] += 1
        if w.startswith(PREFIXES):
            cnt[C_SUFPREF] += 1
        if len(w) >= 7:
            cnt[C_LONG] += 1
        if w[0].isdigit():
            cnt[C_DIGIT] += 1
    chars = {}
    for mark in ("\u2014", "\u2013", "--", "?", "!", ";", ":", "(", ",", "...", "\u2026", "**", "`"):
        chars[mark] = text.count(mark)
    chars["straight"] = text.count('"') + text.count("'")
    curly = sum(text.count(c) for c in CUR)
    fmt = heads + items + chars["**"] + chars["`"] + len(URL_RE.findall(text)) \
        + len(HASHTAG_RE.findall(text)) + len(MENTION_RE.findall(text))
    emoji = len(EMOJI_RE.findall(text))
    tri_row = {}
    if tri and toks:
        for g in TRI_RE.findall(" ".join(toks)):
            tri_row[g] = tri_row.get(g, 0) + 1
    ph = {}
    if phrases:
        low = text.lower()
        for mid, rxs in PHRASE_RX.items():
            hits = 0
            for rx in rxs:
                for m in rx.finditer(low):
                    if _left_edge(low, m.start()):
                        hits += 1
                        break
            ph[mid] = hits
    return {
        "n": n, "ns": len(sents), "np": n_paras, "tokens": toks, "cnt": cnt, "fwc": fwc,
        "lens": lens, "heads": heads, "items": items,
        "para_words": para_words, "para_units": para_units,
        "snt": (n_pass, n_lower, n_you, n_marked, n_direct, n_please_medial, ov_sum, ov_n),
        "chars": chars, "curly": curly, "fmt": fmt, "emoji": emoji,
        "phrases": ph, "tri": tri_row,
    }


def values(a, ref=None, window=None):
    """All 74 measure values from one shared pass. Below its minimum a
    measure reads None. ref carries the pooled reference rows for the L11
    distances and the register stats for L10-14."""
    ref = ref or {}
    n, ns = a["n"], a["ns"]
    cnt = a["cnt"]
    n_pass, n_lower, n_you, n_marked, n_direct, n_please_medial, ov_sum, ov_n = a["snt"]
    pairs = max(0, ns - 1)
    chars = a["chars"]
    quotes = a["curly"] + chars["straight"]
    lens = a["lens"]
    mean_len = sample_mean(lens) if lens else 0.0
    def below_min(mid):
        _lv, _name, _unit, mk, mv, _floor, _mark = SPEC[mid]
        if mk == "w":
            return n < mv
        if mk == "s":
            return ns < mv
        if mk == "q":
            return quotes < mv
        if mk == "wc10":
            mark, need = mv
            total = chars.get(mark, 0)
            if mark == "dash":
                total = chars["\u2013"] + chars["--"]
            elif mark == "emoji":
                total = a["emoji"]
            elif mark == "ellipsis":
                total = chars["..."] + chars["\u2026"]
            return not (n >= 2000 or total >= need)
        if mk == "pairs":
            return pairs < mv
        if mk == "win":
            return _ttr_windows(a["tokens"], window) is None
        if mk == "docs":
            return int(ref.get("docs", 0)) < mv
        if mk == "ref":
            return n < mv or not ref
        return False

    out = {}
    for mid in ALL_IDS:
        out[mid] = None if below_min(mid) else 0.0

    def want(mid):
        return out[mid] is not None

    # L1 character and format rows
    if want("L1-1"):
        out["L1-1"] = _per(chars["\u2014"], n, 1000.0)
    if want("L1-2"):
        out["L1-2"] = _per(chars["!"], n, 1000.0)
    if want("L1-3"):
        out["L1-3"] = _per(chars["?"], n, 1000.0)
    if want("L1-4"):
        out["L1-4"] = _per(chars[";"], n, 1000.0)
    if want("L1-5"):
        out["L1-5"] = _per(chars[":"], n, 1000.0)
    if want("L1-6"):
        out["L1-6"] = _per(chars["("], n, 1000.0)
    if want("L1-7"):
        out["L1-7"] = _per(chars["\u2013"] + chars["--"], n, 1000.0)
    if want("L1-8"):
        out["L1-8"] = chars[","] / float(ns) if ns else 0.0
    if want("L1-9"):
        out["L1-9"] = a["curly"] / float(quotes) if quotes else 0.0
    if want("L1-11"):
        out["L1-11"] = _per(a["emoji"], n, 1000.0)
    if want("L1-12"):
        out["L1-12"] = _per(a["fmt"], n, 1000.0)
    if want("L1-13"):
        out["L1-13"] = n_lower * 100.0 / ns if ns else 0.0
    if want("L1-14"):
        out["L1-14"] = _per(chars["..."] + chars["\u2026"], n, 1000.0)
    # L2 lexis
    if want("L2-1"):
        out["L2-1"] = _ttr_windows(a["tokens"], window)
    if want("L2-4"):
        out["L2-4"] = _mtld(a["tokens"])
    if want("L2-6"):
        out["L2-6"] = sum(len(w) for w in a["tokens"]) / float(n) if n else 0.0
    if want("L2-7"):
        out["L2-7"] = _per(cnt[C_LONG], n, 100.0)
    content_total = sum(1 for w in a["tokens"] if w not in STOPWORDS)
    content_counts = {}
    for w in a["tokens"]:
        if w not in STOPWORDS:
            content_counts[w] = content_counts.get(w, 0) + 1
    if want("L2-9"):
        out["L2-9"] = max(content_counts.values()) / float(content_total) if content_total else 0.0
    if want("L2-10"):
        out["L2-10"] = content_total / float(n) if n else 0.0
    if want("L2-11"):
        out["L2-11"] = _per(cnt[C_INTENS], n, 100.0)
    if want("L2-12"):
        out["L2-12"] = _per(cnt[C_DIGIT], n, 100.0)
    # L3 morphology (suffix classes; no exception list per the catalog rows)
    for mid, cls in (("L3-1", C_SUFNOM), ("L3-2", C_SUFADJ), ("L3-3", C_SUFLY),
                     ("L3-4", C_SUFING), ("L3-5", C_SUFED), ("L3-6", C_SUFPREF)):
        if want(mid):
            out[mid] = _per(cnt[cls], n, 1000.0)
    # L4 syntax
    if lens:
        if want("L4-1"):
            out["L4-1"] = mean_len
        if want("L4-2"):
            sl = sorted(lens)
            m = len(sl) // 2
            out["L4-2"] = float(sl[m]) if len(sl) % 2 else (sl[m - 1] + sl[m]) / 2.0
        if want("L4-3"):
            sl = sorted(lens)
            out["L4-3"] = float(sl[max(0, math.ceil(0.95 * len(sl)) - 1)])
        if want("L4-4") or want("L10-11"):
            cv = (math.sqrt(sum((x - mean_len) ** 2 for x in lens) / len(lens)) / mean_len) if mean_len else 0.0
            if want("L4-4"):
                out["L4-4"] = cv
            if want("L10-11"):
                out["L10-11"] = cv
        if want("L4-5"):
            out["L4-5"] = sum(1 for x in lens if x > 20) / float(len(lens))
        if want("L4-6"):
            out["L4-6"] = sum(1 for x in lens if x <= 8) / float(len(lens))
    if want("L4-7"):
        out["L4-7"] = cnt[C_SUB] * 100.0 / ns if ns else 0.0
    if want("L4-8"):
        out["L4-8"] = _per(cnt[C_COORD], n, 1000.0)
    if want("L4-9"):
        out["L4-9"] = _per(cnt[C_PREP], n, 100.0)
    if want("L4-10"):
        out["L4-10"] = n_pass / float(ns) if ns else 0.0
    if want("L4-11"):
        out["L4-11"] = _per(cnt[C_COPULA], n, 1000.0)
    if want("L4-16"):
        out["L4-16"] = _per(cnt[C_MODPOS] + cnt[C_MODNEC] + cnt[C_MODPRED], n, 1000.0)
    # L5 cohesion
    if want("L5-1"):
        out["L5-1"] = _per(cnt[C_ADD] + cnt[C_ADV] + cnt[C_CAUS] + cnt[C_TEMP], n, 1000.0)
    for mid, cls in (("L5-2", C_ADD), ("L5-3", C_ADV), ("L5-4", C_CAUS), ("L5-5", C_TEMP)):
        if want(mid):
            out[mid] = _per(cnt[cls], n, 1000.0)
    if want("L5-6"):
        out["L5-6"] = ov_sum / ov_n if ov_n else 0.0
    if want("L5-9"):
        out["L5-9"] = _per(cnt[C_PRON], n, 100.0)
    if want("L5-10"):
        out["L5-10"] = _per(a["phrases"].get("L5-10", 0), n, 1000.0)
    # L6, L8
    if want("L6-11"):
        out["L6-11"] = n_marked / float(ns) if ns else 0.0
    if want("L8-2"):
        out["L8-2"] = content_total / float(ns) if ns else 0.0
    # L7 register scores (raw sides; the band step standardizes them)
    l71 = l72 = None
    if want("L7-1"):
        l71 = _per(cnt[C_PRON] + cnt[C_COPULA] + cnt[C_SUFING] - cnt[C_PREP] - cnt[C_SUFNOM] - cnt[C_LONG],
                   n, 100.0)
        out["L7-1"] = l71
    if want("L7-2"):
        l72 = _per(cnt[C_SUFED] + cnt[C_P3] - cnt[C_MODPOS] - cnt[C_MODNEC] - cnt[C_MODPRED], n, 1000.0)
        out["L7-2"] = l72
    if want("L7-4"):
        reg = ref.get("register") or {}
        out["L7-4"] = reg.get("range")
    if want("L8-1") or want("L10-9"):
        verb_side = cnt[C_VERB] + cnt[C_SUFING] + cnt[C_SUFED] + cnt[C_MODPOS] + cnt[C_MODNEC] + cnt[C_MODPRED]
        ratio = (cnt[C_SUFNOM] + cnt[C_SUFADJ] + cnt[C_THE]) / float(verb_side) if verb_side else 0.0
        if want("L8-1"):
            out["L8-1"] = ratio
        if want("L10-9"):
            out["L10-9"] = ratio
    # L9 pragmatics and tone
    if want("L9-1"):
        out["L9-1"] = n_you / float(ns) if ns else 0.0
    for mid, cls in (("L9-2", C_I), ("L9-3", C_WE), ("L9-4", C_HEDGE), ("L9-5", C_BOOST),
                     ("L9-6", C_MODPOS), ("L9-7", C_MODNEC), ("L9-8", C_MODPRED)):
        if want(mid):
            out[mid] = _per(cnt[cls], n, 1000.0)
    if want("L9-11"):
        out["L9-11"] = _per(cnt[C_POLITE] + n_please_medial, n, 1000.0)
    if want("L9-12"):
        out["L9-12"] = _per(a["phrases"].get("L9-12", 0), n, 1000.0)
    if want("L9-16"):
        out["L9-16"] = n_direct * 100.0 / ns if ns else 0.0
    # L10 machine-pattern markers
    if want("L10-1"):
        out["L10-1"] = _per(cnt[C_MACH], n, 1000.0)
    if want("L10-2"):
        out["L10-2"] = _per(a["phrases"].get("L10-2", 0), ns, 1000.0)
    if want("L10-13"):
        out["L10-13"] = out["L2-4"]
    if want("L10-14"):
        reg = ref.get("register") or {}
        zs = []
        for key, val in (("L7-1", l71), ("L7-2", l72)):
            pair = reg.get(key)
            if pair and val is not None and pair[1] > 0:
                zs.append(abs(val - pair[0]) / pair[1])
        out["L10-14"] = sample_mean(zs) if len(zs) == 2 else None
    # L11 distances (need the pooled reference rows)
    fw_pooled = ref.get("fw_pooled")
    if fw_pooled and n:
        fwc = a["fwc"]
        cand_counts = dict((w, fwc.get(w, 0)) for w in FUNCTION_WORDS)
        cand_counts["(other)"] = max(n - sum(cand_counts.values()), 0)
        keys = list(FUNCTION_WORDS) + ["(other)"]
        if want("L11-4"):
            out["L11-4"] = _js(cand_counts, fw_pooled, keys)
        if want("L11-5"):
            out["L11-5"] = _kl(cand_counts, fw_pooled, keys)
        fw_mean, fw_sd = ref.get("fw_mean"), ref.get("fw_sd")
        if want("L11-1") and fw_mean and fw_sd:
            zs = []
            for w in FUNCTION_WORDS:
                s = fw_sd.get(w, 0.0)
                if s and s > 0:
                    f = cand_counts[w] * 1000.0 / n
                    mu = fw_mean.get(w, 0.0)
                    # AM-06 count floor: s_eff = sqrt(s^2 + r * 1000 / N)
                    se = math.sqrt(s * s + mu * 1000.0 / n)
                    zs.append(abs((f - mu) / se))
            out["L11-1"] = sample_mean(zs) if zs else None
    tri_pooled = ref.get("tri_pooled")
    if want("L11-8"):
        out["L11-8"] = _cos_dist(a["tri"], tri_pooled) if (tri_pooled and a["tri"]) else None
    return out


def run(text, ref=None, window=None):
    """One battery run over one text: scan + values."""
    need_tri = bool(ref and ref.get("tri_pooled"))
    return values(scan(text, phrases=True, tri=need_tri), ref=ref, window=window)


def fast_core(text):
    """Delegate to voice_battery_core.fast_core (the gate path imports the
    small module directly; this alias keeps one call site for tools that
    already hold the full battery)."""
    return core.fast_core(text)


def fw_counts(a):
    """The 60 function-word counts of one document, in FUNCTION_WORDS order."""
    fwc = a["fwc"]
    return [int(fwc.get(w, 0)) for w in FUNCTION_WORDS]


def pooled_counts(rows):
    """Element-wise sum of count rows."""
    return [sum(col) for col in zip(*rows)] if rows else []


def tri_merge(rows):
    """Sum of character 3-gram count dicts."""
    out = {}
    for r in rows:
        for g, c in r.items():
            out[g] = out.get(g, 0) + c
    return out


def ref_block(fw_mean, fw_sd, fw_pooled, register=None, tri_pooled=None, docs=None):
    """The reference dict that values() reads."""
    return {"fw_mean": fw_mean, "fw_sd": fw_sd, "fw_pooled": fw_pooled,
            "register": register or {}, "tri_pooled": tri_pooled, "docs": docs}
