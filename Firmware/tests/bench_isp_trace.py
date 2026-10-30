"""Decode ISPD1 terminal records from the temporary ISP diagnostic image.

This module never opens a serial/USB handle or drives target pins. The dump
is printed by terminal 'i' after mkII returns to CDC, not in the ISP reply.
"""
import argparse
import json
from pathlib import Path
import re


PARAMETERS = ("timeout_ms", "stab_delay_ms", "cmdexe_delay_ms", "synch_loops",
              "byte_delay_ms", "poll_value", "poll_index")
EVENTS = {1: "before_spi_enable", 2: "after_spi_enable",
          3: "reset_assert_immediate", 4: "reset_release_immediate",
          5: "reset_assert_settled", 6: "reset_release_settled", 7: "enable_rx"}


def decode(raw):
    if len(raw) < 35 or raw[0] != 1:
        raise ValueError("Unknown/truncated ISP trace header")
    checksum = 0
    for value in raw:
        checksum ^= value
    if checksum:
        raise ValueError("ISP trace checksum mismatch")
    count = int.from_bytes(raw[29:31], "big")
    if count > 192 or len(raw) != 35 + 6 * count:
        raise ValueError("ISP trace event count/length mismatch")
    params = dict(zip(PARAMETERS, raw[15:22]))
    params["enable_tx_hex"] = raw[22:26].hex(" ")
    records = []
    for offset in range(34, len(raw)-1, 6):
        kind, flags, *payload = raw[offset:offset+6]
        event = {"event": EVENTS.get(kind, "unknown_%d" % kind),
                 "aux0_level": flags & 1,
                 "aux0_direction": "input" if flags & 2 else "output",
                 "aux0_latch": int(bool(flags & 4)),
                 "miso_level": int(bool(flags & 8)),
                 "sck_level": int(bool(flags & 16)),
                 "mosi_level": int(bool(flags & 32)),
                 "miso_direction": "input" if flags & 64 else "output",
                 "sck_direction": "input" if flags & 128 else "output"}
        if kind == 7:
            event["rx_hex"] = bytes(payload).hex(" ")
            index = params["poll_index"]
            event["poll_match"] = (payload[index-1] == params["poll_value"]
                                   if 1 <= index <= 4 else None)
        records.append(event)
    return {"format": "ISPD1", "raw_parameters_hex": raw[4:15].hex(" "),
            "parsed_parameters": params, "parameter_order_matches": raw[4:15] == raw[15:26],
            "sck_duration_index": raw[1], "reset_polarity": raw[2],
            "vtarget_volts": raw[3]/10, "status_hex": "%02x" % raw[26],
            "completed_attempts": raw[27], "truncated": bool(raw[28]),
            "spi1con1_hex": raw[31:33].hex(), "hardware_spi": bool(raw[33]),
            "events": records,
            "caveat": "Levels are BP-end digital samples, not target-pin measurements. "
                      "A high input cannot prove a connected wire or pull-up; "
                      "00/ff receive bytes cannot by themselves prove wiring rather than PHY failure."}


def decode_terminal(data):
    matches = re.findall(rb"ISPD1 ([0-9a-fA-F]+)\r?\n", data)
    if not matches:
        raise ValueError("No complete ISPD1 record in terminal output")
    return [decode(bytes.fromhex(match.decode("ascii"))) for match in matches]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("terminal_log", type=Path)
    args = parser.parse_args()
    print(json.dumps(decode_terminal(args.terminal_log.read_bytes()), indent=2))


if __name__ == "__main__":
    main()
