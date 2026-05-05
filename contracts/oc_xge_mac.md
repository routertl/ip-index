# OpenCores xge_mac (Antoine Tanguay 10G Ethernet MAC) — Curator Contract

**DUT:** `opencores/xge_mac` (registry row, granularity=repo).
**Upstream:** `https://github.com/freecores/xge_mac.git` (community git mirror of opencores.org SVN).
**Author:** Antoine Tanguay et al., 2008.
**License:** LGPL-2.1-or-later (header-confirmed in `xge_mac.v` top module).
**Source spec — primary:** `doc/xge_mac_spec.pdf` (project's own specification, 28 pages, included in repo).
**Source spec — IEEE:** IEEE 802.3-2018 §49 (10GBASE-X PCS), §46 (XGMII), §4 (MAC operation, applies to all rates).
**Source spec — Wishbone:** Wishbone B3 specification (CSR slave only — no DMA master).
**Status:** silver — RTL-P2.517 stage 2c (2026-05-04). Behavioural contract for the IP-rescue + verification taxonomy. **No automated cocotb test exists yet for this DUT** — gold-tier promotion requires landing such a test.

---

## 1. Identity

This is the OpenCores **10 Gbps Ethernet MAC**. Pre-Forencich, pre-Taxi, predates the IEEE 802.3by 25G/40G/100G work entirely. Targets the line-rate XGMII PHY interface (64-bit data + 8-bit control sideband at 156.25 MHz) and exposes a packet-level streaming interface to the user side (no buffer descriptors, unlike opencores/ethmac's DMA model).

The `xge_mac` module is the only entry point users instantiate. README is sparse; `doc/xge_mac_spec.pdf` is the authoritative reference.

## 2. What's distinctive

| Property | Implication |
|---|---|
| **XGMII PHY interface** (64-bit data, 8-bit control sideband, 156.25 MHz SDR) | Wire-side burns 10.3125 Gbaud after PCS encoding. The MAC sees aligned 64-bit data + control flags marking start/end-of-packet, idle, error. Must be paired with a 10GBASE-X PCS or 10GBASE-R PCS for over-fibre links. |
| **Three async clock domains** — `clk_xgmii_tx` / `clk_xgmii_rx` (156.25 MHz each) + `clk_156m25` (system) + `wb_clk_i` (CSR, often 100 MHz) | Internal sync FIFOs (`sync_clk_*` modules) bridge the domains. CDC correctness is load-bearing for line-rate operation; getting reset-deassertion order wrong stalls the link silently. |
| **No DMA master** — pure packet-streaming interface (`pkt_tx_*` / `pkt_rx_*`) | Diverges from opencores/ethmac. The user is responsible for upstream buffer management; the MAC just produces/consumes 64-bit-wide packet streams with sop/eop/mod (mod = byte-valid count for the last word, 1-7). |
| **Local-fault / remote-fault detection** per IEEE 802.3ae §46.3.4 | `local_fault_msg_det[1:0]` + `remote_fault_msg_det[1:0]` signals exposed (typically routed to the Wishbone-accessible status register). Lack of fault recovery state machine in user-side logic is a common integration mistake — drivers must clear faults before TX resumes. |
| **No FCS strip on RX** (controlled by CSR bit; default = pass-through) | Same default as opencores/ethmac, opposite of forencich. Driver convention required to skip trailing 4 bytes. |
| **`pkt_rx_avail` + `pkt_rx_ren` handshake** (host-side flow control on RX) | User asserts `pkt_rx_ren` when ready; MAC presents data when `pkt_rx_avail` indicates a frame is queued. Different from AXI-Stream's tvalid/tready (the available/ready model is asymmetric). |

## 3. Ports — `xge_mac` (the only entry point)

```
Wishbone slave (CSR — wb_clk_i domain):
  wb_clk_i, wb_rst_i
  wb_adr_i[7:0] / wb_we_i / wb_cyc_i / wb_stb_i
  wb_dat_i[31:0] / wb_dat_o[31:0]
  wb_ack_o / wb_int_o

System / control (clk_156m25 domain):
  clk_156m25, reset_156m25_n

XGMII TX-side (clk_xgmii_tx domain — wire-side line rate):
  clk_xgmii_tx, reset_xgmii_tx_n
  xgmii_txd[63:0] / xgmii_txc[7:0]    (out)

XGMII RX-side (clk_xgmii_rx domain — wire-side line rate):
  clk_xgmii_rx, reset_xgmii_rx_n
  xgmii_rxd[63:0] / xgmii_rxc[7:0]    (in)

Packet-side TX (clk_156m25 domain — host → MAC):
  pkt_tx_data[63:0] / pkt_tx_mod[2:0] / pkt_tx_sop / pkt_tx_eop / pkt_tx_val
  pkt_tx_full          (MAC asserts when buffer can't accept more)

Packet-side RX (clk_156m25 domain — MAC → host):
  pkt_rx_data[63:0] / pkt_rx_mod[2:0] / pkt_rx_sop / pkt_rx_eop / pkt_rx_err / pkt_rx_val
  pkt_rx_avail         (MAC asserts when a frame is queued in the RX buffer)
  pkt_rx_ren           (host asserts to dequeue)
```

`pkt_*_mod[2:0]`: the count of valid bytes in the **last** word of the frame. 0 means all 8 bytes valid; 1-7 means that many bytes are valid (rest are don't-care). Same semantics as Xilinx AXI-Stream `tkeep` but encoded as count, not mask.

## 4. Parameters

```
(no top-level parameters — configuration via CSR registers)
```

CSR register map is in `doc/xge_mac_spec.pdf` §3 (Tx_Stat, Rx_Stat, Cfg, Int_Pending, Int_Mask, etc.). Register addresses are 8-bit (`wb_adr_i[7:0]`).

## 5. Clauses (silver-tier, descriptive)

Bus-level invariants and behavioural promises that any working xge_mac instance must honour. Not yet anchored to an automated test.

### `OC_XGE_MAC_XGMII_ALIGNMENT`
TX wire-side: every cycle of `xgmii_txd[63:0]` carries 8 valid characters; `xgmii_txc[7:0]` flags which are control (start, terminate, error, idle). The MAC must never present a packet whose start-of-frame is mid-word — frames begin only at byte lane 0 or 4 (per IEEE 802.3ae §46.3.1.2). Misalignment is a real bug class on this MAC.

### `OC_XGE_MAC_FAULT_PROPAGATION`
On `local_fault` or `remote_fault` asserted, TX must idle within 1 µs (per IEEE 802.3ae §46.3.4 — fault sequence ordered set). The MAC inserts the IEEE-defined Sequence ordered set onto `xgmii_txd`. Drivers reading `Int_Pending[fault]` must observe + acknowledge faults before re-enabling TX, or new traffic will be dropped silently.

### `OC_XGE_MAC_SYNC_FIFO_CDC_CORRECTNESS`
Internal `sync_clk_xgmii_*` and `sync_clk_wb` modules bridge async domains. The MAC's reset deassertion order is implicit but real: `wb_rst_i` deasserts last, after both XGMII reset_n's have been deasserted for at least one clk_156m25 cycle. Violating this order leaves the sync FIFOs in undefined state and is the most-common integration bug for first-time users.

### `OC_XGE_MAC_PKT_TX_FULL_BACKPRESSURE`
Host MUST sample `pkt_tx_full` and drop `pkt_tx_val` within 1 cycle when full. Continuing to drive valid words while `pkt_tx_full` is asserted causes silent frame corruption (the head of the frame may be retained while the tail is dropped — no error indication).

### `OC_XGE_MAC_PKT_RX_AVAIL_HANDSHAKE`
Host pattern: wait for `pkt_rx_avail`, then assert `pkt_rx_ren` for as many cycles as frames-to-dequeue. Each rising `pkt_rx_ren` while `pkt_rx_avail` is asserted dequeues exactly one frame's worth of words. Driving `pkt_rx_ren` without `pkt_rx_avail` is a no-op (data ignored) — no error, no deadlock.

## 6. Future falsifiable headlines (gold-tier, deferred)

When a cocotb test eventually wraps this DUT (RTL-T or RTL-P3 follow-up), candidate REQ-N anchors:

- **REQ-1** Zero core-dropped frames over 1k-frame loopback at 10 Gbps line rate, 9 frame sizes per Fibich §5 methodology adapted (xge_mac is **not** in Fibich-2023's surveyed set — no published baseline).
- **REQ-2** TX/RX latency baseline — author's `doc/xge_mac_spec.pdf` Table "Performance Characteristics" gives expected XGMII-to-pkt cycle counts (~6 cycles RX, ~4 cycles TX). Reproduce within ±2 cycles.
- **REQ-3** FCS preserved end-to-end on every frame.
- **REQ-4** (xge_mac-specific) Local-fault recovery — inject `local_fault` ordered-set on RX, assert MAC raises `Int_Pending[fault]` within 1 µs; driver clears + re-enables; resumed TX delivers next 100 frames clean.
- **REQ-5** (xge_mac-specific) `pkt_tx_full` honoured — adversarial test driving valid through asserted-full, assert frame-corruption symptoms (this REQ should *fail* without backpressure handling, demonstrating the contract is real).
- **REQ-6** (xge_mac-specific) CDC correctness — fuzz reset deassertion order, confirm sync FIFOs reach steady state for any legal ordering within 100 wb_clk cycles.

## 7. Cross-references

- RTL-P3.304 — initial OpenCores ingest of xge_mac via freecores demand-driven convention (RTL-P4.24).
- alex-forencich/verilog-ethernet `eth_mac_10g` for the 10G analogue with active maintenance (Forencich's 10G MAC is the modern open-source replacement; xge_mac is the legacy reference but still works).
- fpganinja/taxi `taxi-ethernet` carries the next-generation 10G/25G MAC that derives from Forencich's 10G work.
- For 10G PCS pairing: xge_mac itself does not include the PCS; integrators typically pair it with Forencich's `eth_phy_10g` core or a vendor PCS megafunction.
