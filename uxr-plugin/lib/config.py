#!/usr/bin/env python3
"""Configuration loader for the UX research plugin.

One loader for every organization value. All commands, scripts, and hooks
read configuration through :func:`load_config`; no other file holds an
organization value.

Merge order (later layers win; mappings deep-merge, lists and scalars
replace):

1. ``config/org.example.yaml`` -- the shipped contract; documents every key.
2. ``config/org.yaml``         -- the user's file (optional, gitignored).
3. Environment overrides       -- ``UXR_CONFIG__SECTION__KEY=value`` where
   ``__`` separates nested path segments (for example
   ``UXR_CONFIG__TRACKER__BASE_URL``). Values are parsed as JSON when they
   parse as JSON, so ``30`` becomes a number and ``'["Done"]'`` becomes a
   list; anything else stays a string.

Validation: after merging, every key in the config contract (REQUIRED_KEYS)
must be present. A missing key raises :class:`ConfigError` naming the full
dotted path. ``tracker.kind`` and ``tracker.body_format`` are also checked
against their allowed values when set.

Path expansion: every string value under the ``paths`` section is expanded
with ``os.path.expandvars`` and then ``os.path.expanduser``, so ``~`` and
``${CLAUDE_PLUGIN_DATA}`` resolve.

Requires PyYAML. On Python <= 3.14: ``pip install pyyaml``. On Python 3.15
no cp315 wheel ships yet (yaml/pyyaml#951); install the pure-Python half of
the 6.0.3 sdist into site-packages, or wait for a 6.0.4 release.

Usage::

    python lib/config.py --selftest   # run the self-test
    python lib/config.py --print      # dump the resolved configuration
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_FILE = PLUGIN_ROOT / "config" / "org.example.yaml"
USER_FILE = PLUGIN_ROOT / "config" / "org.yaml"
ENV_PREFIX = "UXR_CONFIG__"

#: ``tracker.kind`` must be one of these when set.
TRACKER_KINDS = ("jira", "linear", "github", "asana")
#: ``tracker.body_format`` must be one of these when set.
BODY_FORMATS = ("adf", "markdown", "html")

#: The full config contract as dotted paths. Every entry must be present in
#: the merged configuration. ``fields`` holds per-organization entries, so it
#: is required as a section, not as fixed leaves.
REQUIRED_KEYS: tuple[str, ...] = (
    "tracker.kind",
    "tracker.base_url",
    "tracker.workspace_id",
    "tracker.project_key",
    "tracker.ticket_regex",
    "tracker.bare_number_prefix",
    "tracker.study_item_type",
    "tracker.body_format",
    "tracker.closed_states",
    "tracker.priority_values",
    "tracker.default_priority",
    "fields",
    "workflow.initial_status",
    "workflow.phase_order",
    "workflow.requirements",
    "workflow.script_status_candidates",
    "routing.researchers",
    "routing.group_to_area",
    "routing.area_to_researcher",
    "routing.default_researcher",
    "routing.group_to_channels",
    "routing.research_channel",
    "routing.leadership_channel",
    "org.internal_domains",
    "org.team_share_domain",
    "org.brand_name",
    "org.brand_signoff",
    "org.notetaker_email",
    "paths.research_root",
    "paths.state_dir",
    "workspace.remote",
    "workspace.slug_max_body",
    "workspace.gitignored_paths",
    "evidence.sources",
    "evidence.chat_channels",
    "ssot.jtbd_url",
    "ssot.personas_url",
    "ssot.script_template_id",
    "ssot.finished_artifacts_folder_id",
    "ssot.finished_title_pattern",
    "comments.footer",
    "defaults.start_window_days",
    "defaults.fast_path.pod",
    "defaults.fast_path.research_type",
    "defaults.fast_path.method",
    "defaults.fast_path.investment",
    "defaults.fast_path.support",
    "defaults.fast_path.outcomes",
    "links.calculator",
    "links.templates",
    "links.plugin_repo",
    "recruit.statuses.interview",
    "recruit.statuses.survey",
    "recruit.statuses.recruited",
    "recruit.statuses.early",
    "recruit.status_colors",
    "recruit.window_days.default",
    "recruit.window_days.max",
    "recruit.session_minutes.internal",
    "recruit.session_minutes.external",
    "recruit.nudge_after_days",
    "recruit.sheets",
    "recruit.wave_tab_headers",
    "recruit.booking_url_regex",
    "calendar.working_hours",
    "calendar.default_level",
    "calendar.max_moves_per_recruit",
    "calendar.manager_names",
    "calendar.movable_keywords",
    "calendar.immovable_keywords",
    "script.default_minutes",
    "script.time_buffer",
    "script.word_cap",
    "script.grade_warn",
    "script.grade_block",
    "report.tier_matrix",
    "report.multi_group_bump",
    "report.verdict_threshold",
    "publish.repo",
    "publish.pages_url",
    "deck.personas_file",
    "deck.generator_path",
    "deck.critic_agent",
    "feedback.repo",
    "feedback.label",
    "analytics.enabled",
    "analytics.endpoint",
    "analytics.api_key",
    "sync.enabled",
    "sync.remote",
)

#: Sentinel for "key absent", distinct from an explicit null value.
_MISSING = object()


class ConfigError(Exception):
    """Raised when configuration is missing, malformed, or invalid."""


def _read_mapping(path: Path, what: str) -> dict[str, Any]:
    """Load a YAML file and return it as a dict, with clear errors."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{what} is not valid YAML ({path}): {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{what} cannot be read ({path}): {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{what} must be a mapping of sections ({path})")
    return data


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge ``override`` into ``base``; mappings recurse, everything else wins."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_env_value(raw: str) -> Any:
    """Parse an environment override value as JSON, else keep the string."""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _apply_env_overrides(config: dict, environ: Mapping[str, str]) -> dict:
    """Collect ``UXR_CONFIG__...`` variables and deep-merge them into config."""
    overrides: dict[str, Any] = {}
    for name, raw in environ.items():
        if not name.startswith(ENV_PREFIX):
            continue
        parts = [part.lower() for part in name[len(ENV_PREFIX):].split("__") if part]
        if not parts:
            raise ConfigError(
                f"environment override {name!r} has no config path after {ENV_PREFIX!r}"
            )
        cursor = overrides
        for part in parts[:-1]:
            child = cursor.setdefault(part, {})
            if not isinstance(child, dict):
                raise ConfigError(
                    f"environment override {name!r} conflicts with another override: "
                    f"{'.'.join(parts)} is not a mapping path"
                )
            cursor = child
        cursor[parts[-1]] = _parse_env_value(raw)
    if overrides:
        config = _deep_merge(config, overrides)
    return config


def _get_path(config: Mapping[str, Any], dotted: str) -> Any:
    """Return the value at a dotted path, or the _MISSING sentinel."""
    cursor: Any = config
    for part in dotted.split("."):
        if not isinstance(cursor, Mapping) or part not in cursor:
            return _MISSING
        cursor = cursor[part]
    return cursor


def _validate(config: dict) -> None:
    """Raise ConfigError unless every required contract key is present."""
    missing = [
        dotted
        for dotted in REQUIRED_KEYS
        if _get_path(config, dotted) is _MISSING
    ]
    if missing:
        more = f" (and {len(missing) - 1} more)" if len(missing) > 1 else ""
        raise ConfigError(f"Missing required config key: {missing[0]}{more}")
    kind = config["tracker"]["kind"]
    if kind and kind not in TRACKER_KINDS:
        raise ConfigError(
            f"tracker.kind must be one of {', '.join(TRACKER_KINDS)}; got {kind!r}"
        )
    body_format = config["tracker"]["body_format"]
    if body_format and body_format not in BODY_FORMATS:
        raise ConfigError(
            f"tracker.body_format must be one of {', '.join(BODY_FORMATS)}; "
            f"got {body_format!r}"
        )


def _expand_paths(config: dict) -> dict:
    """Expand ``~`` and ``${VAR}`` references in every paths-section string."""
    paths = config.get("paths")
    if isinstance(paths, dict):
        config["paths"] = {
            key: os.path.expanduser(os.path.expandvars(value))
            if isinstance(value, str)
            else value
            for key, value in paths.items()
        }
    return config


def load_config(
    environ: Mapping[str, str] | None = None,
    example_file: str | os.PathLike[str] | None = None,
    user_file: str | os.PathLike[str] | None = None,
) -> dict:
    """Load, merge, validate, and return the plugin configuration.

    Layers: example file, then user file, then environment overrides (later
    wins). See the module docstring for the override syntax and expansion
    rules. Raises :class:`ConfigError` on a missing required key, invalid
    YAML, or an invalid enum value.
    """
    example_path = Path(example_file) if example_file else EXAMPLE_FILE
    user_path = Path(user_file) if user_file else USER_FILE
    if not example_path.is_file():
        raise ConfigError(
            f"config example file not found: {example_path} "
            "(the plugin ships config/org.example.yaml as the key contract)"
        )
    config = _read_mapping(example_path, "config example file")
    if user_path.is_file():
        config = _deep_merge(config, _read_mapping(user_path, "config user file"))
    config = _apply_env_overrides(config, os.environ if environ is None else environ)
    _validate(config)
    return _expand_paths(config)


def load_example_config(
    environ: Mapping[str, str] | None = None,
    example_file: str | os.PathLike[str] | None = None,
    user_file: str | os.PathLike[str] | None = None,
) -> dict:
    """Load the shipped example contract only; never the live user file.

    Both layers default to ``config/org.example.yaml``, so selftests
    exercise the shipped contract and a configured ``config/org.yaml``
    cannot flip the smoke gate red (F1: the README order Install ->
    Verify -> Configure must keep verify green after Configure).
    Environment overrides default to none, not to the process
    environment. ``example_file`` and ``user_file`` stay overridable for
    fixture tests.
    """
    return load_config(
        environ=environ if environ is not None else {},
        example_file=example_file if example_file else EXAMPLE_FILE,
        user_file=user_file if user_file else EXAMPLE_FILE,
    )


def _selftest() -> int:
    """Cover the contract, the missing-key error, env overrides, and ~ expansion."""
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(f"{name}: {detail}")

    print("lib/config.py --selftest")

    # 1. The shipped example file satisfies the full config contract.
    try:
        baseline = load_example_config()
        check("shipped example file satisfies the config contract", True)
    except ConfigError as exc:
        baseline = None
        check("shipped example file satisfies the config contract", False, str(exc))

    # 2. A deleted leaf key raises ConfigError naming the key.
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        data = yaml.safe_load(EXAMPLE_FILE.read_text(encoding="utf-8"))
        del data["org"]["brand_name"]
        broken = tmp / "broken.example.yaml"
        broken.write_text(yaml.safe_dump(data), encoding="utf-8")
        try:
            load_config(
                environ={},
                example_file=broken,
                user_file=tmp / "absent.org.yaml",
            )
            check("missing leaf key raises ConfigError naming the key", False, "no error raised")
        except ConfigError as exc:
            check("missing leaf key raises ConfigError naming the key", "org.brand_name" in str(exc), str(exc))

    # 3. A deleted whole section raises ConfigError naming the section.
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        data = yaml.safe_load(EXAMPLE_FILE.read_text(encoding="utf-8"))
        del data["calendar"]
        broken = tmp / "broken.example.yaml"
        broken.write_text(yaml.safe_dump(data), encoding="utf-8")
        try:
            load_config(
                environ={},
                example_file=broken,
                user_file=tmp / "absent.org.yaml",
            )
            check("missing section raises ConfigError naming it", False, "no error raised")
        except ConfigError as exc:
            check("missing section raises ConfigError naming it", "calendar" in str(exc), str(exc))

    # 4. Environment overrides win over file values and parse as JSON.
    if baseline is not None:
        overridden = load_example_config(
            environ={
                "UXR_CONFIG__DEFAULTS__START_WINDOW_DAYS": "30",
                "UXR_CONFIG__ORG__BRAND_NAME": "Selftest Brand",
                "UXR_CONFIG__TRACKER__CLOSED_STATES": '["Done"]',
            }
        )
        check(
            "environment override replaces a scalar (JSON number)",
            overridden["defaults"]["start_window_days"] == 30,
            repr(overridden["defaults"]["start_window_days"]),
        )
        check(
            "environment override replaces a scalar (plain string)",
            overridden["org"]["brand_name"] == "Selftest Brand",
            repr(overridden["org"]["brand_name"]),
        )
        check(
            "environment override replaces a list (JSON list)",
            overridden["tracker"]["closed_states"] == ["Done"],
            repr(overridden["tracker"]["closed_states"]),
        )
        check(
            "overrides do not leak into the next load",
            load_example_config()["defaults"]["start_window_days"] == 90,
        )

    # 5. '~' and ${VAR} in the paths section are expanded.
    if baseline is not None:
        expanded = load_example_config(
            environ={"UXR_CONFIG__PATHS__RESEARCH_ROOT": "~/zcode-config-selftest"}
        )
        expected = os.path.expanduser("~/zcode-config-selftest")
        check(
            "'~' in paths.research_root is expanded",
            expanded["paths"]["research_root"] == expected,
            repr(expanded["paths"]["research_root"]),
        )
        check(
            "'~' literal does not survive expansion",
            not str(expanded["paths"]["research_root"]).startswith("~"),
        )
        expected_state = os.path.expanduser(
            os.path.expandvars("${CLAUDE_PLUGIN_DATA}/state")
        )
        check(
            "paths.state_dir ${VAR} reference is expanded",
            baseline["paths"]["state_dir"] == expected_state,
            repr(baseline["paths"]["state_dir"]),
        )

    # 6. The example-only loader never merges the live user file (F1):
    # equality with a load whose user file cannot exist proves the default
    # user layer is the example, so a configured config/org.yaml cannot
    # reach a selftest and the smoke gate stays green after Configure.
    example_only = load_example_config()
    pure = load_config(
        environ={}, user_file=EXAMPLE_FILE.parent / "org.yaml.selftest-absent"
    )
    check(
        "the example-only loader never merges the live user file",
        example_only == pure,
        f"example-only start_window_days={example_only['defaults']['start_window_days']!r}, "
        f"pure-example start_window_days={pure['defaults']['start_window_days']!r}",
    )

    if failures:
        print(f"selftest FAILED ({len(failures)} check(s))")
        return 1
    print("selftest: all checks passed")
    return 0


def _print_config() -> int:
    """Dump the resolved configuration as YAML for debugging."""
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    yaml.safe_dump(config, sys.stdout, sort_keys=False, allow_unicode=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in args:
        return _selftest()
    if "--print" in args:
        return _print_config()
    print(__doc__.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
