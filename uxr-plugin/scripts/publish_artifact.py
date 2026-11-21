#!/usr/bin/env python3
"""Publish a rendered report to the static gallery site (issue 03).

``publish_artifact.py publish <html> --slug <slug> --ticket <KEY>
--pod <area> --tier <tier> --audience <audience> --date <YYYY-MM-DD>
--title "<title>" --repo-path <dir> --pages-url <url> [--force]`` files
one rendered report into the gallery repository:

- refuses unless the repo is on ``main`` and clean -- no commit is made
  otherwise;
- refuses a slug folder holding foreign files unless ``--force`` (the
  report command never passes ``--force`` for the user);
- writes ``<slug>/index.html``, upserts ``manifest.json`` (keyed by
  slug), rebuilds the static gallery ``index.html`` (client-side search,
  filter chips, every value HTML-escaped), and updates the README list
  between the ``<!-- reports:start -->`` / ``<!-- reports:end -->``
  markers (creating them at the end when missing);
- commits the touched paths and pushes -- never force-push, never
  stash, never reset;
- prints the page URL (``--pages-url`` + ``/<slug>/``).

Publish is never automatic: the report command asks before calling this.

Exit codes: 0 published, 1 refused or failed, 2 usage, 4 self-test
failure.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from html import escape as html_escape
from pathlib import Path

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_SELFTEST = 4

README_START = "<!-- reports:start -->"
README_END = "<!-- reports:end -->"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

REQUIRED_FLAGS = ("--slug", "--ticket", "--pod", "--tier", "--audience",
                  "--date", "--title", "--repo-path", "--pages-url")


# ---------------------------------------------------------------------------
# git plumbing (read-only checks first; writes only after every refusal)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def check_repo_state(repo: Path) -> tuple[bool, str]:
    """(ok, reason) for the publish preconditions: branch main, tree clean."""
    code, output = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0:
        return False, f"not a usable git repository ({output.strip().splitlines()[0] if output.strip() else 'git failed'})"
    branch = output.strip().splitlines()[0].strip() if output.strip() else ""
    if branch != "main":
        return False, f"repository is on branch {branch!r}; publish requires main"
    code, output = _git(repo, "status", "--porcelain")
    if code != 0:
        return False, "git status failed; refusing to publish"
    if output.strip():
        return False, "working tree is dirty; commit or clean it first"
    return True, ""


def foreign_files(repo: Path, slug: str) -> list[str]:
    """Entries inside the slug folder other than index.html."""
    folder = repo / slug
    if not folder.is_dir():
        return []
    return sorted(
        entry.name for entry in folder.iterdir() if entry.name != "index.html"
    )


# ---------------------------------------------------------------------------
# manifest, gallery, README
# ---------------------------------------------------------------------------


def load_manifest(repo: Path) -> list[dict] | None:
    """The gallery manifest list, or None when absent or not a list."""
    path = repo / "manifest.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def upsert_entry(manifest: list[dict], entry: dict) -> list[dict]:
    """Replace the entry with the same slug, else append; order preserved."""
    result: list[dict] = []
    replaced = False
    for existing in manifest:
        if isinstance(existing, dict) and existing.get("slug") == entry["slug"]:
            result.append(dict(entry))
            replaced = True
        else:
            result.append(existing)
    if not replaced:
        result.append(dict(entry))
    return result


def build_gallery(manifest: list[dict]) -> str:
    """The static gallery page: search box, filter chips, escaped cards."""
    entries = sorted(
        [item for item in manifest if isinstance(item, dict) and item.get("slug")],
        key=lambda item: (str(item.get("date", "")), str(item.get("slug", ""))),
        reverse=True,
    )

    def distinct(key: str) -> list[str]:
        return sorted({str(item.get(key, "")).strip() for item in entries} - {""})

    tiers = distinct("tier")
    audiences = distinct("audience")
    pods = distinct("pod")

    def chips(role: str, values: list[str]) -> str:
        rendered = "".join(
            f'<button class="chip" data-{role}="{html_escape(value, quote=True)}" '
            f'onclick="filterGallery()">{html_escape(value, quote=True)}</button>'
            for value in values
        )
        return f'<div class="chips" data-role="{role}">{rendered}</div>'

    cards = "".join(
        '<article class="card" data-tier="{tier}" data-audience="{audience}" '
        'data-pod="{pod}" data-text="{text}">'
        '<h2><a href="{href}">{title}</a></h2>'
        '<p class="meta">{ticket} - {date} - {tier_line} - {audience_line} - {pod_line}</p>'
        "</article>".format(
            tier=html_escape(str(item.get("tier", "")), quote=True),
            audience=html_escape(str(item.get("audience", "")), quote=True),
            pod=html_escape(str(item.get("pod", "")), quote=True),
            text=html_escape(
                " ".join(str(item.get(key, "")) for key in
                         ("title", "ticket", "pod", "tier", "audience", "date", "slug")),
                quote=True,
            ),
            href=html_escape(f"{item['slug']}/", quote=True),
            title=html_escape(str(item.get("title", "")) or item["slug"], quote=False),
            ticket=html_escape(str(item.get("ticket", "")), quote=False),
            date=html_escape(str(item.get("date", "")), quote=False),
            tier_line=html_escape(str(item.get("tier", "")), quote=False),
            audience_line=html_escape(str(item.get("audience", "")), quote=False),
            pod_line=html_escape(str(item.get("pod", "")), quote=False),
        )
        for item in entries
    )
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<title>Research report gallery</title>\n<style>\n"
        "body { font: 16px/1.6 system-ui, sans-serif; margin: 0 auto; "
        "max-width: 46rem; padding: 1.5rem; }\n"
        ".chip { margin: 0.15rem; cursor: pointer; }\n"
        ".card { border: 1px solid #d0d7de; border-radius: 0.4rem; "
        "padding: 0.75rem 1rem; margin: 0.75rem 0; }\n"
        ".meta { color: #57606a; font-size: 0.9rem; }\n"
        "</style>\n</head>\n<body>\n"
        "<h1>Research report gallery</h1>\n"
        '<input id="q" type="search" placeholder="Search reports" '
        'oninput="filterGallery()">\n'
        + chips("tier", tiers) + chips("audience", audiences) + chips("pod", pods)
        + '<div id="cards">\n' + cards + "\n</div>\n"
        "<script>\n"
        "function filterGallery() {\n"
        "  var query = document.getElementById('q').value.toLowerCase();\n"
        "  var chips = document.querySelectorAll('.chip');\n"
        "  var active = {};\n"
        "  chips.forEach(function (chip) {\n"
        "    if (chip.getAttribute('data-on') === '1') {\n"
        "      var role = chip.parentElement.getAttribute('data-role');\n"
        "      active[role] = chip.textContent;\n"
        "    }\n"
        "  });\n"
        "  document.querySelectorAll('.card').forEach(function (card) {\n"
        "    var ok = card.getAttribute('data-text').toLowerCase().indexOf(query) >= 0;\n"
        "    Object.keys(active).forEach(function (role) {\n"
        "      if (card.getAttribute('data-' + role) !== active[role]) { ok = false; }\n"
        "    });\n"
        "    card.style.display = ok ? '' : 'none';\n"
        "  });\n"
        "}\n"
        "document.querySelectorAll('.chip').forEach(function (chip) {\n"
        "  chip.addEventListener('click', function () {\n"
        "    chip.setAttribute('data-on', chip.getAttribute('data-on') === '1' ? '0' : '1');\n"
        "    filterGallery();\n"
        "  });\n"
        "});\n"
        "</script>\n</body>\n</html>\n"
    )


def update_readme(current: str, entry: dict) -> str:
    """Rewrite the list between the markers (create them at the end)."""
    row = (
        f"- {html_escape(str(entry.get('date', '')), quote=False)} - "
        f"[{html_escape(str(entry.get('title', '')), quote=False)}]"
        f"({html_escape(str(entry.get('slug', '')), quote=False)}/) "
        f"({html_escape(str(entry.get('ticket', '')), quote=False)}, "
        f"{html_escape(str(entry.get('tier', '')), quote=False)})"
    )
    lines = current.splitlines()
    try:
        start = lines.index(README_START)
        end = lines.index(README_END, start + 1)
    except ValueError:
        body = [line for line in lines if line.strip()]
        while body and not body[-1].strip():
            body.pop()
        return (
            "\n".join(body)
            + ("\n\n" if body else "")
            + "## Published reports\n\n"
            + README_START + "\n" + row + "\n" + README_END + "\n"
        )
    kept = [line for line in lines[start + 1:end] if line.strip()]
    updated = "\n".join(
        lines[:start + 1]
        + sorted(kept + [row])
        + lines[end:]
    )
    return updated + ("\n" if not updated.endswith("\n") else "")


# ---------------------------------------------------------------------------
# the publish flow
# ---------------------------------------------------------------------------


def publish(
    html_path: Path,
    slug: str,
    ticket: str,
    pod: str,
    tier: str,
    audience: str,
    date_text: str,
    title: str,
    repo_path: Path,
    pages_url: str,
    force: bool = False,
) -> int:
    """Run the full publish; prints REFUSE lines or the page URL."""
    slug = str(slug or "").strip()
    if not SLUG_RE.match(slug):
        print(f"REFUSE: slug must be lowercase letters, digits, hyphens: {slug!r}")
        return EXIT_FAIL
    if not DATE_RE.match(str(date_text or "").strip()):
        print(f"REFUSE: date must look like YYYY-MM-DD: {date_text!r}")
        return EXIT_FAIL
    if not html_path.is_file():
        print(f"REFUSE: rendered html not found: {html_path}")
        return EXIT_FAIL
    repo_path = repo_path.expanduser()
    ok, reason = check_repo_state(repo_path)
    if not ok:
        print(f"REFUSE: {reason}")
        return EXIT_FAIL
    foreigners = foreign_files(repo_path, slug)
    if foreigners and not force:
        print(
            f"REFUSE: {slug}/ holds files this publish did not create "
            f"({', '.join(foreigners)}); clean the folder or pass --force"
        )
        return EXIT_FAIL
    manifest = load_manifest(repo_path)
    if manifest is None:
        print("REFUSE: manifest.json exists but is not a JSON list; fix it by hand")
        return EXIT_FAIL
    pages_url = str(pages_url or "").strip().rstrip("/")

    entry = {
        "slug": slug,
        "ticket": str(ticket or "").strip(),
        "pod": str(pod or "").strip(),
        "tier": str(tier or "").strip(),
        "audience": str(audience or "").strip(),
        "date": str(date_text or "").strip(),
        "title": str(title or "").strip() or slug,
        "url": f"{pages_url}/{slug}/" if pages_url else f"{slug}/",
    }

    # writes start here; every refusal has already happened
    folder = repo_path / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(
        html_path.expanduser().read_text(encoding="utf-8"), encoding="utf-8"
    )
    manifest = upsert_entry(manifest, entry)
    (repo_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (repo_path / "index.html").write_text(build_gallery(manifest), encoding="utf-8")
    readme_path = repo_path / "README.md"
    current = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
    readme_path.write_text(update_readme(current, entry), encoding="utf-8")

    targets = [f"{slug}/index.html", "manifest.json", "index.html", "README.md"]
    code, output = _git(repo_path, "add", "--", *targets)
    if code != 0:
        print(f"FAILED: git add did not succeed: {output.strip()}")
        return EXIT_FAIL
    code, _ = _git(repo_path, "diff", "--cached", "--quiet")
    if code == 0:
        print(f"nothing changed for {slug}; repository already up to date")
    else:
        code, output = _git(
            repo_path, "commit", "-m", f"publish: {slug} ({entry['ticket']})"
        )
        if code != 0:
            print(f"FAILED: git commit did not succeed: {output.strip()}")
            return EXIT_FAIL
    code, output = _git(repo_path, "push", "origin", "HEAD")
    if code != 0:
        print(f"FAILED: git push did not succeed: {output.strip()}")
        return EXIT_FAIL
    print(f"Published {slug} -> {entry['url']}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__.strip().splitlines()[0])  # terse bare-run pointer; -h prints the full doc
        return EXIT_OK
    if args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return EXIT_USAGE
    if args[0] != "publish":
        print(f"publish_artifact: unknown subcommand {args[0]!r}", file=sys.stderr)
        return EXIT_USAGE
    flags: dict[str, str] = {}
    positional: list[str] = []
    for arg in args[1:]:
        if arg.startswith("--") and "=" in arg:
            flag, value = arg.split("=", 1)
            flags[flag] = value
        elif arg == "--force":
            flags["--force"] = "1"
        elif arg.startswith("--"):
            print(f"publish_artifact: {arg} needs a value", file=sys.stderr)
            return EXIT_USAGE
        else:
            positional.append(arg)
    if len(positional) != 1:
        print("publish_artifact: publish needs exactly one <html> path", file=sys.stderr)
        return EXIT_USAGE
    missing = [flag for flag in REQUIRED_FLAGS if flag not in flags]
    if missing:
        print(f"publish_artifact: missing flags: {', '.join(missing)}", file=sys.stderr)
        return EXIT_USAGE
    return publish(
        html_path=Path(positional[0]),
        slug=flags["--slug"],
        ticket=flags["--ticket"],
        pod=flags["--pod"],
        tier=flags["--tier"],
        audience=flags["--audience"],
        date_text=flags["--date"],
        title=flags["--title"],
        repo_path=Path(flags["--repo-path"]),
        pages_url=flags["--pages-url"],
        force=bool(flags.get("--force")),
    )


if __name__ == "__main__":
    raise SystemExit(main())
