# SPDX-FileCopyrightText: 2024-2026 Daniel J. Mazure
# SPDX-License-Identifier: MIT

# tb/contracts/registry_lookup.py
"""
Registry-side lookup of IP operational contracts (RTL-P2.506 layer 6).

When ``rr pkg add <ns>/<name>`` runs, the index_client caches the
fetched per-package YAML at::

    <project_root>/.routertl_cache/index/packages/<ns>/<name>/<ver>.yml

The YAML carries the curated ``contract`` block (RTL-P2.506 layer 1
emit, persisted via L2, served via L3). This module reads the cached
YAML and returns the contract block so cocotb harnesses
(``EthMacClient`` et al.) can adapt to per-IP behaviour without
hard-coded ``check_fcs=False`` / ``include_fcs_in_user_frame=False``
knobs in every test.

Closes the BFM-side hard-coded-knob anti-pattern that motivated
RTL-P3.309 ("EthMacClient.run_loopback assumes FCS in user-side RX —
wrong for MACs that strip FCS"). The harness now consults the
registry-declared trait ``rx_strips_fcs`` and behaves accordingly.

Cache-miss policy
-----------------
If the cache directory doesn't exist, or no YAML is present, or the
YAML has no ``contract`` field, ``load_ip_contract`` returns ``None``.
The harness then falls back to its legacy hard-coded defaults.

Tests that REQUIRE the contract to be present should pass an explicit
``fallback`` dict (e.g. the curated values from
``sdk/registry/curated_repos.json``) so a cleared cache produces a
clear test failure rather than a silent revert to the wrong defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


_DEFAULT_CACHE_DIR = Path(".routertl_cache/index")


def load_ip_contract(
    namespace: str,
    name: str,
    *,
    cache_dir: Path | None = None,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Look up an IP's operational contract from the local index cache.

    Searches ``<cache_dir>/packages/<ns>/<name>/*.yml`` (newest mtime
    wins for multi-version installs). Returns the ``contract`` field
    from the YAML if present, otherwise ``fallback``, otherwise ``None``.

    Parameters
    ----------
    namespace, name
        Identifies the IP (e.g. ``"alex-forencich"``,
        ``"eth_mac_1g_fifo"``).
    cache_dir
        Override the default ``.routertl_cache/index`` location (used
        for testing against a fixture cache).
    fallback
        Returned when the cache lookup misses. Use this for
        bring-your-own-contract tests that should still pass even
        without a populated cache (typical for CI before the registry
        deploy lands).

    Notes
    -----
    Resolution order matches the user mental model: registry cache
    wins if present (most up-to-date — reflects what `rr pkg add` last
    fetched); fallback wins if not. The harness should treat a None
    return as "no contract metadata available — use legacy defaults".
    """
    base = cache_dir if cache_dir is not None else _DEFAULT_CACHE_DIR
    pkg_dir = base / "packages" / namespace / name
    if not pkg_dir.is_dir():
        return fallback
    yamls = sorted(pkg_dir.glob("*.yml"), key=lambda p: p.stat().st_mtime)
    if not yamls:
        return fallback
    try:
        data = yaml.safe_load(yamls[-1].read_text(
            encoding="utf-8", errors="replace",
        ))
    except (yaml.YAMLError, OSError):
        return fallback
    if not isinstance(data, dict):
        return fallback
    contract = data.get("contract")
    if not isinstance(contract, dict):
        return fallback
    if not contract.get("traits") and not contract.get("defects"):
        return fallback
    return contract


def trait(contract: dict | None, key: str, default: Any = None) -> Any:
    """Safe access to a contract trait. Returns ``default`` for any
    missing-link case (no contract / no traits / no key).

    Convenience for harness code that wants a one-liner:

        rx_strips_fcs = trait(contract, "rx_strips_fcs", False)
    """
    if not contract:
        return default
    traits = contract.get("traits") or {}
    return traits.get(key, default)
