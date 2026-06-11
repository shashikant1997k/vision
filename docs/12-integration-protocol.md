# VIS Integration Protocol v1 — connecting third-party apps & line equipment

How external systems (MES/SCADA/track-and-trace, a PLC, a printer controller, or
any custom app) receive inspection results and command the vision system. Two
complementary channels, modelled on how the industry does it (Cognex "native
mode" ASCII/TCP commands with 1/0/negative acks; Keyence PLC-link; SEA Vision
line-master handshakes):

1. **TCP/IP messaging** — rich data (full results, counters, status, commands)
2. **24 V hard-wired I/O** — hard-real-time signals (trigger, reject, alarm)

Use both: wire decisions in copper (a reject must not depend on a TCP socket),
ship data over TCP.

---

## 1. TCP/IP protocol (JSON Lines, port 9410 by default)

Transport: plain TCP. Every message is one JSON object terminated by `\n`
(UTF-8, no embedded newlines). The server pushes asynchronously; clients may
send commands at any time. Multiple clients may connect; each gets every push.

### 1.1 Pushes (server → client)

```json
{"type":"hello","proto":"VIS/1","app":"vision-inspection","seq":0}
{"type":"result","seq":17,"ts":"2026-06-12T03:21:09.120Z","camera":"cam1",
 "frame":214,"product":"region1","passed":false,"lane":"lane2",
 "batch":"B-2026-001","fields":[
   {"id":"code1","type":"code_verify","passed":true,
    "value":"01095060001343521726123110LOT42<GS>21SN0001","grade":"A"},
   {"id":"text1","type":"ocv_text","passed":false,"value":"EXP 10/2026",
    "expected":"EXP.10/2026","confidence":0.81}]}
{"type":"alarm","seq":18,"ts":"...","code":"CONSECUTIVE_REJECTS","message":"..."}
{"type":"state","seq":19,"running":true,"batch":"B-2026-001"}
{"type":"heartbeat","seq":20,"ts":"..."}        // every 5 s (configurable)
```

`seq` increases monotonically per connection: a gap tells the client it missed
messages (e.g. after reconnect) and should resync counters via `get_counters`.

### 1.2 Commands (client → server) and replies

Every command gets exactly one reply with the client's `id` echoed back.
`{"ok":true,...}` or `{"ok":false,"error":"<CODE>","message":"..."}`.

| Command | Reply payload |
|---|---|
| `{"cmd":"hello","id":1}` | `{"ok":true,"id":1,"proto":"VIS/1","version":"..."}` |
| `{"cmd":"get_status","id":2}` | `{"ok":true,"id":2,"running":true,"batch":"B-1","recipe":"Tablets v3","alarm":null}` |
| `{"cmd":"get_counters","id":3}` | `{"ok":true,"id":3,"total":1290,"passed":1262,"failed":28,"yield":97.8}` |
| `{"cmd":"list_recipes","id":4}` | `{"ok":true,"id":4,"recipes":[{"id":7,"name":"Tablets 500mg","version":3}]}` |
| `{"cmd":"start","id":5}` / `{"cmd":"stop","id":6}` | `{"ok":true,...}` (subject to operator/permissions policy) |
| `{"cmd":"ping","id":7}` | `{"ok":true,"id":7,"pong":true}` |

Error codes: `BAD_JSON`, `UNKNOWN_CMD`, `NOT_ALLOWED`, `BUSY`, `INTERNAL`.

### 1.3 Client rules (for 3rd-party developers)
- Reconnect with exponential backoff (0.5 s → 10 s); on reconnect, `hello` then
  `get_status` + `get_counters` to resync.
- Treat `heartbeat` silence > 3 intervals as link-down.
- Never block on the socket from the control path that gates product release —
  that's what the 24 V interface is for.

---

## 2. 24 V hard-wired I/O (discrete signals)

Opto-isolated 24 V DC, PNP sourcing outputs / sinking inputs (per the line's
I/O block, e.g. the Modbus-TCP remote I/O we already drive). Channel mapping is
configured in the Communications screen.

### Inputs (line → vision)
| Signal | Behaviour |
|---|---|
| TRIGGER | Rising edge = capture/inspect (wired to the camera's Line0 / part sensor) |
| RESET_ALARM | Rising edge clears a latched ALARM output |

### Outputs (vision → line)
| Signal | Behaviour |
|---|---|
| READY | High when powered, configured and able to inspect (drops during recipe change) |
| RUNNING | High while inspection is running (batch or test) |
| PASS | Pulse (default 50 ms) per product that passed |
| REJECT | Pulse (default 100 ms) per failed product — typically also wired to the ejector chain as a backup to the encoder-tracked reject output |
| ALARM | Latched high on line-stop conditions (e.g. N consecutive rejects); cleared by RESET_ALARM or the HMI |
| HEARTBEAT | Toggles every 500 ms — a stuck level means the vision PC hung (PLC watchdog) |

### Timing rules
- PASS/REJECT pulses are per-product, minimum 20 ms gap; at >10 products/s use
  the TCP stream or the encoder-tracked reject queue for per-product actions.
- A PLC must treat READY=low OR HEARTBEAT stuck as "vision unavailable" and
  stop/divert product (fail-safe).

---

## 3. Which channel for what

| Need | Channel |
|---|---|
| Eject a bad product | Encoder-tracked reject output (io/encoder_reject) or REJECT pulse |
| Stop the line on fault | ALARM (hard-wired) |
| Log every result with values | TCP `result` push |
| Dashboards/MES counters | TCP `get_counters` poll or `result` stream |
| Line-master start/stop | TCP `start`/`stop` (policy-gated) + READY/RUNNING feedback |
| Watchdog | HEARTBEAT output + TCP `heartbeat` |

Sources: [Cognex Native Mode](https://support.cognex.com/docs/is_613/web/EN/ise/Content/Communications_Reference/NativeModeCommunications.htm),
[Cognex native commands](https://support.cognex.com/docs/is_590/web/EN/ise/Content/Communications_Reference/NativeMode_Commands.htm),
[PLC↔In-Sight EIP tech note](http://www.cognex.com/support/downloads/ns/1/11/93/PLC_Communications_03.pdf).
