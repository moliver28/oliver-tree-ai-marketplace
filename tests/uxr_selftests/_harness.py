"""Bind a repo-level selftest module to its shipped plugin module.

Every ``tests/uxr_selftests/<name>.py`` opens with::

    from _harness import bind
    bind("lib.prompts", globals())

``bind`` puts the shipped module's globals (functions, constants, its
imports, and its ``__file__``) into the test module, so a selftest body
moved verbatim from the plugin runs byte-identically outside it.
"""
import importlib
import sys
from pathlib import Path

#: <repo>/uxr-plugin — two levels up from tests/uxr_selftests/
PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "uxr-plugin"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


def bind(module_name: str, target: dict) -> None:
    """Copy the shipped module's globals into ``target`` (a module dict)."""
    target.update(vars(importlib.import_module(module_name)))
