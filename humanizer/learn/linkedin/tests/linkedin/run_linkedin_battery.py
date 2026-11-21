#!/usr/bin/env python3
"""Verification battery for the LinkedIn post generator (registry refactor,
config files, post-type catalog + weighted selection). Stdlib only, no LLM,
no network. Run by hand from the repo: see humanizer/learn/LEARN-VOICE.md.

Checks (each prints one PASS/FAIL line; exit 1 on any FAIL):
  [a] 12-cell matrix (3 briefs x 4 variants) through render + voicebook
      checker + lever check, all green under factory defaults (the plugin's
      voice gate runs separately; its invariants are cell [e]).
  [b] registry proof: TAGLINE slot + fixtures-only V_FIXTURES skeleton accepted
      by render and checker with zero python references to TAGLINE; negative:
      a 9-char tagline fails with the slots.yaml boundary message.
  [c] portability: full matrix re-run from a redirected templates dir with a
      config whose allowlist accepts any https URL, briefs linked under a
      third-party https host; negative: a restricted allowlist refuses a link
      off the list ("not on the configured public allowlist").
  [d] default-path byte-compat: the brief_test/V1 render is byte-identical to
      tests/linkedin/expected/test_V1.render.md, and the checker's JSON on that
      rendered post (no template flags, empty log) is byte-identical to
      expected/default_s_v1.checker.json. Regenerate goldens only after a
      deliberate change to briefs, skeletons or checker semantics.
  [e] plugin gate invariants: humanizer/hooks/gate.py exits 4 with a fail JSON
      on tell-laden text and exits 0 with a pass JSON on clean text.
  [f] selection determinism: identical --select runs are byte-identical.
  [g] weights sanity:
      g1 full brief -> announcement-receipt then practical-tips on top with
      --explain breakdown lines present;
      g2 counter+question_tail+source only, has_link=false -> news-reaction
      and pure-question ahead of every link-required kind (those are
      not-viable with fill-gaps reported, never errors).
  [h] --used-kinds demotes the named kind (or its variant alias) one rank step
      and changes the top pick.

Usage: python3 run_linkedin_battery.py   (all cells; deterministic output)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2]           # humanizer/learn/linkedin/
TPL = SCRIPTS / "templates"
TESTS = Path(__file__).resolve().parent                 # .../tests/linkedin/
FIX = TESTS / "fixtures"
EXPECTED = TESTS / "expected"
PLUGIN_DIR = SCRIPTS.parents[1]                         # humanizer/
HOOK = PLUGIN_DIR / "hooks" / "gate.py"
WORK = Path(tempfile.mkdtemp(prefix="li_battery_"))

BRIEFS = {
    "test": TPL / "briefs/brief_test.json",
    "judgment": TPL / "briefs/brief_judgment.json",
    "undertrust": TPL / "briefs/brief_undertrust.json",
}
VARIANTS = ["V1", "V2", "V3", "V5"]
ENV0 = {k: v for k, v in os.environ.items() if k != "LINKEDIN_TEMPLATES_DIR"}

results = []


def run(args, env=None):
    e = dict(ENV0)
    if env:
        e.update(env)
    p = subprocess.run([sys.executable] + [str(a) for a in args],
                       capture_output=True, text=True, env=e, timeout=600)
    return p.returncode, p.stdout, p.stderr


def run_input(script_path, args, stdin_text):
    """Run one script with stdin text (the gate reads stdin)."""
    e = dict(ENV0)
    return subprocess.run([sys.executable, str(script_path)] + args, input=stdin_text,
                          capture_output=True, text=True, env=e, timeout=120)


def script(name):
    return SCRIPTS / name


def record(tag, ok, detail_ok="", detail_bad=None):
    results.append((tag, ok, detail_ok))
    detail = detail_ok if (ok or detail_bad is None) else detail_bad
    print(("PASS" if ok else "FAIL") + " [" + tag + "] " + detail)


def expect_true(cond, tag, detail_ok, detail_bad):
    record(tag, bool(cond), detail_ok if cond else detail_bad)


def jf(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def jf_string(s):
    return json.loads(s)


def _norm_eol(data):
    """LF-normalized bytes so content pins survive any checkout EOL style."""
    return data.replace(b"\r\n", b"\n")


# ---------------------------------------------------------------- [a] matrix
def check_matrix(env=None, brief_links=None, tag_suffix=""):
    n = 0
    fails = []
    for bn, bf in BRIEFS.items():
        brief = jf(bf)
        if brief_links is not None:
            brief = dict(brief, link=brief_links[bn])
        pbrief = WORK / f"brief_{bn}{tag_suffix}.json"
        pbrief.write_text(json.dumps(brief), encoding="utf-8")
        kw, tp = brief["primary_keyword"], ",".join(brief["tags"])
        for v in VARIANTS:
            post = WORK / f"out_{bn}_{v}{tag_suffix}.md"
            rc, out, err = run([script("linkedin_render.py"), "--variant", v, "--brief", pbrief, "--out", post], env)
            if rc != 0 or not post.is_file():
                fails.append(f"render {bn}{v}: {out[:120]}{err[:120]}")
                continue
            rj = jf_string(out)
            if not rj.get("ok"):
                fails.append(f"render ok {bn}{v}")
            rc, out, err = run([script("linkedin_voicebook_check.py"), "--post", post,
                                "--log", WORK / "empty.log", "--template", v, "--slots-file", pbrief,
                                "--keyword", kw, "--topics", tp], env)
            if rc != 0:
                fails.append(f"voice {bn}{v}: {out[:200]}{err[:120]}")
            rc, out, err = run([script("linkedin_lever_check.py"), "--post", post, "--brief", pbrief, "--variant", v], env)
            if rc != 0:
                fails.append(f"lever {bn}{v}: {out[:200]}")
            n += 1
    return n, fails


# --------------------------------------------------------------------- main
def main():
    (WORK / "fix_tpl").mkdir(parents=True)
    (WORK / "port_tpl").mkdir(parents=True)
    (WORK / "port_tpl_restricted").mkdir(parents=True)
    (WORK / "empty.log").write_text("", encoding="utf-8")

    # ---- [a] 12-cell matrix under factory defaults
    n, fails = check_matrix()
    record("a", not fails, f"matrix {n}/12 cells green (render+voice+lever), all gates rc=0"
           if not fails else f"{n}/12 cells green; fails: {fails[:2]}")

    # ---- [b] registry proof: TAGLINE + V_FIXTURES (fixtures only)
    shutil.copy(TPL / "slots.yaml", WORK / "fix_tpl" / "slots.yaml")
    shutil.copy(FIX / "V_FIXTURES.md", WORK / "fix_tpl" / "V_FIXTURES.md")
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
    for py in ("linkedin_render.py", "linkedin_voicebook_check.py", "linkedin_lever_check.py"):
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
    cfg = {"template_dir": str(WORK / "port_tpl"), "url_allowlist": [".+"]}
    (WORK / "port_tpl" / "config.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    links = {bn: "https://blog.example.org/" + re.sub(r"[^a-z0-9]+", "-",
             jf(bf)["title"].lower()).strip("-") for bn, bf in BRIEFS.items()}
    n, fails = check_matrix(env={"LINKEDIN_TEMPLATES_DIR": str(WORK / "port_tpl")}, brief_links=links, tag_suffix="_port")
    record("c", not fails, f"portable config + third-party https links: {n}/12 cells green" if not fails else f"fails: {fails[:2]}")
    # negative: restricted allowlist refuses an off-list link
    for name in sorted(p.name for p in TPL.glob("*")):
        src = TPL / name
        if src.is_file():
            shutil.copy(src, WORK / "port_tpl_restricted" / name)
    cfg2 = {"template_dir": str(WORK / "port_tpl_restricted"), "url_allowlist": ["qa\\.example\\.org"]}
    (WORK / "port_tpl_restricted" / "config.json").write_text(json.dumps(cfg2, indent=1), encoding="utf-8")
    pbrief = WORK / "brief_port_neg.json"
    pbrief.write_text(json.dumps(jf(BRIEFS["test"])), encoding="utf-8")
    rc, out, _ = run([script("linkedin_render.py"), "--variant", "V1", "--brief", pbrief, "--out", WORK / "out_neg.md"],
                     {"LINKEDIN_TEMPLATES_DIR": str(WORK / "port_tpl_restricted")})
    expect_true(rc == 1 and "not on the configured public allowlist" in out, "c-neg",
                "restricted allowlist refuses the off-list LINK with the configured message",
                f"rc={rc} out={out[:200]}")

    # ---- [d] default-path byte-compat vs committed goldens
    post_gold = WORK / "out_golden_v1.md"
    rc, out_r, _ = run([script("linkedin_render.py"), "--variant", "V1", "--brief", BRIEFS["test"], "--out", post_gold])
    # EOL-normalized compare: the content pin must survive any checkout, same
    # rule as tests/test_parity.py
    same_bytes = post_gold.is_file() and _norm_eol(post_gold.read_bytes()) == _norm_eol((EXPECTED / "test_V1.render.md").read_bytes())
    rc, out, _ = run([script("linkedin_voicebook_check.py"), "--post", post_gold, "--log", WORK / "empty.log"])
    try:
        checker_golden_ok = rc == 0 and json.loads(out) == jf(EXPECTED / "default_s_v1.checker.json")
    except Exception:
        checker_golden_ok = False
    expect_true(checker_golden_ok and same_bytes, "d",
                f"default checker JSON + V1 render byte-identical to goldens (sha {json.loads(out)['stats']['sha256'][:12]})",
                f"checker_golden_ok={checker_golden_ok} render_bytes_ok={same_bytes} checker_rc={rc} out={out[:160]} render_out={out_r[:160]}")

    # ---- [e] plugin gate invariants (hooks/gate.py, deterministic)
    sloppy = ("The tool serves as a foundation for innovation, and that is okay. "
              "It is not just about speed, it is about unlocking value at the end of the day.")
    clean = "The scanner loads the rules from the shared module, so the hook and the checker cannot drift."
    rs = run_input(HOOK, ["--surface", "public"], sloppy)
    rc_ok = rs.returncode == 4
    try:
        sj = json.loads(rs.stdout)
        fail_json_ok = sj.get("status") == "fail" and "REPAIR" in sj.get("instruction", "") and sj.get("reported", 0) <= 5
    except Exception:
        fail_json_ok = False
    rc_clean = run_input(HOOK, ["--surface", "public"], clean)
    try:
        clean_json_ok = rc_clean.returncode == 0 and json.loads(rc_clean.stdout).get("status") == "pass"
    except Exception:
        clean_json_ok = False
    expect_true(rc_ok and fail_json_ok and clean_json_ok, "e",
                "gate: tell-laden text exit 4 with <=5-pattern repair JSON; clean text exit 0 pass JSON",
                f"sloppy_rc={rs.returncode} fail_json_ok={fail_json_ok} clean_rc={rc_clean.returncode} clean_json_ok={clean_json_ok}")

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
    sparse = {"source": "A cross-industry survey of platform engineering leads",
              "counter": "the fixed-review story no longer matches what automated pipelines and their silent defaults actually ship",
              "question_tail": "Which step in your release process still claims a record it cannot show?"}
    sb = WORK / "brief_sparse.json"
    sb.write_text(json.dumps(sparse), encoding="utf-8")
    rc, out2, _ = run([script("linkedin_render.py"), "--select", "--brief", sb, "--explain", "--out", WORK / "sel_sparse.json"])
    s2 = jf_string(out2)
    data = (TPL / "post_types.yaml").read_text(encoding="utf-8")
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
    shutil.rmtree(WORK, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
