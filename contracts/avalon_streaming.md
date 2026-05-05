# Avalon-Streaming (Avalon-ST) — Contract Specification

**Monitor:** `tb.monitors.avalon_streaming_monitor.AvalonStreamMonitor`
**Bus:**     `tb.drivers.avalon_streaming.AvalonStreamBus`
**Source spec:** Intel Avalon Interface Specifications, §5 "Avalon Streaming
                 Interface Specification" (public).
**Scope:** any Avalon-ST source or sink — valid/ready handshake with
           optional packet framing (sop/eop), byte-level empty, multi-channel,
           and error signalling.

---

## 1. Ports observed

Resolved via `AvalonStreamBus.from_prefix(dut, prefix)`:

| Signal | Required | Purpose |
|---|:---:|---|
| `clk` | ✓ (monitor constructor) | Sampling clock |
| `{prefix}_valid` | ✓ | Source asserts when data is valid |
| `{prefix}_ready` | ✓ | Sink asserts when ready to accept |
| `{prefix}_data` | ✓ | Payload |
| `{prefix}_startofpacket` or `_sop` |   | First beat of a packet |
| `{prefix}_endofpacket` or `_eop` |   | Last beat of a packet |
| `{prefix}_empty` |   | Number of invalid symbols on the eop beat |
| `{prefix}_channel` |   | Multi-channel stream selector |
| `{prefix}_error` or `_err` |   | Error flag (typically on eop) |

Auto-discovery tries both the long Intel-canonical names and the common
short-form aliases (`sop`/`eop`/`err`). Optional signals that aren't on
the bus are set to `None` and their associated checks are skipped.

---

## 2. Parameters

| Param | Default | Effect |
|---|---|---|
| `rst_active_low` | `False` | Reset polarity. |
| `ready_latency` | `0` | Avalon-ST ready latency (§5.3.3). `0` is the common case. `>0` not yet fully modelled — current monitor assumes source only asserts valid when it's prepared to hold until ready=1. |

---

## 3. Clauses enforced

### `AST_DATA_HOLD`
**Rule:** while `valid=1 & ready=0`, the source MUST hold every payload
field stable — `data`, `startofpacket`, `endofpacket`, `empty`, `channel`,
`error` — until either the sink asserts `ready=1` or the source drops
`valid`. Changing the payload mid-stall is a protocol violation.

**Why it matters:** sinks sample on the ready+valid edge; if the source
"changed its mind" while waiting, the sink gets whatever was driven on
that specific edge — usually the wrong beat. Classic "lost packet header"
bug.

### `AST_RST`
**Rule:** during reset, `valid` MUST be `0`.

**Why it matters:** asserting valid while in reset is undefined. Downstream
monitors may count a spurious beat; CDC synchronisers may capture stale
data past reset release.

### `AST_EOP_WO_SOP` *(packet mode only)*
**Rule:** `endofpacket=1` accompanied by `valid=1 & ready=1` (a beat
transferred) MUST have a matching earlier `startofpacket` since the last
eop. No eop without sop.

**Why it matters:** packet-framing corruption — the sink's packet parser
gets confused about where packets begin and end.

### `AST_SOP_MID_PKT` *(packet mode only)*
**Rule:** `startofpacket=1` MUST NOT be asserted (on a transferred beat)
while a packet is already in flight (sop was seen without a subsequent
eop).

**Why it matters:** same packet-framing bug class from the other side —
two sops with no eop between means one packet was truncated and another
started.

### `AST_EMPTY_WO_EOP` *(empty + packet mode only)*
**Rule:** `empty` MUST be `0` on any transferred beat where `endofpacket=0`.
The `empty` field is only meaningful on the final beat of a packet.

**Why it matters:** non-zero empty on a mid-packet beat indicates stale
signalling — the sink may interpret it as valid-byte metadata and
truncate data bytes that were actually valid.

### `AST_CHANNEL_MID_PKT` *(multi-channel only)*
**Rule:** `channel` MUST remain constant between sop and eop. A packet
belongs to exactly one channel.

**Why it matters:** downstream demuxes route packets by channel; flipping
mid-packet corrupts the logical streams for multiple consumers
simultaneously.

---

## 4. Clauses NOT covered (honest scope)

- **Throughput / back-pressure fairness** — this is a *protocol* monitor,
  not a performance gate. Use a scoreboard for bandwidth assertions.
- **Data-content correctness** — the monitor verifies framing/stability,
  not payload semantics. Per-test assertions carry that load.
- **`ready_latency > 0`** — current implementation assumes latency 0.
  A future upgrade can add a shift register on `ready` to support
  higher-latency sinks per §5.3.3.

---

## 5. Violation record format

Emits `ProtocolViolation` records identical to peer monitors:

```python
ProtocolViolation(
    check_id="AST_DATA_HOLD",
    channel="stream",
    timestamp_ns=1240,
    message="data changed during valid=1 & ready=0 (was 0xCAFEBABE, now 0xDEADBEEF)"
)
```

Consumed by `TbEnv.check_monitors()` at end-of-test.

---

## 6. Composition example

```python
from tb.env import TbEnv

tb = TbEnv(dut, clk="clk", rst="rst_n", period_ns=10)
await tb.start_clock()

tb.attach_monitors(
    avalon_st={
        "src": {"rst_active_low": True},          # source-side stream
        "snk": {"rst_active_low": True},          # sink-side stream
    },
)

await tb.reset(active_low=True)
# ... run stimulus ...

tb.check_monitors()   # one-line contract gate across all attached peers
```

Or manually:

```python
from tb.drivers.avalon_streaming import AvalonStreamBus
from tb.monitors.avalon_streaming_monitor import AvalonStreamMonitor

bus = AvalonStreamBus.from_prefix(dut, "src")
mon = AvalonStreamMonitor(bus, dut.clk, dut.rst_n,
                          log=log, rst_active_low=True)
cocotb.start_soon(mon.run())
```
