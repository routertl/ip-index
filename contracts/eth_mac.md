# IEEE 802.3 1G Ethernet MAC — Frame-Level Contract Specification

**Driver:**  `tb.drivers.eth_frame_gen.EthFrameGen` (frame constructor over AXI-Stream / GMII)
**Monitors:** `tb.monitors.eth_integrity_monitor.EthIntegrityMonitor`,
              `tb.monitors.eth_latency_monitor.EthLatencyMonitor`
**Source spec:** IEEE 802.3-2018 §3 (MAC frame structure) and §4 (MAC operation).
**Composes over:** `tb.contracts.gmii.GmiiMonitor` (PHY-side bus protocol).
**Scope:** the IEEE 802.3 1 Gbit/s MAC service interface — frames, not bytes. Anchors REQ-1, REQ-2, REQ-3 from RTL-P3.299 (eth-validator Stage 2 spine).
**Status:** draft v1 — RTL-P3.299 Stage 2 of eth-validator roadmap.

---

## 1. Key finding — this contract owns the falsifiable headlines

GMII (`tb/contracts/gmii.md`) defines the byte-level protocol. This contract sits one layer up: it consumes a GMII byte stream and asserts properties about **frames** — preamble pattern, FCS correctness, length bounds, latency bounds, integrity attribution.

The RTL-P3.299 ticket pins three falsifiable acceptance criteria — REQ-1, REQ-2, REQ-3 — and they all live in this document, not in GMII. That separation is deliberate: GMII is reusable across any MAC; this contract is what the eth-validator test orchestrator anchors `@requires(REQ-N)` decorators against.

The clauses below are organised as:
- **Bus-level frame structure** (preamble, SFD, length, FCS) — invariant for any IEEE 802.3 1G frame.
- **Falsifiable headlines** (REQ-1, REQ-2, REQ-3) — the criteria the eth-validator test must satisfy to be considered passing for the Forencich `eth_mac_1g_fifo` DUT.

---

## 2. What's distinctive — FCS and the loopback model

Ethernet at the MAC service interface has two properties that drive the contract shape:

| Property | Implication |
|---|---|
| **CRC-32 FCS** is the universal integrity check. A single bit-flip anywhere in the frame should be detected. | `ETH_FCS_VALID` is the most load-bearing clause — if FCS check fails on a known-good DUT, every other clause is suspect. |
| **Frame loss is attributed to a layer**: kernel-drop (K), interface-drop (IF), or core-drop (Core). Fibich Table 14 is the canonical model. | `ETH_LOSS_ATTRIBUTION` (REQ-1) requires the test harness to count drops *separately* by source — not aggregate. A MAC that drops 100 frames is meaningfully different from a kernel that drops 100 frames. |

Plus one **operational** property: latency in the loopback context is the time from **MAC TX user-side ready** to **GMII TX first byte** (TX latency), or from **GMII RX first byte** to **MAC RX user-side valid** (RX latency). Fibich Table 15 publishes average TX and RX latency in clock cycles per MAC for the 1 Gbit/s tier (six MACs ranked); reproducing the Forencich `eth_mac_1g_fifo` averages within ±2 cycles is REQ-2.

**Note:** Table 15 is averages, not per-frame-size. Per-size latency curves are in Figure 10 of the paper but are graphical (curves vs frame length) and not transcribable to robust numerical baselines. Stage 2 anchors REQ-2 against the published averages; per-size baselines are deferred to Stage 3 if Figure 10 extraction proves worthwhile.

---

## 3. Ports observed (logical — composes over GMII)

This monitor does **not** directly bind to DUT signals. It consumes frame events emitted by `GmiiMonitor` (via composition, mirroring `TSEMACMonitor → AvalonMMMonitor`). The composition is hidden from the test author:

```python
# Internal composition pattern (not user-visible)
self._gmii_mon = GmiiMonitor(bus, clk, rst, log=log, channel=channel)

async def run(self):
    # ... start GMII monitor, then layer frame-decode + FCS + latency on top
    cocotb.start_soon(self._gmii_mon.run())
    await self._frame_decoder_loop()
```

The frame decoder loop watches `tx_en` / `rx_dv` edges to delimit frames, accumulates bytes between edges, computes FCS over the captured payload, and emits `ProtocolViolation` records on each clause failure.

For the latency monitor (separate class), the test orchestrator timestamps frames at AXI-Stream user-side ingress and matches them at GMII egress (or vice versa for RX-side latency).

---

## 4. Parameters

| Param | Default | Effect |
|---|---|---|
| `min_frame_bytes` | `64` | Including DST + SRC + Type + Payload + FCS, excluding preamble/SFD. Frames smaller than this trip `ETH_FRAME_LEN_MIN`. Set higher for jumbo-only test scenarios. |
| `max_frame_bytes` | `1518` | Standard Ethernet max. Set to `9000` for jumbo. |
| `fcs_polynomial` | `0x04C11DB7` | CRC-32 polynomial per IEEE 802.3 §3.2.9. The constant is the **only** legal value — overriding is for adversarial test fixtures, not production. |
| `latency_tolerance_cycles` | `2` | REQ-2 floor: average TX and RX latency must match the Fibich Table 15 averages for the DUT within ±N cycles. Tighten to 1 for stricter regression. |
| `expected_latency` | `None` | Required for REQ-2. Dict `{"tx_avg_cycles": float, "rx_avg_cycles": float}` for the DUT. Fibich Table 15 values shipped as `tb.contracts.eth_mac_1g_fifo_baselines.FIBICH_TABLE_15`. |
| `frame_count_per_size` | `100_000` | REQ-1 sample size. Below this, packet-loss statistics are not reliable. |
| `frame_sizes` | `[64, 128, 256, 512, 1024, 1280, 1400, 1518]` | REQ-1 frame-size sweep. Matches Fibich §5 methodology. |
| `loss_budget_per_layer` | `{"K": 0, "IF": 0, "Core": 0}` | REQ-1 acceptance: zero core-dropped frames. K and IF drops are environment artifacts; Core drops are MAC bugs. |
| `rst_active_low` | `False` | Reset polarity (passes through to underlying GMII monitor). |
| `channel` | `"eth_mac"` | Label used in violation records. |

---

## 5. Clauses enforced

Clause IDs follow the `ETH_*` convention.

### Bus-level frame structure

#### `ETH_PREAMBLE`
**Rule:** every frame on GMII begins with exactly 7 bytes of `0x55` followed by 1 byte of `0xD5` (the SFD). Sequences shorter, longer, or with corrupted bytes trip this.

**Why this matters:** receivers depend on the preamble pattern for clock recovery and byte alignment. A MAC that emits 6 or 8 preamble bytes (or `0x57` instead of `0x55`) breaks downstream recovery silently — the next-stage receiver discards the frame without telling anyone upstream.

**Hard-coded expected values per ROUTERTL-002:** `b"\x55" * 7 + b"\xD5"`. Do not derive at runtime.

#### `ETH_SFD`
**Rule:** the 8th byte of every frame is exactly `0xD5`. Asserted as a separate clause (rather than rolled into `ETH_PREAMBLE`) so violation messages can distinguish "preamble pattern wrong" from "SFD missing/wrong".

#### `ETH_FRAME_LEN_MIN`
**Rule:** post-preamble frame length (DST + SRC + Type + Payload + FCS) is ≥ `min_frame_bytes` (default 64). Padding to reach 64 is the MAC's responsibility; observing a sub-64-byte frame on GMII is a MAC bug.

#### `ETH_FRAME_LEN_MAX`
**Rule:** post-preamble frame length ≤ `max_frame_bytes` (default 1518; 9000 in jumbo mode). Frames exceeding this are giants and indicate framing logic that lost track of `tx_en` / `rx_dv` edges.

#### `ETH_FCS_VALID`
**Rule:** the trailing 4 bytes of every frame compute as the IEEE 802.3 §3.2.9 CRC-32 of the preceding payload (DST + SRC + Type + Payload, excluding preamble/SFD). FCS mismatch is the most load-bearing failure mode — it implies bit-corruption somewhere in the frame.

**Hard-coded polynomial per ROUTERTL-002:** `0x04C11DB7`. The CRC-32 reference table is computed once at monitor init; runtime computation is a pure-math reference, not "derived from input."

### Falsifiable headlines (REQ-1 / REQ-2 / REQ-3)

#### `ETH_LOSS_ATTRIBUTION` (REQ-1)
**Rule:** over a `frame_count_per_size`-frame loopback at each size in `frame_sizes`, the count of frames with `attribution=Core` (i.e. dropped by the MAC core, not by Linux kernel or NIC interface) is ≤ `loss_budget_per_layer["Core"]` (default 0).

**Methodology lifted from Fibich §5:** drive packETH-style deterministic generator → loopback through DUT → capture at egress → match outbound to inbound by frame ID embedded in payload. Drops are attributed by *which component* failed to forward the frame: kernel (K), interface FIFO (IF), or MAC core. This monitor enforces only the Core column; K and IF are environmental and outside test scope.

**Why this matters:** LMAC1 (Fibich Table 14) drops 0.05–1.3% of frames at 1G. If the eth-validator gate accepts non-zero Core drops, regressions of that class slip through silently.

#### `ETH_LATENCY_BOUND` (REQ-2)
**Rule:** average TX latency (MAC user-side TX ingress → GMII TX first byte) and average RX latency (GMII RX first byte → MAC user-side RX valid) for the DUT, measured over the same 100k×9-size sweep as REQ-1, match `expected_latency["tx_avg_cycles"]` and `expected_latency["rx_avg_cycles"]` within `latency_tolerance_cycles` (default ±2 at 125 MHz).

**Falsifiable headline:** for the Forencich `eth_mac_1g_fifo` DUT, the published numbers are TX = 11.00 ± 0.00 cycles, RX = 13.97 ± 0.17 cycles (Fibich Table 15). `expected_latency` is loaded from `tb.contracts.eth_mac_1g_fifo_baselines.FIBICH_TABLE_15["verilog-ethernet"]`. If our reproduction drifts more than ±2 cycles from either, Stage 2 is not done.

**Per-size data deferred:** Fibich's per-size latency curves (Figure 10) are graphical and not robustly transcribable. Stage 2 anchors REQ-2 against published averages only. A future ticket can extract Figure 10 if the per-size sweep adds value.

**Why this matters:** the whole point of eth-validator is to provide a contract-first, peer-reviewed-baseline-matching gate. If we can't reproduce a published measurement on the same DUT, we don't have a valid spine and Stage 3 (other DUTs) can't proceed.

#### `ETH_FCS_PRESERVED` (REQ-3)
**Rule:** for every frame that enters the DUT at the AXI-Stream user TX side and exits at the AXI-Stream user RX side (via PHY loopback), the captured FCS at egress equals the computed FCS at ingress. End-to-end FCS preservation.

**Why this matters:** REQ-3 is the cheapest sanity check. A MAC that mangles FCS on most frames will trip immediately; a MAC that mangles it on edge cases (jumbo, runts, alignment-sensitive sizes) will only trip with the full sweep. REQ-3 + the size sweep are co-load-bearing.

---

## 6. Clauses NOT covered (test-driven, higher-layer, or out of scope)

| # | Concern | Why not this monitor |
|---|---|---|
| 1 | Preamble byte pattern at granularity finer than "first 7 bytes are 0x55" — e.g. some PHYs corrupt the first preamble byte during clock recovery (the "preamble shrink" effect) | PHY-side property, not MAC. The MAC must source 7 full bytes; what arrives at the wire is the PHY's problem. |
| 2 | VLAN tagging (IEEE 802.1Q) | Separate frame format; if needed, add `eth_mac_vlan.md` contract. |
| 3 | Pause frames (IEEE 802.3 §31, MAC Control sublayer) | Above MAC service interface. |
| 4 | ARP / IP / UDP / TCP semantics in the payload | Above the MAC. The MAC contract treats payload as opaque bytes. |
| 5 | Auto-negotiation (Clause 37 / Clause 28) | MDIO-level, separate contract. |
| 6 | Clock-domain crossing inside the MAC (e.g. Fibich §3.2.4 GRETH/Ethmac findings) | Test-driven via fault injection. The contract enforces frame-level invariants; CDC bugs manifest as integrity failures *caught* by `ETH_FCS_VALID`, but the *root cause* requires a different test class. See `Haz.42–47` for the per-MAC catalogue. |
| 7 | Half-duplex collision (`COL` signal) | 1000BASE-X full-duplex only; out of scope. |
| 8 | Energy-efficient Ethernet (LPI signalling) | Separate IEEE 802.3az amendment. |

---

## 7. Violation record format

```python
ProtocolViolation(
    check_id="ETH_FCS_VALID",
    channel="eth_mac",
    timestamp_ns=12340,
    message="FCS mismatch at frame 4127 (size=512): expected 0xC3FE9A2D, got 0x00000000"
)
```

Per-frame messages embed the frame index + size for cross-reference with the test orchestrator's transmit log.

---

## 8. Framework changes this triggers

**Two minor additions, no edits to existing modules:**

1. `tb.contracts.eth_mac_1g_fifo_baselines` — Python module shipping `FIBICH_TABLE_15` (a dict keyed by MAC project name, each entry holding tx_avg_cycles, tx_std_cycles, rx_avg_cycles, rx_std_cycles). Hard-coded numbers per ROUTERTL-002, transcribed from the paper, with a `# Source: Fibich 2023 doi:10.1155/2023/9222318 Table 15` provenance comment.

2. `tb.scoreboard.FrameMatchScoreboard` (potential) — generic frame-in / frame-out matcher for loopback tests. The existing `tb.scoreboard` module probably already has something close; check before adding.

---

## 9. Composition example

```python
from tb.env import TbEnv
from tb.drivers.eth_frame_gen import EthFrameGen
from tb.monitors.eth_integrity_monitor import EthIntegrityMonitor
from tb.monitors.eth_latency_monitor import EthLatencyMonitor
from tb.contracts.eth_mac_1g_fifo_baselines import FIBICH_TABLE_15

tb = TbEnv(dut, clk="logic_clk", rst="rst", period_ns=8)
await tb.start_clock()

# Frame integrity (preamble, SFD, length bounds, FCS, REQ-1 attribution).
integrity = EthIntegrityMonitor(
    gmii_tx_bus=tx_bus,
    gmii_rx_bus=rx_bus,
    clk=dut.gmii_tx_clk,
    rst=dut.rst,
    log=log,
    frame_count_per_size=100_000,
    frame_sizes=[64, 128, 256, 512, 1024, 1280, 1400, 1518],
    loss_budget_per_layer={"K": 0, "IF": 0, "Core": 0},
)

# Latency reproduction (REQ-2 falsifiable headline).
latency = EthLatencyMonitor(
    user_axis_bus=user_rx_bus,
    gmii_bus=rx_bus,
    clk=dut.gmii_rx_clk,
    rst=dut.rst,
    log=log,
    expected_latency=FIBICH_TABLE_15["verilog-ethernet"],
    latency_tolerance_cycles=2,
)

cocotb.start_soon(integrity.run())
cocotb.start_soon(latency.run())

# Drive deterministic frames through the DUT (PHY loopback wired in test).
gen = EthFrameGen(user_tx_bus, dut.logic_clk, log=log)
for size in [64, 128, 256, 512, 1024, 1280, 1400, 1518]:
    for i in range(100_000):
        await gen.send_frame(size=size, frame_id=i)

tb.check_monitors()   # REQ-1, REQ-2, REQ-3 gate
```

---

## 10. Methodology — steady-state vs cold-start (RTL-P3.368)

REQ-2 has **two** legitimate measurement methodologies. Use the steady-state form whenever the DUT permits; fall back to cold-start only when a documented DUT defect blocks back-to-back traffic.

### 10.1 Steady-state (Fibich §5 — the reference)

| Property | Value |
|---|---|
| Source | Fibich, Schmitt, Höller, Rössler 2023 §5 |
| Frame count | 100 000 per size, ~9 sizes, line rate (no idle gap) |
| Latency definition | Pipeline-converged TX/RX cycle counts averaged across the sweep |
| Baselines table | `FIBICH_TABLE_15` (cross-size averages, per MAC project) |
| Expected drift on a healthy DUT | ≤ ±2 cycles vs. published average |

Steady-state is the form of REQ-2 that proves we *reproduce a peer-reviewed measurement*. Default Stage-2 / Stage-3 gate on any DUT that can sustain back-to-back loopback (e.g. Forencich `eth_mac_1g_fifo`).

### 10.2 Cold-start (per-size, reset between)

| Property | Value |
|---|---|
| Source | Empirical — harvested per DUT via the `cocotb_eth_mac_tri_mode_steady_state` test (or its peer for other DUTs) |
| Frame count | 1 frame per Fibich size, `Reset=1` pulsed between sizes |
| Latency definition | Per-size, single-frame round-trip cycles measured from a uniformly-cold DUT — includes MAC TX FSM idle-to-active wakeup + FIFO threshold-fill delay |
| Baselines table | `FIBICH_TABLE_15_COLD_START` (per-size dict, per MAC project) |
| Expected drift on an unchanged DUT | ≤ ±2 cycles vs. pinned per-size value (regression detector, not a Fibich reproduction) |

The cold-start regime is *legitimately different* from steady-state — typically ~2× the published numbers (e.g. on opencores tri-mode, TX 29 vs Fibich 13, RX 80 vs Fibich 17.52 at the smallest Fibich wire size). Pinning empirical values for this DUT keeps REQ-2 useful as a drift detector even when steady-state reproduction is impossible.

### 10.3 When to use which

```
DUT can run back-to-back at line rate?
├── YES → steady-state methodology (FIBICH_TABLE_15)
│         REQ-2 is a Fibich reproduction.
└── NO  → known/documented DUT defect blocks back-to-back?
          ├── YES → cold-start methodology (FIBICH_TABLE_15_COLD_START)
          │         REQ-2 is a per-DUT drift detector.
          │         Document the blocking defect in
          │         curated_repos.json contract.defects.
          └── NO  → diagnose first; do not paper over with cold-start.
                    Filing a T-tier defect is the right move.
```

The bias is intentional: cold-start is the *fallback* for documented DUT defects only. A green-bar cold-start run on a DUT that *should* run steady-state hides regressions in the steady-state path itself.

### 10.4 Re-harvesting cold-start values

When the DUT, BFM stack, or simulator changes, the pinned cold-start table can drift. Re-harvest via:

```
ETH_VALIDATOR_HARVEST_COLD_START=1 \
    rr sim run test_eth_mac_tri_mode
```

The test logs an 8-row table (wire size, TX cycles, RX cycles); copy values into `FIBICH_TABLE_15_COLD_START["opencores-ethernet-tri-mode"]` and rerun without the env var to gate. Drift > ±2 cycles between harvests is a real signal — investigate before accepting.

---

## 11. Review checklist

- [ ] CRC-32 polynomial `0x04C11DB7` correct? (IEEE 802.3 §3.2.9)
- [ ] Min frame size 64 bytes — correct including or excluding FCS?
- [ ] Max frame size 1518 — should jumbo (9000) be the default for newer use cases?
- [ ] REQ-1 loss budget set to **zero** for Core — is that the right default, given LMAC1 was rejected for *any* loss?
- [ ] REQ-2 tolerance ±2 cycles — tight enough to be falsifiable, loose enough to absorb sim/board difference?
- [ ] Fibich Table 15 averages transcribed correctly when we ship `eth_mac_1g_fifo_baselines.py`? (TX 11.00 ± 0.00, RX 13.97 ± 0.17 for verilog-ethernet — cross-check at scaffold time.)
- [ ] REQ-2 anchored against averages (Table 15) rather than per-size curves (Figure 10) — confirm this is the right call given Figure 10 is graphical-only?
- [ ] Composition over `GmiiMonitor` — is the hidden-from-test-author pattern the right default, or should the test wire both monitors explicitly?
- [ ] `EthIntegrityMonitor` vs `EthLatencyMonitor` as separate classes — preferred over a single `EthMacMonitor` with both responsibilities?
- [ ] Frame-attribution model (K / IF / Core) — exact match to Fibich §5, or do we coarsen?
- [ ] CDC bugs (Haz.42–47) explicitly out-of-monitor-scope — confirm this is right? (Argument for: monitor enforces invariants; CDC is fault injection. Argument against: a CDC-aware monitor would catch broader bug classes.)
