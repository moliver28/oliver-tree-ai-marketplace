#!/usr/bin/env python3
"""Marketplace verifier. Run before any publish claim.

Checks:
1. marketplace.json parses and every listed plugin source dir exists with a plugin.json manifest.
2. Every SKILL.md in the repo has name + description frontmatter.
3. The /voice gate actually runs: one sloppy text must fail, one clean text must pass (exit codes 4/0).
4. Every README-indexed path exists.
5. voice-gate loads learned rules from the runtime state file (issue #5): a state
   pattern/exemplar/threshold override is applied at scan time with per-source
   provenance; an absent state file falls back to the embedded lists silently; a
   corrupt state file falls back and logs `state_skip` (fail-open unchanged).
6. learn/apply drift: the runtime gate's embedded rule data must hash-match the
   published mirror, and a state file present on the machine must parse under the
   shared loader. No runtime on the machine (CI) -> explicit SKIP line.

Exit 0 = marketplace verified working; nonzero = broken, do not publish.
"""
import hashlib
import importlib.util
import json, os, shutil, sys, subprocess, pathlib, re, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
fails = []

def ck(cond, msg):
    print(("OK  " if cond else "FAIL") + " " + msg)
    if not cond:
        fails.append(msg)


def _rules_hash(mod):
    """Stable content hash of a voice-tells module's embedded rule data."""
    payload = {"patterns": [[a, b] for a, b in mod.PATTERNS], "exemplars": list(mod.EXEMPLARS)}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()


def voice_gate_drift(published, hermes_home):
    """Learn/apply drift check (issue #5). Returns (status, msg), status in
    ok|skip|fail. The runtime gate's embedded rule data must hash-match the
    published mirror, and a state file present on this machine must parse
    under the shared loader contract. No runtime gate and no state file on
    the machine (CI) -> explicit skip."""
    home = pathlib.Path(hermes_home)
    gate = home / "agent-hooks" / "voice-tells.py"
    state = home / "state" / "voice-rules.json"
    gate_present, state_present = gate.is_file(), state.is_file()
    if not gate_present and not state_present:
        return ("skip", f"no Hermes runtime on this machine: {gate} and {state} both absent")
    msgs, status = [], "ok"
    if state_present:
        saved = os.environ.get("VOICE_RULES_STATE")
        try:
            os.environ["VOICE_RULES_STATE"] = str(state)
            eff = published.effective_rules()
            st = eff["state"]
            n_pat = sum(1 for s in eff["pattern_sources"] if s != "embedded")
            n_ex = sum(1 for s in eff["exemplar_sources"] if s != "embedded")
            if st["ok"]:
                msgs.append(f"state file parses under the shared loader ({n_pat} state patterns, "
                            f"{n_ex} state exemplars)" + (f"; warnings: {st['err']}" if st["err"] else ""))
            else:
                status = "fail"
                msgs.append(f"state file invalid -> gate silently embedded-only: {st['err']}")
        except Exception as e:
            status = "fail"
            msgs.append(f"state file unusable under the shared loader: {e!r}")
        finally:
            if saved is None:
                os.environ.pop("VOICE_RULES_STATE", None)
            else:
                os.environ["VOICE_RULES_STATE"] = saved
    if gate_present:
        try:
            spec = importlib.util.spec_from_file_location("runtime_voice_tells", gate)
            rt = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(rt)
            h_rt, h_pub = _rules_hash(rt), _rules_hash(published)
            if h_rt != h_pub:
                status = "fail"
                msgs.append(f"pattern-list hash drift: runtime gate {h_rt[:12]} != published mirror {h_pub[:12]}")
            else:
                msgs.append(f"runtime gate matches published mirror ({h_rt[:12]})")
        except Exception as e:
            status = "fail"
            msgs.append(f"runtime gate unusable for hash compare: {e!r}")
    elif state_present:
        msgs.append("state-only machine: embedded-hash compare skipped (no runtime gate to hash)")
        if status != "fail":
            status = "skip"
    return (status, "; ".join(msgs))

mp = ROOT / ".claude-plugin" / "marketplace.json"
data = json.loads(mp.read_text())
ck(data.get("name") == "oliver-tree-ai-marketplace", "marketplace name")
for p in data["plugins"]:
    src = ROOT / p["source"].lstrip("./")
    ck(src.is_dir(), f"plugin dir {p['name']}")
    ck((src / ".claude-plugin" / "plugin.json").is_file(), f"manifest {p['name']}")
    mj = json.loads((src / ".claude-plugin" / "plugin.json").read_text())
    ck(mj.get("name") == p["name"], f"manifest name matches for {p['name']}")
    ck(mj.get("version") == p.get("version"), f"version parity {p['name']} (manifest vs marketplace)")
    d = mj.get("description", "")
    ck(len(d) <= 256, f"description <=256 chars for {p['name']} ({len(d)})")
    ck("'" in d and "use when the user says" in d.lower(), f"description carries human trigger phrases for {p['name']}")
    chlog = src / "CHANGELOG.md"
    ck(chlog.is_file(), f"changelog exists for {p['name']}")
    ck(f"[{p.get('version')}]" in chlog.read_text(), f"changelog entry for {p.get('version')} in {p['name']}")
    if p["name"] == "humanizer-voice":
        ck((src / "learned" / "phrases.log").exists(), "learned sidecar exists")
        cmd = (src / "commands" / "voice.md").read_text()
        ck("phrases.log" in cmd, "/voice logs learned phrases deterministically")
    if p["name"] == "voice-gate":
        vt_src = (src / "voice-tells.py").read_text()
        ck("COSINE_THRESHOLD" not in vt_src, "voice-gate global cosine threshold removed (per-class table)")
        ck(all(l[:1] in " \t" for l in vt_src.splitlines() if "import onnxruntime" in l),
           "onnxruntime import confined to lazy fallback path (not module scope)")
        vt = None
        try:
            _spec = importlib.util.spec_from_file_location("voice_tells_verify", src / "voice-tells.py")
            vt = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(vt)
        except Exception as e:
            ck(False, f"voice-tells.py importable in verifier: {e!r}")
        if vt is not None:
            try:
                cache = json.loads((src / "voice-tells-vectors.json").read_text())
                cal = json.loads((src / "voice-tells-calibration.json").read_text())
                labels = {ex["label"] for b in cache["backends"].values() for ex in b["vectors"]}
                cache_texts = {v["text"] for b in cache["backends"].values() for v in b["vectors"]}
                for backend, b in cache["backends"].items():
                    ck(len(b.get("vectors", [])) >= len(vt.EXEMPLARS),
                       f"exemplar cache complete for {backend} (>= {len(vt.EXEMPLARS)})")
                    ck(set(vt.EXEMPLARS) <= cache_texts,
                       f"exemplar cache covers every embedded exemplar for {backend}")
                    ck(set(cal["backends"][backend]["thresholds"]) >= labels,
                       f"per-class thresholds cover every exemplar class for {backend}")
            except Exception as e:
                ck(False, f"voice-gate cache + calibration parse and cover: {e!r}")
        with tempfile.TemporaryDirectory() as td:
            vf = pathlib.Path(td) / "probe.md"
            vf.write_text("The tool serves as a foundation for innovation, and that is okay. "
                          "It is not just about speed, it is about unlocking value at the end of the day.")
            env = {**os.environ, "VOICE_GATE_VECTOR": "off"}
            r = subprocess.run(["python3", str(src / "voice-check.py"), str(vf)], capture_output=True, text=True, env=env)
            ck(r.returncode == 1, "voice-check regex layer fails tell-laden text (exit 1)")
            ck(not (pathlib.Path(td) / "probe.voice-pass").exists(), "voice-check writes no marker on failure")
            vf.write_text("The scanner loads the rules from the shared module, so the hook and the checker cannot drift.")
            r2 = subprocess.run(["python3", str(src / "voice-check.py"), str(vf)], capture_output=True, text=True, env=env)
            ck(r2.returncode == 0 and "PASS" in r2.stdout, "voice-check passes clean text and writes marker")

        # --- learn/apply decoupling (issue #5): shared state-file loader contract ---
        has_loader = vt is not None and hasattr(vt, "effective_rules") and hasattr(vt, "state_path")
        ck(has_loader, "voice-tells exposes the shared state-file loader API (state_path/effective_rules)")
        if has_loader:
            with tempfile.TemporaryDirectory() as td:
                tdp = pathlib.Path(td)
                logf, stf = tdp / "gate.log", tdp / "voice-rules.json"
                saved = {k: os.environ.pop(k) for k in ("VOICE_RULES_STATE", "VOICE_GATE_LOG") if k in os.environ}
                try:
                    os.environ["VOICE_GATE_LOG"] = str(logf)
                    # case: absent state file -> embedded defaults, silent (identical to today)
                    try:
                        os.environ["VOICE_RULES_STATE"] = str(tdp / "absent.json")
                        eff = vt.effective_rules()
                        ck(eff["patterns"] == list(vt.PATTERNS) and eff["exemplars"] == list(vt.EXEMPLARS),
                           "absent state file -> embedded defaults")
                        ck(eff["state"]["ok"] is False and eff["state"]["err"] == "absent",
                           "absent state file reported via loader status")
                        ck(not logf.exists(), "absent state file -> silent fallback (no log side effects)")
                        ck(str(vt.state_path()) == str(tdp / "absent.json"),
                           "VOICE_RULES_STATE overrides the state path")
                        os.environ.pop("VOICE_RULES_STATE")
                        ck(vt.state_path().parent.name == "state" and vt.state_path().name == "voice-rules.json",
                           "default state path is <HERMES_HOME>/state/voice-rules.json")
                    except Exception as e:
                        ck(False, f"loader case absent-state: {e!r}")
                    # case: valid state file -> overrides applied at scan time, provenance preserved
                    try:
                        stf.write_text(json.dumps({
                            "format": 1,
                            "sources": {
                                "register": {"patterns": [
                                    {"pattern": "\\bfrobnicate\\b", "label": "state pattern 'frobnicate' (register)"}]},
                                "learn": {"exemplars": ["Frobnicate the paradigm to seamlessly unlock synergy."],
                                          "thresholds": {"performed candor": 0.9}}}}, indent=2))
                        os.environ["VOICE_RULES_STATE"] = str(stf)
                        eff = vt.effective_rules()
                        ck(eff["patterns"][-1] == ("\\bfrobnicate\\b", "state pattern 'frobnicate' (register)"),
                           "state pattern appended to effective patterns")
                        ck(eff["pattern_sources"][-1] == "register" and eff["pattern_sources"].count("embedded") == len(vt.PATTERNS),
                           "per-source provenance preserved (register vs embedded)")
                        state_exemplar = "Frobnicate the paradigm to seamlessly unlock synergy."
                        ck(state_exemplar in eff["exemplars"]
                           and eff["exemplar_sources"][eff["exemplars"].index(state_exemplar)] == "learn",
                           "state exemplar merged with provenance (learn)")
                        ck(eff["thresholds"].get("performed candor") == 0.9,
                           "state threshold overrides calibration per class")
                        hits = vt.find_regex_hits("Please frobnicate the stack at the end of the day.")
                        ck(len(hits) == 2 and any("frobnicate" in h for h in hits)
                           and any("at the end of the day" in h for h in hits),
                           "scan-time load: gate fires state pattern alongside embedded patterns")
                        stf.write_text(json.dumps({"format": 1, "sources": {"learn": {"patterns": [
                            {"pattern": "\\bfrobnicate\\b", "label": "updated label"}]}}}))
                        hits2 = vt.find_regex_hits("Please frobnicate the stack.")
                        ck(len(hits2) == 1 and "updated label" in hits2[0],
                           "state edit picked up at scan time without restart")
                    except Exception as e:
                        ck(False, f"loader case override-applied: {e!r}")
                    # case: corrupt state file -> embedded fallback + state_skip logged
                    try:
                        if logf.exists():
                            logf.unlink()
                        stf.write_text("{corrupt json here")
                        eff = vt.effective_rules()
                        ck(eff["patterns"] == list(vt.PATTERNS) and eff["exemplars"] == list(vt.EXEMPLARS),
                           "corrupt state file -> embedded defaults (fail-open unchanged)")
                        ck(eff["state"]["ok"] is False and "parse" in (eff["state"]["err"] or ""),
                           "corrupt state file reported as parse failure")
                        ck(logf.exists() and any('"state_skip"' in line for line in logf.read_text(errors="replace").splitlines()),
                           "corrupt state file -> state_skip logged via _log_vec")
                    except Exception as e:
                        ck(False, f"loader case corrupt-state: {e!r}")
                    # drift-check unit cases against fabricated runtime homes
                    try:
                        fake = tdp / "hermes-fake"
                        (fake / "agent-hooks").mkdir(parents=True)
                        shutil.copyfile(src / "voice-tells.py", fake / "agent-hooks" / "voice-tells.py")
                        st, msg = voice_gate_drift(vt, fake)
                        ck(st == "ok", f"drift: identical runtime gate -> ok ({msg})")
                        gate_py = fake / "agent-hooks" / "voice-tells.py"
                        gate_py.write_text(gate_py.read_text(errors="replace")
                                           + "\nPATTERNS.append((r'\\bdrifted\\b', 'drifted pattern'))\n")
                        st, msg = voice_gate_drift(vt, fake)
                        ck(st == "fail" and "drift" in msg, f"drift: modified runtime gate -> fail ({msg})")
                        st, msg = voice_gate_drift(vt, tdp / "hermes-none")
                        ck(st == "skip", f"drift: no runtime on machine -> skip ({msg})")
                        fake2 = tdp / "hermes-stateonly"
                        (fake2 / "state").mkdir(parents=True)
                        (fake2 / "state" / "voice-rules.json").write_text(json.dumps(
                            {"format": 1, "sources": {"owner": {"patterns": [
                                {"pattern": "\\bwidget\\b", "label": "owner manual 'widget'"}]}}}))
                        st, msg = voice_gate_drift(vt, fake2)
                        ck(st == "skip" and "state-only" in msg,
                           f"drift: valid state file without runtime gate -> skip with note ({msg})")
                        (fake2 / "state" / "voice-rules.json").write_text("{nope")
                        st, msg = voice_gate_drift(vt, fake2)
                        ck(st == "fail" and "state file invalid" in msg,
                           f"drift: corrupt state file -> fail even without gate ({msg})")
                    except Exception as e:
                        ck(False, f"drift unit cases: {e!r}")
                finally:
                    for k in ("VOICE_RULES_STATE", "VOICE_GATE_LOG"):
                        os.environ.pop(k, None)
                    for k, v in saved.items():
                        os.environ[k] = v
        # drift of the real machine's runtime gate vs this published mirror
        if vt is not None:
            try:
                hermes_home = os.environ.get("HERMES_HOME") or str(pathlib.Path.home() / ".hermes")
                drift_status, drift_msg = voice_gate_drift(vt, hermes_home)
                if drift_status == "skip":
                    print("SKIP voice-gate drift check: " + drift_msg)
                else:
                    ck(drift_status == "ok", f"voice-gate drift check (issue #5): {drift_msg}")
            except Exception as e:
                ck(False, f"voice-gate drift check crashed: {e!r}")

skills = list(ROOT.glob("**/SKILL.md"))
for s in skills:
    head = s.read_text()[:400]
    ck("name:" in head and "description:" in head, f"frontmatter {s.relative_to(ROOT)}")
    m = re.search(r'description:(.+)', head)
    if m:
        d = m.group(1).strip()
        ck(len(d) <= 310, f"skill description <=300 chars {s.relative_to(ROOT)} ({len(d)})")
        ck("use when the user says" in d.lower(), f"skill description carries invocation trigger {s.relative_to(ROOT)}")
        ck(len(re.findall(r"'", d)) >= 4 or len(re.findall(r'\\"', d)) >= 4 or d.count("'") >= 4, f"skill description carries quoted human phrases {s.relative_to(ROOT)}")
ck(len(skills) >= 6, f"skill count {len(skills)} >= 6")

hooks = ROOT / "plugins" / "humanizer" / "hooks" / "gate.py"
sloppy = "The tool serves as a foundation for innovation, and that is okay. It is not just about speed, it is about unlocking value at the end of the day."
clean = "The scanner loads the rules from the shared module, so the hook and the checker cannot drift."
r_chat = subprocess.run(["python3", str(hooks), "--surface", "chat"], input="The configuration was completed in order to provide a really robust system that everybody in the building uses daily without any problems.", capture_output=True, text=True)
ck(r_chat.returncode == 4, "gate chat surface fails STE-breaking text (exit 4)")
r_chat2 = subprocess.run(["python3", str(hooks), "--surface", "chat"], input="Set the timeout. The scanner reads the config first. Save the file.", capture_output=True, text=True)
ck(r_chat2.returncode == 0, "gate chat surface passes clean STE text (exit 0)")
ck("Ste" not in r_chat2.stdout, "chat pass carries no nudge")
r = subprocess.run(["python3", str(hooks)], input=sloppy, capture_output=True, text=True)
ck(r.returncode == 4 and json.loads(r.stdout)["status"] == "fail", "gate fails sloppy text (exit 4)")
r2 = subprocess.run(["python3", str(hooks)], input=clean, capture_output=True, text=True)
ck(r2.returncode == 0 and json.loads(r2.stdout)["status"] == "pass", "gate passes clean text (exit 0)")

readme = (ROOT / "README.md").read_text()
for m in re.findall(r"`([\w/.\-]+/)(?:[\w/.\-]+\s*\|)?", readme):
    pass
ck("plugins/humanizer" in readme, "README indexes humanizer plugin")
ck("PROVENANCE.md" in readme, "README links provenance ledger")

print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
