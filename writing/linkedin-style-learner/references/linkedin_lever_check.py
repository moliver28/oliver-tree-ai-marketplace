#!/usr/bin/env python3
"""linkedin_lever_check.py: engagement-lever gates from the slot->lever mapping.

Four deterministic gates (Berger&Milkman practical utility, SAGE QJEP 2025
concrete-language sharing effect, contrast-delta framing, specificity lint):
  1. concreteness >= 2 concrete-noun hits per 100 words in the examples
     paragraph (brief mode) or whole body (brief-less mode).
  2. GAP_STAT_PAIR delta >= 5 points when brief carries gap stats.
  3. TAKEAWAY opens with an imperative verb (save trigger). The verb set is
     slots.yaml TAKEAWAY.imperative_verbs unioned with the builtin list
     (builtins alone when the slot registry is unavailable).
  4. specificity lint: vague-fill patterns hard-fail with location.
Config: load_config() per the shared discovery contract
($LINKEDIN_TEMPLATES_DIR/config.json, then
~/.hermes/scripts/linkedin_config.json); used to resolve the effective
templates directory for the slot registry read.
Usage: linkedin_lever_check.py --post FILE [--brief JSON] [--variant V#]
Exit: 0 pass, 1 hard fail. Out: one JSON line {ok, errors, gates:{...}}.
"""
import argparse, json, os, re, sys
from pathlib import Path

# ---------------- shared config (render-identical copy) --------------------
LINKEDIN_CONFIG = Path(__file__).resolve().parent / "linkedin_config.json"
_CFG = None
CFG_LOADED = False


def load_config():
    """Same discovery contract as the other linkedin*.py scripts:
    $LINKEDIN_TEMPLATES_DIR/config.json, then
    ~/.hermes/scripts/linkedin_config.json; neither -> None (defaults)."""
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


def templates_dir(cfg):
    env = os.environ.get("LINKEDIN_TEMPLATES_DIR")
    if env:
        return Path(env).expanduser()
    if cfg and cfg.get("template_dir"):
        return Path(str(cfg["template_dir"])).expanduser()
    return Path(__file__).resolve().parent / "linkedin_templates"


def _strip_comment(line):
    out, q = [], None
    for ch in line:
        if q:
            out.append(ch)
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            out.append(ch)
        elif ch == "#" and (not out or out[-1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def takeaway_slot_spec(tdir):
    """TAKEAWAY (starts_imperative, imperative_verbs) read from slots.yaml
    (the declarative slot registry). Falls back to the built-in verb set
    whenever the registry is absent or unreadable."""
    try:
        text = (tdir / "slots.yaml").read_text(encoding="utf-8")
    except Exception:
        return {}
    m = re.search(r"^TAKEAWAY:\s*$(.*?)(?=^\S)", text, re.S | re.M)
    if not m:
        return {}
    block = "\n".join(_strip_comment(l) for l in m.group(1).splitlines())
    flag = re.search(r"^\s*starts_imperative:\s*(true|false)\s*$", block, re.M)
    verbs = re.search(r"^\s*imperative_verbs:\s*\[([^\]]*)\]", block, re.M)
    return {"starts_imperative": (flag.group(1) == "true") if flag else None,
            "imperative_verbs": ([v.strip() for v in verbs.group(1).split(",") if v.strip()]
                                 if verbs else [])}

CONCRETE_NOUNS = {
    "panel", "participant", "quote", "transcript", "dataset", "row", "table",
    "dashboard", "ticket", "note", "file", "paper", "citation", "source",
    "audit", "log", "ledger", "prompt", "model", "agent", "pipeline", "tool",
    "report", "draft", "doc", "document", "spreadsheet", "form", "script",
    "template", "checklist", "rubric", "interview", "session", "chart",
    "graph", "screenshot", "record", "entry", "queue", "sample", "tag",
    "filter", "query", "field", "fieldwork", "protocol", "test", "check",
    "gate", "export", "summary", "memo", "email", "slack", "meeting",
    "workflow", "process", "archive", "cache", "review", "repo", "database",
}
IMPERATIVES = {
    "build", "log", "expose", "verify", "keep", "run", "ship", "write",
    "make", "name", "put", "stop", "start", "ask", "read", "trace", "capture",
    "record", "require", "surface", "gate", "audit", "label", "route", "tag",
    "hold", "show", "map", "pick", "decide", "measure", "share", "hand",
    "spell", "state", "treat", "design", "keep", "let", "set", "walk",
}
VAGUE_PATTERNS = [
    (r"\bimproves?\s+(the\s+)?(outcomes|results)\b", "vague-outcome"),
    (r"\bmany\s+teams\b", "vague-many-teams"),
    (r"\ba\s+lot\s+of\b", "vague-a-lot"),
    (r"\bvarious\s+(benefits|ways|approaches)\b", "vague-various"),
    (r"\bsignificantly\s+(better|faster|improved)\b", "vague-significantly"),
    (r"\bbetter\s+results\b", "vague-better-results"),
    (r"\bhigher[-\s]quality\b", "vague-higher-quality"),
    (r"\bsome\s+percentage\b", "vague-some-percentage"),
    (r"\bmore\s+efficient\s+than\s+ever\b", "vague-more-efficient"),
]
NOUN_RE = re.compile(r"[A-Za-z][a-z]+")


def split_sentences(text):
    text = re.sub(r"(\d)\.(\d)", r"\1<D>\2", text)
    return [s.replace("<D>", ".").strip() for s in re.split(r"(?<=[.!?])\s+", text.replace("\n", " ").strip()) if s.strip()]


def concreteness_hits(text):
    words = [w.lower() for w in NOUN_RE.findall(text)]
    return sum(1 for w in words if w in CONCRETE_NOUNS), len(words)


def gate_concreteness(body, brief):
    g = {"gate": "concreteness", "ok": True, "detail": None}
    target = body
    if brief and brief.get("story_examples"):
        STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "by", "is", "are", "was", "were", "that", "this", "it", "as", "its", "their", "one", "another", "which", "who", "what", "from", "at", "be", "been", "our", "your"}
        lead = brief["story_examples"][0].lower()
        tokens = [w for w in NOUN_RE.findall(lead) if len(w) > 3 and w not in STOP]
        best, best_score = None, 0
        for p in re.split(r"\n\s*\n", body):
            pl = p.lower()
            score = sum(1 for t in tokens if t in pl)
            if score > best_score:
                best, best_score = p, score
        if best is not None and best_score >= 2:
            target = best
        else:
            g["ok"] = False; g["detail"] = "examples paragraph not found in rendered post (best overlap %d tokens, need >= 2)" % best_score
            return g
    hits, words = concreteness_hits(target)
    g["hits"], g["words"] = hits, words
    if words < 40:
        g["ok"] = False; g["detail"] = "target paragraph too short (%d words) to judge concreteness" % words
        return g
    if hits < 2:
        g["ok"] = False; g["detail"] = "concreteness floor: %d concrete-noun hits in %d words (need >= 2)" % (hits, words)
    return g


def gate_gap_delta(brief):
    if not brief:
        return {"gate": "gap_delta", "ok": True, "detail": "n/a (no brief)"}
    a, b = brief.get("gap_stat_a"), brief.get("gap_stat_b")
    if a is None and b is None:
        return {"gate": "gap_delta", "ok": True, "detail": "n/a (variant has no gap pair)"}
    try:
        a, b = float(re.findall(r"-?\d+(?:\.\d+)?", str(a))[0]), float(re.findall(r"-?\d+(?:\.\d+)?", str(b))[0])
    except (IndexError, ValueError):
        return {"gate": "gap_delta", "ok": False, "detail": "gap stats not numeric: %r / %r" % (a, b)}
    delta = abs(a - b)
    ok = delta >= 5.0
    return {"gate": "gap_delta", "ok": ok, "detail": "delta %.1f %s 5" % (delta, ">=" if ok else "<")}


def gate_takeaway(brief, body, verbs=None):
    verbs = verbs if verbs is not None else IMPERATIVES
    take = None
    if brief and brief.get("takeaway"):
        take = brief["takeaway"]
    else:
        return {"gate": "imperative_takeaway", "ok": True,
                "detail": "warn: brief-less mode, imperative gate not enforced (slot-driven only)"}
    first = re.split(r"[:,;.]", take, maxsplit=1)[0].strip().lower()
    verb_ok = bool(first) and first.split()[0] in verbs
    if verb_ok:
        return {"gate": "imperative_takeaway", "ok": True, "detail": "takeaway opens with '%s'" % first.split()[0]}
    return {"gate": "imperative_takeaway", "ok": False,
            "detail": "takeaway opens with '%s' (need an imperative verb: build/log/expose/verify/...)" % first.split()[0]}


def gate_specificity(body):
    errs = []
    for paras_i, para in enumerate(re.split(r"\n\s*\n", body), 1):
        for pat, code in VAGUE_PATTERNS:
            m = re.search(pat, para, re.I)
            if m:
                errs.append("para%d %s: '%s'" % (paras_i, code, m.group(0)[:60]))
    return {"gate": "specificity", "ok": not errs, "detail": errs or "clean"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", required=True)
    ap.add_argument("--brief")
    ap.add_argument("--variant")
    ap.add_argument("--allow-short", action="store_true",
                    help="skip concreteness gate on posts under 40 words")
    a = ap.parse_args()
    raw = Path(a.post).read_text()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.S)
    body = raw[m.end():] if m else raw
    text = re.sub(r"(?m)^https?://\S+\s*$", "", body)
    brief = None
    if a.brief:
        brief = json.loads(Path(a.brief).read_text())
    gates = []
    if a.allow_short and len(text.split()) < 40:
        gates.append({"gate": "concreteness", "ok": True, "detail": "skipped (short)"})
    else:
        gates.append(gate_concreteness(text, brief))
    gates.append(gate_gap_delta(brief))
    # TAKEAWAY imperative gate: verb set comes from slots.yaml (union with the
    # built-ins); built-ins alone when the registry is unavailable
    tspec = takeaway_slot_spec(templates_dir(load_config()))
    verbs = set(IMPERATIVES) | set(str(v) for v in (tspec.get("imperative_verbs") or []))
    gates.append(gate_takeaway(brief, text, verbs))
    gates.append(gate_specificity(text))
    errors = [f"{g['gate']}: {g['detail']}" for g in gates if not g["ok"]]
    print(json.dumps({"ok": not errors, "errors": errors, "gates": gates}))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
