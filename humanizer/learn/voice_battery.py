#!/usr/bin/env python3
"""voice_battery.py: the Tier A measurement battery (v1, zero LLM).

One shared pass over a text produces every measure of the battery map
(.zcode/agent-tasks/humanizer-measures-map.out.md, section 3a, plus the five
rows the methodologist's re-tier pass added: L2-5, L7-6, L10-15, L11-2,
L11-11). The rows are
the spec: 79 measures in the levels L1 to L11, each with a source paper of
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
# truth). The sync pin in tests/humanizer/test_voice_battery.py fails the
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
# The 291 rare excess style words of Kobak et al. 2025, figure S6 (all excess
# style words of 2024 with frequency below 0.02), read from the stored paper
# PDF (humanizer-papers/P24-kobak-2025); shipped as R1 with a PROVENANCE row.
EXCESS_WORDS = ("accentuates acknowledges acknowledging addresses adept adhered adhering advancement advancements "
                "advancing advocates advocating affirming afflicted aiding akin align aligning aligns alongside "
                "amidst assessments attains attributed augmenting avenue avenues bolster bolstered bolstering "
                "broader burgeoning capabilities capitalizing categorized categorizes categorizing combating "
                "commendable compelling complicates complicating comprehending comprising consequently "
                "consolidates contributing conversely correlating crafted crafting culminating customizing "
                "delineates delve delved delves delving demonstrating dependability dependable detailing "
                "detrimentally diminishes diminishing discern discerned discernible discerning displaying "
                "disrupts distinctions distinctive elevate elevates elevating elucidate elucidates elucidating "
                "embracing emerges emphasises emphasising emphasize emphasizes emphasizing employing employs "
                "empowers emulating emulation enabling encapsulates encompass encompassed encompasses "
                "encompassing endeavors endeavours enduring enhancements enhances ensuring equipping escalating "
                "evaluates evolving exacerbating examines exceeding excels exceptional exceptionally exerting "
                "exhibiting exhibits expedite expediting exploration explores facilitated facilitates "
                "facilitating featuring formidable fostering fosters foundational furnish garnered garnering "
                "gauged grappling groundbreaking groundwork harness harnesses harnessing heighten heightened "
                "hinder hinges hinting hold holds illuminates illuminating imbalances impacting impede impeding "
                "imperative impressive inadequately incorporates incorporating influencing inherent initially innovative "
                "inquiries integrates integrating integration interconnectedness interplay intricacies "
                "intricate intricately introduces invaluable investigates involves juxtaposed leverages "
                "leveraging maintaining merges methodologies meticulous meticulously multifaceted necessitate "
                "necessitates necessitating necessity notable noteworthy nuanced nuances offering optimizing "
                "orchestrating outlines overlook overlooking paving persist pinpoint pinpointed pinpointing "
                "pioneering pioneers pivotal poised pose posed poses posing predominantly preserving pressing "
                "promise pronounced propelling realm realms recognizing refine refines refining remarkable "
                "renowned revealing reveals revolutionize revolutionizing revolves scrutinize scrutinized "
                "scrutinizing seamless seamlessly seeks serves serving shaping shedding showcased showcases "
                "showcasing signifying solidify spanned spanning spurred stands stemming strategically "
                "streamline streamlined streamlines streamlining struggle substantiated substantiates surged "
                "surmount surpass surpassed surpasses surpassing swift swiftly thorough transformative "
                "typically ultimately uncharted uncovering underexplored underscore underscored underscores "
                "underscoring unexplored unlocking unparalleled unraveling unveil unveiled unveiling unveils "
                "uphold upholding urging utilizes varying versatility warranting yielding").split()
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
 C_VERB, C_SUFNOM, C_SUFADJ, C_SUFLY, C_SUFING, C_SUFED, C_SUFPREF, C_LONG, C_DIGIT,
 C_EXCESS) = range(33)
NCLS = 33


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
    put(EXCESS_WORDS, C_EXCESS)
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
    "L2-5": ("L2", "MATTR", "share01", "w", 200, "share_t", None),
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
    "L7-6": ("L7", "function-word PCA projection", "score", "ref", 500, "none", None),
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
    "L10-15": ("L10", "excess-vocabulary rate", "per1000w", "w", 2000, "rate1000w", None),
    "L11-1": ("L11", "Burrows' Delta", "delta", "ref", 500, "none", None),
    "L11-2": ("L11", "Cosine Delta", "cosdist", "ref", 1500, "none", None),
    "L11-4": ("L11", "Jensen-Shannon distance", "jsd", "ref", 500, "none", None),
    "L11-5": ("L11", "Kullback-Leibler divergence", "kl", "ref", 500, "none", None),
    "L11-8": ("L11", "character 3-gram distance", "cosdist", "ref", 500, "none", None),
    "L11-11": ("L11", "full-covariance Delta", "mahal", "ref", 500, "none", None),
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
    "slen": "words", "words": "words", "spread": "spread", "zmean": "mean z", "score": "score",
    "delta": "delta", "jsd": "distance", "kl": "divergence", "cosdist": "distance",
    "mahal": "distance",
}

# MATTR window (Kendro et al. 2025, Method section: window 50). The map
# prototype's window 100 is superseded; the contract test pins the 50.
MATTR_WINDOW = 50

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


def _mattr(toks, win=MATTR_WINDOW):
    """MATTR (Kendro et al. 2025, Method section: the moving-window type-
    token ratio, window 50): the mean type-token ratio over the sliding
    window positions."""
    if not toks:
        return 0.0
    if len(toks) < win:
        return len(set(toks)) / float(len(toks))
    c = {}
    for w in toks[:win]:
        c[w] = c.get(w, 0) + 1
    total = len(c)
    for i in range(win, len(toks)):
        old = toks[i - win]
        c[old] -= 1
        if not c[old]:
            del c[old]
        w = toks[i]
        c[w] = c.get(w, 0) + 1
        total += len(c)
    return total / (float(len(toks) - win + 1) * win)


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


# ---- reference-derived axes (delta1 row specs; R3 user-local, never shipped) ----

def power_iteration(R, iters=200, tol=1.0e-10):
    """Leading eigenvector of a symmetric PSD matrix by power iteration with
    a deterministic all-ones start (delta1 section 4). Returns (v, lambda)."""
    n = len(R)
    u = [1.0 / math.sqrt(n)] * n
    for _ in range(iters):
        nu = [sum(R[i][j] * u[j] for j in range(n)) for i in range(n)]
        norm = math.sqrt(sum(x * x for x in nu))
        if norm == 0:
            break
        nu = [x / norm for x in nu]
        change = math.sqrt(sum((a - b) ** 2 for a, b in zip(u, nu)))
        u = nu
        if change < tol:
            break
    lam = sum(u[i] * R[i][j] * u[j] for i in range(n) for j in range(n))
    return u, lam


def standardized_columns(rate_rows):
    """Column means and sample standard deviations over the reference
    documents (delta1 section 4)."""
    n_w = len(rate_rows[0]) if rate_rows else 0
    mean = [sample_mean([row[w] for row in rate_rows]) for w in range(n_w)]
    sd = [sample_sd([row[w] for row in rate_rows]) for w in range(n_w)]
    return mean, sd


def correlation_matrix(rate_rows, mean, sd):
    """The 60 by 60 correlation matrix of the standardized rate columns
    (divide the covariance by the product of the sample deviations)."""
    k = len(rate_rows)
    n_w = len(mean)
    zrows = [[(row[w] - mean[w]) / sd[w] if sd[w] > 0 else 0.0 for w in range(n_w)]
             for row in rate_rows]
    R = [[0.0] * n_w for _ in range(n_w)]
    for i in range(n_w):
        for j in range(i, n_w):
            s = sum(zr[i] * zr[j] for zr in zrows) / (k - 1) if k > 1 else 0.0
            R[i][j] = R[j][i] = s
    return R, zrows


def first_pca(rate_rows):
    """The FW-PCA of delta1 section 4: standardize each word column, take
    the correlation matrix's leading eigenvector, and return (v1, mean, sd,
    projections) with each reference document's projection."""
    mean, sd = standardized_columns(rate_rows)
    R, zrows = correlation_matrix(rate_rows, mean, sd)
    v1, _lam = power_iteration(R)
    projs = [sum(v1[w] * zr[w] for w in range(len(v1))) for zr in zrows]
    return v1, mean, sd, projs


def cholesky_lower(S):
    """Lower-triangular Cholesky factor of a symmetric positive definite
    matrix (offline; delta1 section 5). Raises ValueError when a diagonal
    entry goes non-positive (rank deficient without shrinkage)."""
    n = len(S)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = S[i][j] - sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                if s <= 0:
                    raise ValueError("matrix not positive definite; shrink first")
                L[i][j] = math.sqrt(s)
            else:
                L[i][j] = s / L[j][j]
    return L


def shrunk_covariance(rate_rows, alpha=0.1):
    """Covariance of the rate columns with the delta1 shrinkage fix
    S' = (1 - alpha) S + alpha diag(S): the off-diagonal entries scale by
    (1 - alpha), the diagonal entries keep their variance (alpha 0.1 is the
    owner-approved value; the shrinkage makes S' positive definite whenever
    every diagonal variance is positive, so the Cholesky solve stays stable
    at k below 61)."""
    n_w = len(rate_rows[0]) if rate_rows else 0
    k = len(rate_rows)
    mean = [sample_mean([row[w] for row in rate_rows]) for w in range(n_w)]
    S = [[0.0] * n_w for _ in range(n_w)]
    for i in range(n_w):
        for j in range(i, n_w):
            s = sum((row[i] - mean[i]) * (row[j] - mean[j]) for row in rate_rows) / (k - 1) if k > 1 else 0.0
            S[i][j] = S[j][i] = s
    for i in range(n_w):
        for j in range(n_w):
            if i != j:
                S[i][j] *= (1.0 - alpha)
    return S, mean


def forward_substitution(L, d):
    """Solve L y = d with a lower-triangular L; returns y."""
    n = len(d)
    y = [0.0] * n
    for i in range(n):
        s = d[i] - sum(L[i][j] * y[j] for j in range(i))
        y[i] = s / L[i][i]
    return y


def mahalanobis_distance(rate_vec, mean_vec, L):
    """The full-covariance Delta of delta1 section 5: the Euclidean norm of
    the forward-substitution solution of L y = (rate - mean)."""
    d = [rate_vec[w] - mean_vec[w] for w in range(len(rate_vec))]
    y = forward_substitution(L, d)
    return math.sqrt(sum(x * x for x in y))


# ---- MMD two-sample (P84 Nieth et al. 2026, read in full; delta2; report
# path, corpus level; owner-approved 2026-11-27) ----

MMD_SEGMENT_WORDS = 500      # pseudo-document size (owned convention)
MMD_RESAMPLES = 200          # B null resamples (owned convention, fixed)
MMD_SEED = 20261127          # fixed seed so the CI is reproducible
MMD_NULL_HALF = 25           # cap on the units per null half (owned cost cap)
MMD_FEATURE_ROWS = (
    "L1-8", "L1-13", "L2-4", "L2-5", "L2-6", "L2-7", "L2-9", "L2-10",
    "L2-11", "L2-12", "L3-1", "L3-3", "L3-4", "L3-5", "L3-6", "L4-1",
    "L4-4", "L4-5", "L4-7", "L5-6", "L5-9", "L6-11", "L8-2", "L9-4",
)


def mmd_segments(text, words=MMD_SEGMENT_WORDS):
    """Pseudo-document segmentation: consecutive full token chunks of `words`
    tokens; a remainder below `words` tokens is dropped (deterministic)."""
    toks = [w.lower() for w in WORD_RE.findall(text)]
    return [toks[i:i + words] for i in range(0, len(toks) - words + 1, words)]


def mmd_feature_vector(vals):
    """The fixed deterministic feature row values of one pseudo-document
    (delta2: the battery feeds the test its own feature vector). A row that
    reads None below its minimum contributes 0.0 (fixed rule, documented)."""
    return [float(vals[mid]) if vals.get(mid) is not None else 0.0
            for mid in MMD_FEATURE_ROWS]


def _mmd2(K, a, b):
    """Biased squared MMD between two unit sets over a precomputed kernel
    matrix: (1/m^2) S_AA + (1/n^2) S_BB - (2/mn) S_AB."""
    sub_a = [K[i] for i in a]
    sub_b = [K[i] for i in b]
    m, n = float(len(a)), float(len(b))
    s_aa = sum(sub_a[i][j] for i in range(len(a)) for j in a)
    s_bb = sum(sub_b[i][j] for i in range(len(b)) for j in b)
    s_ab = sum(sub_a[i][j] for i in range(len(a)) for j in b)
    return s_aa / (m * m) + s_bb / (n * n) - 2.0 * s_ab / (m * n)


def mmd_two_sample(cand_rows, ref_rows, resamples=MMD_RESAMPLES, seed=MMD_SEED,
                   null_half=MMD_NULL_HALF):
    """Squared maximum mean discrepancy with an RBF kernel between the
    candidate pseudo-documents and the reference pool's pseudo-documents
    (P84 section 3.3-3.4; delta2). Bandwidth by the median heuristic on the
    pooled sample. Null calibration: the reference pool splits into two
    exclusive halves resample times (fixed seed), giving the human-human
    distance CI at 0.95. Features are z-scored over the pooled sample.
    Returns a dict with the distance, the CI, and the counts. Pure."""
    cand = [list(r) for r in cand_rows]
    ref = [list(r) for r in ref_rows]
    if not cand or not ref:
        return None
    pooled = cand + ref
    n_w = len(pooled[0])
    # z-score each feature over the pooled sample; a feature with no spread
    # over the pool contributes nothing and drops from the vector
    cols = []
    for w in range(n_w):
        col = [row[w] for row in pooled]
        mu = sample_mean(col)
        sd = sample_sd(col)
        if sd > 0:
            cols.append((w, mu, sd))
    if not cols:
        return None
    z = [[(row[w] - mu) / sd for (w, mu, sd) in cols] for row in pooled]
    n_c, n_r = len(cand), len(ref)
    n = len(z)
    # pairwise squared distances over the pooled sample, upper triangle
    dists = []
    for i in range(n):
        zi = z[i]
        for j in range(i + 1, n):
            zj = z[j]
            dists.append(sum((a - b) ** 2 for a, b in zip(zi, zj)))
    sigma2 = median(dists)
    if sigma2 <= 0:
        sigma2 = 1.0
    # kernel matrix over all pooled units
    K = [[1.0] * n for _ in range(n)]
    for i in range(n):
        zi = z[i]
        for j in range(i + 1, n):
            d2 = sum((a - b) ** 2 for a, b in zip(zi, z[j]))
            k = math.exp(-d2 / (2.0 * sigma2))
            K[i][j] = K[j][i] = k
    cand_idx = list(range(n_c))
    ref_idx = list(range(n_c, n))
    distance = _mmd2(K, cand_idx, ref_idx)
    # null: exclusive halves of the reference pool, seeded
    import random
    rng = random.Random(seed)
    null_pool = list(ref_idx)
    if len(null_pool) > 2 * null_half:
        null_pool = sorted(rng.sample(null_pool, 2 * null_half))
    nulls = []
    for _ in range(resamples):
        shuffled = list(null_pool)
        rng.shuffle(shuffled)
        half = len(shuffled) // 2
        nulls.append(_mmd2(K, shuffled[:half], shuffled[half:]))
    nulls.sort()
    lo_i = max(0, math.ceil(0.025 * resamples) - 1)
    hi_i = min(resamples - 1, math.ceil(0.975 * resamples) - 1)
    return {
        "distance": distance,
        "null_mean": sample_mean(nulls),
        "null_ci_low": nulls[lo_i],
        "null_ci_high": nulls[hi_i],
        "beyond": distance > nulls[hi_i],
        "units_cand": n_c,
        "units_ref": n_r,
        "features": len(cols),
        "resamples": resamples,
        "segment_words": MMD_SEGMENT_WORDS,
        "null_units": len(null_pool),
    }


# ---- variability rows L10-16 and L10-17 (P84 section 6.2 and P86, both read
# in full; delta4; owner-approved 2026-11-27; report path only, never the
# gate; R0; the two rows stay separate, never fused) ----

VAR_SEGMENT_WORDS = 500      # soft limit: include the sentence that crosses it
VAR_MIN_SENTENCES = 20       # a segment with fewer sentences is discarded
VAR_MIN_REF_DOCS = 5         # minimum reference documents (delta4 minimum pool)
VAR_MIN_REF_SEGS = 50        # minimum reference pseudo-documents
VAR_MIN_CAND_SEGS = 10       # minimum candidate pseudo-documents
VAR_SPLITS = 200             # B size-matched split nulls (owned convention)
VAR_SEED = 20261127          # recorded seed so the CI is reproducible
BATTERY_VERSION = "1.3.0"    # the measure-set version stamped into pool vectors

VAR_FEATURE_ROWS = (
    "L1-1", "L1-2", "L1-3", "L1-4", "L1-5", "L1-6", "L1-7", "L1-8", "L1-9",
    "L2-1", "L2-5", "L2-6",
    "L3-1",
    "L4-1",
    "L5-1", "L5-2", "L5-3", "L5-4",
)
# the two features outside the catalog rows: contraction rate (delta4 names
# it in L3; the map row L9-9 stays 3b) and the within-document sentence-length
# SD. Fixed 20-feature order; never add features without re-checking the
# coupling list of P86 table 6.


def variability_segments(text):
    """Sentence-aligned pseudo-documents (delta4 shared machinery): split at
    sentence boundaries into chunks of at least 500 words (the sentence that
    crosses the mark joins the chunk); the last partial chunk is discarded;
    a chunk with fewer than 20 sentences is discarded."""
    sents, _heads, _items, _pw, _pu, _np = _structure(text)
    segs, cur, cur_words = [], [], 0
    for raw in sents:
        w = len(WORD_RE.findall(raw))
        cur.append(raw)
        cur_words += w
        if cur_words >= VAR_SEGMENT_WORDS:
            segs.append(cur)
            cur, cur_words = [], 0
    if cur and cur_words >= VAR_SEGMENT_WORDS:
        segs.append(cur)
    return [seg for seg in segs
            if len(seg) >= VAR_MIN_SENTENCES]


def var_feature_vector(acc, vals):
    """The fixed 20-feature vector of one pseudo-document (delta4: nine L1
    rows, TTR, MATTR, word length, nominalization, contraction rate, mean
    sentence length, the within-document sentence-length SD, and the four
    connective-class rates). A row that reads None contributes 0.0 (fixed
    rule). Deterministic; never extend without re-checking the coupling
    list."""
    lens = acc["lens"]
    sl_sd = (math.sqrt(sum((x - sample_mean(lens)) ** 2 for x in lens) / len(lens))
             if lens else 0.0)

    def val(mid):
        v = vals.get(mid)
        return float(v) if v is not None else 0.0
    return [
        val("L1-1"), val("L1-2"), val("L1-3"), val("L1-4"), val("L1-5"),
        val("L1-6"), val("L1-7"), val("L1-8"), val("L1-9"),
        val("L2-1"), val("L2-5"), val("L2-6"),
        val("L3-1"),
        _per(acc["n_contra"], acc["n"], 1000.0),
        val("L4-1"),
        sl_sd,
        val("L5-1"), val("L5-2"), val("L5-3"), val("L5-4"),
    ]


def var_v(z_rows):
    """V(pool): the sum over the features of the variance of the z-scores
    across the pool's pseudo-documents (divide by n - 1; delta4 V1)."""
    if len(z_rows) < 2:
        return None
    n_w = len(z_rows[0])
    return sum(sample_sd([r[w] for r in z_rows]) ** 2 for w in range(n_w))


def var_reduction(seg_rows):
    """The per-pool reductions of V2: (sd of the mean sentence lengths,
    sd of the intra-document sentence-length SDs) over the pool. Rows here
    are the raw 20-feature vectors (index 14 = m_d, index 15 = s_d)."""
    m_list = [r[14] for r in seg_rows]
    s_list = [r[15] for r in seg_rows]
    return sample_sd(m_list), sample_sd(s_list)


def var_ratios(cand_z_rows, cand_rows, v_ref, sl_ref_sd, ss_ref_sd):
    """The two reported ratios: R_V = V(candidate z-rows) / v_ref (the
    candidate is z-scored by the stored reference means and SDs);
    R_SL = the candidate SD of {m_d} over the reference SD; R_SS likewise
    for {s_d}."""
    v_cand = var_v(cand_z_rows)
    m_sd, s_sd = var_reduction(cand_rows)
    r_v = v_cand / v_ref if v_ref and v_cand is not None else None
    r_sl = m_sd / sl_ref_sd if sl_ref_sd else None
    r_ss = s_sd / ss_ref_sd if ss_ref_sd else None
    return r_v, r_sl, r_ss


def var_null(ref_z_rows, ref_rows, splits=VAR_SPLITS, seed=VAR_SEED):
    """The B size-matched split null (delta4): seeded draws of two disjoint
    equal halves of the reference pseudo-documents; each draw yields the
    ratio V(half1) / V(half2) and the two half-size SD ratios. Returns the
    2.5th and 97.5th percentiles of each. Pure."""
    import random
    n = len(ref_z_rows)
    if n < 4:
        return None
    idx = list(range(n))
    rng = random.Random(seed)
    vs, sls, sss = [], [], []
    for _ in range(splits):
        rng.shuffle(idx)
        half = n // 2
        a, b = idx[:half], idx[half:2 * half]
        va, vb = var_v([ref_z_rows[i] for i in a]), var_v([ref_z_rows[i] for i in b])
        if va and vb and vb > 0:
            vs.append(va / vb)
        ma, sa = var_reduction([ref_rows[i] for i in a])
        mb, sb = var_reduction([ref_rows[i] for i in b])
        if mb > 0 and sb > 0:
            sls.append(ma / mb)
            sss.append(sa / sb)
    if not vs:
        return None
    lo_i = max(0, math.ceil(0.025 * len(vs)) - 1)
    hi_i = min(len(vs) - 1, math.ceil(0.975 * len(vs)) - 1)

    def pct(xs, i):
        return sorted(xs)[min(len(xs) - 1, max(0, i))]
    out = {"seed": seed, "splits": len(vs),
           "v_lo": pct(vs, lo_i), "v_hi": pct(vs, hi_i),
           "v_mean": sample_mean(vs)}
    if sls:
        out["sl_lo"] = pct(sls, min(len(sls) - 1, lo_i))
        out["sl_hi"] = pct(sls, min(len(sls) - 1, hi_i))
    if sss:
        out["ss_lo"] = pct(sss, min(len(sss) - 1, lo_i))
        out["ss_hi"] = pct(sss, min(len(sss) - 1, hi_i))
    return out


def var_verdict(value, lo, hi):
    """Band of one ratio against the stored interval: below (more uniform
    than the author's own spread), above (more scattered), inside."""
    if value is None or lo is None or hi is None:
        return None
    if value < lo:
        return "below"
    if value > hi:
        return "above"
    return "inside"


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
    n_contra = 0
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
        if w.endswith(("n't", "'re", "'ve", "'ll", "'d", "'m")):
            n_contra += 1
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
        "n_contra": n_contra,
        "chars": chars, "curly": curly, "fmt": fmt, "emoji": emoji,
        "phrases": ph, "tri": tri_row,
    }


def values(a, ref=None, window=None):
    """All 79 measure values from one shared pass. Below its minimum a
    measure reads None. ref carries the pooled reference rows for the L11
    distances, the register stats for L10-14, the per-document rate rows and
    the PCA and Cholesky blocks for the reference-derived axes."""
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
    # the reference-derived axes read None until their side data arrives
    # (a seeded 0.0 must never stand for "no axis data")
    if not ref.get("pca"):
        out["L7-6"] = None
    if not ref.get("docs_rates"):
        out["L11-2"] = None
    if not ref.get("chol"):
        out["L11-11"] = None

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
    if want("L2-5"):
        out["L2-5"] = _mattr(a["tokens"])
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
    if want("L10-15"):
        out["L10-15"] = _per(cnt[C_EXCESS], n, 1000.0)
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
    # reference-derived axes: L7-6 PCA projection, L11-2 Cosine Delta,
    # L11-11 full-covariance Delta (delta1 row specs; all ride the existing
    # function-word counts, no new scan)
    cand_rates = None
    if n:
        fwc = a["fwc"]
        cand_rates = [fwc.get(w, 0) * 1000.0 / n for w in FUNCTION_WORDS]
    pca = ref.get("pca")
    if want("L7-6") and pca and cand_rates:
        v1, pmean, psd = pca["v1"], pca["mean"], pca["sd"]
        out["L7-6"] = sum(v1[w] * (cand_rates[w] - pmean[w]) / psd[w]
                          for w in range(len(v1)) if psd[w] > 0 and v1[w])
    chol = ref.get("chol")
    if want("L11-11") and chol and cand_rates:
        words = chol.get("words") or list(FUNCTION_WORDS)
        idx = dict((w, i) for i, w in enumerate(FUNCTION_WORDS))
        d = [cand_rates[idx[w]] - chol["mean"][j] for j, w in enumerate(words)]
        y = forward_substitution(chol["chol_lower"], d)
        out["L11-11"] = math.sqrt(sum(x * x for x in y))
    docs_rates = ref.get("docs_rates")
    fw_mean, fw_sd = ref.get("fw_mean"), ref.get("fw_sd")
    if want("L11-2") and docs_rates and cand_rates and fw_mean and fw_sd:
        if isinstance(fw_mean, dict):
            mean_l = [fw_mean.get(w, 0.0) for w in FUNCTION_WORDS]
            sd_l = [fw_sd.get(w, 0.0) for w in FUNCTION_WORDS]
        else:
            mean_l, sd_l = fw_mean, fw_sd
        keep = [w for w in range(len(FUNCTION_WORDS)) if sd_l[w] > 0]
        zc = [(cand_rates[w] - mean_l[w]) / sd_l[w] for w in keep]
        norm_c = math.sqrt(sum(x * x for x in zc))
        ds = []
        for row in docs_rates:
            zi = [(row[w] - mean_l[w]) / sd_l[w] for w in keep]
            norm_i = math.sqrt(sum(x * x for x in zi))
            if norm_c and norm_i:
                dot = sum(x * y for x, y in zip(zc, zi))
                ds.append(1.0 - dot / (norm_c * norm_i))
        out["L11-2"] = sample_mean(ds) if ds else None
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
