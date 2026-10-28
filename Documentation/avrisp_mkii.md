AVRISP-MKII programmer
======================

The Bus Pirate firmware contains an AVRISP-MKII compatible programmer
personality for programming AVR microcontrollers over ISP, PDI (XMEGA)
and TPI (TINY) interfaces.  The protocol engine is a port of
[LUFA's AVRISP-MKII project](https://www.lufa-lib.org) (Copyright (C)
Dean Camera, MIT-style licence, full text in
[avrisp-mkii-license.txt](avrisp-mkii-license.txt)).

The programmer is implemented as two binary bitbang mode commands; both
are entered from the binary bitbang mode (send `0x00` to the terminal at
least 20 times until `BBIO1` appears, then send the command byte).

- **`0x08` - AVRISP-MKII over USB** (BPv4 only): re-enumerates the Bus
  Pirate as a vendor-class device with Atmel's AVRISP mkII VID/PID
  (03EB:2104), speaking the raw STK500v2/XPROG command set over bulk
  endpoint 2.  Use `avrdude -c avrispmkII -P usb`.
- **`0x09` - AVRISP-MKII over serial** (BPv3 and BPv4): serves the
  framed STK500v2 (AVR068) protocol over the normal serial port.  Use
  `avrdude -c stk500v2 -P COMx`.  Because of a host-side limitation in
  avrdude (it only enables the XPROG PDI/TPI protocol for mkII-class
  programmers), this route provides **ISP programming only**; PDI and
  TPI require the USB route on BPv4.

Both modes end automatically after a few seconds without host traffic;
the Bus Pirate then returns to the binary bitbang prompt (USB users see
the serial port re-appear).  A hardware reset always leaves the mode.

## Use with avrdude (USB route, BPv4)

1. Enter binary bitbang mode and send `0x08`.
2. Wait for the driver/model string change (the device re-enumerates as
   "AVRISP mkII").
3. Program, for example:

```
avrdude -c avrispmkII -P usb -p <part> -U flash:w:<file>.hex
```

On Windows the 03EB:2104 device needs a libusb/WinUSB style driver
bound to it once (for example with the [Zadig](https://zadig.akeo.ie)
tool, choose the "AVRISP mkII" interface and install the WinUSB or
libusb driver).  The normal Bus Pirate serial port driver is untouched.
The serial route needs no additional driver at all.

## Use with avrdude (serial route, BPv3/BPv4)

1. Enter binary bitbang mode (BPv3: over the FT232 serial port, which
   the mode re-configures for 115200 bps; BPv4: over the USB serial
   port), and send `0x09`.
2. Close the terminal and run, for example:

```
avrdude -c stk500v2 -P COM4 -p <part> -U flash:w:<file>.hex
```

## Wiring

ISP (ATtiny/ATmega, 6-pin programming header convention):

| programmer pin | BP pin | target pin |
|---|---|---|
| SCK | CLK | SCK |
| MOSI | MOSI | MOSI |
| MISO | MISO | MISO |
| /RESET | AUX | /RESET |
| VTARGET sense | ADC | target VCC (optional) |
| rescue clock (4 MHz) | CS | XTAL1, rescue only, see below |
| GND | GND | GND |

PDI (XMEGA) / TPI (TINY):

| programmer pin | BP pin | target pin |
|---|---|---|
| CLOCK | CLK | PDI_CLK / TPI_CLK |
| DATA | MOSI **and** MISO, each through a 220 ohm resistor | PDI_DATA / TPIDATA |
| /RESET | AUX | /RESET |
| VTARGET sense | ADC | target VCC (optional) |
| GND | GND | GND |

The two 220 ohm resistors join the Bus Pirate's MOSI and MISO pins into
the single bidirectional DATA line, the same arrangement LUFA's AVRISP
project uses.

The **VTARGET** parameter reported to avrdude is measured on the BP's
voltage probe pin (ADC), which has a 2:1 divider and accepts 0 to ~6.6 V.
If the target supply is not wired to the ADC pin, VTARGET reads 0.

The **rescue clock** runs continuously on the CS pin at 4 MHz while the
personality is active.  For targets whose fuses select an external
clock, wire CS to the target's XTAL1 pin and use 125 kHz ISP speed
(`-B 125`), exactly as for a real AVRISP-MKII clone.

## Notes and limitations

- BPv3: the personality is included in the default firmware
  (serial ISP route only) but has not been tested on hardware; treat the
  v3 build as build-verified only.
- TPI: the protocol engine is complete, but no TPI-capable target was
  available for bench verification yet.
- The previously shipped `Firmware-Alternates/firmware-STK500v2`
  alternate firmware is superseded by this built-in personality.