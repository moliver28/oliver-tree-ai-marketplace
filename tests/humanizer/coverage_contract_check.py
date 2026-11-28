#!/usr/bin/env python3
"""coverage_contract_check.py: deterministic drift check for the versioned
coverage contract (humanizer/COVERAGE.md, issue #162).

Law: the contract file must match the compiled state exactly. The check is
pure stdlib, offline, and model-free. It never touches gate code and never
runs in the delivery gate; scripts/verify.py runs it on every verify pass.

check_coverage_contract(root, vt=None) returns a list of failure strings;
an empty list means the contract matches the compiled state. The checks:

1. The count block states the compiled totals: the register patterns, the
   exemplar classes, the register families, the 35 catalog patterns, the
   6 ASD-STE100 rules, the 4 battery families, and the 20 gate marker
   words. Every number must equal the compiled value.
2. The catalog table carries exactly the 35 catalog patterns, ids 1 to 35,
   one row each, with a status from the fixed vocabulary and at least one
   resolvable file:line evidence pointer per row.
3. Every compiled `humanizer N` regex family needs its catalog row N marked
   implemented; every implemented row points into shipped plugin code and
   names a compiled register family, an STE rule id, or a battery family id.
4. The register-families table names exactly the compiled non-numbered
   families (byte-exact, both directions).
5. The STE table carries exactly S1 to S6, and the battery table carries
   exactly L10-1, L10-18, L10-19, and L10-20.

Row removal, count edits, status flips on mirrored rows, stale family
names, and broken evidence pointers all fail deterministically.
"""
import importlib.util
import pathlib
import re

STATUSES = ("implemented", "contextual-only", "out of scope")
CATALOG_IDS = set(range(1, 36))
STE_IDS = ("S1", "S2", "S3", "S4", "S5", "S6")
BATTERY_IDS = ("L10-1", "L10-18", "L10-19", "L10-20")
POINTER_RE = re.compile(r"([A-Za-z0-9_./-]+\.(?:py|md)):(\d+)(?:-(\d+))?")
COUNT_KEYS = ("Compiled register patterns", "Exemplar classes", "Compiled register families",
              "Catalog patterns", "ASD-STE100 rules", "Battery families", "Gate marker words")
COUNT_LINE_RE = re.compile(
    r"^- (" + "|".join(re.escape(k) for k in COUNT_KEYS) + r"): (\d+) \([a-z0-9, -]+\)$")


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_voice_tells(root):
    """Import the shipped scanner module from one root (real repo or fixture copy)."""
    return _load_module(pathlib.Path(root) / "humanizer" / "hooks" / "voice_tells.py",
                        "coverage_contract_vt")


def load_battery_core(root):
    """Import the gate-path battery core from one root (or None when absent)."""
    try:
        return _load_module(pathlib.Path(root) / "humanizer" / "learn" / "voice_battery_core.py",
                            "coverage_contract_battery_core")
    except Exception:
        return None


def compiled_families(vt):
    """The exact _family() grouping of the embedded register: {family: pattern count}."""
    out = {}
    for _pat, label in vt.PATTERNS:
        fam = vt._family(label + " (near: x)")
        out[fam] = out.get(fam, 0) + 1
    return out


def _section(text, title_prefix):
    """The body lines of the first '## ' section whose title starts with the prefix."""
    out, grab = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            grab = line[3:].strip().startswith(title_prefix)
            continue
        if grab:
            out.append(line)
    return out


def _table_rows(lines):
    """Markdown table rows after the header separator; cells stripped."""
    rows, seen_sep = [], False
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not seen_sep:
            if cells and all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                seen_sep = True
            continue
        rows.append(cells)
    return rows


def _bad_pointers(root, cell):
    """One failure string per evidence pointer in the cell that does not resolve."""
    problems = []
    pointers = POINTER_RE.findall(cell)
    if not pointers:
        return [f"no file:line evidence pointer in cell: {cell[:70]!r}"]
    for path, start, end in pointers:
        p = pathlib.Path(root) / path
        if not p.is_file():
            problems.append(f"evidence pointer target missing: {path}")
            continue
        try:
            n_lines = len(p.read_text(encoding="utf-8").splitlines())
        except OSError as e:
            problems.append(f"evidence pointer unreadable: {path} ({e!r})")
            continue
        s, e = int(start), int(end) if end else int(start)
        if s < 1 or e < s or e > n_lines:
            problems.append(f"evidence pointer out of range: {path}:{start}"
                            + (f"-{end}" if end else "") + f" (file has {n_lines} lines)")
    return problems


def _counts_block(text, vt, battery_core, fails):
    """Parse the plain-language count lines and compare them with the compiled state."""
    counts = {}
    for line in _section(text, "Plain-language counts"):
        m = COUNT_LINE_RE.match(line.strip())
        if not m:
            continue
        key, num = m.group(1), int(m.group(2))
        if key in counts:
            fails.append(f"coverage contract count line repeated: {key}")
        counts[key] = num
    expected = {
        "Compiled register patterns": len(vt.PATTERNS),
        "Exemplar classes": len(vt.EXEMPLARS),
        "Compiled register families": len(compiled_families(vt)),
        "Catalog patterns": len(CATALOG_IDS),
        "ASD-STE100 rules": len(STE_IDS),
        "Battery families": len(BATTERY_IDS),
        "Gate marker words": len(battery_core.GATE_MARKERS) if battery_core else None,
    }
    for key, want in expected.items():
        if want is None:
            continue
        got = counts.get(key)
        if got is None:
            fails.append(f"coverage contract count line missing: {key} (compiled: {want})")
        elif got != want:
            fails.append(f"coverage contract count drift: {key} says {got}, "
                         f"compiled state is {want}")
    for key in counts:
        if key not in expected:
            fails.append(f"coverage contract count line unknown: {key}")
    return counts


def check_coverage_contract(root, vt=None, cov_text=None, battery_core=None):
    """The full drift check. Returns the list of failure strings; [] = green.
    cov_text overrides the file content (temp-copy mutation tests)."""
    root = pathlib.Path(root)
    fails = []
    cov = root / "humanizer" / "COVERAGE.md"
    text = cov_text
    if text is None:
        text = cov.read_text(encoding="utf-8") if cov.is_file() else None
    if text is None:
        return ["coverage contract file missing: humanizer/COVERAGE.md"]
    if vt is None:
        try:
            vt = load_voice_tells(root)
        except Exception as e:
            return [f"coverage contract check could not import voice_tells: {e!r}"]
    if battery_core is None:
        battery_core = load_battery_core(root)

    if not re.search(r"^Contract version: \d+\.\d+\.\d+", text, re.MULTILINE):
        fails.append("coverage contract carries no 'Contract version: X.Y.Z' line")

    fams = compiled_families(vt)
    numbered = {f: n for f, n in fams.items() if re.fullmatch(r"humanizer \d+", f)}
    plain = {f: n for f, n in fams.items() if f not in numbered}
    allowed_implemented_fams = set(fams) | set(STE_IDS) | set(BATTERY_IDS)

    # 1. the count block vs the compiled state
    _counts_block(text, vt, battery_core, fails)

    # 2. the catalog table: exactly ids 1..35, fixed statuses, resolvable evidence
    by_id = {}
    for cells in _table_rows(_section(text, "Catalog patterns")):
        m = re.match(r"^(\d+)\.\s", cells[0]) if cells else None
        if not m:
            fails.append(f"catalog row without a numeric pattern id: "
                         f"{(cells[0] if cells else '')[:60]!r}")
            continue
        pid = int(m.group(1))
        if pid in by_id:
            fails.append(f"catalog pattern {pid} carries more than one row")
            continue
        by_id[pid] = cells
    for pid in sorted(CATALOG_IDS - set(by_id)):
        fails.append(f"coverage rows do not cover catalog pattern {pid}")
    for pid in sorted(set(by_id) - CATALOG_IDS):
        fails.append(f"catalog row outside the 35-pattern catalog: {pid}")
    for pid, cells in sorted(by_id.items()):
        status = cells[2] if len(cells) > 2 else ""
        fam = cells[1] if len(cells) > 1 else ""
        evidence = cells[3] if len(cells) > 3 else ""
        if status not in STATUSES:
            fails.append(f"catalog pattern {pid}: status {status!r} outside the "
                         f"vocabulary {STATUSES}")
        if not fam:
            fails.append(f"catalog pattern {pid}: empty family cell")
        if not evidence:
            fails.append(f"catalog pattern {pid}: empty evidence cell")
        else:
            fails.extend(f"catalog pattern {pid}: {p}"
                         for p in _bad_pointers(root, evidence))
        if status == "implemented":
            if not any(pathlib.PurePosixPath(path).suffix == ".py"
                       and "humanizer" in pathlib.PurePosixPath(path).parts
                       for path, _s, _e in POINTER_RE.findall(evidence)):
                fails.append(f"catalog pattern {pid}: implemented row points at no "
                             f"shipped plugin code file")
            if fam not in allowed_implemented_fams:
                fails.append(f"catalog pattern {pid}: implemented family {fam!r} is not a "
                             f"compiled family, an STE rule id, or a battery family id")

    # 3. compiled `humanizer N` families need their catalog row implemented
    for f in numbered:
        pid = int(f.split()[1])
        row = by_id.get(pid)
        if row is None or (len(row) > 2 and row[2] != "implemented"):
            fails.append(f"compiled register family {f!r} has no implemented catalog row")

    # 4. register-families table vs the compiled non-numbered families, both ways
    file_plain = set()
    for cells in _table_rows(_section(text, "Register families")):
        fam = cells[0] if cells else ""
        if not fam:
            fails.append("register-families table carries an empty row")
            continue
        file_plain.add(fam)
        if fam not in plain:
            fails.append(f"register-families row is not a compiled family: {fam!r}")
        status = cells[1] if len(cells) > 1 else ""
        if status not in STATUSES:
            fails.append(f"register family {fam!r}: status {status!r} outside the "
                         f"vocabulary {STATUSES}")
        evidence = cells[2] if len(cells) > 2 else ""
        if not evidence:
            fails.append(f"register family {fam!r}: empty evidence cell")
        else:
            fails.extend(f"register family {fam!r}: {p}"
                         for p in _bad_pointers(root, evidence))
    for fam in sorted(set(plain) - file_plain):
        fails.append(f"compiled register family missing from the contract: {fam!r}")

    # 5. the STE table: exactly S1..S6; the battery table: exactly the four ids
    ste_seen = []
    for cells in _table_rows(_section(text, "ASD-STE100")):
        m = re.match(r"^(S\d)\.", cells[0]) if cells else None
        if not m:
            fails.append(f"STE row without an S-rule id: "
                         f"{(cells[0] if cells else '')[:60]!r}")
            continue
        ste_seen.append(m.group(1))
        status = cells[2] if len(cells) > 2 else ""
        if status not in STATUSES:
            fails.append(f"STE rule {m.group(1)}: status {status!r} outside the "
                         f"vocabulary {STATUSES}")
        evidence = cells[3] if len(cells) > 3 else ""
        if not evidence:
            fails.append(f"STE rule {m.group(1)}: empty evidence cell")
        else:
            fails.extend(f"STE rule {m.group(1)}: {p}"
                         for p in _bad_pointers(root, evidence))
    if sorted(ste_seen) != sorted(STE_IDS):
        fails.append(f"STE table must carry exactly {STE_IDS}; found {sorted(ste_seen)}")

    bat_seen = []
    for cells in _table_rows(_section(text, "Battery families")):
        m = re.match(r"^(L10-\d+)\.", cells[0]) if cells else None
        if not m:
            fails.append(f"battery row without an L10 id: "
                         f"{(cells[0] if cells else '')[:60]!r}")
            continue
        bat_seen.append(m.group(1))
        status = cells[1] if len(cells) > 1 else ""
        if status not in STATUSES:
            fails.append(f"battery family {m.group(1)}: status {status!r} outside the "
                         f"vocabulary {STATUSES}")
        evidence = cells[2] if len(cells) > 2 else ""
        if not evidence:
            fails.append(f"battery family {m.group(1)}: empty evidence cell")
        else:
            fails.extend(f"battery family {m.group(1)}: {p}"
                         for p in _bad_pointers(root, evidence))
    if sorted(bat_seen) != sorted(BATTERY_IDS):
        fails.append(f"battery table must carry exactly {BATTERY_IDS}; "
                     f"found {sorted(bat_seen)}")

    return fails
