#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel J. Mazure
# SPDX-License-Identifier: MIT
"""Regenerate catalog.json from all package version files.

Run after adding any new package or version:
    python generate_catalog.py
"""
import json
from pathlib import Path

import yaml

PACKAGES_DIR = Path("packages")
CATALOG_OUT = Path("catalog.json")


def latest_version(versions: list[str]) -> str:
    """Return the highest semantic version string from a list."""
    def _key(v):
        parts = v.lstrip("v").split(".")
        try:
            return tuple(int(p) for p in parts)
        except ValueError:
            return (0, 0, 0)
    return max(versions, key=_key)


def build_catalog() -> list[dict]:
    catalog = []

    for ns_dir in sorted(PACKAGES_DIR.iterdir()):
        if not ns_dir.is_dir():
            continue
        namespace = ns_dir.name

        for pkg_dir in sorted(ns_dir.iterdir()):
            if not pkg_dir.is_dir():
                continue
            name = pkg_dir.name

            version_files = sorted(pkg_dir.glob("*.yml"))
            if not version_files:
                continue

            versions = [f.stem for f in version_files]
            latest = latest_version(versions)

            # Load metadata from latest version file
            latest_file = pkg_dir / f"{latest}.yml"
            with open(latest_file) as f:
                meta = yaml.safe_load(f)

            compat = meta.get("routertl_compat", {}) or {}
            entry = {
                "namespace": namespace,
                "name": name,
                "latest": latest,
                "versions": sorted(versions),
                "description": meta.get("description", ""),
                "license": meta.get("license", ""),
                "language": compat.get("language", ""),
                "library": compat.get("library", ""),
                "source_url": meta.get("source", {}).get("url", ""),
                # DS-T1 (2026-05-18): copy the full routertl_compat block
                # so the resolver has the files / library_deps it needs.
                # Previous versions of this script dropped routertl_compat
                # entirely, producing catalogs that worked for cached
                # consumers (ip.lock retained file lists) but broke every
                # fresh `rr pkg add`. Regression test at
                # tests/test_catalog_integrity.py prevents recurrence.
                "routertl_compat": compat,
            }
            catalog.append(entry)

    return catalog


if __name__ == "__main__":
    catalog = build_catalog()
    with open(CATALOG_OUT, "w") as f:
        json.dump(catalog, f, indent=2)
    print(f"Generated {CATALOG_OUT} with {len(catalog)} packages.")
