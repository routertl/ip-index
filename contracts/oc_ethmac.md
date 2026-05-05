# OpenCores ethmac (Igor Mohor 10/100 Ethernet MAC) — Curator Contract

**DUT:** `opencores/ethmac` (registry row, granularity=repo).
**Upstream:** `https://github.com/freecores/ethmac.git` (community git mirror of opencores.org SVN).
**Author:** Igor Mohor + Olof Kindgren, 2001-2002.
**License:** LGPL-2.1-or-later (header-confirmed in every source file).
**Source spec — primary:** `doc/eth_speci.pdf` (OpenCores Ethernet IP Core Specification, project's own datasheet, 30+ pages).
**Source spec — IEEE:** IEEE 802.3-2018 §3 (MAC frame structure), §4.2 (MAC operation), §5 (10/100 Mbps MII PHY interface).
**Source spec — Wishbone:** Wishbone B3 specification (CSR slave + DMA master).
**Status:** silver — RTL-P2.517 stage 2c (2026-05-04). Behavioural contract for the IP-rescue + verification taxonomy. **No automated cocotb test exists yet for this DUT** — gold-tier promotion requires landing such a test (likely after RTL-P3.355 per-entity tier overrides, since a future per-DUT test only exercises `eth_top`, not the whole repo).

---

## 1. Identity

This is the **canonical OpenCores 10/100 Ethernet MAC**. Two decades old, still works on 90+% of FPGA toolchains, and quietly lives inside dozens of derivative SoCs (notably the OpenRISC reference designs and the Amber CPU example builds). The `eth_top.v` module is the only entry point users instantiate.

The README ships a working Icarus Verilog test harness (`make rtl-tests`); FuseSoC manifest at `ethmac.core` declares Vivado synth target out of the box. Optional `eth_cop` traffic coprocessor is available but not exercised in the registry contract.

## 2. What's distinctive

| Property | Implication |
|---|---|
| **MII PHY interface** (4-bit data, separate TX/RX clocks, half-duplex CRS/COL) | 10/100 Mbps only — does NOT scale to 1G. Pre-Forencich era; for 1G see opencores/ethernet_tri_mode or alex-forencich/eth_mac_1g_fifo. |
| **Wishbone B3 dual-port** — slave for CSRs (host→MAC) + master for buffer descriptors (MAC→memory DMA) | Atypical for OpenCores Ethernet implementations. Most user designs need an SoC bus that can host both a slave and a master from the same peripheral. |
| **Buffer descriptor model** — TX/RX queues live in shared memory accessed via the master Wishbone port | Closer to a commercial NIC driver model than the streaming-interface MACs. Performance hinges on memory bandwidth + descriptor management. |
| **MIIM block** included (`eth_miim.v` / `eth_clockgen.v` / `eth_outputcontrol.v` / `eth_shiftreg.v`) | Drives MDC/MDIO for PHY register access. The same block re-appears in opencores/ethernet_tri_mode (ingest excludes that copy via `exclude_dirs: ["eth_miim", ...]`); ethmac wins as canonical source. |
| **Optional BIST scan chain** (`ETH_BIST` define) | Manufacturing-test scaffolding; not exercised in normal use. |
| **No FCS strip on RX** — the 4-byte CRC32 is delivered to the host as part of the frame buffer | Inverse of forencich's eth_mac_1g_fifo, which strips RX FCS. Drivers must skip the trailing 4 bytes on receive. |

## 3. Ports — `eth_top` (the only entry point)

```
Wishbone slave (CSR):
  wb_clk_i, wb_rst_i
  wb_adr_i[11:2] / wb_sel_i[3:0] / wb_we_i / wb_cyc_i / wb_stb_i
  wb_dat_i[31:0] / wb_dat_o[31:0]
  wb_ack_o / wb_err_o

Wishbone master (DMA — buffer descriptors):
  m_wb_adr_o[31:0] / m_wb_sel_o[3:0] / m_wb_we_o
  m_wb_dat_o[31:0] / m_wb_dat_i[31:0]
  m_wb_cyc_o / m_wb_stb_o / m_wb_ack_i / m_wb_err_i
  m_wb_cti_o[2:0] / m_wb_bte_o[1:0]   (when ETH_WISHBONE_B3 defined)

MII PHY-side (TX domain — mtx_clk_pad_i):
  mtxd_pad_o[3:0] / mtxen_pad_o / mtxerr_pad_o

MII PHY-side (RX domain — mrx_clk_pad_i):
  mrxd_pad_i[3:0] / mrxdv_pad_i / mrxerr_pad_i
  mcoll_pad_i / mcrs_pad_i              (half-duplex collision + carrier-sense)

MIIM (MDC/MDIO):
  mdc_pad_o / md_pad_i / md_pad_o / md_padoe_o

Interrupt:
  int_o
```

Three clock domains: `wb_clk_i` (CSR + DMA + control), `mtx_clk_pad_i` (TX MII), `mrx_clk_pad_i` (RX MII). All asynchronous.

## 4. Parameters

```
TX_FIFO_DATA_WIDTH = `ETH_TX_FIFO_DATA_WIDTH   (default 32)
TX_FIFO_DEPTH      = `ETH_TX_FIFO_DEPTH        (default 4)
TX_FIFO_CNT_WIDTH  = `ETH_TX_FIFO_CNT_WIDTH    (default 3)
RX_FIFO_DATA_WIDTH = `ETH_RX_FIFO_DATA_WIDTH   (default 32)
RX_FIFO_DEPTH      = `ETH_RX_FIFO_DEPTH        (default 16)
RX_FIFO_CNT_WIDTH  = `ETH_RX_FIFO_CNT_WIDTH    (default 5)
```

The defines live in `eth_defines.v`.

## 5. Clauses (silver-tier, descriptive)

Bus-level invariants that any working ethmac instance must honour. These are NOT yet anchored against an automated test (no cocotb suite exists); they describe what the IP promises so a future gold-tier test knows what to assert.

### `OC_ETHMAC_FCS_NOT_STRIPPED`
RX frames delivered to the host buffer include the trailing 4-byte FCS. Drivers must skip those bytes when reading. (Diverges from forencich convention — see contract_traits in curated_repos.json.)

### `OC_ETHMAC_TX_FIFO_BACKPRESSURE`
When the TX FIFO fills, the next descriptor wait is signalled to the host via interrupt + status register. There is **no per-byte AXI-stream-style ready/valid** at the user side — the DMA master drains the descriptor queue at its own pace.

### `OC_ETHMAC_HALF_DUPLEX_PRESERVED`
`mcoll_pad_i` collision handling per IEEE 802.3 §4.2.3.2.4 (binary exponential backoff, 16 attempts max, then drop). Half-duplex is a real exercised path even on full-duplex links — needed for hub-attached test setups.

### `OC_ETHMAC_INTERRUPT_TAXONOMY`
Five interrupt sources via `INT_SOURCE` register: TXB (TX done), TXE (TX error), RXB (RX done), RXE (RX error), BUSY (RX buffer overflow). Drivers must read+clear `INT_SOURCE` on each `int_o` edge.

## 6. Future falsifiable headlines (gold-tier, deferred)

When a cocotb test eventually wraps this DUT (likely RTL-T or RTL-P3 follow-up), candidate REQ-N anchors:

- **REQ-1** Zero core-dropped frames over 10k-frame loopback at line rate (100 Mbps), 9 frame sizes per Fibich §5 methodology.
- **REQ-2** TX/RX latency baseline — no published table for ethmac in Fibich-2023 (it's pre-1G), but eth_speci.pdf Figure section "Performance" gives expected round-trip cycle counts. Reproduce within ±5 cycles.
- **REQ-3** FCS preserved end-to-end — every frame's CRC32 verifies on RX.
- **REQ-4** (ethmac-specific) Buffer descriptor wraparound — fill all `RX_FIFO_DEPTH` descriptors, confirm circular wrap honours `EMPTY` flag transitions correctly.
- **REQ-5** (ethmac-specific) Half-duplex collision recovery — adversarial test injecting collisions during TX, assert backoff retry count + final delivery within 16 attempts.

## 7. Cross-references

- RTL-P3.305 — initial OpenCores ingest of ethmac via freecores demand-driven convention (RTL-P4.24).
- RTL-P3.323 — `eth_miim` collision avoidance vs ethernet_tri_mode (this repo wins).
- curated_repos.json `contract.traits`/`defects` blocks per RTL-P2.506 — currently empty for ethmac (this contract markdown drafts what would land there for the silver tier).
- alex-forencich/verilog-ethernet `eth_mac_1g_fifo` for the 1G analogue with full gold-tier evidence (RTL-P3.299).
