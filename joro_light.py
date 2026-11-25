#!/usr/bin/env python3
"""
joro_light.py -- set a static backlight colour on a Razer Joro (RZ03-0236)
without Razer Synapse / Chroma, and read its battery level.

The Joro speaks Razer's control protocol on USB interface 3.  This script
talks to it directly through a HID feature report.  No drivers, no daemon,
no account, no background processes.

Battery over USB uses the same protocol.  Battery over Bluetooth is read
from macOS's own Bluetooth stack (the standard Battery Level that macOS
already shows for BLE peripherals), so it works with or without the cable.

Tested on macOS 13 with the Joro (USB PID 0x02CD, Bluetooth PID 0x02CE).
Requires hidapi:

    python3 -m pip install hidapi

Changing the colour requires the USB-C cable and wired mode; Bluetooth does
not expose the lighting control interface.

Examples:
    ./joro ff8800
    ./joro '#00bfff'
    ./joro 255,170,90
    ./joro --off
    ./joro --info
    ./joro --battery
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    import hid
except ImportError:
    sys.exit(
        "hidapi is not installed for this Python.\n"
        "Run:  python3 -m pip install hidapi"
    )

VID = 0x1532
PID_WIRED = 0x02CD
PID_BLUETOOTH = 0x02CE
BT_VID = 0x068E
CONTROL_INTERFACE = 3

# Razer protocol
CMD_SET_EFFECT = (0x0F, 0x02)
CMD_GET_BATTERY = (0x07, 0x80)
CMD_GET_CHARGING = (0x07, 0x84)
LED_BACKLIGHT = 0x05
VARSTORE = 0x01
EFFECT_OFF = 0x00
EFFECT_STATIC = 0x01
TRANSACTION_ID = 0x1F

STATUS = {
    0x01: "busy",
    0x02: "success",
    0x03: "failure",
    0x04: "timeout",
    0x05: "not supported",
}

NAMED_COLOURS = {
    "white": (255, 255, 255),
    "warmwhite": (255, 214, 170),
    "amber": (255, 170, 90),
    "orange": (255, 110, 20),
    "red": (255, 0, 0),
    "pink": (255, 60, 140),
    "magenta": (255, 0, 255),
    "purple": (150, 60, 255),
    "violet": (120, 80, 255),
    "blue": (0, 80, 255),
    "ice": (120, 200, 255),
    "cyan": (0, 220, 255),
    "teal": (0, 200, 160),
    "green": (0, 220, 80),
    "lime": (170, 255, 0),
    "yellow": (255, 220, 0),
}

DEEPSEEK_BLUE = (0x4D, 0x6B, 0xFE)
DEFAULT_COLOUR = NAMED_COLOURS["ice"]
STATE_FILE = Path(__file__).resolve().with_name(".last-colour")

MORSE = {
    "D": "-..",
    "E": ".",
    "P": ".--.",
    "S": "...",
    "K": "-.-",
}


def crc(report: bytearray) -> int:
    """Razer's checksum: XOR of bytes 2..87."""
    value = 0
    for byte in report[2:88]:
        value ^= byte
    return value


def make_report(command_class: int, command_id: int, args: bytes) -> bytes:
    if len(args) > 80:
        raise ValueError(f"report arguments too long: {len(args)} (max 80)")

    report = bytearray(90)
    report[0] = 0x00  # status
    report[1] = TRANSACTION_ID
    report[2:4] = (0).to_bytes(2, "big")  # remaining packets
    report[4] = 0x00  # protocol type
    report[5] = len(args)
    report[6] = command_class
    report[7] = command_id
    report[8 : 8 + len(args)] = args
    report[88] = crc(report)
    return bytes(report)


def find_usb_device() -> dict | None:
    devices = [
        d
        for d in hid.enumerate()
        if d.get("vendor_id") == VID
        and d.get("product_id") == PID_WIRED
        and d.get("interface_number") == CONTROL_INTERFACE
    ]
    return devices[0] if devices else None


def require_usb_device() -> dict:
    device = find_usb_device()
    if device:
        return device

    wireless = [
        d
        for d in hid.enumerate()
        if d.get("vendor_id") == VID and d.get("product_id") == PID_BLUETOOTH
    ]
    if wireless:
        raise SystemExit(
            "Found the Joro over Bluetooth.  The lighting control interface only\n"
            "exists over USB.  Plug in the USB-C cable and switch the keyboard\n"
            "to wired mode, then run this again."
        )

    raise SystemExit(
        "No Razer Joro found (looking for 1532:02cd, interface 3).\n"
        "Check that the USB-C cable is connected and the keyboard is in wired mode."
    )


def open_usb_device():
    device_info = require_usb_device()
    dev = hid.device()
    try:
        dev.open_path(device_info["path"])
    except OSError as exc:
        raise SystemExit(f"could not open the Joro's control interface: {exc}")
    return dev


def exchange(dev, command_class: int, command_id: int, args: bytes) -> bytearray:
    dev.send_feature_report(b"\x00" + make_report(command_class, command_id, args))
    time.sleep(0.08)

    response = bytearray(dev.get_feature_report(0, 91))
    if len(response) < 9:
        raise RuntimeError(f"short response ({len(response)} bytes)")

    # The first byte is the report ID; the actual status is in byte 1.
    status = response[1]
    if status == 0x00 and not any(response[2:]):
        return response  # accepted, no reply
    if status != 0x02:
        name = STATUS.get(status, f"unknown 0x{status:02x}")
        raise RuntimeError(
            f"keyboard returned {name} (status 0x{status:02x}, "
            f"data {bytes(response[:16]).hex()})"
        )
    return response


def apply_static(dev, red: int, green: int, blue: int) -> None:
    for component in (red, green, blue):
        if not isinstance(component, int) or not 0 <= component <= 255:
            raise ValueError(f"colour component out of range: {component!r}")

    args = bytes(
        [
            VARSTORE,
            LED_BACKLIGHT,
            EFFECT_STATIC,
            0x00,
            0x00,
            0x01,
            red,
            green,
            blue,
        ]
    )
    exchange(dev, *CMD_SET_EFFECT, args)


def set_static(dev, red: int, green: int, blue: int) -> None:
    apply_static(dev, red, green, blue)
    save_state(f"#{red:02x}{green:02x}{blue:02x}")


def apply_off(dev) -> None:
    args = bytes([VARSTORE, LED_BACKLIGHT, EFFECT_OFF, 0x00, 0x00, 0x00])
    exchange(dev, *CMD_SET_EFFECT, args)


def set_off(dev) -> None:
    apply_off(dev)
    save_state("off")


def parse_colour(text: str) -> tuple[int, int, int]:
    value = text.strip().lower()

    if value in NAMED_COLOURS:
        return NAMED_COLOURS[value]

    match = re.fullmatch(r"#?([0-9a-f]{3})", value)
    if match:
        r, g, b = match.group(1)
        return (int(r * 2, 16), int(g * 2, 16), int(b * 2, 16))

    match = re.fullmatch(r"#?([0-9a-f]{6})", value)
    if match:
        num = int(match.group(1), 16)
        return (num >> 16 & 0xFF, num >> 8 & 0xFF, num & 0xFF)

    match = re.fullmatch(r"(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})", value)
    if match:
        rgb = tuple(int(part) for part in match.groups())
        if all(0 <= part <= 255 for part in rgb):
            return rgb  # type: ignore[return-value]

    raise argparse.ArgumentTypeError(
        f"invalid colour {text!r}; use #rrggbb, rrggbb, r,g,b, or a name like 'amber'"
    )


def save_state(value: str) -> None:
    """Remember the last colour/off state for the easter egg to restore.

    Only the exact format this script writes is accepted, so a bug or a
    corrupted caller cannot smuggle arbitrary text into the state file.
    """
    if not isinstance(value, str):
        return
    if value != "off" and re.fullmatch(r"#[0-9a-f]{6}", value) is None:
        return

    try:
        STATE_FILE.write_text(value + "\n", encoding="utf-8")
    except OSError:
        pass


def load_state() -> tuple[str, tuple[int, int, int] | None] | None:
    """Read the last state, accepting only "off" or #rrggbb.

    The read is capped at 64 bytes and any malformed content falls back to
    None, which the easter egg treats as ice blue.  A crafted state file can
    therefore never produce an out-of-range RGB byte.
    """
    try:
        with STATE_FILE.open("r", encoding="utf-8") as handle:
            value = handle.read(64).strip().lower()
    except (OSError, UnicodeDecodeError):
        return None

    if value == "off":
        return ("off", None)

    match = re.fullmatch(r"#?([0-9a-f]{6})", value)
    if match is None:
        return None

    number = int(match.group(1), 16)
    return ("static", (number >> 16 & 0xFF, number >> 8 & 0xFF, number & 0xFF))


def firmware(dev) -> str:
    response = exchange(dev, 0x00, 0x81, b"\x00\x00")
    major, minor = response[9], response[10]
    return f"{major}.{minor}"


def usb_battery(dev) -> tuple[int, bool | None]:
    """Return (percent, charging) straight from the keyboard over USB."""
    response = exchange(dev, *CMD_GET_BATTERY, b"\x00\x00")
    raw = response[10]  # arguments[1]; OpenRazer scales 0-255 -> 0-100

    try:
        charging_response = exchange(dev, *CMD_GET_CHARGING, b"\x00\x00")
        charging: bool | None = bool(charging_response[10])
    except RuntimeError:
        charging = None

    return round(raw / 255 * 100), charging


def bluetooth_battery() -> tuple[int, bool] | None:
    """Read the Battery Level macOS already collected for the BLE Joro.

    Returns (percent, currently_connected), or None if macOS has no reading.
    The value survives a disconnect: it is the last level the keyboard
    reported, which is why it still shows up while the keyboard is asleep.
    """
    try:
        completed = subprocess.run(
            ["system_profiler", "-json", "SPBluetoothDataType"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        data = json.loads(completed.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None

    try:
        section = (data.get("SPBluetoothDataType") or [{}])[0]
    except (AttributeError, IndexError):
        return None

    for group, connected in (("device_connected", True), ("device_not_connected", False)):
        for entry in section.get(group) or []:
            for name, info in entry.items():
                is_joro = (
                    str(info.get("device_productID", "")).lower() == "0x02ce"
                    or name == "Joro"
                )
                if not is_joro:
                    continue
                level = info.get("device_batteryLevelMain")
                if not level:
                    continue
                match = re.search(r"\d+", str(level))
                if match:
                    return int(match.group()), connected
    return None


def print_info(battery_only: bool = False) -> None:
    device_info = find_usb_device()
    if device_info:
        dev = hid.device()
        try:
            dev.open_path(device_info["path"])
        except OSError as exc:
            raise SystemExit(f"could not open the Joro's control interface: {exc}")
        try:
            if not battery_only:
                print(f"device:   {device_info.get('product_string', 'Razer Joro')} (USB)")
                print(f"path:     {device_info['path'].decode(errors='replace')}")
                print(f"firmware: {firmware(dev)}")

            percent, charging = usb_battery(dev)
            suffix = ""
            if charging is True:
                suffix = ", charging"
            elif charging is False:
                suffix = ", not charging"
            print(f"battery:  {percent}%{suffix}")
        finally:
            dev.close()
        return

    bt = bluetooth_battery()
    if not battery_only:
        print("device:   Razer Joro (Bluetooth)")
        print("firmware: unavailable over Bluetooth")
    if bt is None:
        print("battery:  unavailable (macOS has no reading for this keyboard yet)")
        return

    percent, connected = bt
    if connected:
        print(f"battery:  {percent}% (Bluetooth)")
    else:
        print(f"battery:  {percent}% (Bluetooth, last reported)")


def deepthink(dev) -> None:
    """Easter egg: flash DEEPSEEK in Morse, then restore the previous state.

    Hidden from --help on purpose. The Joro is a single-zone keyboard, so a
    per-key logo is physically impossible; this is the next best thing.
    """
    state = load_state() or ("static", DEFAULT_COLOUR)
    dot = 0.09
    gap = dot
    dash = dot * 3
    letter_gap = dot * 3

    def push(red: int, green: int, blue: int) -> None:
        args = bytes(
            [
                VARSTORE,
                LED_BACKLIGHT,
                EFFECT_STATIC,
                0x00,
                0x00,
                0x01,
                red,
                green,
                blue,
            ]
        )
        dev.send_feature_report(b"\x00" + make_report(*CMD_SET_EFFECT, args))

    def dark() -> None:
        args = bytes([VARSTORE, LED_BACKLIGHT, EFFECT_OFF, 0x00, 0x00, 0x00])
        dev.send_feature_report(b"\x00" + make_report(*CMD_SET_EFFECT, args))

    try:
        for letter in "DEEPSEEK":
            for symbol in MORSE[letter]:
                push(*DEEPSEEK_BLUE)
                time.sleep(dash if symbol == "-" else dot)
                dark()
                time.sleep(gap)
            time.sleep(letter_gap)

        push(*DEEPSEEK_BLUE)
        time.sleep(0.5)
    finally:
        try:
            if state[0] == "off":
                apply_off(dev)
            else:
                apply_static(dev, *state[1])
        except OSError:
            pass

    print("deepthink: -.. . . .--. ... . . . -.-")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set a static backlight colour on a Razer Joro, or read its battery.",
        epilog="The colour is stored in the keyboard's active onboard profile.",
    )
    parser.add_argument(
        "colour",
        nargs="?",
        type=parse_colour,
        help="colour as #rrggbb, rrggbb, r,g,b, or a name (e.g. amber)",
    )
    parser.add_argument("--off", action="store_true", help="turn the backlight off")
    parser.add_argument(
        "--info", action="store_true", help="show device, firmware, and battery"
    )
    parser.add_argument(
        "--battery", action="store_true", help="show battery level only"
    )
    # Hidden on purpose: the easter egg is for people who read the code.
    parser.add_argument("--deepthink", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.info or args.battery:
        print_info(battery_only=args.battery)
        return 0

    if args.deepthink:
        dev = open_usb_device()
        try:
            deepthink(dev)
        finally:
            dev.close()
        return 0

    if not args.off and args.colour is None:
        parser.print_help()
        return 1

    dev = open_usb_device()

    try:
        if args.off:
            set_off(dev)
            print("backlight off")

        if args.colour is not None:
            red, green, blue = args.colour
            set_static(dev, red, green, blue)
            print(f"static colour set to #{red:02x}{green:02x}{blue:02x}")
    finally:
        dev.close()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        raise SystemExit(f"error: {exc}")
