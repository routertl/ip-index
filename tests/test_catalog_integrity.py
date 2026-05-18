# SPDX-FileCopyrightText: 2026 Daniel J. Mazure
# SPDX-License-Identifier: MIT
"""Regression guard: every catalog.json entry MUST carry the fields the
resolver needs to install a package without re-scanning.

Origin: DS-T1 (deepskopion, 2026-05-18). The catalog deployed to
registry.routertl.dev had lost the per-entry ``routertl_compat.files``
field for ALL 804 entries — every consumer attempting a fresh install
fell back to "empty file list" errors. Existing installs only worked
because they had file lists cached in their per-project ``ip.lock``
from before the regression.

The per-package source YAMLs at ``packages/<ns>/<name>/<ver>.yml``
always had the data; ``generate_catalog.py`` was just dropping it
during catalog assembly. This test runs after ``generate_catalog.py``
in CI so a future regression fails the workflow instead of silently
shipping a broken catalog.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG = REPO_ROOT / "catalog.json"


@pytest.fixture(scope="module")
def catalog() -> list[dict]:
    assert CATALOG.is_file(), f"{CATALOG} not found — run generate_catalog.py first"
    with open(CATALOG) as f:
        return json.load(f)


def _entry_id(e: dict) -> str:
    return f"{e.get('namespace', '?')}/{e.get('name', '?')}@{e.get('latest', '?')}"


def test_catalog_non_empty(catalog: list[dict]) -> None:
    """Catch the trivial case where the catalog itself is empty."""
    assert len(catalog) > 0, "catalog.json is empty"


def test_every_entry_has_files(catalog: list[dict]) -> None:
    """The resolver needs file lists to install packages. An entry that
    lacks them is functionally a "404" for any fresh consumer — but the
    catalog still ships, masking the breakage behind cached ip.lock
    state in existing consumers.

    Files must live under ``routertl_compat.files`` (canonical) OR at the
    top-level ``files`` key (legacy). Empty list is treated as missing.
    """
    missing = []
    for e in catalog:
        compat = e.get("routertl_compat") or {}
        files = compat.get("files") or e.get("files") or []
        if not files:
            missing.append(_entry_id(e))
    assert not missing, (
        f"{len(missing)}/{len(catalog)} catalog entries are missing "
        f"`routertl_compat.files` (or top-level `files`). The resolver "
        f"will fail on every fresh `rr pkg add` against these entries. "
        f"First 10: {missing[:10]}. "
        f"Most likely cause: generate_catalog.py regenerated the catalog "
        f"without copying the per-package YAML's routertl_compat block."
    )


def test_every_entry_has_required_identity(catalog: list[dict]) -> None:
    """Identity fields (namespace, name, latest) are non-negotiable for
    lookup."""
    broken = []
    for e in catalog:
        for k in ("namespace", "name", "latest"):
            if not e.get(k):
                broken.append((e.get("namespace", "?"), e.get("name", "?"), k))
                break
    assert not broken, (
        f"{len(broken)} entries missing identity fields. First 5: {broken[:5]}"
    )


def test_versions_list_includes_latest(catalog: list[dict]) -> None:
    """If `latest: X` is set, `X` must be in `versions: [...]` — otherwise
    the resolver chains a lookup that always fails."""
    broken = []
    for e in catalog:
        latest = e.get("latest")
        versions = e.get("versions") or []
        if latest and latest not in versions:
            broken.append((_entry_id(e), latest, versions[:5]))
    assert not broken, (
        f"{len(broken)} entries where `latest` is not in `versions`. "
        f"First 5: {broken[:5]}"
    )
