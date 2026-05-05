# SPDX-FileCopyrightText: 2024-2026 Daniel J. Mazure
# SPDX-License-Identifier: MIT

"""
Published latency baselines for 1 Gbit/s open-source Ethernet MAC IP cores.

These are hard-coded transcriptions from peer-reviewed measurements.  Per
ROUTERTL-002, baselines used in test gates must be hard-coded expected
values, not derived at runtime.

Source
------
Fibich, Schmitt, Höller, Rössler (2023).  *Open-Source Ethernet MAC IP
Cores for FPGAs: Overview and Evaluation.*  International Journal of
Reconfigurable Computing, Article 9222318.  doi:10.1155/2023/9222318.

Specifically Table 15 ("Ranking of 1 Gbit/s open-source Ethernet MACs in
terms of high speed/low latency"), reproduced verbatim with the paper's
own ± standard deviation.

Methodology
-----------
The paper measured average TX and RX latency in clock cycles at 125 MHz
(GMII clock) over a packETH-driven loopback test of 100 000 frames per
size across {48, 64, 128, 256, 512, 1024, 1280, 1400, 1518} bytes.  The
numbers below are the cross-size averages.

TX latency = MAC user-side TX ingress (e.g. AXI-Stream ``tvalid && tready``
on the s_axis_tx port) → first GMII TX byte (``gmii_tx_en`` first cycle).

RX latency = first GMII RX byte (``gmii_rx_dv`` first cycle) → MAC
user-side RX valid (``tvalid && tready`` on m_axis_rx).

Use
---
The eth-validator test orchestrator anchors REQ-2 against these values:

    from tb.contracts.eth_mac_1g_fifo_baselines import FIBICH_TABLE_15

    baseline = FIBICH_TABLE_15["verilog-ethernet"]
    assert abs(measured_tx - baseline["tx_avg_cycles"]) <= 2
    assert abs(measured_rx - baseline["rx_avg_cycles"]) <= 2

Per-frame-size latency curves are in Figure 10 of the paper but are
graphical only; transcription would not be robust.  Per-size baselines
are intentionally NOT shipped here — REQ-2 is anchored against averages.
"""

from __future__ import annotations

from typing import Dict, TypedDict


class LatencyBaseline(TypedDict):
    """Per-MAC published average latency at 1 Gbit/s, in 125 MHz clock cycles."""

    tx_avg_cycles: float
    tx_std_cycles: float
    rx_avg_cycles: float
    rx_std_cycles: float


# Source: Fibich 2023 doi:10.1155/2023/9222318 Table 15, page 35.
# Verbatim transcription with the paper's own ± standard deviation.
# Keys are the upstream project shorthand used elsewhere in the registry
# (e.g. curated_repos.json keyspace where applicable).
FIBICH_TABLE_15: Dict[str, LatencyBaseline] = {
    "litex-liteeth": {
        "tx_avg_cycles": 10.09,
        "tx_std_cycles": 0.29,
        "rx_avg_cycles": 12.97,
        "rx_std_cycles": 0.16,
    },
    "verilog-ethernet": {
        "tx_avg_cycles": 11.00,
        "tx_std_cycles": 0.00,
        "rx_avg_cycles": 13.97,
        "rx_std_cycles": 0.17,
    },
    "p-kerling-mac": {
        "tx_avg_cycles": 12.00,
        "tx_std_cycles": 0.00,
        "rx_avg_cycles": 16.91,
        "rx_std_cycles": 0.29,
    },
    "opencores-ethernet-tri-mode": {
        "tx_avg_cycles": 13.00,
        "tx_std_cycles": 0.00,
        "rx_avg_cycles": 17.52,
        "rx_std_cycles": 2.85,
    },
    "wge-100": {
        "tx_avg_cycles": 14.00,
        "tx_std_cycles": 0.00,
        "rx_avg_cycles": 14.99,
        "rx_std_cycles": 0.14,
    },
    "lewiz-lmac1": {
        "tx_avg_cycles": 17.50,
        "tx_std_cycles": 1.12,
        "rx_avg_cycles": 278.86,
        "rx_std_cycles": 0.35,
    },
}


def baseline_for(project: str) -> LatencyBaseline:
    """Look up baseline by project key, raising KeyError with the full available list."""
    try:
        return FIBICH_TABLE_15[project]
    except KeyError:
        raise KeyError(
            f"No Fibich-2023 Table 15 baseline for project {project!r}. "
            f"Available: {sorted(FIBICH_TABLE_15)}"
        ) from None


# ──────────────────────────────────────────────────────────────────────
# Cold-start sibling table (RTL-P3.368)
# ──────────────────────────────────────────────────────────────────────
#
# Methodology distinct from FIBICH_TABLE_15:
#
#   FIBICH_TABLE_15           — steady-state cross-size averages from
#                               100k frames at line rate (Fibich §5).
#                               The reference methodology.
#
#   FIBICH_TABLE_15_COLD_START — empirically observed single-frame
#                               post-reset latencies on a specific DUT,
#                               measured per Fibich wire size with
#                               Reset=1 pulsed between sizes so each
#                               frame is uniformly cold-start (MAC TX
#                               FSM idle-to-active wakeup + FIFO
#                               threshold-fill delays included).
#
# Why we ship a cold-start table at all: some DUTs (notably
# opencores/ethernet_tri_mode) have a documented back-to-back RX
# defect (OC-TRIMODE-RX-WAIT-END) that makes Fibich-style steady-state
# measurement fundamentally impossible — running >1 frame without a
# reset cycle stalls the RX path. Cold-start measurement dodges the
# defect and gives us a per-DUT REQ-2 drift detector. It is NOT a
# Fibich reproduction. See ``tb/contracts/eth_mac.md §11
# Methodology — steady-state vs cold-start``.
#
# Per ROUTERTL-002, the values below are hard-coded — they come from
# a calibrated harvest run via the cocotb test:
#
#     ETH_VALIDATOR_HARVEST_COLD_START=1 \
#         rr sim run cocotb_eth_mac_tri_mode_steady_state
#
# Re-harvest if the DUT, BFM stack, or simulator changes — drift > ±2
# cycles is then a real signal worth investigating, not noise.


class ColdStartLatency(TypedDict):
    """Per-size cold-start latency in 125 MHz clock cycles."""

    tx_cycles: int
    rx_cycles: int


# Outer key: project shorthand (same keyspace as FIBICH_TABLE_15).
# Inner key: Fibich wire size in bytes (one of FIBICH_SIZES).
FIBICH_TABLE_15_COLD_START: Dict[str, Dict[int, ColdStartLatency]] = {
    # Tri-mode harvested 2026-05-05 with Tx_Hwmark=0x1F (31 entries, the
    # OC-TRIMODE-TX-HWMARK workaround per curated_repos.json). Note the
    # TX saturation at 141 cycles for wire ≥ 512 B — the MAC TX FSM
    # waits for the FIFO to fill to HWM before starting wire emission;
    # once frame size exceeds the HWM threshold, TX startup latency is
    # bounded by the threshold-fill time, not the frame size. RX
    # latency tracks wire_size + 16 cycles cleanly across all sizes
    # (preamble traversal + 1G GMII per-byte clocking).
    "opencores-ethernet-tri-mode": {
        64:   {"tx_cycles":  29, "rx_cycles":   80},
        128:  {"tx_cycles":  45, "rx_cycles":  144},
        256:  {"tx_cycles":  77, "rx_cycles":  272},
        512:  {"tx_cycles": 141, "rx_cycles":  528},
        1024: {"tx_cycles": 141, "rx_cycles": 1040},
        1280: {"tx_cycles": 141, "rx_cycles": 1296},
        1400: {"tx_cycles": 141, "rx_cycles": 1416},
        1518: {"tx_cycles": 141, "rx_cycles": 1534},
    },
}
