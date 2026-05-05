# AXI4-Stream (AXIS) — Contract Specification

**Monitor:** `tb.monitors.axi_stream_monitor.AxiStreamMonitor`
**Bus:**     `tb.drivers.axi_stream.AxiStreamBus`
**Source spec:** ARM AMBA AXI4-Stream Protocol Specification (IHI 0051)
                 §2 "Signal Description" and §2.2 "Handshake Process"
                 (public).
**Scope:** any AXI-Stream source or sink — tvalid/tready handshake with
           optional per-byte validity (tkeep/tstrb), packet framing
           (tlast), user-side-band (tuser), and routing fields
           (tid/tdest).

---

## 1. Ports observed

Resolved via `AxiStreamBus.from_prefix(dut, prefix)`:

| Signal | Required | Purpose |
|---|:---:|---|
| `clk` | ✓ (monitor constructor) | Sampling clock |
| `{prefix}_tvalid` | ✓ | Source asserts when data is valid |
| `{prefix}_tready` | ✓ | Sink asserts when ready to accept |
| `{prefix}_tdata` | ✓ | Payload |
| `{prefix}_tkeep` |   | Per-byte validity on the current beat |
| `{prefix}_tstrb` |   | Per-byte "position" strobe (byte-level packing) |
| `{prefix}_tlast` |   | Last beat of a packet / frame |
| `{prefix}_tuser` |   | User-defined side-band (often SOF on video streams) |
| `{prefix}_tid`   |   | Stream identifier for demux fabrics |
| `{prefix}_tdest` |   | Routing destination for interconnects |

Auto-discovery tries the canonical lower-case names and case variants.
Optional signals that aren't on the bus are set to `None`; the
corresponding checks are skipped.

Signal naming note: AXIS uses the `t`-prefixed convention
(`tvalid`/`tdata`/…), distinct from Avalon-ST's bare names
(`valid`/`data`/…).  Don't reuse an Avalon-ST monitor against an AXIS
bus — signal discovery will fail or attach to the wrong wires.

---

## 2. Parameters

| Param | Default | Effect |
|---|---|---|
| `rst_active_low` | `False` | Reset polarity.  Set `True` for AMBA-standard `aresetn`. |
| `sof_on_tuser_bit` | `None` | If not `None`, enable packet-framing checks assuming bit N of `tuser` is SOF.  AXIS has no universal SOF signal; this is a common SDI/video convention. |
| `channel` | `"stream"` | Label used in violation records — set to something identifying (e.g. `"s_axis_rx0"`) when attaching multiple monitors. |

---

## 3. Clauses enforced

### `AXIS_DATA_HOLD`
**Rule:** while `tvalid=1 & tready=0`, the source MUST hold every
payload field stable — `tdata`, `tkeep`, `tstrb`, `tlast`, `tuser`,
`tid`, `tdest` — until either the sink asserts `tready=1` or the
handshake completes.  Changing the payload mid-stall is a protocol
violation.

**Why it matters:** sinks sample on the `tready=1 & tvalid=1` edge; if
the source "changed its mind" while stalled, the sink accepts whatever
was driven on that specific edge — usually a different beat from the
one originally offered.  Classic "lost packet header" bug.

### `AXIS_RST`
**Rule:** during reset (per `rst_active_low`), `tvalid` MUST be `0`.

**Why it matters:** AMBA §2.7.1 specifies tvalid is driven low during
reset.  Asserting valid in reset is undefined — downstream synchronisers
may capture stale payload past reset release, and downstream counters
may record spurious transactions that never actually happened.

### `AXIS_VALID_STICKY`
**Rule:** once `tvalid=1` is asserted, the source MUST keep it asserted
until `tready=1` is observed in the same cycle.  Producers may not
withdraw an offered beat.

**Why it matters:** AMBA §2.2.1 defines the handshake as "source holds
the offer, sink decides when to take it".  A producer that drops valid
before the accept cycle violates this — the sink sees a one-cycle
pulse it cannot latch, and the beat is effectively lost.  Common
regression when a producer's internal FSM has a mis-timed "cancel"
branch.

### `AXIS_EOP_WO_SOP` *(opt-in: `sof_on_tuser_bit` set)*
**Rule:** with caller-supplied SOF semantics on `tuser[sof_on_tuser_bit]`,
a `tlast=1` beat MUST follow a SOF-carrying beat in the same packet.

**Why it matters:** packet-framing corruption — a sink counting packets
by tlast will miscount if SOFs are lost, and a sink reconstructing
packets will splice fragments from adjacent frames.

### `AXIS_SOF_MID_PKT` *(opt-in: `sof_on_tuser_bit` set)*
**Rule:** SOF (tuser bit) MUST NOT be asserted while a packet is
already in flight (after SOF but before its matching tlast).

**Why it matters:** two overlapping packets on a single-stream bus
means the downstream demux cannot tell them apart — fragment of
packet N followed by fragment of packet N+1.

### `AXIS_TID_MID_PKT` / `AXIS_TDEST_MID_PKT` *(opt-in)*
**Rule:** `tid` and `tdest` MUST be stable from SOF through `tlast=1`.
A packet belongs to one logical stream and one destination; flipping
these mid-packet confuses interconnect demuxes that route per-beat.

**Why it matters:** `tid`/`tdest` are the AXIS equivalents of
Avalon-ST's `channel` — same bug class, same fix (latch at SOF,
compare on every downstream beat).

---

## 4. Clauses NOT covered (honest scope)

- **Data-content correctness** — the monitor checks framing/stability,
  not payload semantics.  Per-test assertions or a scoreboard carry
  the payload-equivalence load.
- **`tkeep` / `tstrb` semantic interpretation** — observed for
  HOLD-stability only; which bytes are valid vs position-strobed is
  the test's job.  AMBA specifies four combinations (null byte,
  position byte, data byte, unspec); the monitor doesn't enforce the
  encoding.
- **`tlast` without framing semantics** — when `sof_on_tuser_bit` is
  not set, `tlast` is tracked only for HOLD-stability.  Packet-framing
  clauses (`EOP_WO_SOP`, `SOF_MID_PKT`, `TID_MID_PKT`) require the
  caller to opt in because AXIS has no universal SOF signal.
- **Throughput / fairness** — this is a protocol monitor, not a
  performance gate.
- **Bus-width validation** — the monitor treats `tdata` as a single
  integer; byte-level width mismatches between source and sink are
  out of scope (let the simulator's width checks or elaboration catch
  those).

---

## 5. Violation record format

Emits `ProtocolViolation` records identical to peer monitors:

```python
ProtocolViolation(
    check_id="AXIS_DATA_HOLD",
    channel="s_axis_rx0",
    timestamp_ns=1240,
    message="tdata changed during tvalid=1 & tready=0 "
            "(was 0xDEAD, now 0xBEEF)"
)
```

Consumed by `TbEnv.check_monitors()` at end-of-test.

---

## 6. Composition example

```python
from tb.drivers.axi_stream import AxiStreamBus
from tb.monitors.axi_stream_monitor import AxiStreamMonitor
import cocotb, logging

bus = AxiStreamBus.from_prefix(dut, "s_axis_rx0")
mon = AxiStreamMonitor(
    bus, dut.aclk, dut.aresetn,
    log=logging.getLogger("axi_stream"),
    rst_active_low=True,
    channel="s_axis_rx0",
)
cocotb.start_soon(mon.run())
# ... drive stimulus ...
assert mon.violation_count == 0, mon.report()
```

With opt-in packet framing (SDI-style SOF on `tuser[0]`):

```python
mon = AxiStreamMonitor(
    bus, dut.aclk, dut.aresetn,
    log=log,
    rst_active_low=True,
    sof_on_tuser_bit=0,   # enable EOP_WO_SOP / TID_MID_PKT checks
    channel="video_in",
)
```
