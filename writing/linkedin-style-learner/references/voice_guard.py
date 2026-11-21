#!/usr/bin/env python3
"""voice_guard.py (stage 1): semantic AI-tell gate for any public-facing Michael Oliver text.

Arms, in latency order:
  1. Rules (0ms): deterministic surface patterns from humanizer v2.6.0 (patterns
     9, 23, 27, 28, 31, 32, 33, 34, 35) plus the owner-flagged canonical tells.
  2. Semantic: kNN-over-exemplars + stylometric agreement gate.
     - Each anti-pattern class persists its exemplar (seed) embeddings in the
       state store. A sentence scores a class as the mean of its top-2
       mean-centered cosine similarities to that class's exemplars.
     - A semantic hit is a hard tell error only when the stylometric arm
       agrees: the sentence's 11-feature surface vector (function-word
       density, word count, sentence-length z-score, comma/semicolon/colon/
       question/exclamation counts, starts-with-pronoun, starts-with-there/
       here, contractions), z-scored against the voice corpus, sits within
       the class centroid distance threshold.
     - Semantic hit with stylometric disagreement degrades to a warning,
       unless the kNN margin is >= +0.10 above threshold (stands alone).
  3. Voice fit: per-sentence cosine against the voice corpus (published
     drafts/posts). Bottom-band sentences surface as rewrite warnings.

Thresholds: --init (re)calibrates from the 3 corpus files. kNN threshold per
class sits above the corpus background (bg_p99 + 0.03) but no further than
0.05 under the weakest exemplar self-match; classes where corpus background
collides with exemplar self-similarity degrade to warn-mode.
Stylometric thresholds sit at min(corpus distance) - 0.02, raised to at least
median(seed distance) - 0.04 so typical class members still agree. Feature
z-scores use a 0.20 sigma floor so rare surface flags (there/here openers,
semicolons) cannot dominate the distance.

Ledger: --label-file FILE --label-sent N --label CLASS --verdict tell|clean
--src michael|daneel appends one line to ~/.hermes/state/voice-guard/
labels.jsonl (embeds only the target sentence, not the corpus); --labels
prints per-class label counts as JSON.

Auto-growth loop (stage 1.5): --sync-labels PREV CUR [--src michael|daneel]
sentence-diffs the prev snapshot vs the current kit file (difflib over the
sentence index, exact normalized match), runs the rules + vector arms on
each removed/materially changed prev sentence, and appends one tell row per
error-level hit plus an optional clean row for a passing 1:1 replacement.
Rows are deduped on (class, sentence-hash[:80], verdict, src); prints
{added, skipped_dupes, hits} and exits 0. --auto-init compares the ledger
row count to the persisted ledger_cursor in the store: >=5 new rows
triggers the full --init recalibration (authored seed exemplars only; the
ledger is bookkeeping, not exemplar material, until the stage-2 head),
advances the cursor, and prints {auto_init, new_labels}; exits 0 either
way. Growth paths only append to the ledger and re-run the same init() the
operators run, so the calibrated invariants (corpus sweep, catch test)
cannot loosen mechanically.

Canon arm (owner gold): --init stores 'canon_tells' in the state file with
the six verbatim lines, punctuation-stripped normalized forms, their
exemplar embeddings, and a corpus-safe similarity threshold. A sentence
matching a canon line (normalized containment in either direction, >=3
words on the shorter side) or scoring >= the canon threshold is a
high-confidence catch that bypasses both the stylometric veto and the
normal class threshold; the error and gate row are labeled src:canon
(details.canon_matches carries per-line evidence incl. the matched canon
line and match type). Sentences the rules arm already hard-failed are
subsumed, so each tell sentence reports once.

Init: --init (embeds classes + corpus once; ~1-2s warm). Check: --check FILE.
Exit codes: 0 pass, 1 fail (anti-tell hit), 2 pass-with-warnings.
Out: one JSON line {ok, errors, warnings, secs, arms, details}.
"""
import argparse, difflib, hashlib, http.client, ipaddress, json, math, os, re, socket, sys, time, urllib.parse
from pathlib import Path

try:
    import numpy as np
except Exception:  # pure-python fallback keeps every arm functional
    np = None

STATE = Path.home() / ".hermes/state/voice-guard"
OLLAMA = "http://127.0.0.1:11434/api/embed"
MODEL = "nomic-embed-text"
CATCH = 0.52          # default catch threshold floor (per-class tuned at init)
VOICE_FLOOR = 0.30    # voice-fit warning floor
VOICE_WARN_MAX = 2    # max rewrite warnings before escalation
MARGIN_OVERRIDE = 0.10  # semantic hit that beats stylometric veto if this far above threshold
STYL_EPS = 0.02       # stylometric threshold sits this far under the closest corpus sentence
STYL_SEED_EPS = 0.04  # ... but never more than this under the class's median seed distance
STYL_STD_FLOOR = 0.20 # min sigma for z-scaling: bounds rare flags (there/here, semicolons) at ~5 sigma
LABELS_FILE = STATE / "labels.jsonl"

# ---------------- config (optional; one local loader copy) -----------------
LINKEDIN_CONFIG = Path(__file__).resolve().parent / "linkedin_config.json"
_CFG = None
CFG_LOADED = False


def load_config():
    """Config loader (one local copy per linkedin*.py script; no cross-imports).
    Discovery: $LINKEDIN_TEMPLATES_DIR/config.json first, then
    ~/.hermes/scripts/linkedin_config.json. Neither present -> None: factory
    defaults, byte-identical legacy CLI/output."""
    global _CFG, CFG_LOADED
    if CFG_LOADED:
        return _CFG
    CFG_LOADED = True
    candidates = []
    env = os.environ.get("LINKEDIN_TEMPLATES_DIR")
    if env:
        candidates.append(Path(env).expanduser() / "config.json")
    candidates.append(LINKEDIN_CONFIG)
    for cand in candidates:
        if cand.is_file():
            try:
                _CFG = json.loads(cand.read_text(encoding="utf-8"))
            except Exception as e:
                raise ValueError(f"config unreadable: {cand} ({e})")
            if not isinstance(_CFG, dict):
                raise ValueError(f"config must be a JSON object: {cand}")
            break
    return _CFG


def apply_config():
    """Apply config overrides when a live config exists: ollama_url (embed
    endpoint) and voice_corpus paths. Module globals stay untouched without a
    config file, so CLI/output is byte-identical to the factory defaults."""
    cfg = load_config()
    if not cfg:
        return None
    global OLLAMA, CORPUS_FILES
    ou = cfg.get("ollama_url")
    if ou:
        OLLAMA = str(ou)
    vc = cfg.get("voice_corpus")
    if vc and isinstance(vc, list) and vc:
        CORPUS_FILES = [str(x) for x in vc]
    return cfg

# owner-flagged canonical tells (gold): these lines must hard-fail in ANY
# structural position. The canon arm (exact/normalized containment in either
# direction, or kNN vs calibrated canon exemplars above the canon threshold)
# bypasses both the stylometric veto and the per-class threshold. Calibration
# keeps the voice corpus sweep and the owner-approved samples at zero errors.
CANON_TELLS = [
    "The adoption line is settled. Where human judgment happens is not.",
    "It reads as prudence, and it calms stakeholders. The calm is the problem.",
    "There is real weight there",
    "Here is the case it misses.",
    "Pretending the boundary holds just makes the allocation invisible.",
    "The failure was not the model. It was a pipeline that never had to show its work.",
]

# ---------------- anti-pattern classes ----------------
# Each seed sentence is a canonical exemplar; every exemplar is persisted and
# scored individually (kNN), and seeds also define the stylometric centroids.
CLASSES = {
    "inversion_pair": [
        "The failure was not the model. It was a pipeline that never had to show its work.",
        "It's not just about the beat riding under the vocals; it's part of the aggression and atmosphere.",
        "It's not merely a song, it's a statement.",
        "The problem is not the tool. The problem is the workflow around it.",
        "It's not the price that stings; it's the ambiguity.",
    ],
    "filler_concession": [
        "There is real weight there.",
        "There is real merit to this view, and the hesitation is understandable.",
        "That instinct is understandable, and the concern is reasonable.",
        "There is something to the idea that humans stay in the loop.",
        "It's a fair point, and it deserves a serious answer.",
    ],
    "pivot_marker": [
        "Here is the case it misses.",
        "Here's the uncomfortable shift.",
        "But here's the thing most teams skip.",
        "Here is where the framing falls apart.",
        "That's where most analysis stops, and it shouldn't.",
    ],
    "reassurance": [
        "And that's okay. Plenty of teams start without one.",
        "There's nothing wrong with starting small, and no shame in it.",
        "You're not alone in this, and it's completely normal.",
        "If you have not gotten there yet, that's fine too.",
    ],
    "qa_selfanswer": [
        "What makes an API good? It comes down to predictability.",
        "So what should teams do? The answer is simpler than it looks.",
        "Why does this matter? Because the stakes are real.",
        "Ever wondered why the audit never closes? The reason is boring.",
    ],
    "kicker_punch": [
        "The adoption line is settled. Where human judgment happens is not.",
        "The calm is the problem.",
        "Pretending the boundary holds just makes the allocation invisible.",
        "It just works. Every time.",
        "Not promises. Precision.",
    ],
    "signpost_announce": [
        "That changes everything about how we work.",
        "Let me explain why this matters more than you think.",
        "The shift hiding underneath is bigger than it looks.",
        "What comes next surprised me.",
    ],
    "adverb_opener": [
        "Interestingly, adoption went up.",
        "Crucially, the audit failed at exactly this step.",
        "Importantly, churn rose alongside it.",
        "Ultimately, the numbers argue for patience.",
        "Essentially, the team rebuilt the same gate twice.",
    ],
}

CORPUS_FILES = [
    "/Users/moliver/Documents/uxr-blog/pipeline/why-ux-researchers-undertrust-ai-synthesis/final-draft.md",
    "/Users/moliver/.hermes/cache/web/michaeleoliver.notion.site-01d31214f7.md",
    "/Users/moliver/Documents/uxr-blog/marketing/2026-10-03-why-ux-researchers-undertrust-ai-synthesis/linkedin-post.md",
]
SENT_MIN, SENT_MAX = 4, 45


def split_sentences(text):
    text = re.sub(r"(\d)\.(\d)", r"\1<D>\2", text)
    parts = re.split(r"(?<=[.!?])\s+", text.replace("\n", " ").strip())
    return [s.replace("<D>", ".").strip() for s in parts if s.strip()]


def _post_json(url, body, timeout):
    """POST JSON to the model server. http is allowed only for
    loopback/link-local hosts (the local model server); https elsewhere.
    No userinfo; redirects are never followed."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.username or parts.password or not host:
        raise ValueError("endpoint must have a plain hostname")
    if parts.scheme == "https":
        conn_cls = http.client.HTTPSConnection
    elif parts.scheme == "http":
        _require_local(host)
        conn_cls = http.client.HTTPConnection
    else:
        raise ValueError("only https, or http to a local model server, is supported")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    conn = conn_cls(host, port, timeout=timeout)
    try:
        conn.request("POST", path, body=json.dumps(body).encode(),
                     headers={"Content-Type": "application/json"})
        payload = conn.getresponse().read()
    finally:
        conn.close()
    return json.loads(payload)


def _require_local(host):
    """Every resolved address must be loopback/link-local."""
    for _fam, _typ, _proto, _canon, sockaddr in socket.getaddrinfo(host, None):
        ip = ipaddress.ip_address(sockaddr[0])
        if not (ip.is_loopback or ip.is_link_local):
            raise ValueError(f"{host} resolves outside loopback/link-local")


def embed(texts, timeout=60):
    """Chunked with retry: Ollama's tokenizer subprocess crashes on large or
    unlucky batches; 64-item chunks with one retry keep coverage deterministic."""
    texts = [t if isinstance(t, str) else str(t) for t in texts]
    texts = [t.strip() for t in texts if t and t.strip()]
    if not texts:
        return []
    out = []
    for i in range(0, len(texts), 64):
        chunk = texts[i:i + 64]
        for attempt in (1, 2):
            try:
                out += _post_json(str(OLLAMA), {"model": MODEL, "input": chunk,
                                                "keep_alive": "15m"}, timeout)["embeddings"]
                break
            except Exception:
                if attempt == 2:
                    out += [None] * len(chunk)  # coverage gap: rules arm still applies
                time.sleep(0.4)
    return out


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def load_store():
    return json.loads((STATE / "store.json").read_text())


def save_store(store):
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "store.json").write_text(json.dumps(store))


def corpus_sentences():
    sents = []
    for f in CORPUS_FILES:
        p = Path(f)
        if not p.exists():
            continue
        for para in re.split(r"\n\s*\n", p.read_text()):
            para = para.strip()
            if para.startswith(("---", "#", "|", "```")) or len(para) < 30:
                continue
            for s in split_sentences(para):
                if SENT_MIN <= len(s.split()) <= SENT_MAX and "?" not in s:
                    sents.append(s)
    # dedupe, keep order
    seen, out = set(), []
    for s in sents:
        k = s.lower()[:80]
        if k not in seen:
            seen.add(k); out.append(s)
    return out


def read_stanzas(path):
    raw = Path(path).read_text()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.S)
    body = raw[m.end():] if m else raw
    stanzas = [re.sub(r"\n+", " ", p).strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    stanzas = [st for st in stanzas if not st.lstrip().startswith("#")]  # titles/headings are not prose
    def _is_citation(st):
        return bool(re.match(r"^\[\d+\]", st) or re.search(r"doi\.org|Retrieved\s+from|^[A-Z][a-z]+,\s+[A-Z]\.", st))
    stanzas = [st for st in stanzas if not _is_citation(st)]
    stanzas = [st for st in stanzas if not st.lstrip().startswith("#")]  # titles/headings are not prose
    return stanzas


def flat_sentences(stanzas):
    return [s for st in stanzas for s in split_sentences(st)]


# ---------------- stylometric arm ----------------
FW = frozenset("""a an the and or but nor so yet if because while as of in on at by for with from to
into through over under between against before after during than then that this these those there
here it its is are was were be been am have has had do does did will can not no only just""".split())
PRON_START = frozenset("i you he she it we they this that these those".split())
THEREHERE = frozenset(("there", "here", "there's", "here's"))
CONTRACTIONS = re.compile(
    r"\b(i'm|you're|we're|they're|it's|that's|there's|here's|he's|she's|what's|let's|"
    r"don't|doesn't|didn't|isn't|aren't|won't|can't|couldn't|shouldn't|wouldn't|hasn't|haven't|"
    r"wasn't|weren't|i've|we've|you've|they've|i'll|we'll|you'll|they'll|he'll|she'll|"
    r"i'd|we'd|you'd|he'd|she'd|they'd)\b", re.I)
FEAT_NAMES = ["fw_density", "wc", "len_z", "commas", "semicolons", "colons", "qmarks", "bangs",
              "start_pron", "start_therehere", "contractions"]


def styl_feats(s, len_mean, len_std):
    """11 deterministic surface features for one sentence."""
    words = re.findall(r"[A-Za-z']+", s)
    wc = len(words) or 1
    first = words[0].lower() if words else ""
    return [sum(1 for w in words if w.lower() in FW) / wc, float(wc),
            (wc - len_mean) / (len_std or 1.0),
            s.count(","), s.count(";"), s.count(":"), s.count("?"), s.count("!"),
            1.0 if first in PRON_START else 0.0,
            1.0 if first in THEREHERE else 0.0,
            len(CONTRACTIONS.findall(s))]


def styl_z(vec, mean, std):
    if np is not None:
        return (np.asarray(vec, dtype=float) - np.asarray(mean)) / np.asarray(std)
    return [(x - m) / s for x, m, s in zip(vec, mean, std)]


def styl_dist(zv, centroid):
    if np is not None:
        return float(np.linalg.norm(np.asarray(zv) - np.asarray(centroid)))
    return math.sqrt(sum((x - c) ** 2 for x, c in zip(zv, centroid)))


def knn_score(emb_nc, exemplars_nc):
    """mean of the top-2 mean-centered cosine sims against a class's exemplars."""
    if emb_nc is None:
        return 0.0
    if np is not None:
        sims = np.asarray(exemplars_nc) @ np.asarray(emb_nc)
        top = np.sort(sims)[::-1][:2]
        return float(top.mean())
    sims = sorted((cosine(emb_nc, e) for e in exemplars_nc), reverse=True)
    top = sims[:2] if len(sims) >= 2 else sims + [0.0] * (2 - len(sims))
    return sum(top) / len(top)


def _center_norm_rows(rows, cc):
    """mean-center by corpus centroid and L2-normalize (lists or 2D array in, same out)."""
    if np is not None:
        M = np.asarray(rows, dtype=float) - np.asarray(cc, dtype=float)
        n = np.linalg.norm(M, axis=1, keepdims=True)
        return M / (n + 1e-12)
    out = []
    for e in rows:
        v = [x - y for x, y in zip(e, cc)]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


# ---------------- label ledger ----------------
def label_add(label_file, label_sent, label, verdict, src):
    stanzas = read_stanzas(label_file)
    sents = flat_sentences(stanzas)
    if not (1 <= label_sent <= len(sents)):
        print(json.dumps({"labeled": False, "error": f"--label-sent {label_sent} out of range",
                          "file": label_file, "sentence_count": len(sents)}))
        sys.exit(2)
    s = sents[label_sent - 1]
    store = load_store()
    embs = embed([s])
    sim = None
    e = embs[0] if embs and embs[0] is not None else None
    cd = store.get("classes", {}).get(label)
    if e is not None and cd and cd.get("exemplars"):
        cc = store.get("corpus_centroid")
        e_nc = _center_norm_rows([e], cc)[0]
        ex_nc = _center_norm_rows(cd["exemplars"], cc)
        sim = round(knn_score(e_nc, ex_nc), 3)
    rec = {"date": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": str(label_file),
           "sentence": s, "class": label, "verdict": verdict, "src": src, "sim": sim}
    STATE.mkdir(parents=True, exist_ok=True)
    with open(LABELS_FILE, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps({"labeled": True, "line": rec}))


def labels_report():
    counts = {}
    total = 0
    if LABELS_FILE.exists():
        for line in LABELS_FILE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            cls = rec.get("class", "none")
            d = counts.setdefault(cls, {"tell": 0, "clean": 0})
            v = rec.get("verdict", "tell")
            d[v if v in ("tell", "clean") else "tell"] = d.get(v if v in ("tell", "clean") else "tell", 0) + 1
            total += 1
    out = {cls: {"tell": v["tell"], "clean": v["clean"], "total": v["tell"] + v["clean"]}
           for cls, v in sorted(counts.items())}
    out["_total"] = total
    print(json.dumps(out))


# ---------------- auto-growth loop (sync-labels + auto-init) ----------------
def _norm_sent(s):
    return re.sub(r"\s+", " ", s.strip().lower())


def _canon_norm(s):
    """Punctuation-stripped, case-folded, whitespace-collapsed normalization
    for canon containment matching (absorbs ', . : ; ! ? and quote variants)."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _label_key(class_, sentence, verdict, src):
    """Dedupe key: (class, sentence-hash[:80], verdict, src)."""
    h = hashlib.sha256(_norm_sent(sentence).encode()).hexdigest()[:80]
    return (class_, h, verdict, src)


def _ledger_rows():
    rows = []
    if LABELS_FILE.exists():
        for line in LABELS_FILE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if isinstance(rec, dict):
                rows.append(rec)
    return rows


def _ledger_count():
    return len(_ledger_rows())


def _append_row(rec):
    STATE.mkdir(parents=True, exist_ok=True)
    with open(LABELS_FILE, "a") as f:
        f.write(json.dumps(rec) + "\n")


def _class_sim(sentence, class_, store):
    """kNN similarity of one sentence vs a class's persisted exemplars."""
    cd = store.get("classes", {}).get(class_)
    if not cd or not cd.get("exemplars"):
        return None
    cc = store.get("corpus_centroid")
    embs = embed([sentence])
    e = embs[0] if embs and embs[0] is not None else None
    if e is None or cc is None:
        return None
    e_nc = _center_norm_rows([e], cc)[0]
    ex_nc = _center_norm_rows([x for x in cd["exemplars"] if x is not None], cc)
    if not len(ex_nc):
        return None
    return round(knn_score(e_nc, ex_nc), 3)


def score_single(s, store):
    """Canon + rules + vector arms on one sentence alone, mirroring check()'s
    per-sentence error accounting. Returns error-level hits only:
    [{class, sim, arm, canon?}] (sim=None when evidence has no embedding)."""
    hits, out = [], []
    r_hits = rules_check([s])  # single-sentence stanza: kicker-density can never fire
    embs = embed([s])
    e = embs[0] if embs and embs[0] is not None else None
    cc = store.get("corpus_centroid")
    e_nc = _center_norm_rows([e], cc)[0] if (e is not None and cc is not None) else None
    vector_hit = None
    if e_nc is not None:
        classes = store.get("classes", {})
        ex_nc = {name: _center_norm_rows([x for x in cd.get("exemplars", []) if x is not None], cc)
                 for name, cd in classes.items() if cd.get("exemplars")}
        for name, cd in classes.items():
            if name not in ex_nc or not len(ex_nc[name]):
                continue
            score = knn_score(e_nc, ex_nc[name])
            if score is None:
                continue
            if score >= cd["threshold"] - 1e-9:
                sty = cd.get("stylometric", {})
                if sty.get("centroid"):
                    zv = styl_z(styl_feats(s, store.get("len_mean", 14.0), store.get("len_std", 7.0)),
                                store.get("feat_mean"), store.get("feat_std"))
                    sd_ = styl_dist(zv, sty["centroid"])
                    agrees = sd_ <= sty.get("threshold", 9e9) + 1e-9
                else:
                    agrees = True
                # error-level only: catch-mode class with stylometric agreement
                # or a margin big enough to stand alone (vetoed hits stay warnings)
                if cd["mode"] == "catch" and (agrees or (score - cd["threshold"]) >= MARGIN_OVERRIDE - 1e-9):
                    vector_hit = {"class": name, "sim": round(score, 3), "arm": "vector"}
                break
    # owner-flagged canon arm (same bypass as check(): veto + class threshold off)
    canon = store.get("canon_tells") or {}
    sn = _canon_norm(s)
    c_match, c_line, c_sim = None, None, None
    if sn:
        for cn_i, cn in enumerate(canon.get("norms", [])):
            if min(len(sn.split()), len(cn.split())) >= 3 and (cn in sn or sn in cn):
                c_match, c_line = "exact", cn_i
                break
    canon_nc = _center_norm_rows([x for x in canon.get("exemplars", []) if x is not None], cc) \
        if (canon.get("exemplars") and cc is not None) else None
    if c_sim is None and e_nc is not None and canon_nc is not None:
        c_sim = knn_score(e_nc, canon_nc)
    if c_match is None and c_sim is not None and canon.get("mode", "catch") == "catch" \
            and c_sim >= canon.get("threshold", 9e9) - 1e-9:
        c_match, c_line = "knn", -1
    if c_match is not None:
        if vector_hit:  # class attribution when the class arm also strikes
            attrs = vector_hit
        elif r_hits:
            attrs = {"class": r_hits[0]["class"], "arm": "rules"}
        else:
            attrs = {"class": "canon_tell", "arm": "canon"}
        hits.append({"class": attrs["class"],
                     "sim": round(c_sim, 3) if c_sim is not None else (vector_hit or {}).get("sim"),
                     "arm": "canon", "canon": True, "canon_line": c_line, "match": c_match})
    else:
        if vector_hit:
            hits.append(vector_hit)
        for h in r_hits:
            sim = _class_sim(s, h["class"], store) if e is not None else None
            hits.append({"class": h["class"], "sim": sim, "arm": "rules"})
    seen = set()
    for h in hits:  # canon + rules + vector can strike the same class: one row per class
        if h["class"] in seen:
            continue
        seen.add(h["class"])
        out.append(h)
    return out


def sync_labels(prev_file, cur_file, src):
    """Label the edit: removed/materially changed prev sentences scored as
    tells, clean rows for passing replacements. Deduped against the ledger."""
    out = {"added": 0, "skipped_dupes": 0, "hits": []}
    try:
        pv, cv = Path(prev_file).expanduser(), Path(cur_file).expanduser()
        if not pv.exists() or not cv.exists():
            out["error"] = "missing file: %s" % (prev_file if not pv.exists() else cur_file)
            print(json.dumps(out))
            return
        prev_sents = flat_sentences(read_stanzas(pv))
        cur_sents = flat_sentences(read_stanzas(cv))
        if not prev_sents or not cur_sents:
            out["error"] = "no sentences found"
            print(json.dumps(out))
            return
        sm = difflib.SequenceMatcher(a=[_norm_sent(s) for s in prev_sents],
                                     b=[_norm_sent(s) for s in cur_sents], autojunk=False)
        removed, paired = [], {}
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag in ("delete", "replace"):
                removed += list(range(i1, i2))
            if tag == "replace":
                k = min(i2 - i1, j2 - j1)
                for t in range(k):
                    paired[i1 + t] = j1 + t
        if not removed:
            print(json.dumps(out))
            return
        store = load_store()
        keys = {_label_key(r.get("class", ""), r.get("sentence", ""), r.get("verdict", "tell"), r.get("src", ""))
                for r in _ledger_rows()}
        tell_class = {}
        for i in removed:
            s = prev_sents[i]
            for h in score_single(s, store):
                tell_class.setdefault(i, h["class"])
                k = _label_key(h["class"], s, "tell", src)
                if k in keys:
                    out["skipped_dupes"] += 1
                    continue
                keys.add(k)
                rec = {"date": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": str(cur_file),
                       "sentence": s, "class": h["class"], "verdict": "tell", "src": src, "sim": h.get("sim")}
                if h.get("canon"):
                    rec["canon"] = True
                    rec["canon_line"] = h.get("canon_line")
                    rec["canon_match"] = h.get("match")
                _append_row(rec)
                out["added"] += 1
                out["hits"].append({"file": str(cur_file), "sent": s[:70], "class": h["class"],
                                    "verdict": "tell", "sim": h.get("sim"), "arm": h.get("arm")})
                tell_class.setdefault(i, h["class"])
        for i, cls in tell_class.items():
            j = paired.get(i)
            if j is None:
                continue  # removed without replacement: no clean counterpart
            s2 = cur_sents[j]
            if score_single(s2, store):
                continue  # replacement still flags: no clean example
            k = _label_key(cls, s2, "clean", src)
            if k in keys:
                out["skipped_dupes"] += 1
                continue
            keys.add(k)
            rec = {"date": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": str(cur_file),
                   "sentence": s2, "class": cls, "verdict": "clean", "src": src,
                   "sim": _class_sim(s2, cls, store)}
            _append_row(rec)
            out["added"] += 1
            out["hits"].append({"file": str(cur_file), "sent": s2[:70], "class": cls,
                                "verdict": "clean", "sim": rec["sim"]})
    except Exception as e:
        import traceback
        traceback.print_exc()
        out["error"] = str(e)[:140]
    print(json.dumps(out))


def auto_init():
    """Recalibrate when >=5 ledger rows landed since the persisted cursor."""
    rows = _ledger_rows()
    try:
        cursor = int(load_store().get("ledger_cursor", 0))
    except Exception:
        cursor = 0
    n = max(0, _ledger_count() - cursor)
    if n >= 5:
        init(quiet=True)  # same recalibration operators run; ledger_cursor advances inside init()
        print(json.dumps({"auto_init": True, "new_labels": n}))
    else:
        print(json.dumps({"auto_init": False, "new_labels": n}))
    sys.exit(0)


# ---------------- init ----------------
def init(quiet=False):
    t0 = time.time()
    labels, texts = [], []
    for name, seeds in CLASSES.items():
        texts += seeds; labels.append((name, len(seeds)))
    corpus = corpus_sentences()
    texts += corpus
    embs = embed(texts)
    n_seeds = sum(n for _, n in labels)
    # corpus length stats for the stylometric length z-score
    wcs = [len(s.split()) for s in corpus] or [14.0]
    len_mean = sum(wcs) / len(wcs)
    len_std = (sum((w - len_mean) ** 2 for w in wcs) / len(wcs)) ** 0.5 or 1.0
    cc = [sum(col) / len(cemb) for col in zip(*cemb)] if (cemb := embs[n_seeds:]) else None
    store = {"version": 2, "classes": {}}
    if cc:
        cc = [round(x, 6) for x in cc]
        store["corpus_centroid"] = cc
    # stylometric z-normalization stats from the voice corpus
    craw = [styl_feats(s, len_mean, len_std) for s in corpus]
    mu = [sum(col) / len(col) for col in zip(*craw)] if craw else [0.0] * 11
    sd = [(sum((r[j] - mu[j]) ** 2 for r in craw) / len(craw)) ** 0.5 if craw else 1.0 for j in range(11)]
    sd = [s if s > STYL_STD_FLOOR else STYL_STD_FLOOR for s in sd]
    zc = [styl_z(r, mu, sd) for r in craw]
    store["feat_mean"] = [round(x, 6) for x in mu]
    store["feat_std"] = [round(x, 6) for x in sd]
    store["len_mean"] = round(len_mean, 6)
    store["len_std"] = round(len_std, 6)
    seed_z = {}
    i = 0
    calib = {}
    for name, n in labels:
        seeds_e = embs[i:i + n]; i += n
        seeds_e = [[round(x, 6) for x in e] if e is not None else None for e in seeds_e]
        centroid = [sum(col) / n for col in zip(*[e for e in seeds_e if e is not None])]
        centroid = [round(x, 6) for x in centroid]
        ex_nc = _center_norm_rows([e for e in seeds_e if e is not None], cc)
        self_scores = [knn_score(row, ex_nc) for row in ex_nc]
        min_self = min(self_scores)
        bg_scores = sorted(knn_score(row, ex_nc) for row in _center_norm_rows(cemb, cc))
        bg_p99 = bg_scores[int(len(bg_scores) * 0.99)] if bg_scores else 0.0
        # threshold must clear the voice corpus: colliding classes degrade to
        # warn-only and their bar rises just above the corpus background.
        if bg_p99 >= min_self - 0.01:
            thr = round(bg_p99 + 0.02, 3); mode = "warn"
        else:
            thr = round(max(CATCH, min_self - 0.05, bg_p99 + 0.03), 3); mode = "catch"
        # stylometric centroid + corpus-safe threshold
        seed_z[name] = [styl_z(styl_feats(s, len_mean, len_std), mu, sd)
                        for s in CLASSES[name]]
        ccent = [sum(col) / len(seed_z[name]) for col in zip(*seed_z[name])]
        ccent = [round(x, 6) for x in ccent]
        cdist = sorted(styl_dist(zr, ccent) for zr in zc)
        sdist = sorted(styl_dist(zv, ccent) for zv in seed_z[name])
        styl_thr = round(max((cdist[0] - STYL_EPS) if cdist else 0.0,
                             (sdist[len(sdist) // 2] - STYL_SEED_EPS) if sdist else 0.0), 3)
        store["classes"][name] = {
            "exemplar_texts": CLASSES[name],
            "exemplars": seeds_e,
            "centroid": centroid,  # kept for backward compatibility
            "threshold": thr, "mode": mode,
            "min_seed_sim": round(min_self, 3), "bg_p99": round(bg_p99, 3),
            "stylometric": {"centroid": ccent, "threshold": styl_thr,
                            "corpus_min": round(cdist[0], 3) if cdist else None,
                            "seed_median": round(sdist[len(sdist) // 2], 3) if sdist else None},
        }
        calib[name] = {"knn_threshold": thr, "mode": mode,
                       "min_exemplar_self": round(min_self, 3), "bg_p99": round(bg_p99, 3),
                       "stylometric_threshold": styl_thr,
                       "styl_corpus_min": round(cdist[0], 3) if cdist else None,
                       "styl_seed_median": round(sdist[len(sdist) // 2], 3) if sdist else None,
                       "exemplars": n}
    store["corpus"] = corpus
    store["corpus_embeds"] = [[round(x, 6) for x in e] if e is not None else None for e in cemb]
    # voice-fit floor from within-corpus nearest-neighbor distribution (raw cosine)
    cnc_rows = _center_norm_rows(cemb, [0.0] * len(cemb[0]))
    nn = []
    if np is not None:
        M = np.asarray(cnc_rows)
        sims = M @ M.T  # diagonal stays 1.0 so sims[3] matches the pure-python path
        top4 = np.sort(sims, axis=1)[:, ::-1][:, :4]
        nn = [float(row[3]) for row in top4]
    else:
        for e in cnc_rows:
            sims = sorted((cosine(e, o) for o in cnc_rows), reverse=True)
            nn.append(sims[3] if len(sims) > 3 else sims[-1])
    nn.sort()
    floor = round(nn[int(len(nn) * 0.15)] - 0.02, 3) if nn else VOICE_FLOOR
    store["voice_floor"] = max(0.18, min(0.42, floor))
    # owner-flagged canon arm: exemplars + corpus-safe similarity threshold.
    # Same recipe as the class calibration: above the corpus background, no
    # further than 0.05 under the canon lines' cross-similarity; colliding
    # geometry degrades to the exact/normalized containment path only.
    canon_norms = [_canon_norm(c) for c in CANON_TELLS]
    canon_e = embed(CANON_TELLS)
    canon_ex = [[round(x, 6) for x in e] if e is not None else None for e in canon_e]
    canon_rows_nc = [r for r in _center_norm_rows([e for e in canon_ex if e is not None], cc)] \
        if (cc and any(e is not None for e in canon_ex)) else []
    bg_rows_nc = [r for r in _center_norm_rows(cemb, cc)] if (cc and cemb) else []
    bg_canon = sorted(knn_score(row, canon_rows_nc) for row in bg_rows_nc) \
        if (canon_rows_nc and bg_rows_nc) else []
    bg_p99c = bg_canon[int(len(bg_canon) * 0.99)] if bg_canon else 0.0
    # a rendered canon line self-matches its own stored exemplar, so the
    # detection reference is the self-INCLUSIVE score, not leave-one-out
    min_self_inc = min((round(knn_score(row, canon_rows_nc), 3) for row in canon_rows_nc), default=0.0)
    # threshold: above corpus background (+0.03), at least CATCH, never above
    # the weakest canon self-match (-0.02); colliding geometry degrades to the
    # exact/normalized containment path only.
    if not bg_canon or not min_self_inc or (min_self_inc - 0.02) < CATCH:
        canon_thr, canon_mode = round(bg_p99c + 0.02, 3), "exact"
    else:
        canon_thr = min(max(bg_p99c + 0.03, CATCH), min_self_inc - 0.02)
        canon_thr, canon_mode = round(canon_thr, 3), "catch"
    store["canon_tells"] = {
        "lines": CANON_TELLS,
        "norms": canon_norms,
        "exemplars": canon_ex,
        "threshold": canon_thr, "mode": canon_mode,
        "bg_p99": round(bg_p99c, 3), "min_self_inclusive": min_self_inc,
    }
    # auto-growth cursor: rows already reflected by the latest recalibration
    store["ledger_cursor"] = _ledger_count()
    save_store(store)
    if quiet:
        return
    print(json.dumps({"init": True,
                      "classes": [f"{n}:{calib[n]['mode']}@{calib[n]['knn_threshold']}" for n, _ in labels],
                      "calibration": calib,
                      "corpus": len(corpus),
                      "voice_floor": store["voice_floor"],
                      "secs": round(time.time() - t0, 2)}))


# ---------------- rules arm ----------------
RULE_FLAGS = [
    (r"\b(there\s+is|there's)\s+(real|genuine)\s+(weight|merit|truth)\s+(there|to\s+this|in\s+this)", "filler_concession", "rules"),
    (r"^here('s|\s+is)\s+(the|where)", "pivot_marker", "rules"),
    (r"\b(that'?s\s+okay|that'?s\s+fine|nothing\s+wrong\s+with|no\s+shame\s+in)", "reassurance", "rules"),
    (r"^(so|look),\s", "opener_tic", "rules"),
    (r"^(interestingly|importantly|crucially|notably|essentially|ultimately),\s", "adverb_opener", "rules"),
    (r"\bnot\s+only\b.{0,60}\bbut\s+also\b", "negative_parallelism", "rules"),
    (r"\bit'?s\s+worth\s+(noting|mentioning)", "filler", "rules"),
]


def rules_check(stanzas):
    hits = []
    for si, st in enumerate(stanzas):
        sents = split_sentences(st)
        for si2, s in enumerate(sents):
            low = s.lower()
            for pat, cls, src in RULE_FLAGS:
                if re.search(pat, low) or re.search(pat, low, re.I):
                    hits.append({"class": cls, "sent": s[:90], "full": s, "src": src}); break
            # pronoun-restatement inversion across adjacent sentences
            if re.search(r"\b(is|was|are|were|it'?s)\s+not\b[^.!?]{0,70}[.;]\s*$", low) and si2 + 1 < len(sents):
                nxt = sents[si2 + 1].strip().lower()
                if re.match(r"^(it|that|this)\s+(is|was|'s)\b", nxt):
                    hits.append({"class": "inversion_pair", "sent": (s + " / " + sents[si2 + 1])[:90],
                                 "full": s + " / " + sents[si2 + 1], "src": "rules"})

        # kicker density: CONSECUTIVE staccato runs outside the final stanza
        # (a long evidence sentence legitimately sits between short ones)
        if si < len(stanzas) - 1:
            runs, run = [], 0
            for sq in sents:
                if 2 <= len(sq.split()) <= 8 and sq[-1] in ".!":
                    run += 1
                else:
                    if run:
                        runs.append(run)
                    run = 0
            if run:
                runs.append(run)
            max_run = max(runs) if runs else 0
            if (max_run >= 3) or (max_run == 2 and len(sents) <= 2):
                shorts = [x for x in sents if 2 <= len(x.split()) <= 8]
                hits.append({"class": "kicker_punch", "sent": " / ".join(x[:40] for x in shorts)[:80],
                             "full": " / ".join(shorts), "src": "rules-density"})
    # question answered immediately
    flat = [s for st in stanzas for s in split_sentences(st)]
    for a, b in zip(flat, flat[1:]):
        if "?" in a and re.match(r"^(it\s+comes\s+down|the\s+answer|here'?s|that'?s\s+right|it'?s\s+simple)", b.lower()):
            hits.append({"class": "qa_selfanswer", "sent": (a + " / " + b)[:90],
                         "full": a + " / " + b, "src": "rules"})
    return hits


# ---------------- semantic (kNN + stylometric gate) + voice fit ----------------
def vector_check(stanzas, store, covered_rules=None):
    """Returns (semantic_errors, warnings, gate_rows, styl_counters, canon_meta)."""
    sents = flat_sentences(stanzas)
    styl_meta = {"agrees": 0, "vetoes": 0}
    if not sents:
        return [], [], [], styl_meta, {"errors": 0, "matches": []}
    classes = store["classes"]
    cc = store.get("corpus_centroid")
    embs = embed(sents)
    errors, warns, gate_rows = [], [], []
    # canon arm setup: owner-flagged lines hard-catch before the class scan
    canon = store.get("canon_tells") or {}
    canon_nc = _center_norm_rows([x for x in canon.get("exemplars", []) if x is not None], cc) \
        if (canon.get("exemplars") and cc) else None
    canon_norms = canon.get("norms") or []
    canon_thr = canon.get("threshold", 9e9)
    canon_meta = {"errors": 0, "matches": []}
    # pre-center exemplar matrices once
    ex_nc = {name: _center_norm_rows([e for e in cd.get("exemplars", []) if e is not None], cc)
             for name, cd in classes.items() if cd.get("exemplars")}
    styl_thr = {name: cd.get("stylometric", {}).get("threshold", 9e9) for name, cd in classes.items()}
    styl_cent = {name: cd.get("stylometric", {}).get("centroid") for name, cd in classes.items()}
    # voice-fit setup
    corpus_e = store.get("corpus_embeds") or []
    corpus_nc = _center_norm_rows([e for e in corpus_e if e is not None], [0.0] * 768) if corpus_e else []
    floor = store.get("voice_floor", VOICE_FLOOR)

    for (s, e) in zip(sents, embs):
        if e is None:
            continue
        e_nc = _center_norm_rows([e], cc)[0]
        # owner-flagged canon arm: containment in either direction or kNN vs
        # canon exemplars above the canon threshold. Bypasses the stylometric
        # veto and the per-class threshold; rules-covered sentences are
        # subsumed (they already hard-failed), everything else is a canon error.
        sn = _canon_norm(s)
        c_match, c_line, c_sim = None, None, None
        if sn:
            for cn_i, cn in enumerate(canon_norms):
                if min(len(sn.split()), len(cn.split())) >= 3 and (cn in sn or sn in cn):
                    c_match, c_line = "exact", cn_i
                    break
        if c_match is None and canon_nc is not None and canon.get("mode", "catch") == "catch":
            c_sim = knn_score(e_nc, canon_nc)
            if c_sim >= canon_thr - 1e-9:
                c_match, c_line = "knn", -1
        if c_match is not None:
            row = {"sent": s[:90], "canon_line": c_line, "match": c_match,
                   "sim": round(c_sim, 3) if c_sim is not None else None,
                   "gate": "src:canon"}
            if covered_rules and any(rn and (rn in sn or sn in rn) for rn in covered_rules):
                row["covered_by_rules"] = True
                canon_meta["matches"].append(row)
                continue
            row["covered_by_rules"] = False
            canon_meta["matches"].append(row)
            canon_meta["errors"] += 1
            cthr = canon_thr if c_match == "knn" else None
            gate_rows.append({"sent": s[:90], "class": "canon_tell", "sim": row["sim"],
                              "canon_line": c_line, "match": c_match,
                              "threshold": cthr, "gate": "src:canon"})
            errors.append({"class": "canon_tell", "sent": s[:90],
                           "sim": row["sim"] if row["sim"] is not None else c_match,
                           "gate": "src:canon"})
            continue
        # kNN-over-exemplars semantic candidate (first class above threshold, store order)
        for name, cd in classes.items():
            score = knn_score(e_nc, ex_nc.get(name, [])) if name in ex_nc else 0.0
            if score is None:
                continue
            if score >= cd["threshold"] - 1e-9:
                zv = styl_z(styl_feats(s, store.get("len_mean", 14.0), store.get("len_std", 7.0)),
                            store["feat_mean"], store["feat_std"])
                sd_ = styl_dist(zv, styl_cent[name])
                agrees = sd_ <= styl_thr[name] + 1e-9
                vote = min(((styl_dist(zv, styl_cent[c2]), c2) for c2 in styl_cent), key=lambda t: t[0])
                row = {"sent": s[:90], "class": name, "sim": round(score, 3),
                       "threshold": cd["threshold"], "margin": round(score - cd["threshold"], 3),
                       "styl_d": round(sd_, 2), "styl_thr": styl_thr[name],
                       "styl_vote": vote[1], "mode": cd["mode"]}
                gate_rows.append(row)
                if cd["mode"] != "catch":
                    warns.append({"class": name, "sent": s[:90], "sim": round(score, 3),
                                  "note": "warn-mode class"})
                elif agrees:
                    styl_meta["agrees"] += 1
                    errors.append({"class": name, "sent": s[:90], "sim": round(score, 3),
                                   "gate": "stylometric-agree"})
                elif (score - cd["threshold"]) >= MARGIN_OVERRIDE - 1e-9:
                    styl_meta["vetoes"] += 1
                    errors.append({"class": name, "sent": s[:90], "sim": round(score, 3),
                                   "gate": "margin-standalone"})
                else:
                    styl_meta["vetoes"] += 1
                    warns.append({"class": name, "sent": s[:90], "sim": round(score, 3),
                                  "note": f"semantic hit vetoed by stylometric arm (d={round(sd_, 2)} > {styl_thr[name]})"})
                break
        # voice-fit arm (raw top-1 cosine vs corpus), unchanged behavior
        if len(corpus_nc):
            if np is not None:
                top = float(np.max(np.asarray(corpus_nc, dtype=float) @ np.asarray(e, dtype=float) /
                                   (math.sqrt(sum(x * x for x in e)) or 1.0)))
            else:
                top = max(cosine(e, o) for o in corpus_e if o is not None)
            if top < floor and len(s.split()) >= 5:
                warns.append({"class": "voice_fit", "sent": s[:90], "sim": round(top, 3), "src": "vector"})
    styl_meta["sentences"] = len(sents)
    return errors, warns, gate_rows, styl_meta, canon_meta


def check(path, via_vector=True):
    t0 = time.time()
    stanzas = read_stanzas(path)
    errors, warnings = [], []
    details = {"sentences": len(flat_sentences(stanzas)), "semantic_gate": [], "styl": {"agrees": 0, "vetoes": 0}}
    r_hits = rules_check(stanzas)
    errors += [f"tell-{h['class']}: {h['sent']}" for h in r_hits]
    arms = {"rules": {"verdict": "hit" if r_hits else "clean", "hits": len(r_hits)},
            "semantic": {"verdict": "clean", "errors": 0, "warnings": 0, "standalone_margin_catches": 0},
            "stylometric": {"agree": 0, "veto": 0},
            "voice_fit": {"verdict": "clean", "warnings": 0},
            "canon_hits": 0}
    if via_vector:
        try:
            store = load_store()
            r_norms = {_canon_norm(h.get("full") or h["sent"]) for h in r_hits if h.get("sent")}
            v_err, w, gate_rows, styl_meta, canon_meta = vector_check(stanzas, store, covered_rules=r_norms)
            seen = {e.split(': ', 1)[1][:60] for e in errors}
            for h in v_err:
                if h['sent'][:60] not in seen:
                    errors.append(f"tell-{h['class']}({h['sim']},{h['gate']}) : {h['sent']}")
                    arms["semantic"]["errors"] += 1
                    if h['gate'] == "margin-standalone":
                        arms["semantic"]["standalone_margin_catches"] += 1
            warnings += [f"semantic-{x['class']}({x['sim']})[{x.get('note', '')}]: {x['sent']}"
                         for x in w if x.get("class") != "voice_fit"][:8]
            warnings += [f"voice-{x['class']}({x['sim']}): {x['sent']}" for x in w if x.get("class") == "voice_fit"][:8]
            vf_warn = [x for x in w if x['class'] == 'voice_fit']
            arms["voice_fit"]["warnings"] = min(len(vf_warn), 8)
            if len(vf_warn) > VOICE_WARN_MAX:
                errors.append(f"voice-fit: {len(vf_warn)} sentences below the voice floor (max {VOICE_WARN_MAX})")
            arms["semantic"]["warnings"] = min(len([x for x in w if x.get("class") != "voice_fit"]), 8)
            if arms["semantic"]["errors"] or arms["semantic"]["warnings"]:
                arms["semantic"]["verdict"] = "hit" if arms["semantic"]["errors"] else "warn-only"
            details["semantic_gate"] = gate_rows
            details["styl"] = {"agrees": styl_meta.get("agrees", 0), "vetoes": styl_meta.get("vetoes", 0)}
            details["canon_matches"] = canon_meta.get("matches", [])
            arms["stylometric"] = {"agree": styl_meta.get("agrees", 0), "veto": styl_meta.get("vetoes", 0)}
            arms["canon_hits"] = canon_meta.get("errors", 0)
        except Exception as e:
            warnings.append(f"vector-arm degraded: {str(e)[:80]}")
    ok = not errors
    print(json.dumps({"ok": ok, "errors": errors, "warnings": warnings,
                      "secs": round(time.time() - t0, 2), "arms": arms, "details": details}))
    sys.exit(0 if ok else (2 if warnings and not errors else 1))


if __name__ == "__main__":
    apply_config()  # no live config -> globals unchanged (byte-identical path)
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--check")
    ap.add_argument("--no-vector", action="store_true")
    ap.add_argument("--sync-labels", action="store_true")
    ap.add_argument("--prev", dest="prev_file")
    ap.add_argument("--cur", dest="cur_file")
    ap.add_argument("--auto-init", action="store_true")
    ap.add_argument("--label-file")
    ap.add_argument("--label-sent", type=int)
    ap.add_argument("--label", default="none")
    ap.add_argument("--verdict", choices=["tell", "clean"], default="tell")
    ap.add_argument("--src", choices=["michael", "daneel"], default="michael")
    ap.add_argument("--labels", action="store_true")
    a = ap.parse_args()
    if a.label_file is not None:
        if a.label_sent is None:
            ap.error("--label-file requires --label-sent N")
        label_add(a.label_file, a.label_sent, a.label, a.verdict, a.src)
    elif a.sync_labels:
        if not (a.prev_file and a.cur_file):
            ap.error("--sync-labels requires --prev FILE and --cur FILE")
        sync_labels(a.prev_file, a.cur_file, a.src)
    elif a.auto_init:
        auto_init()
    elif a.labels:
        labels_report()
    elif a.init:
        init()
    elif a.check:
        check(a.check, via_vector=not a.no_vector)
    else:
        ap.print_help()
