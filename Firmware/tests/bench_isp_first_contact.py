"""One read-only ATmega64A signature attempt and post-exit ISP trace capture.

Requires the temporary diagnostic image, whose merge ID must be supplied.
Never run until XM64 signal leads are removed, MOSI/MISO are separate and
the PE0/PE1/SCK/AUX0 paths have been physically confirmed. Entry itself
drives the CS rescue clock. This runner cannot verify physical wiring.
"""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import time

import serial

from bench_cdc_latency import Usb, drain, open_serial, receive
from bench_isp_trace import decode_terminal

DEV = Path(__file__).resolve().parents[3]
LOGS = DEV / "Bus_Pirate/.bpv4-work/mkii-build"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--bitclock", type=float)
    parser.add_argument("--wiring-confirmed", action="store_true",
                        help="Human confirmed XM64 off, data separate, PE0/PE1/SCK/AUX0 correct")
    args = parser.parse_args()
    if not args.wiring_confirmed:
        parser.error("STOP: physical confirmation required BEFORE any device access")
    if not args.name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in args.name):
        parser.error("Name must contain only letters, digits, underscores or hyphens")
    if args.bitclock is not None and not 8 <= args.bitclock <= 20000:
        parser.error("Bitclock must be a period in microseconds, >=8 and <=20000")
    prefix = LOGS / ("mkii_atmega_" + args.name)
    files = [prefix.with_suffix(suffix) for suffix in (".log", ".json", ".terminal.bin")]
    if any(path.exists() for path in files):
        parser.error("Refusing to overwrite evidence")
    if Usb().present() != {"cdc"}:
        raise RuntimeError("STOP: expected FB00/COM6 before fresh entry")
    with files[0].open("x", encoding="utf-8") as logfile:
        def log(text):
            line = datetime.datetime.now().isoformat(timespec="milliseconds") + " " + text
            print(line, flush=True)
            logfile.write(line + "\n")
            logfile.flush()

        with open_serial() as port:
            log("Initial pending: " + repr(drain(port)))
            port.write(b"\0" * 24)
            reply = receive(port, 5) + drain(port, quiet=.05)
            log("BBIO probe: " + repr(reply))
            if not reply or reply.replace(b"BBIO1", b""):
                raise RuntimeError("STOP: BBIO identity mismatch; 08 not sent")
            # Confirm the image before any mkII pin-driving.
            port.write(b"\x0f")
            banner = drain(port, quiet=.2, maximum=3)
            log("Pre-entry banner: " + repr(banner))
            if args.expected_version.encode("ascii") not in banner or b"HiZ>" not in banner:
                raise RuntimeError("STOP: diagnostic image not verified; 08 not sent")
            port.write(b"\0" * 24)
            reply = receive(port, 5) + drain(port, quiet=.05)
            if not reply or reply.replace(b"BBIO1", b""):
                raise RuntimeError("STOP: BBIO re-entry failed; 08 not sent")
            port.write(b"\x08")
            log("Strict binary 08 sent; physical wiring confirmed by caller")
        usb = Usb()
        deadline = time.monotonic() + 3
        while "mkii" not in usb.present():
            if time.monotonic() >= deadline:
                raise RuntimeError("STOP: mkII did not enumerate; no retry/reset")
            time.sleep(.025)
        command = [str(DEV / "XM64/tools/avrdude-8.3/avrdude.exe"),
                   "-c", "avrispmkII", "-P", "usb", "-p", "m64a", "-n",
                   "-U", "signature:r:-:h", "-vvvv"]
        if args.bitclock is not None:
            command += ["-B", str(args.bitclock)]
        log("Command: " + repr(command))
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=40)
            log("AVRDUDE stdout:\n" + result.stdout)
            log("AVRDUDE stderr:\n" + result.stderr)
            log("AVRDUDE exit: " + str(result.returncode))
        except subprocess.TimeoutExpired as error:
            log("STOP: avrdude timeout; partial stdout/stderr: " + repr((error.stdout, error.stderr)))
            result = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if usb.present() == {"cdc"}:
                try:
                    port = open_serial()
                except serial.SerialException:
                    time.sleep(.03)
                    continue
                with port:
                    pending = drain(port, quiet=.1)
                    log("CDC pending: " + repr(pending))
                    port.write(b"\0")
                    reply = receive(port, 5)
                    if reply != b"BBIO1" or drain(port):
                        raise RuntimeError("STOP: unexpected return state; no further writes")
                    port.write(b"\x0f")
                    terminal = drain(port, quiet=.2, maximum=4)
                    files[2].write_bytes(terminal)
                    if b"HiZ>" not in terminal or args.expected_version.encode("ascii") not in terminal:
                        raise RuntimeError("STOP: terminal/banner not confirmed")
                    traces = decode_terminal(terminal)
                    log("Post-exit trace: " + json.dumps(traces))
                    data = {"command": command, "avrdude_exit": None if result is None else result.returncode,
                            "traces": traces, "final_state": "HiZ/COM6, handle closed"}
                    files[1].write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                    return
            time.sleep(.03)
        raise RuntimeError("STOP: CDC recovery not confirmed in 30s; human recovery required, no retry")


if __name__ == "__main__":
    main()
