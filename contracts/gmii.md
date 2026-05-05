# GMII (Gigabit Media Independent Interface) — Contract Specification

**Driver:**  `tb.drivers.gmii.GmiiSource` / `tb.drivers.gmii.GmiiSink`
**Monitor:** `tb.monitors.gmii_monitor.GmiiMonitor`
**Source spec:** IEEE 802.3-2018 §35 — *Reconciliation Sublayer (RS) and Gigabit Media Independent Interface (GMII)*.
**Scope:** the 8-bit-wide point-to-point interface between a 1 Gbit/s MAC and an external PHY. Strictly 1000BASE-X / 1000BASE-T at full-duplex; legacy 10/100 fall-back via MII or RGMII variants are out of scope (separate contracts).
**Status:** draft v1 — RTL-P3.299 Stage 2 of eth-validator roadmap.

---

## 1. Key finding — GMII is a clocked unidirectional byte bus, not a packet bus

GMII has no notion of "frames" at the wire level. It is two independent unidirectional 8-bit buses (TX and RX), each clocked by its own 125 MHz reference, with a single qualifier (`tx_en` / `rx_dv`) marking valid bytes and a single error indicator (`tx_er` / `rx_er`).

Frame structure — preamble, SFD, payload, FCS, IFG — is a **layer-2 convention** the MAC obeys when sourcing onto GMII. The PHY simply transports whatever the MAC asserts. This contract therefore separates two concerns:

- **Bus-level invariants** (this document): clock-domain rules, signal qualification, IFG minimums, error indication. The monitor enforces these on raw bytes.
- **Frame-level invariants** (see `tb/contracts/eth_mac.md`): preamble pattern, SFD value, FCS correctness, frame length bounds. The MAC contract enforces these on top of GMII.

Implication: `GmiiMonitor` is small and protocol-pure. It does not decode frames. Frame-level checks live in `EthIntegrityMonitor` (a higher-layer monitor that consumes GMII bytes via composition, similar to how `TSEMACMonitor` composes over `AvalonMMMonitor`).

---

## 2. What's distinctive — clock domains and the IFG floor

GMII has three properties peer monitors don't share:

| Property | Implication |
|---|---|
| **Two independent clocks** (`gmii_tx_clk`, `gmii_rx_clk`) sourced by opposite ends of the link | The monitor must instantiate one observer per direction. There is no single clock that gates both sides. |
| **No `ready` / backpressure signal** | Source-driven only. The MAC must always be able to accept incoming RX bytes; the PHY must always accept outgoing TX bytes. Failures here are catastrophic, not retried. |
| **Minimum IFG of 12 bytes** (IEEE 802.3 §4.4.2, "DIC" allows down to 5 in 1000BASE-T transmit, but receive must tolerate 12) | The monitor counts idle cycles between `tx_en` deassertion and re-assertion. Anything below the floor is a violation. |

---

## 3. Ports observed

GMII exposes one pair of buses, observed independently:

### `GmiiTxBus` (MAC → PHY direction)
| Signal | Width | Notes |
|---|---|---|
| `gmii_tx_clk` | 1 | 125 MHz clock, sourced by the MAC |
| `gmii_txd`    | 8 | Transmit data byte |
| `gmii_tx_en`  | 1 | High when `gmii_txd` is valid |
| `gmii_tx_er`  | 1 | High to signal a transmit error (qualified by `tx_en`) |

### `GmiiRxBus` (PHY → MAC direction)
| Signal | Width | Notes |
|---|---|---|
| `gmii_rx_clk` | 1 | 125 MHz clock, sourced by the PHY |
| `gmii_rxd`    | 8 | Receive data byte |
| `gmii_rx_dv`  | 1 | High when `gmii_rxd` is valid |
| `gmii_rx_er`  | 1 | High to signal a receive error (qualified by `rx_dv`) |

`GmiiTxBus.from_prefix(dut, "gmii_tx")` and `GmiiRxBus.from_prefix(dut, "gmii_rx")` use the same case-variant resolution as `AxiStreamBus.from_prefix`. Forencich's `eth_mac_1g_fifo` exposes exactly these names; vendor MACs that prefix with `phy_` or omit `gmii_` are handled via the second resolution attempt.

---

## 4. Parameters

| Param | Default | Effect |
|---|---|---|
| `min_ifg_cycles` | `12` | Minimum cycles of `tx_en==0` (or `rx_dv==0`) between consecutive valid windows. Below this → `GMII_IFG_MIN` violation. Set to `5` to model 1000BASE-T DIC-minimum receive. |
| `rst_active_low` | `False` | Reset polarity. Forencich's MAC uses active-high reset. |
| `channel` | `"gmii_tx"` / `"gmii_rx"` | Label used in violation records. |
| `strict_error_qualification` | `True` | If `True`, flag any cycle where `tx_er==1` while `tx_en==0` (per IEEE §35.2.2.5). Some PHYs assert error bits during idle; lax mode suppresses these. |

The two buses (TX, RX) are monitored by separate `GmiiMonitor` instances with separate parameter sets — no shared state.

---

## 5. Clauses enforced

Clause IDs follow the `GMII_*` convention, matching `AXIS_*` / `TSE_*` in peer monitors.

### `GMII_RST` — control signals deasserted during reset
**Rule:** `tx_en` (or `rx_dv`) must be `0` during the reset window. Asserting a valid byte while the interface is in reset is undefined.

**Why this matters:** a MAC that drives data during reset of its TX domain pushes garbage onto the wire as the PHY exits reset. Cross-domain reset glitches are the most common silent-corruption class in MAC integration.

### `GMII_VALID_QUALIFICATION`
**Rule:** `tx_er` (or `rx_er`) must only be asserted while `tx_en` (or `rx_dv`) is also asserted. Standalone error bits during idle are not legal per IEEE 802.3 §35.2.2.5.

**Why this matters:** consumers gate error logic on the data-valid signal. An unqualified error pulse is silently dropped, masking real corruption events.

**Lax mode** (`strict_error_qualification=False`): the monitor records unqualified error pulses informationally without flagging. Some real PHYs (e.g. older Broadcom designs) assert `rx_er` during link-down idle as a signal-loss indicator — strictly out-of-spec but widespread. Match real silicon by default.

### `GMII_IFG_MIN`
**Rule:** between deassertion of `tx_en` (the cycle following the last valid byte) and its next reassertion (the SOF byte of the next frame), a minimum of `min_ifg_cycles` clock cycles must elapse with `tx_en==0`. The same rule applies to `rx_dv` on the receive side.

**Why this matters:** receivers depend on the IFG to resync clock recovery and clear FIFOs. A MAC that bursts back-to-back frames with sub-minimum IFG will desync the link and trigger packet loss at the *receiver*, far from the offender — exactly the silent-corruption pattern Fibich Table 14 attributes to LMAC1.

**Cycle count semantics:** the IFG counter starts on the first cycle where `tx_en==0` after a `tx_en==1→0` edge, and stops on the first cycle where `tx_en==1` again. Reset clears the counter without firing.

### `GMII_DATA_HOLD`
**Rule:** while `tx_en==1`, every cycle must present a fresh byte on `gmii_txd`. There is no "stall" — `tx_en` cannot stay high while `gmii_txd` repeats the previous byte. Repetition during `tx_en==1` is presumed accidental and flagged.

**Why this matters:** GMII has no native handshake. Repeated bytes during a valid window are usually a clock-crossing FIFO underflow that the MAC failed to detect.

**Note:** legitimate same-byte sequences (e.g. preamble = 7× `0x55`) are still flagged-then-allow-listed at frame-level by `EthIntegrityMonitor`. The bus monitor doesn't know what's "supposed to" repeat.

Actually — on reflection this clause is too aggressive for a bus-pure monitor. **Defer to v2 if it earns its keep.** Real preambles legitimately repeat the same byte 7× and a bus monitor flagging that is noise. Marking as TODO.

### `GMII_CLOCK_PERIOD` (optional, off by default)
**Rule:** if `expected_clock_period_ps` is supplied, the monitor measures clock period across N cycles and flags drift > 100 ppm. Not enforced by default — clock period is a board-level property, not a protocol property.

---

## 6. Clauses NOT covered (test-driven, frame-level, or out of scope)

| # | Concern | Why not a bus monitor |
|---|---|---|
| 1 | Preamble pattern (7×`0x55` + `0xD5` SFD) | Frame-level — `EthIntegrityMonitor` |
| 2 | FCS correctness | Frame-level — `EthIntegrityMonitor` |
| 3 | Minimum frame length (64 B) / max (1518 B / 9000 B jumbo) | Frame-level — `EthIntegrityMonitor` |
| 4 | Auto-negotiation (Clause 37 / Clause 28) | Separate MDIO domain, separate contract |
| 5 | Carrier extension (1000BASE-T half-duplex bursts) | Half-duplex obsolete; explicitly out of scope |
| 6 | Pause frame semantics (IEEE 802.3 §31) | MAC-control sublayer, not GMII |
| 7 | Latency bounds | Test-driven — `EthLatencyMonitor` measures, doesn't enforce |
| 8 | Half-duplex collision (`COL` signal) | GMII §35.2.3 deprecates collision for full-duplex 1G; we don't model |

---

## 7. Violation record format

Emits `ProtocolViolation` records identical to peer monitors:

```python
ProtocolViolation(
    check_id="GMII_IFG_MIN",
    channel="gmii_tx",
    timestamp_ns=12340,
    message="IFG of 8 cycles between frames is below minimum 12 (IEEE 802.3 §4.4.2)"
)
```

Consumed by `TbEnv.check_monitors()` at end-of-test.

---

## 8. Framework changes this triggers

**None.** GMII fits cleanly into the existing `Bus` + `Monitor` pattern. No generalisation of peer abstractions required.

The only addition is `tb/drivers/gmii.py` itself (`GmiiSource` and `GmiiSink` BFMs) — pure new code, no edits to existing drivers.

---

## 9. Composition example

```python
from tb.env import TbEnv
from tb.drivers.gmii import GmiiSource, GmiiSink, GmiiTxBus, GmiiRxBus
from tb.monitors.gmii_monitor import GmiiMonitor

tb = TbEnv(dut, clk="gmii_tx_clk", rst="rst", period_ns=8)
await tb.start_clock()

# Independent buses, one monitor per direction.
tx_bus = GmiiTxBus.from_prefix(dut, "gmii_tx")
rx_bus = GmiiRxBus.from_prefix(dut, "gmii_rx")

tx_mon = GmiiMonitor(tx_bus, dut.gmii_tx_clk, dut.rst, log=log, channel="gmii_tx")
rx_mon = GmiiMonitor(rx_bus, dut.gmii_rx_clk, dut.rst, log=log, channel="gmii_rx")

cocotb.start_soon(tx_mon.run())
cocotb.start_soon(rx_mon.run())

# RX-side stimulus: PHY → MAC. The test injects bytes; the MAC consumes.
rx_src = GmiiSource(rx_bus, dut.gmii_rx_clk, dut.rst, log=log)
await rx_src.send_bytes(b"\x55"*7 + b"\xD5" + frame_payload)

# TX-side capture: MAC → PHY. The test observes what the MAC produced.
tx_sink = GmiiSink(tx_bus, dut.gmii_tx_clk, dut.rst, log=log)
captured = await tx_sink.recv_frame(timeout_ns=10_000)

tb.check_monitors()   # one-line contract gate, both buses
```

---

## 10. Review checklist

- [ ] IEEE 802.3-2018 §35 cited correctly for GMII bus signals?
- [ ] IFG floor of 12 bytes — correct for receive side; 5 (DIC) acceptable on transmit?
- [ ] Lax error-qualification default — matches what real silicon does in idle?
- [ ] `GMII_DATA_HOLD` clause deferred (preamble repetition is legitimate) — confirm the deferral is right?
- [ ] Two-monitor instantiation (one per direction) — preferred over a single bidirectional monitor?
- [ ] Bus dataclass split into `GmiiTxBus` + `GmiiRxBus` — preferred over a single `GmiiBus` with optional fields?
- [ ] Clock-period clause off by default — confirm clock checking belongs at the env level, not the bus monitor?
- [ ] Frame-level concerns (preamble pattern, FCS, length bounds) correctly delegated to `eth_mac.md` contract?
