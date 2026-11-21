from _harness import bind

bind("scripts.validate_cheatsheet", globals())
def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/validate_cheatsheet.py selftest")

    # 1. Sources read clean from the repo.
    sources = collect_sources()
    check("command sources found", len(sources["commands"]) >= 14, str(len(sources["commands"])))
    check("edit shorthands extracted", len(sources["shorthands"]) >= 15, str(sources["shorthands"][:5]))
    check("field values extracted", len(sources["fields"]) >= 5, str(sorted(sources["fields"])))
    check("workflow statuses extracted", len(sources["workflow"]) >= 7, str(sources["workflow"][:3]))
    check("method rows extracted", len(sources["methods"]) == 12, str(len(sources["methods"])))
    check("template sections extracted", len(sources["template"]) >= 12, str(sources["template"][:3]))

    # 2. The freshly built document is in sync (builders match checkers).
    document = build_document()
    drifts = check_all(sources, document)
    check("a freshly built document has zero drift", not drifts, json.dumps(drifts[:2]))

    # 3. Every checker catches its own tamper (deletion) in a temp copy.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        # Tamper inside the generated commands section only (the page lede
        # also names a command; a naive replace would hit that first).
        first_command = sources["commands"][0]
        count = len(sources["commands"])
        section_match = SECTION_RE["commands"].search(document)
        tampered_inner = section_match.group(2)
        tampered_inner = tampered_inner.replace(
            f"<code>{first_command}</code>", "<code>uxr-gone</code>", 1
        ).replace(
            f"<strong>{count} commands</strong>", f"<strong>{count - 1} commands</strong>", 1
        )
        tampered = document[: section_match.start(2)] + tampered_inner + document[section_match.end(2):]
        drifts = check_all(sources, tampered)
        check(
            "a deleted command name drifts (missing-command and count-word)",
            any(d["section"] == "commands" and d["kind"] == "missing-command" for d in drifts)
            and any(d["kind"] == "count-word" for d in drifts),
            json.dumps(drifts[:2]),
        )
        # 4. Remediation repairs the file, prints FIX lines, and stays exit 1.
        target = Path(td) / CHEATSHEET_RELATIVE.name
        target.write_text(tampered, encoding="utf-8")
        new_html, fixed = remediate(tampered, sources)
        check(
            "remediation produces a FIX commands line",
            any(line.startswith("FIX commands:") for line in fixed),
            str(fixed),
        )
        check("remediated document is back in sync", not check_all(sources, new_html))
        target.write_text(new_html, encoding="utf-8")
        exit_code = main([str(target)])
        check("a remediated file validates clean (exit 0)", exit_code == EXIT_OK, str(exit_code))

        # 5. Remediation never touches editorial sections.
        dirty = tampered
        faq_match = re.search(r'(<section id="faq">)(.*?)(</section>)', dirty, re.DOTALL)
        new_html, fixed = remediate(dirty, sources)
        faq_after = re.search(r'(<section id="faq">)(.*?)(</section>)', new_html, re.DOTALL)
        check(
            "remediation leaves the FAQ byte-identical",
            faq_match is not None and faq_after is not None and faq_match.group(2) == faq_after.group(2),
        )
        check("remediation fixed exactly the commands section", fixed == [line for line in fixed if line.startswith("FIX commands:")], str(fixed))

        # 6. Flag, shorthand, field, workflow, method, and template tampers drift.
        check("flags section exists in the document", _section_exists(document, "flags"))
        no_flags = re.sub(
            r'(<section[^>]*data-generated="flags"[^>]*>).*?(</section>)',
            r"\1\2",
            document,
            flags=re.DOTALL,
        )
        drifts = check_all(sources, no_flags)
        check(
            "an emptied flags section drifts with missing-flag rows",
            any(d["section"] == "flags" and d["kind"] == "missing-row" for d in drifts),
            json.dumps(drifts[:2]),
        )
        for section in ("shorthands", "fields", "workflow", "methods", "template"):
            emptied = re.sub(
                r'(<section[^>]*data-generated="' + section + r'"[^>]*>).*?(</section>)',
                r"\1\2",
                document,
                flags=re.DOTALL,
            )
            drifts = check_all(sources, emptied)
            check(
                f"an emptied {section} section drifts",
                any(d["section"] == section for d in drifts),
                json.dumps(drifts[:1]),
            )

    # 7. CLI surface on the real sheet (read-only check).
    real = PLUGIN_ROOT / CHEATSHEET_RELATIVE
    if real.is_file():
        exit_code = main([str(real), "--json"])
        check("the shipped cheat sheet validates clean (exit 0)", exit_code == EXIT_OK, str(exit_code))
    else:
        print("  [SKIP] shipped cheat sheet check (docs/cheat-sheet.html not written yet)")

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
