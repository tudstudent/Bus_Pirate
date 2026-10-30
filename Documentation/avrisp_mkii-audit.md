# AVRISP-MKII independent source audit

Date: 2026-10-28. Baseline: `ffd7aa9` plus documentation `6cd8052`.
Scope: the combined firmware on branch `feat/avrisp-mkii`, both board builds.
All fixes are uncommitted. No device, USB programmer, COM port, flashing,
or target programming was accessed. This is source/build verification,
not a claim of electrical or bench conformance.

**Bench update (2026-10-30):** the audited fixes are committed (`9492bbb`
and the bench-fix series after it); the combined firmware passed full
hardware validation (XM64 PDI incl. erase/restore; ATmega64A ISP incl.
write/readback; serial route; USB entry/idle-exit incl. Windows driver
bind + PnP restarts).  Evidence and residual observations:
`WORKLOG-AVRMKII.md` §14 (esp. §14.9–§14.13).  The 2026-10-28 sentences
above describe that snapshot only.

## Evidence

- LUFA checkout: `90d65ba059d91078a34b9c26c8772ee14b556a13`, project
  `Bus_Pirate/.bpv4-work/lufa/Projects/AVRISP-MKII`. References below use
  paths relative to that project, and name the relevant functions.
- avrdude: `9aa44d08cb207a80a5d1005ead61142d21fb50de` (current `main`),
  `src/stk500v2.c`, `src/usb_libusb.c`, and `src/usbdevs.h`, fetched from
  `https://raw.githubusercontent.com/avrdudes/avrdude/main/src/`.
- BPv4 primary manual: PIC24FJ256GB110 family DS39897C; the full local
  extract `Bus_Pirate/.bpv4-work/PIC24FJ256GB110_ds39897c.pdf.txt` was used.
  The compiled part is PIC24FJ256GB106, in this family.
- BPv3 primary manual: PIC24FJ64GA004 family DS39881E. The supplied short
  extract contains UART information only; the supplied PDF was extracted
  in full for PPS, GPIO, OC, SPI, timers, ADC, and interrupt checks.
  The compiled part is PIC24FJ64GA002, in this family.
- Target primary manuals: XMEGA AU 8331F, especially sections 32.3, 32.7,
  and 33.12; ATxmega128A3U datasheet 8386, reset and PDI characteristics.
- Additional primary TPI manual: ATtiny4/5/9/10 complete datasheet 8127H,
  sections 15, 16, and 17, fetched from
  `https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-8127-AVR-8-bit-Microcontroller-ATtiny4-ATtiny5-ATtiny9-ATtiny10_Datasheet.pdf`.
- AVR053 primary application note: 2555H, sections 2 and 3, fetched from
  `https://ww1.microchip.com/downloads/en/Appnotes/Atmel-2555-Internal-RC-Oscillator-Calibration-for-tinyAVR-and-megaAVR-Devices_ApplicationNote_AVR053.pdf`.
- PIC24 programmer's reference 70000157G: RCOUNT, REPEAT, NOP, MUL.UU,
  and interrupt behavior. XC16 output was disassembled to check the idle
  ISR and the millisecond multiplication, not inferred from C alone.
- Board-specific wiring/divider facts come from `hardwarev3.h`,
  `hardwarev4.h`, and the existing probe conversion in `base.c`;
  MCU pin capabilities and peripheral behavior were checked in the manuals.

Generated reference extracts and native test binaries remain only in
`Firmware/build/`, which is ignored. Parent ledgers/study were read only.

## Changes Applied

Locations refer to the audited working tree. Each row gives before -> after,
and why; several independent fixes share a function.

| Location | Before -> after; reason |
|---|---|
| `Firmware/avrisp_mkii.c:242` | Copy next reply packet before checking UOWN -> wait first, then copy; prevents overwriting the SIE-owned IN buffer. |
| `Firmware/avrisp_mkii.c:256` | Queue last IN packet without waiting -> wait for final short packet/ZLP completion; avoids response/mode-exit races. |
| `Firmware/avrisp_mkii.c:282` | Handler-driven USB byte stream -> bounded complete-transfer collection; consumes the actual wire-length ZLP, drains oversized transfers, and cannot read through a short packet into the next command. |
| `Firmware/avrisp_v2.c:204` | Missing bytes synthesized as 0xFF, unchecked poll index, oversized reads silently shortened -> validate complete headers, payload lengths, read limits, and indices before target access. |
| `Firmware/avrisp_mkii.c:175` | Nonvolatile descriptor pointer/count accesses and personality flag -> volatile DMA/ISR-visible accesses; prevents cached hardware state. |
| `Firmware/avrisp_mkii.c:135` | Self-powered configuration -> bus-powered configuration; matches the USB-powered board and stack device status. |
| `Firmware/avrisp_mkii.c:308` | Live USB ISR during detach/reinitialization -> mask it across descriptor/personality replacement, then re-enable after start; avoids mixed personalities. |
| `Firmware/avrisp_mkii.c:323` | initCDC before usb_init, which clears callbacks -> initialize CDC afterward; preserves class-handler setup. |
| `Firmware/dp_usb/cdc.c:123` | SOF callback cleared by bus reset and not restored at configuration -> register CDC flushing on every CDC configuration and reset flush/lock state; restores serial transmission after personality exit/reset. |
| `Firmware/avrisp_mkii.c:334` | Print/wait for CDC IN before USB detach -> detach without requiring a CDC reader; closing the COM port no longer prevents mode entry. |
| `Firmware/dp_usb/usb_stack.c:456` | Endpoint GET_STATUS clears BSTALL and tests other BD bits -> read only BSTALL; returns the correct halt status without changing it. |
| `Firmware/avrisp_mkii.c:384` | Blocking getc_cdc after readiness, including ZLP -> nonblocking poll_getc_cdc; a lone CDC ZLP cannot hang framed serial parsing. |
| `Firmware/avrisp_mkii.c:405` | Unbounded serial transmit primitives -> watchdog-bounded CDC/UART readiness and raw byte output; a closed CDC reader cannot trap the programmer loop. |
| `Firmware/avrisp_mkii.c:452` | v3 sleeps 1 ms while waiting for UART input -> busy-poll its four-character FIFO with timer-bounded frame waits; prevents overrun at 115200 baud. |
| `Firmware/avrisp_mkii.c:384` | No UART overrun recovery -> clear OERR, drain the FIFO, and abort the partial frame; framing can resynchronize. |
| `Firmware/avrisp_mkii.c:636` | Documented but absent v3 baud switch -> use U1BRG=34 for the session, then restore the previous BRG; matches 115200-baud host use. |
| `Firmware/avrisp_mkii.c:603` | Expired target timeout also blocks its error reply, idle expires during long commands -> fresh reply budget and idle refresh at completion; reports failures and measures actual idleness. |
| `Firmware/avrisp_xprog.c:40` | Clock stops between PDI/TPI commands -> priority-6 Timer 4 idle clock at 25 kHz during host waits and parsing; prevents PDI automatic disable below approximately 10 kHz. |
| `Firmware/avrisp_xprog.c:133` | No ownership transfer between idle clock and frame clock -> mask idle ISR only when target byte exchange begins, resume at response output; payload copying cannot disable PDI. |
| `Firmware/avrisp_mkii.c:625` | v4 globally forbids interrupt nesting -> temporarily permit it, restore on exit; the idle clock can preempt USB servicing. |
| `Firmware/avrisp_xprog.c:110` | RX->TX delay without a clock, output enabled before latch setup, TX->RX low glitch -> actual idle cycle, preload HIGH, float before clearing the latch; meets direction-change and DATA ownership rules. |
| `Firmware/avrisp_xprog.c:154` | Receive parity/stops ignored -> verify even parity and both stop bits; corrupted NVM reads fail instead of succeeding. |
| `Firmware/avrisp_xprog.c:214` | Idle shutdown merely floats pins -> clear PDI reset/TPI NVMEN with a bounded exchange before releasing pins; TPI otherwise may require power cycling. |
| `Firmware/avrisp_mkii.c:654` | Stop watchdog and ISP pins before XPROG cleanup -> clean XPROG first with Timer 3 still running, then ISP and timer shutdown; cleanup remains bounded and can still clock the target. |
| `Firmware/avrisp_xprog.c:461` | Reject length 256 -> accept 256; avrdude deliberately uses 256-byte XPROG chunks, including halves of 512-byte pages. |
| `Firmware/avrisp_xprog.c:318` | Accept arbitrary non-JTAG modes, unknown memory/erase paths, zero-length fuse writes, truncated TPI addresses -> reject invalid values, preserve mode on failure, and validate TPI address/alignment/span; avoids silent wrong operations. |
| `Firmware/avrisp_xprog.c:663` | Arbitrary EEPROM page size -> accept 1..256; matches the one-byte REPEAT encoding and prevents underflow/overflow. |
| `Firmware/avrisp_xprog.c:734` | Unknown XPROG subcommand gets no reply -> framed XPROG failure; avoids an unnecessary host timeout. |
| `Firmware/avrisp_nvm_pdi.c:320` | Eight-bit EEPROM-tag counter can wrap at 256 -> 16-bit counter and timeout check; whole-EEPROM erase can tag all 256 bytes and terminate. |
| `Firmware/avrisp_nvm_pdi.c:154` | Zero-length read fetches/stores one byte -> no target read; prevents unintended access. |
| `Firmware/avrisp_nvm_pdi.c:192` | Fuse/page write returns before completion -> wait for NVM ready; final writes are complete before ACK/leave. |
| `Firmware/avrisp_nvm_tpi.c:158` | Final word ACK precedes NVM completion -> poll ready after the final word; matches the primary programming algorithm. |
| `Firmware/avrisp_nvm_pdi.c:33` | NVM base OR register -> base plus offset; identical for the normal aligned base, correct for general supplied bases. |
| `Firmware/avrisp_xprog.h:166` | Unused READUSERSIG opcode 0x03 -> 0x01; matches AU Table 33-5. Runtime reads still use READNVM. |
| `Firmware/avrisp_isp.c:83` | v3-style OC5 configuration used on enhanced v4 OC -> per-chip PWM setup; v4 uses OC5CON2 self-sync, OC5RS=3 period, OC5R=2 duty. v3 retains PR2=3 and OC5RS=2 duty. |
| `Firmware/avrisp_isp.c:336` | Inherit PPS/open-drain/old PWM routing -> detach stale routes and use known push-pull settings; an earlier binary PWM mode cannot drive RESET. |
| `Firmware/avrisp_mkii.h:21` | Write GPIO through PORT -> write LAT; avoids read-modify-write corruption of neighboring pin latches. |
| `Firmware/avrisp_isp.c:259` | Enable reset output before loading polarity -> preload correct polarity and release reset at shutdown; avoids glitches and stuck reset after idle exit. |
| `Firmware/avrisp_isp.c:477` | One fallback write permanently changes polling mode -> per-byte temporary mode; later writes still use host-selected polling. |
| `Firmware/avrisp_isp.c:471` | Address zero doubles as invalid-poll sentinel -> separate validity flag; data polling works at address zero. |
| `Firmware/avrisp_isp.c:489` | Continue rapid transfers after watchdog expiry / overwrite failure during page commit -> stop target transfers, preserve failure, skip commit, and return timeout status. |
| `Firmware/avrisp_isp.c:764` | Reject TxBytes=255 and omit remaining TX bytes after RX window -> permit all 255 bytes and finish NumTx; implements SPI_MULTI's transmit count independently of receive count. |
| `Firmware/avrisp_isp.c:643` | Approximate 15 us software OSCCAL half-period -> hardware 32786.9 Hz MOSI C-clock (+0.058%), MISO pull-up, eight-edge response count, bounded duration, then rescue-clock restoration; follows AVR053. |
| `Firmware/avrisp_v2.c:79` | Partially inherited ADC configuration and double-truncated VTARGET -> explicit unsigned/manual-sample ADC setup and rounded decivolts; ADC=512 reports 3.3 V instead of 3.2 V. |
| `Firmware/base.c:622` | Sixteen-bit milliseconds*1000 wraps above 65 ms -> widen before multiplication; makes the requested 100 ms USB detach actually 100 ms and fixes other callers' intended delays. |
| `Firmware/busPirate.X/nbproject/configurations.xml:8` | New sources only in local untracked Makefile -> list all six sources and three headers in the tracked MPLAB project; IDE builds can link the feature. |
| `Documentation/avrisp_mkii.md:58` | Ambiguous PDI reset wiring, missing voltage cautions, -B 125 described as 125 kHz, floating ADC claimed zero, alternate claimed removed -> correct wiring/safety, -B 8, measurement caveat, build-only status, and retained alternate status. |
| `Documentation/bitbang.md:59` | Unqualified Studio compatibility and underspecified serial mode -> label Studio unverified, document ISP-only avrdude/baud restoration, narrow reserved opcodes to 0x0A..0x0E. |
| `Documentation/avrisp-mkii-license.txt:30` | Generic LUFA notice only -> also preserve project permission text and Jacob September's ISP contribution copyright. |
| `Firmware/tests/test_avrisp.py:1` | No native protocol regressions -> compile actual instrumented sources against explicit hardware mocks, plus a timed v3 FIFO simulation; repeatable without hardware. |

## Remaining Findings / Deliberate Choices

- RISK - no electrical/bench verification. USB enumeration/driver binding,
  PDI/TPI waveforms under interrupts, level margins, actual SPI rates,
  rescue/OSCCAL frequency, target erase/write/readback, and other-mode
  regressions still require the separately authorized bench gate. The
  shared millisecond-delay correction also merits existing-mode regression.
- RISK - AU manual contradiction for application/boot section erase.
  Table 33-5 (page 422) explicitly says PDI-write trigger for 0x20/0x68;
  section 33.12.3.8 (page 425) instead says CMDEX. The implementation keeps
  LUFA `XMEGANVM_EraseMemory` and Table 33-5's PDI-write sequence, not an
  unverified change to CMDEX. Bench-test both section erases on expendable,
  backed-up targets before relying on them.
- RISK - slowest ISP rates versus the LUFA-style one-second target budget.
  At 51.1 Hz one four-byte SPI operation is about 0.626 s, so large reads or
  paged writes cannot fit that budget (nor many normal host timeouts).
  All 164 ladder indices are represented, but full pages at every rate are
  not promised. Small custom-host blocks/timeouts are needed at this end;
  failures now stop clocking and report timeout, not success.
- RISK - BPv3 flash margin is only 819 bytes; stack/dynamic space is 1488
  bytes. Both link successfully; this is not a worst-case stack proof.
  Do not silently trim protocols if future edits exceed the image budget.
- RISK - inherited `usb_start()` in `Firmware/dp_usb/usb_stack.c:110`
  busy-waits for SE0 to disappear without consulting the mode watchdog.
  A permanently faulted/reset-held bus can still stall startup. Normal
  enumeration and bulk/serial waits are bounded; changing the common USB
  startup API was not necessary for normal-host protocol compatibility.
- RISK - if a damaged/disconnected TPI link prevents NVMEN clearing during
  cleanup, the ATtiny datasheet says a target power cycle may be required.
  Cleanup is bounded, attempts the specified sequence, and does not claim
  it can recover an electrically inaccessible target.
- NIT - the read-only parent port study incorrectly says 158 ladder entries
  and indices ending at 157 in several places. Current avrdude and this
  firmware use 164 entries, indices 0..163. Parent documentation was not
  edited under the workspace rules.

No remaining confirmed normal-host protocol corruption issue is known from
this audit. Native models are not proof of real PIC24 or target behavior.

## Coverage Against the Checklist

### 1. Protocol and NVM

- V2 dispatch and reply layouts, SIGN_ON identities, reset-protection ACK,
  parameter IDs/defaults/read/write privileges, live VTARGET refresh, and
  big-endian LOAD_ADDRESS: checked against LUFA `V2Protocol.c`,
  `V2ProtocolParams.c`, and avrdude `stk500v2_getsync` / parameter calls.
  Parameter persistence is deliberately absent and documented.
- ISP enter/leave field order, synchronization/poll indexing, polarity,
  pre/post delays, chip erase delay/busy choice, flash low/high command
  toggle and word increments, EEPROM byte increments, extended-address
  emission and boundary reloads, page commit, all six completion modes,
  poll values, timeout statuses, fuse/lock/signature/OSCCAL reads, write
  reply status bytes, and SPI_MULTI padding/RX window: checked against
  LUFA `Lib/ISP/ISPProtocol.c` and `ISPTarget.c`. Corrections beyond LUFA
  (zero-address polling, SPI_MULTI tail/count, malformed input) are explicit.
  LOAD_ADDRESS still preserves an already pending extended-address reload
  when the new command lacks bit 31, matching LUFA.
- XPROG mode/subcommand wrappers, erase maps, memory type and page-mode
  fields, big-endian addresses/counts/parameters, PDI fuse/lock single-byte
  operations, TPI multi-byte fuse blocks, 256-byte writes, unknown/error
  shapes, and undocumented parameter 5's two discarded bytes: checked
  against LUFA `XPROGProtocol.c` and avrdude `stk600_xprog_*`.
- CRC reply deliberately remains high byte, low byte, middle byte, as in
  LUFA `XPROGProtocol_ReadCRC` (Write_8 then Write_16_LE). The fetched
  avrdude driver does not implement a CRC consumer; no incompatible
  hypothetical host byte order was substituted.
- PDI key FF 88 D8 CD 45 AB 89 12 on the wire, RESET=0x59, CTRL=2,
  LDCS NVMEN, pointer/address endianness, REPEAT count minus one, READNVM,
  page-buffer erase/load/write, byte/fuse/lock writes, chip/EEPROM/page/user
  erases, CRC CMD/CMDEX/DAT reads, controller/bus polling, and disable:
  checked against LUFA `XMEGANVM.c` and AU sections 32.7/33.12. The section
  erase manual conflict is recorded rather than hidden.
- TPI SKEY, SLDCS/SSTCS, SIN/SOUT six-bit address encoding, low/high pointer
  loading, post-increment, word ordering/padding, chip/section erase through
  an odd-byte trigger address, busy polling, and NVMEN clear: checked
  against LUFA `TINYNVM.c` and 8127H sections 15/16.

### 2. USB Packet Layer

- VID/PID 03EB:2104, raw commands without AVR068 framing, vendor interface,
  EP 0x02 OUT / 0x82 IN, 64-byte packets, and USB/serial identity selection:
  LUFA `AVRISPDescriptors.c/.h`; avrdude `usbdevs.h:77`,
  `stk500v2_send_mk2`, `stk500v2_recv_mk2`, and getsync.
- OUT packets collected through the real short packet/ZLP, including an
  exact 64-byte ISP request; oversize draining and next-command isolation:
  avrdude `usb_libusb.c:262` usbdev_send explicitly sends a ZLP for exact
  multiples. This avoids PIC24 structure-padding-dependent ZLP arithmetic.
- IN ownership, count/data readiness, initial DATA0/DTS alternation, all
  full/short/ZLP response endings, and volatile DMA reads: DS39897C USB
  chapter 18, stack `BDentry`/CDC ownership convention, and avrdude
  `usbdev_recv_frame`. Native replies of 64, 128, 129, and 259 bytes verify
  contents and packet boundaries, not just returned lengths.
- Detach via USBEN=0 and hardware pull-up removal: DS39897C register 18-7;
  descriptor reinitialization/start/configuration dispatch and CDC class/SOF
  restoration: `usb_stack.c` usb_init/ClearUSBtoDefault/SET_CONFIGURATION
  and `cdc.c` user_configured_init. Startup SE0 fault risk is listed above.
- ISR/foreground ownership, disabled USB IRQ across personality changes,
  explicit interrupt nesting for keepalive, state/watchdog exits, bounded
  transfer waits, complete-reply wait, and five-second idle policy:
  code-path analysis plus DS39897C INTCON1 and timer/USB descriptions.

### 3. Serial Transport

- Start 0x1B, sequence echo including wrap-capable arbitrary sequence bytes,
  big-endian payload length, token 0x0E, XOR over the complete frame, and
  framed B0/C1 checksum-error reply: avrdude `stk500v2_send` and
  `stk500v2_recv`; native valid/error/oversize/truncated/resync cases.
- Identity STK500_2 keeps avrdude on AVR068; its XPROG initialization is
  gated to mkII/STK600/JTAGICE-mkII classes. Stock serial use is ISP-only,
  not a claim that the shared engine lacks PDI/TPI.
- v3 asynchronous UART, four-character RX FIFO, OERR clearing, BRGH=1,
  FCY/(4*(BRG+1)), BRG=34, and previous-baud restoration: DS39881E chapter
  17 and existing UART initialization. Timed native UART test streams a
  266-byte command at one character per 87 us without FIFO overrun.
- Frame/byte timeout, bounded oversize drain, idle exit, CDC ZLP-safe polling,
  and stalled CDC response exit: native tests and the actual CDC primitives.

### 4. Physical Layers

- Hardware SPI divider masks 0x1B, 0x1E, 0x1A, 0x1D, 0x19, 0x1C, 0x18:
  DS39897C and DS39881E SPIxCON1 register 15-2, PPRE at bits 1:0 and SPRE
  at bits 4:2. All seven masks calculate to 8M, 4M, 2M, 1M, 500k, 250k,
  125k at FCY=16 MHz; CKP=0, CKE=1, SMP=0 is mode 0.
- AVR069 host ladder: avrdude `stk500v2.c:3217` has 164 entries. All 157
  software half-period entries were compared with round(500000/frequency),
  with no mismatches. Spots: index 7=96386 Hz/5 us, 17=55945/9,
  64=5879/85, 100=1049/477, 163=51.1/9785. Actual software overhead makes
  these approximate rates; bench timing is still required.
- Rescue clock and PPS: DS39897C OCxCON1/2 registers 14-1/14-2 and
  DS39881E OCxCON register 14-1; Timer 2 prescale 1, period 4 instruction
  clocks, duty 2 -> 4 MHz/50%. Enhanced v4 and legacy v3 compare registers
  are intentionally different. Both PPS Table 10-3 assign OC5 function 22;
  v4 RP25 is RPOR12 (register 10-34), v3 RP6 is RPOR3 (register 10-18).
  Both CS pins are legal routable OC5 outputs; the baseline v3 RPOR3 fix
  is correct and retained.
- GPIO latch writes/direction, open-drain state, and reset polarity/release:
  both PIC24 manuals' I/O chapter 10, board macros, and LUFA reset semantics.
- OSCCAL: AVR053 section 2 requires target calibration firmware, a MOSI
  C-clock, MISO pull-up, and eight response toggles, normally within 1024
  clock cycles. Hardware divider 488 gives 32786.9 Hz; existing 25-cycle
  tolerance is retained. It is not a fuse-write command.
- Both PIC24 UARTs are asynchronous-only: DS39897C and DS39881E chapter 17.
  The software synchronous engine is therefore intentional, not an omitted
  UART synchronous option.
- PDI 12-bit 8E2, LSB first, falling-edge DATA setup/rising-edge sample,
  start alignment, guard-time clocks, idle levels, DATA float/drive order,
  DATA-high enable interval, first clock within 100 us, at least 16 enable
  clocks, and approximately 10 kHz inactivity threshold: AU 32.3.1 through
  32.3.8 and 8386 reset/PDI characteristics. Native frames cover all 256
  byte values plus bad parity and stop bits. TPI counterparts, reset
  assertion, 5 V NVM requirement, NVMEN clear, and unsupported 12 V reset:
  8127H sections 15/16/17.
- Idle ISR uses sixteen NOPs, not an inline REPEAT that would silently
  clobber interrupted RCOUNT. Final XC16 disassembly confirms the NOPs,
  GPIO writes, flag clear, and RETFIE with no hidden register clobber.

### 5. Integration and Resources

- Feature gating, v4-only USB code, both serial routes, binary commands
  0x08/0x09 and return/reset handling: configuration.h, binary_io.c,
  hardware headers, and both complete builds.
- T1 remains the free-running delay timer; T2/OC5 own rescue/OSCCAL;
  T3 PR=624 with 1:256 prescale is the 10 ms watchdog; T4 PR=639 with
  prescale 1 is 25 kHz idle clock. Timers/OC are exclusive to this binary
  mode; no competing T3/T4 ISR definitions exist. Other T4-using modes are
  mutually exclusive. Source analysis plus both MCU manuals' timer chapters.
- Target cleanup precedes pin and watchdog shutdown. The saved nesting and
  v3 baud state are restored. Physical/data buffers are static, not large
  target-page arrays on the limited v3 stack.
- ADC unsigned 10-bit format, automatic conversion/manual sample, SAMC=31,
  ADCS=2, probe channel/analog setup, and rounded 0.1 V reporting: both
  manuals' AD1CON1/2/3 definitions plus board-specific probe conversion.
- CLI Makefile already lists all sources and was not edited. Tracked MPLAB
  metadata now lists them too. Both -O1 builds have zero compiler warnings.

### 6. Documentation

- Corrected binary entries, stock-host transport restrictions, v3 baud,
  XMEGA RESET-as-clock wiring, 3.3 V drive/target-power/translation cautions,
  TPI supply/reset restrictions, VTARGET behavior, -B units, OSCCAL purpose,
  idle/watchdog limitations, volatile parameters, and build-only status.
- Confirmed the historical alternate still exists and did not delete it
  before bench validation. Preserved the LUFA library and project notices,
  including the additional ISP contributor.

## Final Verification

Run native tests from `Firmware` with `python tests/test_avrisp.py`:

```text
AVRISP native regression checks passed: 1661
AVRISP v3 timed UART: 266-byte payload, no FIFO overrun; baud/nesting restored
```

Both complete forced rebuilds (`make -B`, XC16 v2.10, -O1) exit 0 with
zero compiler warnings/errors. Sizes are the maps' actual
`Total "program" memory used` and `Total "data" memory used` entries:

| Board | Program bytes | Static data bytes | Maximum dynamic/stack bytes | App flash free |
|---|---:|---:|---:|---:|
| BPv4 | 77292 / 249588 (30% reported) | 12136 | 4242 | 172296 |
| BPv3 | 62919 / 63738 (98% reported) | 6698 | 1488 | 819 |

Maps: `Firmware/bpv4.map:444`, `Firmware/bpv4.map:469`,
`Firmware/bpv3.map:420`, and `Firmware/bpv3.map:438`.
Build logs: `Bus_Pirate/.bpv4-work/mkii-build/audit-final-v4.log` and
`Bus_Pirate/.bpv4-work/mkii-build/audit-final-v3.log`.

Final delivery remains a working-tree diff plus new audit/tests files.
The intentional untracked Makefile, .gitignore, and measurement HEX files
were left untouched. No commit, amend, stash, flash, or hardware operation
was performed.
