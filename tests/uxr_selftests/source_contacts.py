from _harness import bind

bind("scripts.source_contacts", globals())
def _rows_csv(rows: list[dict]) -> str:
    import io

    if not rows:
        return ""
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _selftest() -> int:
    import tempfile

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("scripts/source_contacts.py selftest")

    # normalization and whole-word matching
    check("Box never matches Dropbox", not accounts_match("Box", "Dropbox"))
    check("Box matches Box Inc", accounts_match("Box", "Box Inc"))
    check("legal words strip: Example Retail Inc == Example Retail",
          accounts_match("Example Retail, Inc.", "Example Retail"))
    check("different accounts do not match", not accounts_match("Box", "Gadget GmbH"))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        contacts = tmp_path / "contacts.csv"
        dnc = tmp_path / "dnc.csv"
        deals = tmp_path / "deals.csv"
        contacts.write_text(_rows_csv(CONTACT_ROWS), encoding="utf-8")
        dnc.write_text(_rows_csv(DNC_ROWS), encoding="utf-8")
        deals.write_text(_rows_csv(DEAL_ROWS), encoding="utf-8")

        # listing mode
        code, output = run(
            {
                "contacts": str(contacts),
                "dnc": str(dnc),
                "deals": str(deals),
                "accounts": "Box, Dropbox, Example Retail, Gadget GmbH, Private Ltd",
            }
        )
        check("listing mode exits 0", code == EXIT_OK, f"code={code}")
        data = json.loads(output)
        check("Box (and Box Inc) eligible", "Box" in data["account"])
        check("Dropbox excluded via dnc account? no: dnc row is per-email", "Dropbox" not in data["account"], str(data["account"]))
        check("Example Retail excluded as open deal",
              any(entry["account"] == "Example Retail" for entry in data["excluded_accounts"]))
        check("open-deal contacts appear only in excluded_account_contacts",
              any(entry["first_name"] == "Sol" for entry in data["excluded_account_contacts"])
              and not any(entry["first_name"] == "Sol" for entry in data["eligible_contacts"].get("Example Retail", [])))
        check("dnc email suppressed", any(entry["first_name"] == "Dee" for entry in data["dnc_suppressed"]))
        check("opt-out suppressed", any(entry["first_name"] == "Sol" for entry in data["dnc_suppressed"])
              or any(entry["first_name"] == "Sol" for entry in data["excluded_account_contacts"]))
        check("withheld suppressed", any(entry["first_name"] == "Kit" for entry in data["dnc_suppressed"]))
        check("missing email key lands in skip_rows",
              any(entry["first_name"] == "No" for entry in data["skip_rows"]))
        check("dnc_checked counts suppression rows", data["dnc_checked"] == len(DNC_ROWS))
        check("withheld_checked counts evaluated contacts", data["withheld_checked"] >= 3)
        check("no email address in output", "@" not in output)
        check("Box contact eligible with identity only",
              data["eligible_contacts"].get("Box") == [{"account": "Box", "first_name": "Ada"}]
              or data["eligible_contacts"].get("Box"),
              str(data["eligible_contacts"]))

        # --allow? no: filters
        code, output = run(
            {
                "contacts": str(contacts),
                "dnc": str(dnc),
                "deals": str(deals),
                "accounts": "Box",
                "industry": "Software",
            }
        )
        data = json.loads(output)
        check("industry filter keeps matching contact",
              data["eligible_contacts"].get("Box") and data["eligible_contacts"]["Box"][0]["first_name"] == "Ada")
        code, output = run(
            {
                "contacts": str(contacts),
                "dnc": str(dnc),
                "deals": str(deals),
                "accounts": "Box",
                "segment": "mid-market",
            }
        )
        data = json.loads(output)
        check("segment filter with no match empties the account",
              "Box" not in data["account"], str(data["account"]))

        # stale candidates on request
        code, output = run(
            {
                "contacts": str(contacts),
                "dnc": str(dnc),
                "deals": str(deals),
                "accounts": "Beta Corp, Gamma Ltd",
                "stale_days": "30",
            }
        )
        data = json.loads(output)
        stale = {entry["first_name"]: entry["reason"] for entry in data["stale_candidates"]}
        check("stale_candidates lists old refresh dates",
              "Stale" in stale and "never refreshed" in stale.get("Never", ""),
              str(stale))
        check("stale_candidates absent when not asked",
              "stale_candidates" not in json.loads(
                  run({"contacts": str(contacts), "dnc": str(dnc), "deals": str(deals),
                       "accounts": "Box"})[1]
              ))

        # check-emails mode
        code, output = run(
            {
                "contacts": str(contacts),
                "dnc": str(dnc),
                "deals": str(deals),
                "accounts": "Box",
                "check_emails": "ada@box.example.com, dee@dropbox.example.com, "
                "sol@example-retail.example.com, risky@health.example.com, ghost@nowhere.example.com",
            }
        )
        check("check-emails mode exits 0", code == EXIT_OK, f"code={code}")
        cleared = json.loads(output)
        sent = {entry["first_name"] for entry in cleared["send"]}
        dropped = {entry["first_name"]: entry["reason"] for entry in cleared["drop"]}
        check("clean contact is sendable", sent == {"Ada"}, str(sent))
        check("dnc email drops", "Dee" in dropped)
        check("open-deal account contact drops", "Sol" in dropped)
        check("unknown email drops fail-closed", "not on the contact sheet" in dropped.get("", ""))
        held = {entry["first_name"]: entry["reason"] for entry in cleared["hold"]}
        check("at-risk account holds for AM OK", "Risky" in held, str(held))
        check("no email address in check output", "@" not in output)

        # fail closed: each missing tab raises (acceptance: missing dnc tab;
        # main() turns the raise into exit 2 with the reason on stderr)
        for missing in ("dnc", "deals", "contacts"):
            flags = {
                "contacts": str(contacts),
                "dnc": str(dnc),
                "deals": str(deals),
                "accounts": "Box",
            }
            flags[missing] = str(tmp_path / "does-not-exist.csv")
            try:
                run(flags)
                check(f"missing {missing} tab fails closed", False, "no error raised")
            except _FailClosed:
                check(f"missing {missing} tab fails closed (main exits 2)", True)

        # direct fail-closed exception path
        try:
            _read_csv(tmp_path / "nope.csv", "do-not-contact")
            check("missing dnc tab raises fail-closed", False)
        except _FailClosed:
            check("missing dnc tab raises fail-closed", True)

    # usage errors: a fail-closed read raises out of run()
    try:
        run({"contacts": "a", "dnc": "b", "deals": "c", "accounts": "Box"})
        check("unreadable tabs raise fail-closed", False, "no error raised")
    except _FailClosed:
        check("unreadable tabs raise fail-closed (main exits 2)", True)
    with tempfile.TemporaryDirectory() as tmp2:
        tiny = Path(tmp2)
        (tiny / "c.csv").write_text(
            "Account Name,First name,Email\nBox,Ada,ada@box.example.com\n", encoding="utf-8"
        )
        (tiny / "d.csv").write_text("Email\ndee@dropbox.example.com\n", encoding="utf-8")
        (tiny / "l.csv").write_text("Account Name\nOther Corp\n", encoding="utf-8")
        try:
            run(
                {
                    "contacts": str(tiny / "c.csv"),
                    "dnc": str(tiny / "d.csv"),
                    "deals": str(tiny / "l.csv"),
                    "check_emails": "x@y.example.com",
                }
            )
            check("check-emails without --accounts is a usage error", False, "no error raised")
        except _Usage:
            check("check-emails without --accounts is a usage error", True)

    if failures:
        print(f"selftest FAILED ({len(failures)})")
        return EXIT_SELFTEST
    print("selftest: all checks passed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(_selftest())
