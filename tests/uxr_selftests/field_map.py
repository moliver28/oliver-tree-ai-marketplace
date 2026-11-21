from _harness import bind

bind("lib.field_map", globals())

import config as _config  # tests/uxr_selftests/config.py: the moved home of load_example_config (selftest body stays verbatim)

def _test_config(tracker_kind: str = "jira") -> dict[str, Any]:
    """A synthetic config for the self-test; no organization values."""
    return {
        "tracker": {
            "kind": tracker_kind,
            "priority_values": ["Low", "Medium", "High", "Urgent"],
        },
        "fields": {
            "research-type": {
                "id": "ref_research_type",
                "kind": "single_select",
                "values": ["Evaluative", "Generative", "Strategic", "Other"],
            },
            "pod": {
                "id": "ref_pod",
                "kind": "multi_select",
                "values": ["Platform", "Payments", "Growth"],
            },
            "support": {
                "id": "ref_support",
                "kind": "multi_select",
                "values": ["UXR to Lead", "UXR to Assist", "UXR to Review", "Not Sure"],
            },
            "method": {
                "id": "ref_method",
                "kind": "multi_select",
                "values": [
                    "Internal Interviews",
                    "External Interviews",
                    "Survey",
                    "Usability Test",
                    "Card Sort",
                    "Desk Research",
                    "Not Sure",
                ],
            },
            "investment": {
                "id": "ref_investment",
                "kind": "single_select",
                "values": ["0", "SM", "M", "LRG", "XLG", "XXLG"],
            },
            "reviewed": {
                "id": "ref_reviewed",
                "kind": "single_select",
                "values": ["Needs Review", "Reviewed", "N/A"],
            },
            "feature": {"id": "ref_feature", "kind": "text"},
            "start": {"id": "ref_start", "kind": "interval"},
            "target": {"id": "ref_target", "kind": "interval"},
            "uxr": {"id": "ref_uxr", "kind": "user"},
            "pm": {"id": "ref_pm", "kind": "user"},
            "script": {"id": "ref_script", "kind": "url"},
            "output": {"id": "ref_output", "kind": "url"},
            "summary": {"id": "ref_summary", "kind": "text"},
            "priority": {"id": "ref_priority", "kind": "single_name"},
            "labels": {"id": "ref_labels", "kind": "labels"},
            "duedate": {"id": "ref_duedate", "kind": "date"},
        },
        "routing": {
            "researchers": [
                {"display_name": "Ada Example", "role": "uxr", "area": "Platform"},
                {"display_name": "Grace Example", "role": "manager", "area": "Payments"},
            ],
            "group_to_area": {"Platform": "Platform", "Checkout": "Payments"},
            "area_to_researcher": {
                "Platform": {"primary": "Ada Example", "fallbacks": ["Grace Example"]},
                "Payments": {"primary": "Grace Example", "fallbacks": []},
            },
            "default_researcher": "Rook Example",
        },
    }


def _routing_map_missing_area() -> dict[str, Any]:
    routing = _test_config()["routing"]
    routing["group_to_area"]["Docs"] = "Documentation"
    return routing


def _selftest() -> int:
    """Cover every accepted shorthand shape, every rejection, and routing."""
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    def resolves(name: str, shorthand: str, expected: dict, config: dict | None = None) -> None:
        try:
            payload = resolve_shorthand(shorthand, config if config is not None else _test_config())
        except ResolveError as exc:
            check(name, False, f"unexpected ResolveError: {exc}")
            return
        check(name, payload == expected, f"got {payload!r}, want {expected!r}")

    def rejects(name: str, shorthand: str, config: dict | None = None) -> None:
        try:
            payload = resolve_shorthand(shorthand, config if config is not None else _test_config())
        except ResolveError as exc:
            check(name, True, str(exc))
            return
        check(name, False, f"resolved to {payload!r} but should have raised")

    print("lib/field_map.py --selftest")

    # --- single_select -----------------------------------------------------
    resolves(
        "single_select canonical case (research-type=Strategic)",
        "research-type=Strategic",
        {"ref_research_type": {"value": "Strategic"}},
    )
    resolves(
        "single_select matches without case",
        "research-type=strategic",
        {"ref_research_type": {"value": "Strategic"}},
    )
    resolves(
        "single_select quoted zero investment stays a string",
        "investment=0",
        {"ref_investment": {"value": "0"}},
    )
    rejects("bad enum value rejected", "research-type=Bogus")
    rejects("'+=' on single_select rejected", "research-type+=Strategic")

    # --- multi_select -------------------------------------------------------
    resolves(
        "multi_select replace (pod=<value>, case-insensitive)",
        "pod=platform",
        {"ref_pod": [{"value": "Platform"}]},
    )
    resolves(
        "multi_select replace with several values",
        "method=Usability Test, card sort",
        {"ref_method": [{"value": "Usability Test"}, {"value": "Card Sort"}]},
    )
    resolves(
        "multi_select add keeps existing values via __op__ add",
        "method+=Survey",
        {"ref_method": {"__op__": "add", "values": [{"value": "Survey"}]}},
    )
    resolves(
        "multi_select remove via __op__ remove",
        "method-=desk research",
        {"ref_method": {"__op__": "remove", "values": [{"value": "Desk Research"}]}},
    )
    rejects("bad enum inside multi_select rejected", "pod=Bogus")

    # --- labels -------------------------------------------------------------
    resolves(
        "labels plain list replaces",
        "labels=a,b,c",
        {"ref_labels": ["a", "b", "c"]},
    )
    resolves(
        "labels +token adds",
        "labels=+urgent",
        {"ref_labels": {"__op__": "add", "values": ["urgent"]}},
    )
    resolves(
        "labels -token removes",
        "labels=-stale",
        {"ref_labels": {"__op__": "remove", "values": ["stale"]}},
    )
    resolves(
        "labels += operator adds",
        "labels+=urgent",
        {"ref_labels": {"__op__": "add", "values": ["urgent"]}},
    )
    rejects("labels mixing plain and signed tokens rejected", "labels=a,+b")
    rejects("labels mixing add and remove signs rejected", "labels=+a,-b")
    rejects("labels signed token with += rejected", "labels+=+x")

    # --- priority (single_name) ---------------------------------------------
    resolves(
        "priority emits name with canonical case",
        "priority=High",
        {"ref_priority": {"name": "High"}},
    )
    rejects("priority outside tracker.priority_values rejected", "priority=Bogus")

    # --- interval -----------------------------------------------------------
    resolves(
        "interval range on Jira emits the JSON string",
        "start=2026-01-05..2026-03-31",
        {"ref_start": '{"start":"2026-01-05","end":"2026-03-31"}'},
    )
    resolves(
        "interval single day gives start equal to end (Jira)",
        "target=2026-02-01",
        {"ref_target": '{"start":"2026-02-01","end":"2026-02-01"}'},
    )
    resolves(
        "interval on a non-Jira tracker emits the object",
        "start=2026-01-05..2026-03-31",
        {"ref_start": {"start": "2026-01-05", "end": "2026-03-31"}},
        _test_config(tracker_kind="github"),
    )
    rejects("interval end before start rejected", "start=2026-03-31..2026-01-05")
    rejects("interval month 13 day 40 rejected", "start=2026-13-40")
    rejects("interval non-date rejected", "start=May 10th")

    # --- date ---------------------------------------------------------------
    resolves(
        "duedate accepts a real calendar date",
        "duedate=2026-05-10",
        {"ref_duedate": "2026-05-10"},
    )
    rejects("duedate=May 10th rejected", "duedate=May 10th")
    rejects("duedate impossible date rejected", "duedate=2026-02-30")

    # --- url, text, user ----------------------------------------------------
    resolves(
        "url value is trimmed",
        "script=  https://example.com/survey  ",
        {"ref_script": "https://example.com/survey"},
    )
    resolves(
        "text value is trimmed",
        "summary=  Onboarding flows  ",
        {"ref_summary": "Onboarding flows"},
    )
    rejects("empty text value rejected", "summary=")
    resolves(
        "user emits __resolve_user__ for the command to resolve",
        "uxr=Ada Example",
        {"ref_uxr": {"__resolve_user__": "Ada Example"}},
    )
    resolves(
        "user token 'me' passes through",
        "pm=me",
        {"ref_pm": {"__resolve_user__": "me"}},
    )

    # --- parsing ------------------------------------------------------------
    resolves(
        "earliest operator wins (= before a later += inside the value)",
        "summary=a+=b",
        {"ref_summary": "a+=b"},
    )
    rejects("unknown key rejected", "bogus=x")
    rejects("shorthand without an operator rejected", "method Survey")
    rejects("shorthand with an empty key rejected", "=x")
    rejects("multi_select empty token rejected", "pod=Platform,")
    rejects("unknown kind in config rejected", "feature=x", {
        **_test_config(),
        "fields": {**_test_config()["fields"], "feature": {"id": "ref_feature", "kind": "dropdown"}},
    })

    # --- routing ------------------------------------------------------------
    routing = _test_config()["routing"]
    check(
        "role detection: researcher name gives uxr",
        detect_role("Ada Example", routing) == "uxr",
        detect_role("Ada Example", routing),
    )
    check(
        "role detection: manager name gives manager",
        detect_role("Grace Example", routing) == "manager",
        detect_role("Grace Example", routing),
    )
    check(
        "role detection matches without case",
        detect_role("ada example", routing) == "uxr",
        detect_role("ada example", routing),
    )
    check(
        "role detection: unknown name gives stakeholder",
        detect_role("Nobody Example", routing) == "stakeholder",
        detect_role("Nobody Example", routing),
    )
    check(
        "role detection: empty name gives stakeholder",
        detect_role("", routing) == "stakeholder",
        detect_role("", routing),
    )

    assigned = resolve_researcher("Platform", routing)
    check(
        "known group routes to its area primary",
        assigned["researcher"] == "Ada Example" and assigned["area"] == "Platform",
        repr(assigned),
    )
    check(
        "known group carries the fallback chain",
        assigned["fallbacks"] == ["Grace Example"] and not assigned["notes"],
        repr(assigned),
    )
    checkout = resolve_researcher("checkout", routing)
    check(
        "group matching is case-insensitive",
        checkout["researcher"] == "Grace Example" and checkout["area"] == "Payments",
        repr(checkout),
    )
    unknown = resolve_researcher("Unknown Area", routing)
    check(
        "unknown group routes to routing.default_researcher",
        unknown["researcher"] == "Rook Example" and unknown["area"] is None,
        repr(unknown),
    )
    note = unknown["notes"][0] if unknown["notes"] else ""
    check(
        "unknown group prints the map-update note",
        "group_to_area" in note and "Update" in note and "default researcher" in note,
        note,
    )
    unmapped = resolve_researcher("Docs", _routing_map_missing_area())
    check(
        "group mapped to an area with no researcher falls back with a note",
        unmapped["researcher"] == "Rook Example"
        and unmapped["area"] == "Documentation"
        and "area_to_researcher" in unmapped["notes"][0],
        repr(unmapped),
    )
    no_default = resolve_researcher("Unknown Area", {**routing, "default_researcher": ""})
    check(
        "unset default_researcher adds its own note",
        no_default["researcher"] == "" and "default_researcher" in no_default["notes"][-1],
        repr(no_default),
    )

    # --- the shipped example file resolves through the real loader ----------
    # The fixture is the shipped example only (F1): a plain load_config()
    # merges the live config/org.yaml, so after the organization configures
    # the plugin the example's free-token pod check below would reject and
    # flip the smoke gate red -- the README order Install -> Verify ->
    # Configure must keep verify green after Configure.
    try:
        example = _config.load_example_config()
        payload = resolve_shorthand("research-type=Strategic", example)
        shape_ok = isinstance(payload, dict) and list(payload.values()) == [
            {"value": "Strategic"}
        ]
        check("shipped example field schema resolves via load_config", shape_ok, repr(payload))
        free = resolve_shorthand("pod=Anything", example)
        check(
            "example select field with empty values accepts any token",
            free == {"": [{"value": "Anything"}]},
            repr(free),
        )
    except (ResolveError, ConfigError) as exc:
        check("shipped example field schema resolves via load_config", False, str(exc))

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 4
    print("selftest: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
