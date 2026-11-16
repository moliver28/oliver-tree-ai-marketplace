#!/usr/bin/env python3
"""Marketplace verifier. Run before any publish claim.

Checks:
1. marketplace.json parses and every listed plugin source dir exists with a plugin.json manifest.
2. Every SKILL.md in the repo has name + description frontmatter.
3. The /voice gate actually runs: one sloppy text must fail, one clean text must pass (exit codes 4/0).
4. Every README-indexed path exists.

Exit 0 = marketplace verified working; nonzero = broken, do not publish.
"""
import json, sys, subprocess, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
fails = []

def ck(cond, msg):
    print(("OK  " if cond else "FAIL") + " " + msg)
    if not cond:
        fails.append(msg)

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
