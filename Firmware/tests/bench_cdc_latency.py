"""Windows-only, non-destructive mkII -> CDC latency measurements.

Only programmer SIGN_ON and an optional read-only XM64 signature command
are used. Serial opens do not purge receive queues. No target writes,
device restarts, or physical resets are performed. Stop on a failed probe.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import datetime
import json
from pathlib import Path
import statistics
import subprocess
import threading
import time
import uuid
import winreg

import serial
from serial import win32
from serial.tools import list_ports

DEV = Path(__file__).resolve().parents[3]
LOGS = DEV / "Bus_Pirate/.bpv4-work/mkii-build"


class Guid(c.Structure):
    _fields_ = [("a", w.DWORD), ("b", w.WORD), ("c", w.WORD), ("d", c.c_ubyte * 8)]


class Interface(c.Structure):
    _fields_ = [("size", w.DWORD), ("guid", Guid), ("flags", w.DWORD), ("reserved", c.c_void_p)]


class Usb:
    def __init__(self):
        self.api = c.WinDLL("setupapi", use_last_error=True)
        self.guid = Guid.from_buffer_copy(uuid.UUID("a5dcbf10-6530-11d2-901f-00c04fb951ed").bytes_le)
        self.api.SetupDiGetClassDevsW.argtypes = [c.POINTER(Guid), w.LPCWSTR, w.HWND, w.DWORD]
        self.api.SetupDiGetClassDevsW.restype = w.HANDLE
        self.api.SetupDiEnumDeviceInterfaces.argtypes = [w.HANDLE, c.c_void_p, c.POINTER(Guid), w.DWORD, c.POINTER(Interface)]
        self.api.SetupDiEnumDeviceInterfaces.restype = w.BOOL
        self.api.SetupDiGetDeviceInterfaceDetailW.argtypes = [w.HANDLE, c.POINTER(Interface), c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.c_void_p]
        self.api.SetupDiGetDeviceInterfaceDetailW.restype = w.BOOL
        self.api.SetupDiDestroyDeviceInfoList.argtypes = [w.HANDLE]

    def present(self):
        info = self.api.SetupDiGetClassDevsW(c.byref(self.guid), None, None, 0x12)
        if info == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        result = set()
        try:
            index = 0
            while True:
                item = Interface()
                item.size = c.sizeof(item)
                if not self.api.SetupDiEnumDeviceInterfaces(info, None, c.byref(self.guid), index, c.byref(item)):
                    if c.get_last_error() == 259:
                        break
                    raise c.WinError(c.get_last_error())
                required = w.DWORD()
                self.api.SetupDiGetDeviceInterfaceDetailW(info, c.byref(item), None, 0, c.byref(required), None)
                buffer = c.create_string_buffer(required.value)
                c.cast(buffer, c.POINTER(w.DWORD))[0] = 8 if c.sizeof(c.c_void_p) == 8 else 6
                if not self.api.SetupDiGetDeviceInterfaceDetailW(info, c.byref(item), buffer, required, None, None):
                    raise c.WinError(c.get_last_error())
                path = c.wstring_at(c.addressof(buffer) + 4).lower()
                if "vid_03eb&pid_2104#000200012345#" in path:
                    result.add("mkii")
                if "vid_04d8&pid_fb00#00000001#" in path:
                    result.add("cdc")
                index += 1
        finally:
            self.api.SetupDiDestroyDeviceInfoList(info)
        return result


class WinUsb:
    def __init__(self):
        self.k = c.WinDLL("kernel32", use_last_error=True)
        self.u = c.WinDLL("winusb", use_last_error=True)
        self.k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, c.c_void_p]
        self.k.CreateFileW.restype = w.HANDLE
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.k.CancelIoEx.argtypes = [w.HANDLE, c.c_void_p]
        self.u.WinUsb_Initialize.argtypes = [w.HANDLE, c.POINTER(c.c_void_p)]
        self.u.WinUsb_Initialize.restype = w.BOOL
        self.u.WinUsb_Free.argtypes = [c.c_void_p]
        sig = [c.c_void_p, c.c_ubyte, c.c_void_p, w.ULONG, c.POINTER(w.ULONG), c.c_void_p]
        self.u.WinUsb_WritePipe.argtypes = sig
        self.u.WinUsb_WritePipe.restype = w.BOOL
        self.u.WinUsb_ReadPipe.argtypes = sig
        self.u.WinUsb_ReadPipe.restype = w.BOOL
        self.u.WinUsb_SetPipePolicy.argtypes = [c.c_void_p, c.c_ubyte, w.ULONG, w.ULONG, c.c_void_p]
        self.u.WinUsb_GetPowerPolicy.argtypes = [c.c_void_p, w.ULONG, c.POINTER(w.ULONG), c.c_void_p]
        self.u.WinUsb_GetPowerPolicy.restype = w.BOOL
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Enum\USB\VID_03EB&PID_2104\000200012345\Device Parameters") as key:
            guid = winreg.QueryValueEx(key, "DeviceInterfaceGUIDs")[0][0]
        path = "\\\\?\\USB#VID_03EB&PID_2104#000200012345#" + guid
        self.file = self.k.CreateFileW(path, 0xc0000000, 3, None, 3, 0x40000000, None)
        self.usb = c.c_void_p()
        if self.file == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        if not self.u.WinUsb_Initialize(self.file, c.byref(self.usb)):
            error = c.get_last_error()
            self.k.CloseHandle(self.file)
            raise c.WinError(error)
        timeout = w.ULONG(8000)
        self.u.WinUsb_SetPipePolicy(self.usb, 0x82, 3, 4, c.byref(timeout))
        self.power = {}
        for name, policy in [("auto_suspend", 0x81), ("suspend_delay_ms", 0x83)]:
            size = w.ULONG(4)
            value = w.ULONG()
            ok = self.u.WinUsb_GetPowerPolicy(self.usb, policy, c.byref(size), c.byref(value))
            self.power[name] = {"value": value.value, "bytes": size.value,
                                "error": 0 if ok else c.get_last_error()}

    def signon(self):
        data = (c.c_ubyte * 1)(1)
        count = w.ULONG()
        if not self.u.WinUsb_WritePipe(self.usb, 2, data, 1, c.byref(count), None):
            raise c.WinError(c.get_last_error())
        reply, error = self.read()
        if error or reply != b"\x01\0\x0aAVRISP_MK2":
            raise RuntimeError("Bad SIGN_ON: " + repr((reply, error)))

    def read(self):
        buffer = (c.c_ubyte * 64)()
        count = w.ULONG()
        ok = self.u.WinUsb_ReadPipe(self.usb, 0x82, buffer, 64, c.byref(count), None)
        return bytes(buffer[:count.value]), 0 if ok else c.get_last_error()

    def close(self):
        self.u.WinUsb_Free(self.usb)
        self.k.CloseHandle(self.file)


def open_serial():
    # Pyserial normally calls PurgeComm on open, hiding queued return data.
    purge = win32.PurgeComm
    try:
        win32.PurgeComm = lambda *args: 1
        return serial.Serial("COM6", 115200, timeout=0, write_timeout=.5)
    finally:
        win32.PurgeComm = purge


def drain(port, quiet=.015, maximum=1):
    data = bytearray()
    start = last = time.perf_counter()
    while time.perf_counter() - start < maximum:
        n = port.in_waiting
        if n:
            data.extend(port.read(n))
            last = time.perf_counter()
        elif time.perf_counter() - last >= quiet:
            return bytes(data)
        if len(data) > 4096:
            raise RuntimeError("STOP: unbounded CDC output")
        time.sleep(.001)
    return bytes(data)


def receive(port, length, timeout=1):
    data = bytearray()
    start = time.perf_counter()
    while len(data) < length and time.perf_counter() - start < timeout:
        data.extend(port.read(length - len(data)))
        if len(data) < length:
            time.sleep(.001)
    return bytes(data)


def snapshot(usb):
    start = time.perf_counter()
    devices = usb.present()
    ports = {p.device for p in list_ports.comports() if
             (p.vid, p.pid) in {(0x04d8, 0xfb00), (0x1209, 4)}}
    return devices, ports, time.perf_counter() - start


def cycle(usb, port, mode, number, prefix):
    pending = drain(port)
    if pending:
        raise RuntimeError("Unexpected pre-entry data: " + repr(pending))
    port.write(b"\0")
    if receive(port, 5) != b"BBIO1":
        raise RuntimeError("STOP: pre-entry probe failed")
    if drain(port):
        raise RuntimeError("Unexpected bytes after pre-entry probe")
    item = {"method": "v2-open-when-COM-present", "cycle": number, "mode": mode,
            "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "events": [], "serial_open_errors": [], "winusb_open_errors": []}
    start = time.perf_counter()
    port.write(b"\x08")
    try:
        port.close()
    except serial.SerialException:
        pass  # Expected removal can race the serial Close call.
    native = process = thread = None
    previous = None
    gaps = []
    costs = []
    last_poll = start
    try:
        while time.perf_counter() - start < 60:
            devices, ports, cost = snapshot(usb)
            now = time.perf_counter()
            elapsed = now - start
            gaps.append(now - last_poll)
            costs.append(cost)
            last_poll = now
            state = ("mkii" in devices, "cdc" in devices, "COM6" in ports, "COM14" in ports)
            if state != previous:
                item["events"].append([elapsed, *state])
                previous = state
            if state[0] and "mkii_present_s" not in item:
                item["mkii_present_s"] = elapsed
            if state[0]:
                item["last_mkii_present_s"] = elapsed
            if "mkii_present_s" in item and not state[0] and "exit_observed_s" not in item:
                item["exit_observed_s"] = elapsed
            if state[1] and "exit_observed_s" in item and "cdc_present_s" not in item:
                item["cdc_present_s"] = elapsed
            if state[2] and "exit_observed_s" in item and "com6_present_s" not in item:
                item["com6_present_s"] = elapsed
            if "mkii_present_s" in item and elapsed - item["mkii_present_s"] >= .10 and "client_started_s" not in item:
                if mode.startswith("avrdude"):
                    args = [str(DEV / "XM64/tools/avrdude-8.3/avrdude.exe"), "-c", "avrispmkII",
                            "-P", "usb", "-p", "x128a3u", "-n"]
                    if mode == "avrdude":
                        args += ["-U", "signature:r:-:h"]
                    else:
                        memory = "flash" if mode == "avrdude-flash" else "boot"
                        target = prefix.parent / (prefix.name + "_%03d_%s.bin" % (number, memory))
                        args += ["-A", "-U", "%s:r:%s:r" % (memory, target)]
                    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    item["client_command"] = args
                    item["client_started_s"] = elapsed
                elif mode in {"hold", "signon-close", "pending-read"}:
                    try:
                        native = WinUsb()
                    except OSError as error:
                        item["winusb_open_errors"].append([elapsed, str(error)])
                    else:
                        item["client_started_s"] = elapsed
                        item["winusb_power_policy"] = native.power
                        if mode == "signon-close":
                            native.signon()
                            native.close()
                            native = None
                            item["client_finished_s"] = time.perf_counter() - start
                        if mode == "pending-read":
                            def listener():
                                reply, error = native.read()
                                item["listener_result"] = [time.perf_counter() - start, reply.hex(), error]
                            thread = threading.Thread(target=listener)
                            thread.start()
                else:
                    item["client_started_s"] = elapsed
                    item["client_finished_s"] = elapsed
            if process is not None and process.poll() is not None and "client_exit" not in item:
                stdout, stderr = process.communicate()
                item["client_finished_s"] = time.perf_counter() - start
                item["client_exit"] = process.returncode
                (prefix.parent / (prefix.name + "_%03d_avrdude.log" % number)).write_text(
                    repr(item["client_command"]) + "\nSTDOUT:\n" + stdout + "\nSTDERR:\n" + stderr,
                    encoding="utf-8")
                if process.returncode or (mode == "avrdude" and "0x1e,0x97,0x42" not in stdout.lower()):
                    raise RuntimeError("Read-only avrdude failed: " + repr((stdout, stderr)))
            if state[2] and "exit_observed_s" in item:
                try:
                    new_port = open_serial()
                except serial.SerialException as error:
                    item["serial_open_errors"].append([elapsed, str(error)])
                else:
                    item["com6_open_s"] = time.perf_counter() - start
                    pending = drain(new_port)
                    item["pending_hex"] = pending.hex()
                    if pending.startswith(b"CDCT"):
                        packet = pending[:16]
                        xor = 0
                        for value in packet:
                            xor ^= value
                        if len(packet) != 16 or xor or packet[4] != 1:
                            raise RuntimeError("Bad diagnostic packet: " + pending.hex())
                        names = ["idle_tick", "cleanup_tick", "attach_tick", "configured_tick"]
                        item["firmware_trace"] = {name: int.from_bytes(packet[6+2*i:8+2*i], "big")
                                                  for i, name in enumerate(names)}
                        item["firmware_trace"]["attempts"] = packet[5]
                        item["firmware_trace"]["se0_timeouts"] = packet[14]
                        item["firmware_trace"]["tick_ms"] = 10
                        item["pending_after_trace_hex"] = pending[16:].hex()
                    new_port.write(b"\0")
                    reply = receive(new_port, 5)
                    item["com6_usable_s"] = time.perf_counter() - start
                    item["probe_hex"] = reply.hex()
                    if reply != b"BBIO1":
                        new_port.close()
                        raise RuntimeError("STOP: post-return probe failed: " + repr(reply))
                    extra = drain(new_port)
                    if extra:
                        new_port.close()
                        raise RuntimeError("Unexpected extra probe data: " + repr(extra))
                    item["exit_to_usable_s"] = item["com6_usable_s"] - item["exit_observed_s"]
                    item["max_poll_gap_s"] = max(gaps)
                    item["median_snapshot_s"] = statistics.median(costs)
                    item["max_snapshot_s"] = max(costs)
                    return new_port, item
            time.sleep(.02)
        raise RuntimeError("STOP: no usable CDC return within 60 seconds; no new entry")
    except BaseException as error:
        item["error"] = repr(error)
        prefix.with_suffix(".failure.json").write_text(json.dumps(item, indent=2), encoding="utf-8")
        raise
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
        if thread is not None:
            thread.join(.5)
            if thread.is_alive():
                native.k.CancelIoEx(native.file, None)
                thread.join(2)
            if thread.is_alive():
                raise RuntimeError("STOP: own WinUSB listener did not cancel")
        if native is not None:
            native.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--modes", default="silent,hold,signon-close,pending-read,avrdude")
    parser.add_argument("--expected-version", default="5a8eda9")
    args = parser.parse_args()
    modes = args.modes.split(",")
    if not args.round or any(x not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for x in args.round):
        parser.error("Round names must contain only letters, digits, underscores or hyphens")
    if set(modes) - {"silent", "hold", "signon-close", "pending-read", "avrdude", "avrdude-boot", "avrdude-flash"} or args.repeats < 1:
        parser.error("Invalid modes/repeats")
    prefix = LOGS / ("mkii_cdc_" + args.round)
    if prefix.with_suffix(".jsonl").exists():
        parser.error("Refusing to overwrite an existing round")
    usb = Usb()
    if usb.present() != {"cdc"}:
        raise RuntimeError("STOP: expected only CDC at initial check")
    port = open_serial()
    samples = []
    try:
        initial = drain(port)
        port.write(b"\0" * 24)
        reply = receive(port, 5)
        reply += drain(port, quiet=.05)
        if not reply or reply.replace(b"BBIO1", b""):
            raise RuntimeError("STOP: initial BBIO identity is not valid: " + repr(reply))
        for repeat in range(args.repeats):
            order = modes[repeat % len(modes):] + modes[:repeat % len(modes)]
            for mode in order:
                port, item = cycle(usb, port, mode, len(samples) + 1, prefix)
                item["round"] = args.round
                item["repeat"] = repeat
                samples.append(item)
                with prefix.with_suffix(".jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(item) + "\n")
                print("%s %02d %-12s exit=%6.3fs usable=%6.3fs exit->usable=%6.3fs pending=%s" % (
                    args.round, item["cycle"], mode, item["exit_observed_s"], item["com6_usable_s"],
                    item["exit_to_usable_s"], item["pending_hex"]), flush=True)
        port.write(b"\x0f")
        terminal = drain(port, quiet=.2)
        if b"HiZ>" not in terminal or args.expected_version.encode("ascii") not in terminal:
            raise RuntimeError("STOP: final terminal/banner not confirmed: " + repr(terminal))
        summary = {"round": args.round, "count": len(samples), "initial_pending_hex": initial.hex(),
                   "final_terminal": terminal.decode("ascii", errors="replace"), "modes": {}}
        for mode in modes:
            values = [x["exit_to_usable_s"] for x in samples if x["mode"] == mode]
            summary["modes"][mode] = {"n": len(values), "min": min(values),
                                      "median": statistics.median(values), "max": max(values)}
        prefix.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2), flush=True)
    finally:
        port.close()


if __name__ == "__main__":
    main()
