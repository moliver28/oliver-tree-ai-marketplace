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

    python lib/config.py --print            # dump the resolved configuration
    python lib/config.py --init-ignore-set  # the effective interview-data
                                            # ignore set, one path per line
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_FILE = PLUGIN_ROOT / "config" / "org.example.yaml"
USER_FILE = PLUGIN_ROOT / "config" / "org.yaml"
ENV_PREFIX = "UXR_CONFIG__"

#: ``tracker.kind`` must be one of these when set. The issue systems plus
#: the knowledge-base kinds the adapters section ships (issue 114: adapters
#: cover issue systems and knowledge-base systems).
TRACKER_KINDS = ("jira", "linear", "github", "gitlab", "asana", "notion")
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
    "checklists.enforcement",
    "checklists.autonomy",
    "fields",
    "adapters",
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
    "workspace.remote_push",
    "privacy.init_ignore",
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
    "priority.weights",
    "priority.formula",
    "prioritization.fields",
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
    "recruiting.org_chart_paths",
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


#: The interview-data ignore set when ``privacy.init_ignore`` is empty
#: (issue 57): the default covers ALL interview data, the whole
#: ``interviews/`` tree. This flips the shipped default of earlier
#: releases, which ignored only the participant key and the raw
#: transcripts. The participant-identity floor stays enforced by the
#: ``init`` command's hardcoded gate arguments and is never replaceable
#: by this section.
INIT_IGNORE_DEFAULT = ("interviews/",)


def init_ignore_set(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the effective interview-data ignore set (issue 57).

    An empty or missing ``privacy.init_ignore`` returns
    :data:`INIT_IGNORE_DEFAULT` (all interview data). A non-empty list
    returns exactly the listed paths, in order, with blank entries
    dropped. Pure function of the config; the ``init`` command passes the
    result to the gitignore gate.
    """
    privacy = config.get("privacy") if isinstance(config, Mapping) else None
    entries = privacy.get("init_ignore") if isinstance(privacy, Mapping) else None
    if not entries:
        return INIT_IGNORE_DEFAULT
    return tuple(str(entry) for entry in entries if str(entry).strip())


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


def _print_config() -> int:
    """Dump the resolved configuration as YAML for debugging."""
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    yaml.safe_dump(config, sys.stdout, sort_keys=False, allow_unicode=True)
    return 0


def _print_init_ignore_set() -> int:
    """Print the effective interview-data ignore set, one path per line."""
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    for entry in init_ignore_set(config):
        print(entry)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--print" in args:
        return _print_config()
    if "--init-ignore-set" in args:
        return _print_init_ignore_set()
    print(__doc__.strip().splitlines()[0])  # terse bare-run pointer; full doc in this file
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
