"""Native, hardware-free regression tests of the actual AVRISP C sources.

Run with Python 3 and an existing GCC on PATH. Generated files stay in build/.
Mocks complete DMA transactions at polling points and supply SPI/USRT data;
they do not emulate PIC24 timing, USB enumeration, or electrical behavior.
"""
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "avrisp-tests"
OUT.mkdir(parents=True, exist_ok=True)
for source in ROOT.glob("avrisp_*"):
    text = source.read_text()
    if source.suffix == ".c":
        text = re.sub(r"#pragma interrupt[^\n]*", "", text)
        text = text.replace("__attribute__((interrupt, no_auto_psv))", "")
        text = re.sub(r"__asm__ volatile\(.*?\);", "", text, flags=re.S)
        text = text.replace("while (avrisp_ep_in->BDSTAT & UOWN)",
                            "while ((mock_usb_in(), avrisp_ep_in->BDSTAT) & UOWN)")
        text = text.replace("while (avrisp_ep_out->BDSTAT & UOWN)",
                            "while ((mock_usb_out(), avrisp_ep_out->BDSTAT) & UOWN)")
        text = text.replace("while (usb_device_state < CONFIGURED_STATE)",
                            "while ((mock_usb_configure(), usb_device_state) < CONFIGURED_STATE)")
        text = text.replace(
            "while ((usb_device_state >= CONFIGURED_STATE) && avrisp_activity_ticks)",
            "while ((mock_usb_run_poll(), usb_device_state >= CONFIGURED_STATE) && avrisp_activity_ticks)",
        )
        text = text.replace("while (!IFS0bits.SPI1IF && avrisp_timeout_ticks)",
                            "while ((mock_spi(), !IFS0bits.SPI1IF) && avrisp_timeout_ticks)")
        text = text.replace("bool sampled_level = true;",
                            "mock_bit(drive, bit, sample);\n  bool sampled_level = true;")
    (OUT / source.name).write_text(text)
shutil.copyfile(ROOT / "tests" / "avrisp_mock.h", OUT / "base.h")
shutil.copyfile(ROOT / "tests" / "avrisp_test.c", OUT / "test.c")
exe = OUT / "test.exe"
subprocess.run(["gcc", "-std=gnu99", "-O1", "-Wall", "-Wextra",
                "-Werror", "-I", str(OUT), str(OUT / "test.c"), "-o", str(exe)],
               check=True)
subprocess.run([str(exe)], check=True)
shutil.copyfile(ROOT / "tests" / "avrisp_serial_v3_test.c", OUT / "serial_v3.c")
v3exe = OUT / "serial_v3.exe"
subprocess.run(["gcc", "-std=gnu99", "-O1", "-Wall", "-Wextra", "-Werror",
                "-Wno-unused-function", "-Wno-unused-variable", "-DAVRISP_NATIVE_V3",
                "-I", str(OUT), str(OUT / "serial_v3.c"), "-o", str(v3exe)],
               check=True)
subprocess.run([str(v3exe)], check=True)
