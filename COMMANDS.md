# Joro command codes

A field guide to the Razer Joro's HID control protocol, for anyone who wants
to extend [`joro_light.py`](joro_light.py) instead of installing Synapse.

Everything here is for the **wired** Joro (USB `1532:02CD`) on **USB interface
3**. Bluetooth (`1532:02CE`) does not expose this control interface, so all
of these commands require the USB-C cable and wired mode.

Legend: **✅ verified** on a real Joro · **🧪 adjacent**, taken from
OpenRazer's Joro support and checked against the source, but not exercised on
this particular unit yet · **⚠️** a quirk that will save you an hour.

---

## 1. The wire format

Razer's control protocol is a 90-byte report, sent as HID feature report
**ID 0**. On macOS with `hidapi`, the buffer you pass to
`send_feature_report()` is **91 bytes**: one report-ID byte followed by the
90-byte report.

```text
offset  size  meaning
0       1     status (0x00 when sending)
1       1     transaction ID (0x1F for most Joro commands)
2       2     remaining packets (0x0000, big endian)
4       1     protocol type (0x00)
5       1     data size = number of argument bytes
6       1     command class
7       1     command ID
8       80    arguments, zero padded
88      1     CRC = XOR of bytes 2..87 inclusive
89      1     reserved (0x00)
```

The response has the same 91-byte shape:

```text
byte 0   report ID (0x00)
byte 1   status: 0x02 success, 0x01 busy, 0x03 failure,
                 0x04 timeout, 0x05 not supported
byte 6   data size
byte 7   command class (echoes the request)
byte 8   command ID (echoes the request)
byte 9+  arguments
```

A response of all zeroes means “accepted, no reply” — some commands (Joro
custom frames, for example) never answer. Don't block forever waiting.

```python
def crc(report: bytearray) -> int:
    value = 0
    for byte in report[2:88]:
        value ^= byte
    return value
```

### Transaction IDs

| ID | Used for |
| --- | --- |
| `0x1F` | Most Joro commands: lighting, brightness, battery, firmware |
| `0xFF` | Game-mode and macro-LED state in OpenRazer's Joro path ⚠️ |
| `0x9F` | Wireless variants of other keyboards — **not** the Joro |

If a `0xFF` command returns “failure”, try `0x1F`; if a `0x1F` command fails,
try `0xFF`. Firmware revisions are inconsistent about this.

### Finding the interface

```python
import hid

devices = [
    d for d in hid.enumerate()
    if d["vendor_id"] == 0x1532
    and d["product_id"] == 0x02CD
    and d["interface_number"] == 3
]
```

The other interfaces are the boot keyboard, the NKRO keyboard, and the
consumer-control collection. Interface 3 is the one that talks Razer.

---

## 2. Command table

Commands are `class / command`, followed by argument bytes. `RR GG BB` is an
RGB triple; `EN` is 0/1; `SPD` is 1–4.

| Command | Class | Cmd | Arguments (hex) | Data size | Response / notes | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Firmware version | `00` | `81` | `00 00` | 2 | `args[0]` major, `args[1]` minor | ✅ |
| Static colour | `0F` | `02` | `01 05 01 00 00 01 RR GG BB` | 9 | status only | ✅ |
| Backlight off | `0F` | `02` | `01 05 00 00 00 00` | 6 | status only | ✅ |
| Battery level | `07` | `80` | `00 00` | 2 | `args[1]` = 0–255 | ✅ |
| Charging status | `07` | `84` | `00 00` | 2 | `args[1]` = 0/1 | ✅ |
| Brightness set | `0F` | `04` | `01 05 BB` | 3 | `BB` = 0–255 | 🧪 |
| Brightness get | `0F` | `84` | `01 05 00` | 3 | `args[2]` = 0–255 | 🧪 |
| Spectrum | `0F` | `02` | `01 05 03 00 00 00` | 6 | status only | 🧪 |
| Wave | `0F` | `02` | `01 05 04 DIR 28 00` | 6 | `DIR` 0/1, speed `28` | 🧪 |
| Reactive | `0F` | `02` | `01 05 05 00 SPD 01 RR GG BB` | 9 | `SPD` 1–4 | 🧪 |
| Breathing, one colour | `0F` | `02` | `01 05 02 01 00 01 RR GG BB` | 9 | status only | 🧪 |
| Breathing, two colours | `0F` | `02` | `01 05 02 02 00 02 R1 G1 B1 R2 G2 B2` | 12 | status only | 🧪 |
| Breathing, random | `0F` | `02` | `01 05 02 00 00 00` | 6 | status only | 🧪 |
| Game mode set | `03` | `00` | `01 08 EN` | 3 | transaction `0xFF` | 🧪 |
| Game mode get | `03` | `80` | `01 08 00` | 3 | `args[2]`, transaction `0xFF` | 🧪 |
| Macro mode set | `03` | `00` | `01 07 EN` | 3 | transaction `0xFF` | 🧪 |
| Macro mode get | `03` | `80` | `01 07 00` | 3 | `args[2]`, transaction `0xFF` | 🧪 |
| Custom-frame mode | `0F` | `02` | `00 00 08` + nine `00`s | `0x0C` | no response ⚠️ | 🧪 |
| Custom-frame row | `0F` | `03` | `00 00 ROW START STOP` + RGB | `0x47` | no response ⚠️ | 🧪 |

⚠️ The custom-frame rows are protocol reference only. The Joro is
single-zone, so they cannot drive individual keys — see the warning in §3.

### What the tested ones do

- **Static** writes the colour to the active onboard profile, so it survives
  unplugging and reconnecting over Bluetooth. `01` = store, `05` = backlight,
  `01` = static effect, `01` = one colour.
- **Off** is the same effect with effect ID `00`. Yes, it persists — this is
  the command that recreates the “why is my keyboard dark?” state.
- **Battery** returns a raw `0..255`; scale it with
  `round(raw / 255 * 100)`. A full Joro returns `255`.
- **Charging** is `0` or `1` in `args[1]`.

### Edge cases

- **Game mode** turns off the Windows/Super/Command key. OpenRazer uses
  transaction `0xFF` for it on the Joro; that is not a typo.
- **Macro mode** is the macro-LED/mode toggle, not a macro recorder.
- **Wave** direction is `0x00`/`0x01` on most keyboards; a few use
  `0x01`/`0x02`. `0x28` is speed, lower is faster.
- **Reactive** speed is clamped to `1..4`.

---

## 3. Custom per-key frames (a red herring on this keyboard)

> **Reality check:** the Joro is a **single-zone** keyboard. Razer's
> [tech specs](https://www.razer.com/gaming-keyboards/razer-joro?page=tech-specs)
> say “Single Zone Razer Chroma RGB,” and every key shares that one zone.
> The generic Razer per-key protocol and OpenRazer's `MATRIX_DIMS = [6, 16]`
> metadata make the Joro look like it supports this, but the hardware does
> not: these packets cannot produce independently coloured keys on this
> board. Keep the section as a reference for how you *would* do per-key
> lighting on a Razer keyboard that actually has per-key LEDs. On the Joro
> it is a dead end. (The easter egg in `joro_light.py` flashes Morse on the
> single zone instead, for exactly this reason.)

OpenRazer still describes the Joro as a 6-row × 16-column matrix, and the
generic per-key protocol looks like this:

### Step 1: switch to custom-frame mode

| Field | Value |
| --- | --- |
| Class / command | `0F / 02` |
| Arguments | `00 00 08 00 00 00 00 00 00 00 00 00` |
| Data size | `0x0C` (12) |
| Transaction | `0x1F` |
| Response | **none** ⚠️ |

Effect ID `08` is “custom frame”, with variable-storage `00` and LED `00`.

### Step 2: send each row

| Field | Value |
| --- | --- |
| Class / command | `0F / 03` |
| Arguments | `00 00 ROW START STOP` + 48 RGB bytes |
| Data size | `0x47` (71) |
| Transaction | `0x1F` |
| Response | **none** ⚠️ |

The meaningful arguments:

```text
args[0] 0x00
args[1] 0x00
args[2] row index (0..5)
args[3] start column (0..15)
args[4] stop column (0..15, inclusive)
args[5..] RGB triplets, 3 bytes per column, left to right
```

The packet is always 71 argument bytes, zero padded. For a full row that is
48 RGB bytes starting at `args[5]`.

On a genuinely per-key keyboard, send the custom-mode packet first, then rows
0 through 5, and do **not** wait for a reply on either. OpenRazer marks this
path as `want_response = false` for the Joro, BlackWidow V4, and BlackWidow V4
Pro.

```python
# Only meaningful on a Razer board with real per-key LEDs.
from joro_light import find_usb_device, make_report
import hid

dev = hid.device()
dev.open_path(find_usb_device()["path"])

def send_no_reply(cls, cmd, args):
    dev.send_feature_report(b"\x00" + make_report(cls, cmd, args))

# enter custom-frame mode
send_no_reply(0x0F, 0x02, bytes([0x00, 0x00, 0x08] + [0] * 9))

# six rows, 16 columns, all ice blue
row = bytes([0x78, 0xC8, 0xFF]) * 16
for row_index in range(6):
    args = bytes([0x00, 0x00, row_index, 0x00, 0x0F]) + row
    args = args.ljust(0x47, b"\x00")
    send_no_reply(0x0F, 0x03, args)

dev.close()
```

⚠️ The column order is the keyboard's matrix order, not necessarily the
physical left-to-right order. OpenRazer's `set_key_row` and the OpenRGB Razer
layouts are where to look if you want to map individual keys.

---

## 4. Supported but not documented here

The Joro class in OpenRazer also advertises starlight, ripple, macro-LED
effects, and per-key custom effects. Starlight and ripple are more `0F / 02`
effect payloads; macro-LED effects use the `03 / xx` LED commands; per-key is
covered above (and is a single-zone dead end on this board). Rather than
duplicate a large table that might drift, read the builders:

- [`driver/razerchromacommon.c`](https://github.com/openrazer/openrazer/blob/master/driver/razerchromacommon.c)
  — every `razer_chroma_extended_matrix_effect_*` function has a comment
  showing the bytes.
- [`driver/razerkbd_driver.c`](https://github.com/openrazer/openrazer/blob/master/driver/razerkbd_driver.c)
  — search for `USB_DEVICE_ID_RAZER_JORO` to see which builder and transaction
  ID the Joro uses for each feature.
- [`daemon/openrazer_daemon/hardware/keyboards.py`](https://github.com/openrazer/openrazer/blob/master/daemon/openrazer_daemon/hardware/keyboards.py)
  — the `RazerJoro` class lists every method the daemon exposes.
- [`driver/razercommon.h`](https://github.com/openrazer/openrazer/blob/master/driver/razercommon.h)
  — the `razer_report` struct, LED IDs, effect IDs, and status codes.

There is no official Razer protocol document. OpenRazer is the de facto one.

---

## 5. Adding a command to the script

`exchange()` already does the boring parts:

```python
from joro_light import find_usb_device, exchange
import hid

dev = hid.device()
dev.open_path(find_usb_device()["path"])
try:
    # spectrum cycling
    exchange(dev, 0x0F, 0x02, bytes([0x01, 0x05, 0x03, 0x00, 0x00, 0x00]))
finally:
    dev.close()
```

For a CLI flag, add it to `main()` and call `exchange()` with the arguments
above. For commands that do not reply, use `dev.send_feature_report()` with
`make_report()` and skip the read, as in the custom-frame example.

Two things that will bite you:

1. `data_size` is the number of argument bytes, not the total packet size.
2. The 91-byte buffer includes the report-ID byte; the 90-byte report does
   not. `hidapi` on macOS is picky about this.

---

## 6. Sources

- **OpenRazer** — the protocol reference and the Joro support that made this
  possible: <https://github.com/openrazer/openrazer>
- **OpenRazer device list** — Joro as `1532:02CD`:
  <https://github.com/openrazer/openrazer/blob/master/docs/devices.md>
- **OpenRGB** — the inspiration for “just set one colour”:
  <https://openrgb.org/> and
  <https://gitlab.com/CalcProgrammer1/OpenRGB>
- **hidapi** — the HID transport:
  <https://github.com/libusb/hidapi> and <https://pypi.org/project/hidapi/>
- **Razer Joro manual** — hotkeys, profiles, and the Chroma-effect table:
  <https://dl.razerzone.com/master-guides/RazerSynapse4/JORO-00000717-en.pdf>
- **Razer Joro reset procedure**:
  <https://mysupport.razer.com/app/answers/detail/a_id/20134>

If you add a command, send it to a real keyboard, check the status byte, and
write down what happened. That is the only way any of this stays true.
