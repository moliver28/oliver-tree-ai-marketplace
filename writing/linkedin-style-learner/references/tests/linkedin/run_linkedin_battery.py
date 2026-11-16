#!/usr/bin/env python3
"""Verification battery for the LinkedIn post generator (registry refactor,
config files, post-type catalog + weighted selection). Stdlib only, no LLM.

Checks (each prints one PASS/FAIL line; exit 1 on any FAIL):
  [a] 12-cell matrix (3 briefs x 4 variants) through render + voicebook
      checker + lever check + voice guard, all green under factory defaults.
  [b] registry proof: TAGLINE slot + fixtures-only V_FIXTURES skeleton accepted
      by render and checker with zero python references to TAGLINE; negative:
      a 9-char tagline fails with the slots.yaml boundary message.
  [c] portability: full matrix re-run from a redirected templates dir with a
      config whose allowlist accepts any https URL, briefs linked under a
      third-party https host; negative: a restricted allowlist refuses a link
      off the list ("not on the configured public allowlist").
  [d] default-path byte-compat: checker on /tmp/s_v1.md + render of
      brief_test/V1 byte-identical to the committed goldens (tests/linkedin/
      expected/). Regenerate goldens only after deliberate content changes.
  [e] guard invariants: /tmp/tells_test.md = 6 errors, /tmp/canon_sweep.md =
      9 errors, the three voice_guard.py CORPUS_FILES sweep clean (exit 0).
  [f] selection determinism: identical --select runs are byte-identical.
  [g] weights sanity:
      g1 full brief -> announcement-receipt then practical-tips on top with
      --explain breakdown lines present;
      g2 counter+question_tail+source only, has_link=false -> news-reaction
      and pure-question ahead of every link-required kind (those are
      not-viable with fill-gaps reported, never errors).
  [h] --used-kinds demotes the named kind (or its variant alias) one rank step
      and changes the top pick.

Usage: python3 run_linkedin_battery.py [--fast]   (--fast skips the guard arm)
"""
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2]           # ~/.hermes/scripts
TPL = SCRIPTS / "linkedin_templates"
TESTS = Path(__file__).resolve().parent
FIX = TESTS / "fixtures"
EXPECTED = TESTS / "expected"
WORK = Path.home() / ".hermes/cache/scratch/li_battery"
FAST = "--fast" in sys.argv

BRIEFS = {
    "test": TPL / "briefs/brief_test.json",
    "judgment": TPL / "briefs/brief_judgment.json",
    "undertrust": TPL / "briefs/brief_undertrust.json",
}
VARIANTS = ["V1", "V2", "V3", "V5"]
ENV0 = {k: v for k, v in os.environ.items() if k != "LINKEDIN_TEMPLATES_DIR"}

results = []


def run(args, env=None, check_rc=True):
    e = dict(ENV0)
    if env:
        e.update(env)
    p = subprocess.run([sys.executable] + [str(a) for a in args],
                       capture_output=True, text=True, env=e, timeout=600)
    return p.returncode, p.stdout, p.stderr


def script(name):
    return SCRIPTS / name


def record(tag, ok, detail_ok="", detail_bad=None):
    results.append((tag, ok, detail_ok))
    detail = detail_ok if (ok or detail_bad is None) else detail_bad
    print(("PASS" if ok else "FAIL") + " [" + tag + "] " + detail)


def expect_true(cond, tag, detail_ok, detail_bad):
    record(tag, bool(cond), detail_ok if cond else detail_bad)


def jf(path):
    return json.loads(Path(path).read_text())


# ---------------------------------------------------------------- [a] matrix
def check_matrix(env=None, brief_links=None, tag_suffix=""):
    n = 0
    fails = []
    for bn, bf in BRIEFS.items():
        brief = jf(bf)
        slug = re.sub(r"[^a-z0-9]+", "-", brief["title"].lower()).strip("-")
        if brief_links is not None:
            brief = dict(brief, link=brief_links[bn])
        pbrief = WORK / f"brief_{bn}{tag_suffix}.json"
        pbrief.write_text(json.dumps(brief))
        kw, tp = brief["primary_keyword"], ",".join(brief["tags"])
        for v in VARIANTS:
            post = WORK / f"out_{bn}_{v}{tag_suffix}.md"
            rc, out, err = run([script("linkedin_render.py"), "--variant", v, "--brief", pbrief, "--out", post], env)
            if rc != 0 or not post.is_file():
                fails.append(f"render {bn}{v}: {out[:120]}{err[:120]}")
                continue
            rj = jf_string(out)
            ok_line = rj.get("ok")
            if not ok_line:
                fails.append(f"render ok {bn}{v}")
            rc, out, err = run([script("linkedin_voicebook_check.py"), "--post", post,
                                "--log", WORK / "empty.log", "--template", v, "--slots-file", pbrief,
                                "--keyword", kw, "--topics", tp, "--record"], env)
            if rc != 0:
                fails.append(f"voice {bn}{v}: {out[:200]}{err[:120]}")
            rc, out, err = run([script("linkedin_lever_check.py"), "--post", post, "--brief", pbrief, "--variant", v], env)
            if rc != 0:
                fails.append(f"lever {bn}{v}: {out[:200]}")
            if not FAST:
                rc, out, err = run([script("voice_guard.py"), "--check", post], env)
                if rc != 0:
                    fails.append(f"guard {bn}{v}: rc={rc} {out[:150]}")
            n += 1
    return n, fails


def jf_string(s):
    return json.loads(s)


# --------------------------------------------------------------------- main
def main():
    if WORK.exists():
        shutil.rmtree(WORK)
    (WORK / "tpl").mkdir(parents=True)
    (WORK / "port_tpl").mkdir(parents=True)
    (WORK / "port_tpl_restricted").mkdir(parents=True)
    (WORK / "fix_tpl").mkdir(parents=True)
    (WORK / "empty.log").write_text("")

    # ---- [a] 12-cell matrix under factory defaults
    n, fails = check_matrix()
    record("a", not fails, f"{n}/12 cells green (render+voice+lever{' + guard' if not FAST else ''}); fails: {fails[:2]}" if fails else f"matrix {n}/12 cells green, all gates rc=0")

    # ---- [b] registry proof: TAGLINE + V_FIXTURES (fixtures only)
    shutil.copy(TPL / "slots.yaml", WORK / "fix_tpl/slots.yaml")
    shutil.copy(FIX / "V_FIXTURES.md", WORK / "fix_tpl/V_FIXTURES.md")
    fenv = {"LINKEDIN_TEMPLATES_DIR": str(WORK / "fix_tpl")}
    fix_brief = FIX / "brief_fixture.json"
    post = WORK / "out_fixture.md"
    rc, out, err = run([script("linkedin_render.py"), "--variant", "V_FIXTURES", "--brief", fix_brief, "--out", post], fenv)
    r_ok = rc == 0 and post.is_file()
    rc2, out2, err2 = run([script("linkedin_voicebook_check.py"), "--post", post, "--log", WORK / "empty.log",
                           "--template", "V_FIXTURES", "--slots-file", fix_brief], fenv)
    c_ok = rc2 == 0
    # negative: short tagline -> slots.yaml-sourced boundary message
    rc3, out3, _ = run([script("linkedin_render.py"), "--variant", "V_FIXTURES", "--brief", FIX / "brief_fixture_short.json",
                        "--out", WORK / "out_fixture_short.md"], fenv)
    neg_ok = rc3 == 1 and "TAGLINE must be 10-60 chars" in out3
    # zero python references to the fixture slot
    py_refs = 0
    for py in ("linkedin_render.py", "linkedin_voicebook_check.py", "linkedin_lever_check.py", "voice_guard.py"):
        src = (SCRIPTS / py).read_text(encoding="utf-8")
        py_refs += src.count("TAGLINE")
    expect_true(r_ok and c_ok and neg_ok and py_refs == 0, "b",
                "TAGLINE renders + checks via slots.yaml only (0 python refs); 9-char tagline refused",
                f"render_ok={r_ok} checker_ok={c_ok} negative_ok={neg_ok} python_refs_to_TAGLINE={py_refs}")

    # ---- [c] portability: redirected dir + permissive config + external link
    for name in sorted(p.name for p in TPL.glob("*")):
        src = TPL / name
        if src.is_file():
            shutil.copy(src, WORK / "port_tpl" / name)
    cfg = {"template_dir": str(WORK / "port_tpl"), "url_allowlist": [".+"],
           "ollama_url": "http://127.0.0.1:11434/api/embed",
           "voice_corpus": ["/Users/moliver/Documents/uxr-blog/pipeline/why-ux-researchers-undertrust-ai-synthesis/final-draft.md"]}
    (WORK / "port_tpl/config.json").write_text(json.dumps(cfg, indent=1))
    links = {bn: "https://blog.example.org/" + re.sub(r"[^a-z0-9]+", "-",
             jf(bf)["title"].lower()).strip("-") for bn, bf in BRIEFS.items()}
    n, fails = check_matrix(env={"LINKEDIN_TEMPLATES_DIR": str(WORK / "port_tpl")}, brief_links=links, tag_suffix="_port")
    record("c", not fails, f"portable config + third-party https links: {n}/12 cells green" if not fails else f"fails: {fails[:2]}")
    # negative: restricted allowlist refuses an off-list link
    for name in sorted(p.name for p in TPL.glob("*")):
        src = TPL / name
        if src.is_file():
            shutil.copy(src, WORK / "port_tpl_restricted" / name)
    cfg2 = {"template_dir": str(WORK / "port_tpl_restricted"), "url_allowlist": ["qa\\.example\\.org"],
            "ollama_url": "http://127.0.0.1:11434/api/embed"}
    (WORK / "port_tpl_restricted/config.json").write_text(json.dumps(cfg2, indent=1))
    pbrief = WORK / "brief_port_neg.json"
    b = jf(BRIEFS["test"])
    pbrief.write_text(json.dumps(b))
    rc, out, _ = run([script("linkedin_render.py"), "--variant", "V1", "--brief", pbrief, "--out", WORK / "out_neg.md"],
                     {"LINKEDIN_TEMPLATES_DIR": str(WORK / "port_tpl_restricted")})
    expect_true(rc == 1 and "not on the configured public allowlist" in out, "c-neg",
                "restricted allowlist refuses the off-list LINK with the configured message",
                f"rc={rc} out={out[:200]}")

    # ---- [d] default-path byte-compat vs committed goldens
    rc, out, _ = run([script("linkedin_voicebook_check.py"), "--post", "/tmp/s_v1.md", "--log", WORK / "empty.log"])
    golden = EXPECTED / "default_s_v1.checker.json"
    try:
        checker_golden_ok = rc == 0 and json.loads(out) == jf(golden)
    except Exception:
        checker_golden_ok = False
    post_gold = EXPECTED / "test_V1.render.md"
    rc, out_r, _ = run([script("linkedin_render.py"), "--variant", "V1", "--brief", BRIEFS["test"], "--out", WORK / "out_golden_v1.md"])
    same_bytes = (WORK / "out_golden_v1.md").read_bytes() == post_gold.read_bytes() if rc == 0 else False
    expect_true(checker_golden_ok and same_bytes, "d",
                f"default checker JSON + V1 render byte-identical to goldens (sha {json.loads(out)['stats']['sha256'][:12]})",
                f"checker_golden_ok={checker_golden_ok} render_bytes_ok={same_bytes} checker_rc={rc} out={out[:160]} render_out={out_r[:160]}")

    # ---- [e] guard invariants
    if not FAST:
        rc, out, _ = run([script("voice_guard.py"), "--check", "/tmp/tells_test.md"])
        tells = len(jf_string(out)["errors"]) if rc == 1 else -1
        rc, out, _ = run([script("voice_guard.py"), "--check", "/tmp/canon_sweep.md"])
        canon = len(jf_string(out)["errors"]) if rc == 1 else -1
        import importlib.util
        spec = importlib.util.spec_from_file_location("voice_guard_probe", SCRIPTS / "voice_guard.py")
        vg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vg)
        corp_files = list(vg.CORPUS_FILES)
        clean = 0
        for f in corp_files:
            rc, out, _ = run([script("voice_guard.py"), "--check", f])
            if rc == 0:
                clean += 1
        guard_ok = tells == 6 and canon == 9 and clean == len(corp_files)
        record("e", guard_ok,
               f"guard: tells_test {tells} errors, canon_sweep {canon} errors, corpus {clean}/{len(corp_files)} clean"
               if guard_ok else
               f"tells={tells} (want 6) canon={canon} (want 9) corpus_clean={clean}/{len(corp_files)}")
    else:
        record("e", True, "SKIPPED (--fast)")

    # ---- [f] selection determinism
    base = [script("linkedin_render.py"), "--select", "--brief", BRIEFS["test"], "--explain",
            "--situations", "news_hook=false"]
    rc1, out1, _ = run(base + ["--out", WORK / "sel1.json"])
    rc2, out2, _ = run(base + ["--out", WORK / "sel2.json"])
    det = rc1 == rc2 == 0 and out1 == out2
    s1 = jf_string(out1)
    expect_true(det, "f", f"two select runs byte-identical (top={s1.get('top_pick')})",
                f"rc1={rc1} rc2={rc2} same={out1 == out2}")

    # ---- [g1] full brief: announcement-receipt + practical-tips on top
    explain_ok = all("explain" in r and r["explain"].strip() for r in s1["ranked"][:2])
    g1 = (s1["ranked"][0]["kind"] == "announcement-receipt"
          and s1["ranked"][1]["kind"] == "practical-tips" and explain_ok)
    record("g1", g1,
           f"full brief: top = {s1['ranked'][0]['kind']} ({s1['ranked'][0]['score']}), #2 = {s1['ranked'][1]['kind']} ({s1['ranked'][1]['score']}), explain present",
           f"top={s1['ranked'][0]['kind']}, second={s1['ranked'][1]['kind']}, ranked={[r['kind'] for r in s1['ranked']]}")

    # ---- [g2] sparse brief, has_link=false: commentary kinds ahead
    sparse = {"source": "A cross-vendor survey of research operations leads",
              "counter": "the fixed-boundary story no longer matches what agent pipelines and their silent defaults actually allocate",
              "question_tail": "Which step in your pipeline still claims survey provenance it cannot show?"}
    sb = WORK / "brief_sparse.json"
    sb.write_text(json.dumps(sparse))
    rc, out2, _ = run([script("linkedin_render.py"), "--select", "--brief", sb, "--explain", "--out", WORK / "sel_sparse.json"])
    s2 = jf_string(out2)
    ptypes = {}
    data = (TPL / "post_types.yaml").read_text()
    link_required = {}
    current = None
    for line in data.splitlines():
        m2 = re.match(r"^  ([a-z\-]+):\s*$", line)
        if m2:
            current = m2.group(1)
        m3 = re.match(r"^\s+link_required:\s*(true|false)", line)
        if m3 and current:
            link_required[current] = m3.group(1) == "true"
    link_required_kinds = [k for k, v in link_required.items() if v]
    top_ok = s2["ranked"] and s2["ranked"][0]["kind"] in ("news-reaction", "pure-question")
    bad = [k for k in link_required_kinds if k in {r["kind"] for r in s2["ranked"]} and
           s2["ranked"][0]["kind"] not in ("news-reaction", "pure-question")]
    gaps_ok = s2["not_viable"] and all(s2["not_viable"].get(k) for k in link_required_kinds)
    record("g2", bool(top_ok) and not bad and bool(gaps_ok),
           f"sparse brief (has_link=false): top = {s2['ranked'][0]['kind']} ({s2['ranked'][0]['score']}); all {len(link_required_kinds)} link-required kinds not-viable with fill-gaps, no errors",
           f"ranked={[r['kind'] for r in s2['ranked']]} not_viable={list(s2['not_viable'])}")

    # ---- [h] --used-kinds demotion changes the top pick
    rc, out3, _ = run([script("linkedin_render.py"), "--select", "--brief", BRIEFS["test"], "--used-kinds", "announcement-receipt", "--out", WORK / "sel_used.json"])
    s3 = jf_string(out3)
    rc4, out4, _ = run([script("linkedin_render.py"), "--select", "--brief", BRIEFS["test"], "--used-kinds", "V1", "--out", WORK / "sel_used_alias.json"])
    s4 = jf_string(out4)
    dem = s3["top_pick"] != s1["top_pick"] and s3["top_pick"] == "practical-tips"
    alias_ok = s4["top_pick"] == s3["top_pick"] and out3 == out4
    marked = next((r for r in s3.get("ranked", []) if r.get("used_demoted")), None)
    expect_true(dem and alias_ok and bool(marked), "h",
                f"--used-kinds demotes {marked['kind'] if marked else '?'} one rank; top {s1['top_pick']} -> {s3['top_pick']}; variant alias V1 identical",
                f"top_default={s1['top_pick']} top_used={s3['top_pick']} alias_ok={alias_ok} demoted_marked={bool(marked)}")

    # summary + exit
    bad = [t for t, ok, _ in results if not ok]
    print("BATTERY: " + ("ALL GREEN (n=%d checks)" % len(results) if not bad else f"{len(bad)} FAILING: {bad}"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
