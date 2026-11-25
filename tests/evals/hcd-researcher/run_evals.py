#!/usr/bin/env python3
"""Seeded-error eval runner for the hcd-researcher agent (issue 120).

Operator-run only; never a wired gate, never imported by the three gates.
One run dispatches one review per case in ``evals.json`` and scores the
saved replies mechanically against the planted defects:

- CAUGHT: the output names the planted claim - a findings entry's claim or
  source field, or the verdict line's own p0 entries (normalized substring
  match; the containment rule of ``lib/prompts.py:117-119`` with punctuation
  and citation markers folded, so an exact quote always matches).
- FALSE POSITIVE: a findings entry that matches no planted claim of its case.
- FALSE ALARM: a planted non-p0 case (or a case whose planted p0 went
  uncaught) that still produced a ``p0`` verdict line; counts as a false
  positive. The second trigger deliberately extends design section 2.3,
  which names only the planted non-p0 case: a ``p0`` verdict with no
  caught p0 names no evidence, so it is scored as a false positive. No
  recorded run has fired it (issue 133).
- A planted p0 counts toward p0 recall only when it is caught AND its
  case produced the ``p0`` verdict.

Verdict line (exact): ``F1 <n> | recall <n> | precision <n> | p0 recall
<n> | verdict PASS|FAIL`` — with ``| verified-catch <n>`` appended when
the run's cases carry verified ground truth (issue #132). PASS requires
every planted p0 caught with a p0 verdict and overall F1 at or above the
baseline F1 recorded in ``baseline.json`` (the first recorded run sets
it); the verified-catch line is informational and never gates the PASS
bar. Per case, ``evals.json`` may list ``verified``: creditable real
weaknesses of the base artifact; a findings entry is a verified catch
when its match form contains one (the same containment rule as planted
flaws). Precision keeps its historical definition: verified catches are
not removed from the false-positive pool, so the recorded metric series
stays comparable across baselines; the new line carries the credit.

Per-class metrics credit each caught claim to its planted class; a false
positive counts toward the class of its case when the case planted
exactly one class, and stays global otherwise.

Usage::

    python tests/evals/hcd-researcher/run_evals.py prepare [--run-dir <name>]
    python tests/evals/hcd-researcher/run_evals.py score --run-dir <name>
    python tests/evals/hcd-researcher/run_evals.py record --run-dir <name>

``prepare`` copies the base artifacts into ``runs/<name>/artifacts/``,
applies the planted edits mechanically (spec key paths for the draft
suite; anchored line replacement for the report suite), writes
``runs/<name>/dispatch/case-<id>.txt`` (the full dispatch prompt), and
prints each prompt. Dispatch each prompt to one general-purpose
subagent (foreground, at most 3 in flight) and save each reply to
``runs/<name>/outputs/case-<id>.txt`` the moment it lands.
``score`` writes ``scores.json`` and ``verdict.txt``. ``record`` appends
the run to ``baseline.json`` with the scores and the EOL-normalized
sha256 of every researcher instruction asset (the same hash rule as
``tests/test_parity.py:54-58``); runs append and the newest PASS wins.

Exit codes: 0 done, 2 usage, 3 missing inputs (an output file or a
location the applier could not find).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parents[2]
EVALS_JSON = EVALS_DIR / "evals.json"
BASELINE = EVALS_DIR / "baseline.json"
RUNS = EVALS_DIR / "runs"
PLUGIN_ROOT = REPO_ROOT / "uxr-plugin"

#: The full dispatch prompt prefix every case input carries (the harness run law).
DISPATCH_PREFIX = (
    "You are the researcher defined in `uxr-plugin/agents/hcd-researcher.md`; "
    "follow that file as your agent definition and "
    "`uxr-plugin/prompts/hcd-gate/fragments/verdict-contract.md` as your output contract."
)

ASSET_FILES = (
    "uxr-plugin/agents/hcd-researcher.md",
    "uxr-plugin/prompts/hcd-gate/prompt.md",
    "uxr-plugin/references/script-rigor.md",
)
FRAGMENT_GLOB = "uxr-plugin/prompts/hcd-gate/fragments/*.md"

SPEC_LOCATION_RE = re.compile(r"^([A-Za-z_]\w*)(?:\[(\d+)\])?(?:\.([A-Za-z_]\w*))?$")


def _normalized(text: str) -> str:
    """Whitespace-collapsed, case-folded form for exact containment checks."""
    return " ".join(str(text).split()).casefold()


_MATCH_STRIP_RE = re.compile(r"[^a-z0-9]+")
_CITATION_RE = re.compile(r"\[S:[^\]]*\]")


def _match_norm(text: str) -> str:
    """The match form for claim containment: case-folded, punctuation-folded
    to word boundaries, citation markers and bullet markers dropped, so an
    exact quote of the planted wording always contains the planted match form."""
    cleaned = _CITATION_RE.sub(" ", str(text))
    cleaned = re.sub(r"^\s*-\s+", "", cleaned)
    return _MATCH_STRIP_RE.sub(" ", cleaned.casefold()).strip()


def _eol_sha256(path: Path) -> str:
    """Content hash, EOL-normalized so a pin survives any checkout."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def instruction_assets() -> dict:
    """The EOL-normalized sha256 of every researcher instruction asset."""
    hashes = {}
    for rel in ASSET_FILES:
        path = REPO_ROOT / rel
        if path.is_file():
            hashes[rel] = _eol_sha256(path)
    for path in sorted(REPO_ROOT.glob(FRAGMENT_GLOB)):
        hashes[f"uxr-plugin/prompts/hcd-gate/fragments/{path.name}"] = _eol_sha256(path)
    return hashes


# ---------------------------------------------------------------------------
# prepare: copy, plant, dispatch
# ---------------------------------------------------------------------------


def _apply_spec_plant(spec: dict, location: str, text: str) -> None:
    """Replace the value at a spec key path (``hypotheses[1].text``) with ``text``."""
    match = SPEC_LOCATION_RE.match(location)
    if not match:
        raise ValueError(f"unsupported spec location {location!r}")
    key, index, sub = match.group(1), match.group(2), match.group(3)
    if index is None and sub is None:
        if key not in spec:
            raise ValueError(f"location {location!r} not found in the spec")
        spec[key] = text
        return
    if key not in spec or not isinstance(spec[key], (dict, list)):
        raise ValueError(f"location {location!r} not found in the spec")
    if index is not None:
        try:
            row = spec[key][int(index)]
        except (IndexError, TypeError):
            raise ValueError(f"location {location!r} not found in the spec") from None
        if sub:
            if not isinstance(row, dict) or sub not in row:
                raise ValueError(f"location {location!r} not found in the spec")
            row[sub] = text
        else:
            spec[key][int(index)] = text
    else:
        if not isinstance(spec[key], dict) or sub not in spec[key]:
            raise ValueError(f"location {location!r} not found in the spec")
        spec[key][sub] = text


def _apply_report_plant(lines: list[str], location: str, text: str) -> None:
    """Replace the one line that contains the anchor ``location`` with ``text``."""
    for index, line in enumerate(lines):
        if location in line:
            lines[index] = text
            return
    raise ValueError(f"location anchor {location!r} not found in the report")


def prepare(run_name: str) -> int:
    data = json.loads(EVALS_JSON.read_text(encoding="utf-8"))
    run_dir = RUNS / run_name
    artifacts = run_dir / "artifacts"
    dispatch_dir = run_dir / "dispatch"
    artifacts.mkdir(parents=True, exist_ok=True)
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    manifest_cases = []
    for case in data["cases"]:
        case_id = case["id"]
        base = REPO_ROOT / case["base_artifact"]
        suite = case["suite"]
        suffix = ".json" if suite == "draft-spec" else ".md"
        target = artifacts / f"case-{case_id}{suffix}"
        shutil.copyfile(base, target)
        try:
            for plant in case["planted"]:
                if suite == "draft-spec":
                    spec = json.loads(target.read_text(encoding="utf-8"))
                    _apply_spec_plant(spec, plant["location"], plant["text"])
                    target.write_text(
                        json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                    )
                else:
                    lines = target.read_text(encoding="utf-8").splitlines()
                    _apply_report_plant(lines, plant["location"], plant["text"])
                    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except ValueError as exc:  # a plant location the applier could not find: exit 3
            print(f"prepare: case {case_id}: {exc}", file=sys.stderr)
            return 3
        prompt = f"{DISPATCH_PREFIX}\n\nArtifact: {target.resolve()}\n\n{case['request']}"
        (dispatch_dir / f"case-{case_id}.txt").write_text(prompt + "\n", encoding="utf-8")
        print(prompt)
        print("-" * 72)
        manifest_cases.append(
            {
                "id": case_id,
                "suite": suite,
                "artifact": target.name,
                "planted": case["planted"],
                "verified": case.get("verified", []),
            }
        )
    manifest = {
        "run_dir": run_name,
        "recorded": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cases": manifest_cases,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"prepared {len(manifest_cases)} cases in {run_dir}")
    return 0


# ---------------------------------------------------------------------------
# score: parse outputs, match, metrics
# ---------------------------------------------------------------------------

_VERDICT_LINE_RE = re.compile(r"verdict:\s*(\{.*\})\s*$", re.MULTILINE)
_FINDINGS_HEAD_SPLIT_RE = re.compile(r"^findings:[ \t]*$", re.MULTILINE)
_FINDING_FIELDS_RE = re.compile(
    r"claim:\s*\"?(.*?)\"?\s*,\s*source:\s*\"?(.*?)\"?\s*,\s*confidence:\s*\"?(high|medium|low)\"?\s*$",
    re.IGNORECASE,
)


def _parse_output(text: str) -> dict:
    """The findings entries and the verdict of one saved reply (tolerant parse).

    Each findings entry yields ``claim`` and ``source`` (either may carry the
    planted wording); the verdict yields its ``result`` word and the ``p0``
    list, whose entries name the claims the agent says invalidate the
    artifact.
    """
    entries: list[dict] = []
    blocks = _FINDINGS_HEAD_SPLIT_RE.split(text)
    if len(blocks) > 1:
        for line in blocks[-1].splitlines():
            stripped = line.strip()
            if not (stripped.startswith("- {") and stripped.endswith("}")):
                continue
            content = stripped[3:-1].strip()
            claim = source = ""
            try:
                parsed = json.loads("{" + content + "}")
                claim = str(parsed.get("claim") or "")
                source = str(parsed.get("source") or "")
            except ValueError:
                match = _FINDING_FIELDS_RE.search(content)
                if match:
                    claim = match.group(1).strip()
                    source = match.group(2).strip()
            if claim or source:
                entries.append({"claim": claim, "source": source})
    verdict_result = ""
    verdict_p0: list[str] = []
    for raw in reversed(_VERDICT_LINE_RE.findall(text)):
        try:
            parsed = json.loads(raw)
        except ValueError:
            continue
        if isinstance(parsed, dict) and str(parsed.get("result") or ""):
            verdict_result = str(parsed["result"])
            p0_list = parsed.get("p0")
            if isinstance(p0_list, list):
                verdict_p0 = [str(entry) for entry in p0_list if str(entry).strip()]
            break
    return {"entries": entries, "verdict": verdict_result, "verdict_p0": verdict_p0}


def _score_run(run_dir: Path) -> dict:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    outputs = run_dir / "outputs"
    case_rows, case_triples = [], []
    planted_all, caught_all, fp_all = [], [], 0
    verified_total_all = verified_caught_all = 0
    for case in manifest["cases"]:
        case_id = case["id"]
        output_file = outputs / f"case-{case_id}.txt"
        if not output_file.is_file():
            print(f"score: missing output {output_file}", file=sys.stderr)
            return {}
        parsed = _parse_output(output_file.read_text(encoding="utf-8", errors="replace"))
        planted = case["planted"]
        planted_norms = [(p["id"], p["class"], p["severity"], _match_norm(p["text"])) for p in planted]
        # The naming pool: every findings entry (claim plus source) and the
        # verdict's own p0 entries, all in match form.
        entry_norms = [
            _match_norm(f"{entry['claim']} {entry['source']}") for entry in parsed["entries"]
        ]
        verdict_norms = [_match_norm(entry) for entry in parsed["verdict_p0"]]
        verified_norms = [
            (f"v{i}", _match_norm(v)) for i, v in enumerate(case.get("verified", []), 1)
        ]
        caught_ids, matched_flags = [], []
        for entry_norm in entry_norms:
            matched = [
                (pid, pclass, psev, pnorm)
                for pid, pclass, psev, pnorm in planted_norms
                if pnorm and pnorm in entry_norm
            ]
            if matched:
                matched_flags.append(True)
                for pid, _pclass, _psev, _pnorm in matched:
                    if pid not in caught_ids:
                        caught_ids.append(pid)
            else:
                matched_flags.append(False)
        for pid, _pclass, _psev, pnorm in planted_norms:
            if pnorm and any(pnorm in vnorm for vnorm in verdict_norms) and pid not in caught_ids:
                caught_ids.append(pid)
        planted_p0_ids = [pid for pid, _c, sev, _n in planted_norms if sev == "p0"]
        caught_p0_ids = [pid for pid in planted_p0_ids if pid in caught_ids]
        p0_verdict = parsed["verdict"] == "p0"
        false_alarm = p0_verdict and not caught_p0_ids
        false_positives = matched_flags.count(False) + (1 if false_alarm else 0)
        verified_caught = [
            vid for vid, vnorm in verified_norms
            if vnorm and any(vnorm in entry_norm for entry_norm in entry_norms)
        ]
        case_rows.append(
            {
                "id": case_id,
                "entries": len(parsed["entries"]),
                "caught": caught_ids,
                "missed": [pid for pid, _c, _s, _n in planted_norms if pid not in caught_ids],
                "verdict_result": parsed["verdict"],
                "false_alarm": false_alarm,
                "false_positives": false_positives,
                "verified_total": len(verified_norms),
                "verified_caught": len(verified_caught),
                "verified_ids": verified_caught,
            }
        )
        planted_all.extend(planted_norms)
        caught_all.extend(
            [(pid, pclass, psev) for pid, pclass, psev, _n in planted_norms if pid in caught_ids]
        )
        fp_all += false_positives
        verified_total_all += len(verified_norms)
        verified_caught_all += len(verified_caught)
        case_triples.append((case_id, planted_norms, case_rows[-1]))

    total, caught_n = len(planted_all), len(caught_all)
    precision = caught_n / (caught_n + fp_all) if (caught_n + fp_all) else 0.0
    recall = caught_n / total if total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    # p0 recall is per case: a planted p0 counts only when its own case's
    # findings caught it AND that case produced the p0 verdict.
    p0_total = 0
    p0_ok = 0
    for _case_id, planted_norms, row in case_triples:
        for pid, _pclass, sev, _n in planted_norms:
            if sev != "p0":
                continue
            p0_total += 1
            if pid in row["caught"] and row["verdict_result"] == "p0":
                p0_ok += 1
    p0_recall = (p0_ok / p0_total) if p0_total else 1.0

    classes = sorted({pclass for _pid, pclass, _sev in caught_all}
                     | {pclass for _pid, pclass, _sev, _n in planted_all})
    single_class_cases = {
        case["id"]: case["planted"][0]["class"]
        for case in manifest["cases"]
        if len({p["class"] for p in case["planted"]}) == 1
    }
    per_class = {}
    for klass in classes:
        c_total = sum(1 for _pid, pclass, _sev, _n in planted_all if pclass == klass)
        c_caught = sum(1 for _pid, pclass, _sev in caught_all if pclass == klass)
        c_fp = sum(
            row["false_positives"]
            for row in case_rows
            if single_class_cases.get(row["id"]) == klass
        )
        c_precision = c_caught / (c_caught + c_fp) if (c_caught + c_fp) else 0.0
        c_recall = c_caught / c_total if c_total else 0.0
        c_f1 = (
            2 * c_precision * c_recall / (c_precision + c_recall) if (c_precision + c_recall) else 0.0
        )
        per_class[klass] = {
            "planted": c_total,
            "caught": c_caught,
            "precision": round(c_precision, 4),
            "recall": round(c_recall, 4),
            "f1": round(c_f1, 4),
        }

    baseline_f1 = None
    if BASELINE.is_file():
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
        baseline_f1 = base.get("baseline_f1")
    f1_bar_met = baseline_f1 is None or f1 >= baseline_f1
    pass_run = p0_recall == 1.0 and f1_bar_met
    verdict_word = "PASS" if pass_run else "FAIL"
    verdict_line = (
        f"F1 {f1:.2f} | recall {recall:.2f} | precision {precision:.2f} "
        f"| p0 recall {p0_recall:.2f} | verdict {verdict_word}"
    )
    if verified_total_all:
        verdict_line += f" | verified-catch {verified_caught_all / verified_total_all:.2f}"
    return {
        "run_dir": str(run_dir),
        "cases": case_rows,
        "per_class": per_class,
        "overall": {
            "planted": total,
            "caught": caught_n,
            "false_positives": fp_all,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "p0_recall": round(p0_recall, 4),
            "verified_total": verified_total_all,
            "verified_caught": verified_caught_all,
            "verified_rate": round(verified_caught_all / verified_total_all, 4) if verified_total_all else None,
        },
        "baseline_f1": baseline_f1,
        "verdict_line": verdict_line,
        "verdict": verdict_word,
    }


def score(run_name: str) -> int:
    run_dir = RUNS / run_name
    result = _score_run(run_dir)
    if not result:
        return 3
    (run_dir / "scores.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "verdict.txt").write_text(result["verdict_line"] + "\n", encoding="utf-8")
    print(json.dumps(result["overall"], ensure_ascii=False, indent=2))
    print(json.dumps(result["per_class"], ensure_ascii=False, indent=2))
    print(result["verdict_line"])
    return 0


# ---------------------------------------------------------------------------
# record: append the run to baseline.json
# ---------------------------------------------------------------------------


def _entry_date(run_name: str) -> str:
    """The recorded entry date: the run-dir name's date prefix, else today.

    The run name is the date-stamped label the operator gave the run, so
    the entry date follows it instead of the record-time clock, which can
    straddle midnight between prepare and record (issue 133).
    """
    match = re.match(r"(\d{4}-\d{2}-\d{2})", run_name)
    return match.group(1) if match else time.strftime("%Y-%m-%d")


def record(run_name: str) -> int:
    run_dir = RUNS / run_name
    result = _score_run(run_dir)
    if not result:
        return 3
    assets = instruction_assets()
    entry = {
        "date": _entry_date(run_name),
        "dir": f"runs/{run_name}",
        "verdict": result["verdict"],
        "verdict_line": result["verdict_line"],
        "f1": result["overall"]["f1"],
        "recall": result["overall"]["recall"],
        "precision": result["overall"]["precision"],
        "p0_recall": result["overall"]["p0_recall"],
        "instruction_assets": assets,
    }
    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {}
    base.setdefault("recorded", entry["date"])
    if "baseline_f1" not in base:
        base["baseline_f1"] = result["overall"]["f1"]
    base.setdefault("runs", [])
    base["runs"].append(entry)
    if result["verdict"] == "PASS":
        base["instruction_assets"] = assets
    BASELINE.write_text(
        json.dumps(base, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(result["verdict_line"])
    print(f"recorded run {entry['dir']} in {BASELINE}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if not args:
        print(__doc__.strip().splitlines()[0])
        return 2
    command = args[0]
    if command == "prepare":
        run_name = ""
        if "--run-dir" in args[1:]:
            index = args.index("--run-dir")
            if index + 1 >= len(args):
                print("prepare: --run-dir needs a value", file=sys.stderr)
                return 2
            run_name = args[index + 1]
        if not run_name:
            run_name = time.strftime("%Y%m%d-%H%M%S")
        return prepare(run_name)
    if command in ("score", "record"):
        if "--run-dir" not in args[1:]:
            print(f"{command}: --run-dir is required", file=sys.stderr)
            return 2
        index = args.index("--run-dir")
        if index + 1 >= len(args):
            print(f"{command}: --run-dir needs a value", file=sys.stderr)
            return 2
        run_name = args[index + 1]
        if not (RUNS / run_name).is_dir():
            print(f"{command}: no run dir {(RUNS / run_name)}", file=sys.stderr)
            return 2
        return score(run_name) if command == "score" else record(run_name)
    print(f"unknown command {command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
