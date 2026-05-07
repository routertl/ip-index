# `test_results/<namespace>/<entity>/last_run.json` — schema

Public surface for the **test_status_url** field on curated_repos.json entries.
One file per IP entity. Records the most recent contract-suite run.

Backstory: ticket RTL-P2.525 (routertl super-repo). Companion to the
`contract_url` field — `contract_url` answers *"what was expected?"* (points
at `contracts/<entity>_requirements.yml`); `last_run.json` answers
*"did the contract pass, when, and on what?"*

## Layout

```
routertl-ip-index/
└── test_results/
    └── <namespace>/
        └── <entity>/
            └── last_run.json
```

`<namespace>/<entity>` matches the curated_repos.json key pair
(e.g. `forencich/eth_mac_1g_fifo`, `fpganinja/taxi-ethernet`).

## Schema (version 1.0)

```json
{
  "schema_version": "1.0",
  "ip": "fpganinja/taxi-ethernet",
  "contract_url": "https://github.com/routertl/ip-index/blob/main/contracts/eth_mac_1g_requirements.yml",

  "run_at": "2026-05-05T18:14:23Z",
  "result": "pass",
  "duration_seconds": 47,

  "test_engine": "engine.simulation.run_simulation()",
  "test_runner": "rr sim run eth-validator -t test_eth_mac_1g_fifo",
  "simulator": "verilator-5.024",

  "commit_sha":     "<routertl HEAD at run time — full 40-char SHA>",
  "ip_commit_sha":  "<DUT HEAD at run time — full 40-char SHA>",
  "host":           "operator/machine_class",

  "tests": [
    {
      "name": "test_eth_mac_1g_fifo::test_loopback_64B",
      "status": "pass",
      "duration_seconds": 12.4,
      "message": ""
    }
  ],

  "adversarial": {
    "test_runner": "rr sim run eth-validator -t test_eth_validator_adversarial",
    "duration_seconds": 8,
    "tests": [
      {
        "name": "test_eth_validator_adversarial::test_fcs_corruption_detected",
        "status": "pass",
        "duration_seconds": 2.1,
        "message": ""
      }
    ]
  },

  "notes": "Fibich Table 15 baselines reproduced within ±2 cycles. See contract_url for expected values."
}
```

## Field reference

### Top-level

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | string | yes | `"1.0"` for this revision |
| `ip` | string | yes | `<namespace>/<entity>` matching curated_repos.json key |
| `contract_url` | string | yes | URL to the requirements.yml that defines pass criteria |
| `run_at` | string (ISO-8601 UTC) | yes | When the run executed |
| `result` | enum | yes | `pass` / `fail` / `error` — overall verdict (main suite, not adversarial) |
| `duration_seconds` | number | yes | Wall-clock for the main suite |
| `test_engine` | string | yes | Always `engine.simulation.run_simulation()` per ROUTERTL-001 |
| `test_runner` | string | yes | The `rr sim run ...` command users can re-execute |
| `simulator` | string | yes | `<simulator-name>-<version>` (e.g. `verilator-5.024`, `nvc-1.16.2`) |
| `commit_sha` | string | yes | routertl HEAD (40-char SHA) at run time |
| `ip_commit_sha` | string | yes | DUT repo HEAD (40-char SHA) at run time |
| `host` | string | yes | Sanitized: `<git-config-user>/<arch-os>` only. Never hostname or PII. |
| `tests` | array | yes | Main contract suite results — one entry per testcase |
| `adversarial` | object | no | Adversarial / attacker suite results (file-don't-fix evidence) |
| `notes` | string | no | Free-text caveats — what is and isn't covered |

### `tests[]` entry

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | yes | `<module>::<testcase>` |
| `status` | enum | yes | `pass` / `fail` / `error` / `skip` |
| `duration_seconds` | number | yes | Per-testcase wall-clock |
| `message` | string | no | Failure / skip reason — empty string if pass |

### `adversarial` object

Same shape as the top level, minus the IP identity / commit / host fields
(those are inherited from the parent run). Required keys:
`test_runner`, `duration_seconds`, `tests`.

A passing adversarial test means *the attacker confirmed the DUT correctly
rejects the bad input* (per the bug-finding-is-success rule). A failing
adversarial test means a witness defect — file as a T-tier ticket.

## Sanitization rules

- **Never write raw hostnames** to `host` — only operator + machine class
  (e.g. `dasjimaz/x86_64-linux`). The capture helper enforces this; if the
  operator is not configured, `host` is `"unknown/<arch-os>"`.
- **Never include user paths**, env vars, or absolute filesystem paths.
- **Never include private network info** (IPs, subnets, internal hostnames).

## Consumer expectations

The curated_repos.json `test_status_url` field points at the **raw** form:

```
https://github.com/routertl/ip-index/blob/main/test_results/<ns>/<entity>/last_run.json
```

(or `raw.githubusercontent.com/...` for direct JSON fetch). Any future
registry UI rendering tier badges should:

1. Fetch last_run.json
2. Verify `result == "pass"` AND `run_at` is within freshness window (per
   the health-tier rules — gold typically ≤ 90 days)
3. Verify `commit_sha` and `ip_commit_sha` round-trip to live repos
4. Surface `simulator`, `host`, `notes` for trust signals

## Generation

Use `routertl/tools/capture-test-status.py` after `rr sim run` to convert
`results/<module>/latest.json` (the internal result_collector artifact) into
a public-facing `last_run.json`. See the **health-tier-promotion** skill for
the full silver→gold ritual.

## Versioning

Bump `schema_version` on any breaking change (field rename, type change,
removed required field). Additive changes (new optional fields) keep the
same schema_version. Consumers must accept and ignore unknown fields.
