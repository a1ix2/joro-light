# joro-light

> **Built by:** `lead`, a DeepSeek Harness coding agent, at the request of
> **the human** — who supplied the keyboard, the constraints, and the field
> testing. The human did not write this; the human commissioned it, tested it, 
> and rejected the bloatware. The robot wrote the Python and documentation.

A single-file, no-daemon way to set a **static backlight colour** on a Razer
Joro (RZ03-0236) and read its **battery level**, without Razer Synapse or
Chroma.

The Joro exposes Razer's HID control protocol on **USB interface 3**.  This
script sends one feature report, checks the reply, and exits.  Nothing stays
running, nothing phones home, no login item, no system extension.

Battery over USB uses that same protocol.  Battery over Bluetooth comes from
macOS's own Bluetooth stack, so it works without the cable.

Razer's own Linux driver (OpenRazer) already supports this keyboard as
`1532:02CD`; this is a tiny macOS-friendly port of the static-colour and
battery commands.  OpenRGB does not list the Joro yet.

## Requirements

- To **change the colour**: the keyboard plugged in with the **USB-C cable**,
  switched to **wired mode**.  Bluetooth does not expose the control interface.
- To **read the battery**: no cable needed; Bluetooth is fine.
- Python 3 with `hidapi` (already installed in `.venv` here).  Fresh setup:
  `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.

## Usage

```sh
./joro red                 # named colours
./joro amber
./joro '#00bfff'           # hex
./joro 255,170,90          # r,g,b
./joro --off               # backlight off
./joro --info              # device, firmware, battery
./joro --battery           # battery only
```

For the raw protocol, every packet layout, and notes on extending it, see
[COMMANDS.md](COMMANDS.md).

The colour is written to the keyboard's **active onboard profile**.  Verified:
after unplugging the USB cable and switching back to Bluetooth, the keyboard
comes back in the same colour.  You only need the cable when you want to
*change* the colour.

If the shell says `permission denied`, run `chmod +x joro` once.

If you run a **colour** command while the keyboard is on Bluetooth, it will say
`No Razer Joro found (looking for 1532:02cd, interface 3)` — plug in the
USB-C cable and switch to wired mode first.  `--info` and `--battery` work
over Bluetooth.

Named colours: `white`, `warmwhite`, `amber`, `orange`, `red`, `pink`,
`magenta`, `purple`, `violet`, `blue`, `ice`, `cyan`, `teal`, `green`,
`lime`, `yellow`.  Or use `#rrggbb`, `rrggbb`, or `r,g,b`.

## Battery

```sh
./joro --battery
# battery:  83% (Bluetooth)

./joro --info
# device:   Razer Joro (USB)
# path:     DevSrvsID:...
# firmware: 1.0
# battery:  100%, charging
```

- **USB** reads the keyboard's own battery counter and charging state
  (`0x07/0x80` and `0x07/0x84` in Razer's protocol).
- **Bluetooth** reads the standard Battery Level that macOS already collects
  for BLE peripherals.  It is the last level the keyboard reported, so it
  still shows up when the keyboard is asleep or disconnected — labelled
  `last reported`.

There is no extra permission prompt and no background process; the Bluetooth
value comes from `system_profiler -json SPBluetoothDataType`.

## Keyboard shortcuts (no software needed)

| Keys | Effect |
| --- | --- |
| `fn` + `ctrl` + `1` | Off |
| `fn` + `ctrl` + `2` | Static — **press again to cycle colours** |
| `fn` + `ctrl` + `3` | Breathing — press again to change colour |
| `fn` + `ctrl` + `4` | Spectrum cycling |
| `fn` + `F10` / `F11` | Keyboard brightness down / up |
| `fn` + right `alt` | Cycle onboard profiles |
| hold `fn` | Right `alt` lights up in the active profile's colour |

The built-in static colours are the "approximate control" from the box.  The
script gives you the exact colour instead.

## Factory reset (if the shortcuts stop making sense)

1. Turn the keyboard **off**.
2. Hold **Left Ctrl + Esc**.
3. Turn the keyboard **on** while still holding both keys.
4. Keep holding for about 5 seconds, then release.

This is Razer's documented Joro reset procedure:
<https://mysupport.razer.com/app/answers/detail/a_id/20134>

## Credits, sources, and blame

- **OpenRazer** — the protocol documentation and the Joro support that made
  this possible. The per-device switches in `razerkbd_driver.c` and the packet
  builders in `razerchromacommon.c` are the reference for everything in
  [COMMANDS.md](COMMANDS.md). <https://github.com/openrazer/openrazer>
- **OpenRGB** — for the “why do I need 1.2 GB to set one LED” energy, and for
  proving cross-platform RGB control can be a normal, focused tool.
  <https://openrgb.org/>
- **hidapi** — the small, sane HID layer this script actually talks through.
  <https://github.com/libusb/hidapi> · <https://pypi.org/project/hidapi/>
- **Razer's Joro manual** — the hotkey table, onboard profiles, and the
  “press again to change colour” footnote that started all this.
  <https://dl.razerzone.com/master-guides/RazerSynapse4/JORO-00000717-en.pdf>
- **Razer support** — the factory-reset procedure.
  <https://mysupport.razer.com/app/answers/detail/a_id/20134>
- **macOS `system_profiler`** — the Bluetooth battery reading, because macOS
  already collects the standard BLE Battery Level.
- **the human** — for the keyboard, the patience, and the field testing. 
  The human did not write this; the human made it necessary.

Written by `lead` (DeepSeek Harness), 2026-11-23. If you extend this, add your
name and keep the links.

## Removing it

Delete this folder.  There is nothing else to uninstall.
