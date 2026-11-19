#!/usr/bin/env python3
"""Mechanical voicebook validator for LinkedIn article posts.

Deterministic gate over marketing/linkedin-voicebook.md rules. Reads a
linkedin-post.md draft; hard-fails on voice violations; prints one JSON line
with stats plus, on request, the exact enriched log line to append after posting.

The template-coverage arm reads the declarative slot registry
(linkedin_templates/slots.yaml: name -> brief_keys) for presence checks, and
the post_types.yaml refusal entries (V4 refuses from data until the brief
carries a non-empty FAILURE_ROW). Template names resolve to skeletons in the
effective templates dir: V-numbers (V1..V5) plus any file-backed V*.md name
(for fixtures). The link-domain gate validates against the configured
url_allowlist (config file discovery: $LINKEDIN_TEMPLATES_DIR/config.json or
~/.hermes/scripts/linkedin_config.json; no config = factory notion.site /
synology-nas defaults, byte-identical legacy behavior). app.notion.com links
are always rejected in code, whatever the config says.

Exit codes: 0 = pass; 1 = hard fail (blocked); 2 = pass with warnings.

Usage:
  linkedin_voicebook_check.py --post FILE --log LOG [--variant V1..V5] [--record]
"""
import argparse, hashlib, http.client, ipaddress, json, os, re, socket, sys, urllib.parse
from pathlib import Path


def _fetch_page(url: str, timeout: float) -> str:
    """GET an https page: no userinfo, resolved hosts must be public (no
    loopback/link-local/private/metadata ranges); redirects are followed
    manually up to 3 hops with re-validation per hop."""
    for _hop in range(4):
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or parts.username or parts.password or not host:
            raise ValueError("only plain https URLs are fetched")
        infos = socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)
        ips = [ipaddress.ip_address(info[4][0]) for info in infos]
        if not ips or any(ip.is_loopback or ip.is_link_local or ip.is_multicast
                          or ip.is_unspecified
                          or (ip.is_private and not ip.is_global) for ip in ips):
            raise ValueError(f"{host} resolves into a refused range")
        conn = http.client.HTTPSConnection(host, parts.port or 443, timeout=timeout)
        try:
            conn.request("GET", (parts.path or "/") + ("?" + parts.query if parts.query else ""),
                         headers={"User-Agent": "facebookexternalhit/1.1"})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                url = urllib.parse.urljoin(url, resp.getheader("Location") or "")
                continue
            page = resp.read().decode("utf-8", "replace")
        finally:
            conn.close()
        return page
    raise ValueError("too many redirects")

VARIANTS = ["V1", "V2", "V3", "V4", "V5"]

BANNED_WORDS = [
    "leverage", "unlock", "supercharge", "game-changer", "journey", "synergy",
    "delve", "tapestry", "delight", "best-in-class", "seamless", "seamlessly",
    "effortlessly", "robust", "in today's rapidly evolving", "let's dive in",
    "dive in", "it's worth noting", "excited to share", "i'm happy to",
    "happy to announce", "new post up", "i just posted", "thrilled to share",
    "deep dive", "unlocking", "let's discuss", "how do you see", "agree?",
    "ready to level", "level up", "want to learn more", "what do you think",
    "drop a comment", "comment below", "reshape",
]
ALLOWED_CAPS = {"AI", "UX", "UXR", "API", "HCI", "ML", "LLM", "OK", "LLMS",
                "UXRS", "AGI", "SEO", "PS", "B2B", "FT", "AS", "RAG"}
ALLOW_LONG_RUN = 25  # words; three consecutive sentences over this = error

TEMPLATE_DIR_FALLBACK = Path(__file__).resolve().parent / "linkedin_templates"
LINKEDIN_CONFIG = Path(__file__).resolve().parent / "linkedin_config.json"

# slot brief-key map now lives in linkedin_templates/slots.yaml (loaded per
# run by slot_registry(); same subset parser copy as linkedin_render.py)


def parse_template_frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    fm["required_slots"] = [s for s in (x.strip() for x in re.split(r"[,\[\]]", fm.get("required_slots", ""))) if s]
    fm["word_floors"] = {int(a): int(b) for a, b in re.findall(r"(\d+)\s*:\s*(\d+)", fm.get("word_floors", ""))}
    return fm, text[m.end():]


# ---------------- shared config + registry (render-identical copies) ------
_CFG = None
CFG_LOADED = False


def load_config():
    """Same discovery contract as linkedin_render.py: $LINKEDIN_TEMPLATES_DIR/
    config.json first, then ~/.hermes/scripts/linkedin_config.json. Neither
    present -> None (factory default, byte-identical legacy behavior)."""
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
    return TEMPLATE_DIR_FALLBACK


def url_allowlisted(url, cfg):
    pats = (cfg or {}).get("url_allowlist")
    if not pats:
        return "notion.site" in url or "synology-nas" in url
    return any(re.search(p, url) for p in pats)


def _yaml_strip_comment(line):
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


def _yaml_scalar(s):
    s = s.strip()
    if s == "":
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    if s == "true":
        return True
    if s == "false":
        return False
    if s in ("null", "~"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _yaml_ws(s, i):
    while i < len(s) and s[i] in " \t":
        i += 1
    return i


def _yaml_flow_key(s, i):
    i = _yaml_ws(s, i)
    if i < len(s) and s[i] in "\"'":
        q = s[i]
        j = s.find(q, i + 1)
        if j < 0:
            raise ValueError("yaml flow: unterminated quote in %r" % s)
        return s[i + 1:j], j + 1
    j = i
    while j < len(s) and s[j] != ":":
        j += 1
    while j > i and s[j - 1] in " \t":
        j -= 1
    if j == i:
        raise ValueError("yaml flow: empty key in %r" % s)
    return _yaml_scalar(s[i:j]), j


def _yaml_flow_node(s, i):
    i = _yaml_ws(s, i)
    if i >= len(s):
        raise ValueError("yaml flow: unexpected end in %r" % s)
    ch = s[i]
    if ch == "[":
        i += 1
        arr = []
        i = _yaml_ws(s, i)
        if i < len(s) and s[i] == "]":
            return arr, i + 1
        while True:
            v, i = _yaml_flow_node(s, i)
            arr.append(v)
            i = _yaml_ws(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
            elif i < len(s) and s[i] == "]":
                return arr, i + 1
            else:
                raise ValueError("yaml flow list: expected ',' or ']' in %r" % s)
    if ch == "{":
        i += 1
        mp = {}
        i = _yaml_ws(s, i)
        if i < len(s) and s[i] == "}":
            return mp, i + 1
        while True:
            k, i = _yaml_flow_key(s, i)
            i = _yaml_ws(s, i)
            if i >= len(s) or s[i] != ":":
                raise ValueError("yaml flow map: expected ':' in %r" % s)
            v, i = _yaml_flow_node(s, i + 1)
            mp[k] = v
            i = _yaml_ws(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
            elif i < len(s) and s[i] == "}":
                return mp, i + 1
            else:
                raise ValueError("yaml flow map: expected ',' or '}' in %r" % s)
    if ch in "\"'":
        q = ch
        j = i + 1
        while j < len(s) and s[j] != q:
            j += 1
        if j >= len(s):
            raise ValueError("yaml flow: unterminated quote in %r" % s)
        return s[i + 1:j], j + 1
    j = i
    while j < len(s) and s[j] not in ",]}":
        j += 1
    while j > i and s[j - 1] in " \t":
        j -= 1
    if j == i:
        raise ValueError("yaml flow: empty scalar in %r" % s)
    return _yaml_scalar(s[i:j]), j


def _yaml_flow(s):
    v, i = _yaml_flow_node(s, 0)
    i = _yaml_ws(s, i)
    if i != len(s):
        raise ValueError("yaml: trailing data after flow scalar: %r" % s[i:])
    return v


def _yaml_block_seq(lines, i, indent):
    out = []
    while i < len(lines):
        ind, content = lines[i]
        if ind < indent or not (content == "-" or content.startswith("- ")):
            break
        if ind != indent:
            break
        rest = content[1:].strip()
        if rest:
            out.append(_yaml_flow(rest))
            i += 1
        else:
            if i + 1 >= len(lines) or lines[i + 1][0] <= indent:
                raise ValueError("yaml seq: dash at %r needs a nested block" % content)
            v, i = _yaml_block(lines, i + 1, lines[i + 1][0])
            out.append(v)
    return out, i


def _yaml_block_map(lines, i, indent):
    out = {}
    while i < len(lines):
        ind, content = lines[i]
        if ind < indent:
            break
        if ind > indent:
            raise ValueError("yaml: unexpected extra indent at %r" % content)
        if content == "-" or content.startswith("- "):
            break
        if ":" not in content:
            raise ValueError("yaml mapping: not a key line: %r" % content)
        key, _, rest = content.partition(":")
        key_s = _yaml_scalar(key.strip())
        if not isinstance(key_s, str):
            raise ValueError("yaml mapping: key must be a string: %r" % content)
        rest = rest.strip()
        if rest:
            if rest == "-" or rest.startswith("- "):
                raise ValueError("yaml: dash values on key lines unsupported: %r" % content)
            out[key_s] = _yaml_flow(rest)
            i += 1
        else:
            if i + 1 < len(lines) and lines[i + 1][0] > indent:
                out[key_s], i = _yaml_block(lines, i + 1, lines[i + 1][0])
            else:
                out[key_s] = None
                i += 1
    return out, i


def _yaml_block(lines, i, indent):
    if lines[i][1] == "-" or lines[i][1].startswith("- "):
        return _yaml_block_seq(lines, i, indent)
    return _yaml_block_map(lines, i, indent)


def parse_yaml_subset(text):
    """Registry YAML subset parser (same code as linkedin_render.py)."""
    lines = []
    for raw in text.splitlines():
        line = _yaml_strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        lines.append((indent, line.strip()))
    if not lines:
        return {}
    val, i = _yaml_block(lines, 0, 0)
    if i != len(lines):
        raise ValueError("yaml: unparsed line %d: %r" % (i + 1, lines[i][1]))
    return val


def slot_registry(tdir):
    return load_registry(tdir / "slots.yaml")


def load_registry(path):
    if not path.is_file():
        raise ValueError(f"slot registry missing: {path}")
    data = parse_yaml_subset(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError(f"slot registry malformed: {path}")
    for name, spec in data.items():
        if not isinstance(spec, dict) or not spec.get("brief_keys"):
            raise ValueError(f"slot registry: '{name}' needs brief_keys")
    return data


def load_post_types_file(tdir):
    p = tdir / "post_types.yaml"
    if not p.is_file():
        return {}
    data = parse_yaml_subset(p.read_text(encoding="utf-8"))
    post_types = (data or {}).get("post_types")
    if not isinstance(post_types, dict):
        raise ValueError(f"post types malformed: {p}")
    return post_types


def post_types_by_variant(ptypes):
    out = {}
    for kind, pt in (ptypes or {}).items():
        v = str(pt.get("variant", "")).strip().upper()
        if v:
            out[v] = (kind, pt)
    return out


def refusal_missing_slots(brief, pt, reg):
    out = []
    for slot in (pt.get("refuse_unless") or []):
        keys = (reg.get(slot) or {}).get("brief_keys") or [slot.lower()]
        if not any(brief.get(k) not in (None, "", [], {}) for k in keys):
            out.append(slot)
    return out


def normalize_ws(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def template_slot_problems(fm, brief, reg, cfg):
    """Presence + fillability of every variant-required slot in the brief.
    brief_keys come from the slots.yaml registry; the LINK public check
    validates against the configured allowlist."""
    missing, invalid = [], []
    for slot in fm.get("required_slots", []):
        keys = reg.get(slot, {}).get("brief_keys")
        if keys is None:
            invalid.append(f"{slot}: template frontmatter names an unknown slot")
            continue
        raws = {k: brief.get(k) for k in keys}
        if all(raws[k] in (None, "", [], {}) for k in keys):
            missing.append("; ".join(f"{slot} (brief key: {k})" for k in keys))
            continue
        for k in keys:
            if raws[k] in (None, "", [], {}):
                invalid.append(f"{slot}: brief key '{k}' empty while sibling keys present")
        if slot == "STAT" and not re.search(r"\d", str(raws["stat"] or "")):
            invalid.append("STAT: brief 'stat' must contain a digit")
        if slot == "GAP_STAT_PAIR":
            for k in keys:
                if not re.search(r"\d", str(raws.get(k) or "")):
                    invalid.append(f"GAP_STAT_PAIR: brief '{k}' must contain a digit")
        if slot in ("STORY_EXAMPLES", "DESIGN_MOVES"):
            v = raws[keys[0]]
            if not isinstance(v, list) or not (2 <= len(v) <= 3):
                invalid.append(f"{slot}: brief needs a 2-3 item array")
            elif any(not isinstance(it, str) or not it.strip() for it in v):
                invalid.append(f"{slot}: empty item in array")
        if slot == "QUESTION_TAIL":
            v = str(raws["question_tail"] or "")
            if v.count("?") != 1 or not re.search(r"\b(you|your)\b", v, re.I):
                invalid.append("QUESTION_TAIL: needs exactly one '?' shaped to the reader's experience (you/your)")
        if slot == "DEFINITION" and not re.search(r"(?<![A-Za-z])is(?![A-Za-z])", str(raws.get("definition") or "")):
            invalid.append("DEFINITION: needs the 'Term is plain-words definition' shape")
        if slot == "LINK":
            v = str(raws["link"] or "")
            if "app.notion.com" in v or not re.fullmatch(r"https://\S+", v) or not url_allowlisted(v, cfg):
                if cfg and cfg.get("url_allowlist"):
                    invalid.append("LINK: must be a public URL on the configured allowlist, never app.notion.com")
                else:
                    invalid.append("LINK: must be a public notion.site URL or the KB mirror, never app.notion.com")
    return missing, invalid


def template_coverage(fm, brief, paras, body):
    """Mechanical coverage checks, run after the default checks pass."""
    cov = []
    hits = re.findall(r"\{\{[^}]{0,80}\}\}", body)
    if hits:
        fail(cov, "unrendered-slot", f"{len(hits)} surviving placeholder(s): " + "; ".join(dict.fromkeys(hits))[:160])
        return cov
    pn = [normalize_ws(p) for p in paras]
    # stat/source stanza: carry the evidence digit or a source token up front
    probes = []
    for k in ("stat", "gap_stat_a", "gap_stat_b", "source"):
        v = normalize_ws(brief.get(k, ""))
        if v:
            probes.append(v[:40])
    idx = next((i for i, t in enumerate(pn) if any(pr and pr in t for pr in probes)), None)
    if idx is None:
        idx = 0  # variant carries no stat slot (V3); paragraph 1 falls back to the source-token check
    window = paras[idx][:210] if paras else ""
    tokens = re.findall(r"[A-Za-z][A-Za-z]{3,}", normalize_ws(brief.get("source", "") + " " + brief.get("stat", "")))
    if not (re.search(r"\d", window) or any(t in window.lower() for t in tokens)):
        fail(cov, "template-hook", f"stanza {idx + 1} first 210 chars carry neither a digit nor a source token")
    # examples stanza: at least two brief examples, in at least two 40+ char clauses
    items = brief.get("story_examples") or []
    eprobes = [normalize_ws(i)[:20] for i in items if isinstance(i, str) and i.strip()]
    counts = [sum(1 for pr in eprobes if pr and pr in t) for t in pn]
    top = max(counts) if counts else 0
    if top < 2:
        fail(cov, "examples-coverage", f"no stanza carries 2+ of the brief examples (best={top})")
    elif top == 2 or top > 2:
        ex_par = paras[counts.index(top)]
        protected = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", ex_par)
        clauses = [c.strip().replace("<DOT>", ".") for c in re.findall(r"[^.!?;]+[.!?;]*", protected) if c.strip()]
        long_n = sum(1 for c in clauses if len(c) >= 40)
        if long_n < 2:
            fail(cov, "examples-coverage", f"examples stanza has {long_n} clause(s) of 40+ chars (need 2)")
    # per-stanza word floors from the skeleton frontmatter
    for i, p in enumerate(paras, 1):
        floor = (fm.get("word_floors") or {}).get(i)
        if floor is not None:
            n = len(words(p))
            if n < floor:
                fail(cov, "template-floor", f"stanza {i} has {n} words, floor {floor} (post body, before link)")
    return cov


def fail(errors, code, detail):
    errors.append(f"{code}: {detail}")


def split_sentences(text):
    text = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", text)  # protect decimals
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.replace("<DOT>", ".").strip() for s in parts if s.strip()]


def words(s):
    return [w for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", s)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--variant", help="override variant (normally the draft's frontmatter)")
    ap.add_argument("--record", action="store_true", help="emit the enriched posted-log line")
    ap.add_argument("--urn", default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--slug", default="")
    ap.add_argument("--keyword", default="", help="primary keyword (DB SEO column) enforced in body")
    ap.add_argument("--topics", default="", help="comma-separated topic keywords for cross-post consistency")
    ap.add_argument("--check-og", action="store_true", help="verify og:title/og:description on the linked URL (crawler UA)")
    ap.add_argument("--template", help="template coverage mode: template name (requires --slots-file; V-numbers plus any file-backed V*.md skeleton; refusal entries from post_types.yaml apply)")
    ap.add_argument("--slots-file", help="brief JSON for template coverage (requires --template)")
    a = ap.parse_args()

    cfg = load_config()
    tdir = templates_dir(cfg)

    errors, warnings = [], []
    raw = Path(a.post).read_text(encoding="utf-8")

    # strip frontmatter
    body = raw
    fm = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.S)
    if m:
        body = raw[m.end():]
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip().lower()] = v.strip()

    lines = body.splitlines()
    # link line = last non-empty line; it must be a bare URL
    nonempty = [l for l in lines if l.strip()]
    errors_link = []
    link_line = nonempty[-1].strip() if nonempty else ""
    url = ""
    if re.fullmatch(r"https?://\S+", link_line):
        url = link_line
    else:
        fail(errors_link, "link-line", "final non-empty line must be the bare article URL")
    if url and ":app.notion.com/" in url or url.startswith("https://app.notion.com"):
        fail(errors_link, "link-private", "article link is a private app.notion.com URL")
    if url and not url_allowlisted(url, cfg):
        if cfg and cfg.get("url_allowlist"):
            fail(errors_link, "link-domain", "link is not on the configured public URL allowlist")
        else:
            fail(errors_link, "link-domain", "link is neither a notion.site nor the KB mirror")

    # strip the link line but PRESERVE blank lines (they are the paragraph separators)
    link_idx = max(i for i, l in enumerate(lines) if l.strip()) if url else None
    kept = [l for i, l in enumerate(lines) if link_idx is None or i != link_idx]
    content = "\n".join(kept).strip()
    stanzas = [re.sub(r"\n+", " ", p).strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    stanzas = [st for st in stanzas if not st.lstrip().startswith("#")]  # headings are not paragraphs
    # tolerate a short lead-in right before the link ("Full post:")
    paras = stanzas
    if paras and len(paras[-1].split()) <= 6 and paras[-1].rstrip().endswith(":"):
        paras = paras[:-1]  # link lede line, not a body paragraph

    # voice bans
    low = content.lower()
    for w in BANNED_WORDS:
        if w in low:
            fail(errors, "banned", f"'{w}'")
    if "\u2014" in content or " — " in content or " -- " in content:
        fail(errors, "dash", "em dash or spaced double hyphen present")
    if "!" in content:
        fail(errors, "caps-punc", "exclamation mark present")
    for cap in re.findall(r"\b[A-Z]{2,}\b", content):
        if cap not in ALLOWED_CAPS:
            fail(errors, "caps-punc", f"all-caps '{cap}' not in allowlist")
    for sen in split_sentences(content):
        if re.search(r"\b(it'?s|is|are|was|were)\s+not\b[^.!?]{0,80}\b(it'?s|it is|they are)\b", sen, re.I):
            fail(errors, "inversion", "not-X-but-Y construction: " + sen[:80])
            break

    # variant: explicit frontmatter/arg, rotation from log
    variant = (a.variant or fm.get("variant", "")).upper() or None
    if variant and variant not in VARIANTS:
        fail(errors, "variant", f"unknown variant '{variant}'")
    log_path = Path(a.log)
    entries = []
    if log_path.exists():
        for line in log_path.read_text().splitlines():
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
    posted = [e for e in entries if e.get("posted_at") or e.get("sha256")]
    n = len(posted)
    expected = VARIANTS[n % 5]
    if variant:
        if variant == expected:
            if posted and posted[-1].get("variant") == variant:
                fail(errors, "rotation", f"{variant} would post twice in a row; use {VARIANTS[(VARIANTS.index(variant)+1) % 5]}")
        elif VARIANTS[(VARIANTS.index(expected) + 1) % 5] == variant:
            if posted and posted[-1].get("variant") == expected:
                warnings.append(f"rotation-steer: same-variant rule fired; {variant} used instead of {expected}")
            else:
                warnings.append(f"rotation: expected {expected}, got {variant} (allowed as steer, logged)")
        else:
            warnings.append(f"rotation: expected {expected}, draft chose {variant} (logged; audit via card)")


    # shape
    wc = len(words(content))
    if not (150 <= wc <= 280):
        fail(errors, "length", f"{wc} words before link (need 120-280)")
    if len(content.split()) < len(content):  # placeholder to keep flake quiet
        pass
    for i, p in enumerate(paras, 1):
        n = len(split_sentences(p))
        cap = 5 if (variant == "V1" and i == 1) else 4
        if n > cap:
            fail(errors, "paragraph", f"paragraph {i} has {n} sentences (max {cap})")
    sents = split_sentences(content)
    run = 0
    for s in sents:
        run = run + 1 if len(words(s)) > ALLOW_LONG_RUN else 0
        if run >= 3:
            fail(errors, "rhythm", "three long sentences in a row (>25 words)")
            break
    qcount = content.count("?")
    if paras and "?" in paras[0]:
        fail(errors, "question-opener", "first paragraph contains a question")
    if qcount > 1:
        fail(errors, "question-budget", f"{qcount} questions (max 1, close only)")
    tag_pos = content.find("#")
    if re.search(r"(^|\s)#[A-Za-z0-9_]+", content):
        fail(errors, "hashtags", "hashtags in body")
    if content.count("http") > 1:
        fail(errors, "links", "more than one URL in body")

    # per-variant mechanical shape
    if variant and not errors_link:
        p0 = split_sentences(paras[0]) if paras else []
        if variant == "V1" and len(paras) != 4:
            fail(errors, "shape-V1", f"expected 4 body paragraphs, got {len(paras)}")
        if variant == "V1" and p0 and len(p0) > 5:
            fail(errors, "shape-V1", "opener must be 2-5 tight sentences")
        if variant == "V2" and p0:
            joined = paras[0].lower()
            if not (("found" in joined and re.search(r"\d", joined)) or "study" in joined or "survey" in joined or "report" in joined):
                fail(errors, "shape-V2", "opener must name a source and its finding")
            if len(p0) != 1:
                fail(errors, "shape-V2", "opener must be one sentence")
        if variant == "V3" and len(paras) not in (3, 4):
            fail(errors, "shape-V3", f"expected 3 body paragraphs, got {len(paras)}")
        if variant == "V4":
            joined = paras[0].lower() if paras else ""
            if not re.search(r"\b(i|we)\b", joined) or not re.search(r"(last|this|over)\s+(month|quarter|week|year|sprint)", joined):
                fail(errors, "shape-V4", "opener must be a first-person receipt with a time anchor; the Ledger row is verified by the card, not here")
        if variant == "V5" and p0:
            if len(p0) != 1 or " is " not in " " + p0[0].lower() + " ":
                fail(errors, "shape-V5", "opener must be a single-sentence definition")

    # dedupe + opener guard (entries/posted were collected during rotation resolution)
    full_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    opener = next((l.strip() for l in paras[0].splitlines() if l.strip()), "") if paras else ""
    open_sha = hashlib.sha256(opener[:100].encode("utf-8")).hexdigest()
    for e in posted:
        if e.get("sha256") == full_sha:
            fail(errors, "duplicate", "identical content already in posted log")
        if e.get("open_sha256") == open_sha:
            fail(errors, "opener-repeat", "first 100 characters collide with a prior post")

    # ---- SEO / reach gate (mechanical threshold) ----
    seo = {"hook_210": "skip", "keyword": "skip", "engagement_close": "skip", "og": "skip", "consistency": "warn"}
    # S1 hook: a number or a named source inside the first 210 characters
    hook = content[:210]
    src_tokens = ("study", "survey", "report", "paper", "standard", "researchers", "found")
    if re.search(r"\d", hook) or any(t in hook.lower() for t in src_tokens):
        seo["hook_210"] = "pass"
    else:
        fail(errors, "seo-hook", "first 210 chars need a number or a named source (dwell + credibility hook)")
        seo["hook_210"] = "fail"
    # S2 primary keyword in body (LinkedIn indexes post text; consistent topic use compounds)
    if a.keyword:
        kw = a.keyword.lower().strip()
        hits = low.count(kw)
        if hits >= 1:
            seo["keyword"] = {"pass": True, "hits": hits}
        else:
            fail(errors, "seo-keyword", f"primary keyword '{a.keyword}' absent from body")
            seo["keyword"] = {"pass": False}
    # S3 engagement close: the one question sits in the last paragraph AND asks for experience, not agreement
    if paras:
        if qcount == 1 and "?" in re.split(r"\n\s*\n", content)[-1]:
            q_sen = next((q for q in split_sentences(re.split(r"\n\s*\n", content)[-1]) if "?" in q), "")
            if re.search(r"\b(you|your)\b", q_sen, re.I):
                seo["engagement_close"] = "pass"
            else:
                warnings.append("engagement-close: the close question should ask for the reader's experience (use 'you/your')")
                seo["engagement_close"] = "warn"
        else:
            fail(errors, "seo-close", "exactly one experience question must close the post (comment driver)")
            seo["engagement_close"] = "fail"
    # S5 og metadata on the linked URL (drives LinkedIn preview + search)
    if a.check_og and url:
        import time as _time
        try:
            page = _fetch_page(url, timeout=15)
            mt = re.search(r'<meta property="og:title" content="([^"]*)"', page)
            md = re.search(r'<meta (?:property="og:description"|name="description") content="([^"]*)"', page)
            t_ok = bool(mt) and "notion" not in mt.group(1).lower()[:7]
            d_len = len(md.group(1)) if md else 0
            if t_ok and 60 <= d_len <= 2000:  # exists and specific; LinkedIn truncates the display anyway
                seo["og"] = {"title": (mt.group(1))[:80], "desc_len": d_len}
            else:
                fail(errors, "seo-og", f"og metadata thin on {url[:60]} (title_ok={t_ok}, desc_len={d_len})")
                seo["og"] = {"fail": True, "title_ok": t_ok, "desc_len": d_len}
        except Exception as e:
            fail(errors, "seo-og", f"og fetch failed: {e}")
            seo["og"] = {"fail": True, "fetch_error": str(e)[:80]}
    # S6 topical consistency across the posted log
    if a.topics and posted:
        topics = [t.strip().lower() for t in a.topics.split(",") if t.strip()]
        if topics:
            prior = [e for e in posted if e.get("keywords")]
            shared = sum(1 for e in prior if set(topics) & set(k.lower() for k in (e.get("keywords") or [])))
            if prior and shared / len(prior) < 0.5:
                warnings.append(f"consistency: only {shared}/{len(prior)} prior posts share a topic keyword")
                seo["consistency"] = {"shared": shared, "prior": len(prior)}
            else:
                seo["consistency"] = {"shared": shared, "prior": len(prior)}
            keywords_now = topics
        else:
            keywords_now = []
    else:
        keywords_now = (a.keyword.split() if a.keyword else [])
    keywords_out = sorted(set(k.lower() for k in keywords_now if k))

    # ---- template coverage (mechanical slot enforcement; opt-in flags) ----
    tpl_stats = None
    if a.template or a.slots_file:
        if not (a.template and a.slots_file):
            fail(errors, "template-usage", "--template and --slots-file must be used together")
        else:
            tname = a.template.strip().upper()
            ptypes = load_post_types_file(tdir)
            ventry = post_types_by_variant(ptypes).get(tname)
            ptrefuse = (ventry or (None, {}))[1]
            refuse_unless = ptrefuse.get("refuse_unless") or []
            refuse = None
            brief_early = None
            if refuse_unless:
                try:
                    brief_early = json.loads(Path(a.slots_file).read_text(encoding="utf-8"))
                    if not isinstance(brief_early, dict):
                        raise ValueError("top level must be a JSON object")
                except Exception:
                    brief_early = None
                if brief_early is None or refusal_missing_slots(brief_early, ptrefuse, slot_registry(tdir)):
                    # refusal sourced from post_types.yaml, not from code
                    refuse = str(ptrefuse["refuse_reason"])
            if refuse:
                fail(errors, "template-unavailable", refuse)
            elif not re.fullmatch(r"V[0-9]+", tname) and not (tdir / f"{tname}.md").is_file():
                fail(errors, "template-usage", f"unknown template '{a.template}'")
            else:
                tpl_path = tdir / f"{tname}.md"
                try:
                    tpl_fm, _tpl_body = parse_template_frontmatter(tpl_path.read_text(encoding="utf-8"))
                except Exception as e:
                    fail(errors, "template-usage", f"template unreadable: {tpl_path.name} ({e})")
                    tpl_fm = {}
                try:
                    brief = brief_early if brief_early is not None else json.loads(Path(a.slots_file).read_text(encoding="utf-8"))
                    if not isinstance(brief, dict):
                        raise ValueError("top level must be a JSON object")
                except Exception as e:
                    fail(errors, "template-slots", f"slots file unreadable: {e}")
                    brief = None
                if tpl_fm and brief is not None:
                    reg = slot_registry(tdir)
                    missing, invalid = template_slot_problems(tpl_fm, brief, reg, cfg)
                    if missing:
                        fail(errors, "missing-slots", "; ".join(missing))
                    if invalid:
                        fail(errors, "template-slot-type", "; ".join(invalid))
                    tpl_stats = {"name": tpl_fm.get("name", ""), "required_slots": tpl_fm.get("required_slots", []),
                                 "slots_ok": not (missing or invalid)}
                    # coverage runs only after the existing checks pass
                    if not errors and tpl_fm.get("required_slots"):
                        cov = template_coverage(tpl_fm, brief, paras, content)
                        errors.extend(cov)
                        tpl_stats["coverage"] = "pass" if not cov else "fail"

    errors += errors_link
    ok = not errors
    out = {
        "ok": ok, "errors": errors, "warnings": warnings,
        "stats": {"variant": variant, "rotation_expected": expected,
                  "words": wc, "paragraphs": len(paras),
                  "url_present": bool(url), "open_sha256": open_sha,
                  "sha256": full_sha, "seo": seo},
    }
    if tpl_stats:
        out["stats"]["template"] = tpl_stats
    if a.record and ok:
        from datetime import datetime, timezone
        line = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "variant": variant, "open_sha256": open_sha, "sha256": full_sha}
        if a.slug:
            line["slug"] = a.slug
        if a.urn:
            line["urn"] = a.urn
        if a.url:
            line["linkedin_url"] = a.url
        if keywords_out:
            line["keywords"] = keywords_out
        out["record_line"] = json.dumps(line)
    print(json.dumps(out))
    sys.exit(0 if ok else (2 if warnings and not errors else 1))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"ok": False, "errors": [f"internal: {e}"]}))
        sys.exit(1)
