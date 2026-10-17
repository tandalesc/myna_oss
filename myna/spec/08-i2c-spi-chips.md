# 08 I2C, SPI and the chips behind them

## 1. I2C masters

| Bus | Base | Line | Chips |
|---|---|---|---|
| I2C0 (internal) | 0xC0004000 | 42 | 0x48 power-management chip, 0x49 its second register page |
| I2C1 (external) | 0xC0005000 | 43 | 0x10 FM tuner, 0x1D accelerometer, 0x4A illumination driver, 0x58 and 0x68 port expander; variant B also 0x53 flash-LED driver |

Addresses are 7-bit. The register layout and the flags are those of the I2C cell of ST microcontrollers (as in the STR71x family). The bus has no timing: every step completes at once [MODEL].

### 1.1 Registers (8-bit values in 32-bit slots)

| Offset | Name | Access | Reset | Bits |
|---|---|---|---|---|
| +0x00 | CR | RW | 0 | 0x20 PE (enable), 0x10 ENGC (stored), 0x08 START, 0x04 ACK, 0x02 STOP, 0x01 ITE (interrupt enable). START and STOP act at the write and read back as 0. |
| +0x04 | SR1 | R | 0 | 0x80 EVF (event: SB, BTF, ENDAD or AF is set), 0x20 TRA (transmitter), 0x10 BUSY, 0x08 BTF (byte transfer finished), 0x02 M/SL (master), 0x01 SB (start sent). 0x40 and 0x04 are always 0. |
| +0x08 | SR2 | R | 0 | 0x20 ENDAD (address acknowledged), 0x10 AF (no acknowledge). Others always 0. Reading SR2 clears AF. |
| +0x0C | CCR | S | 0 | Clock divider. No effect. |
| +0x10 | OAR1 | S | 0 | Own address. No effect (slave mode is not modelled). |
| +0x14 | OAR2 | S | 0 | No effect. |
| +0x18 | DR | RW | 0 | Data |
| +0x1C | ECCR | S | 0 | No effect. |

The interrupt line is high while CR.PE = 1, CR.ITE = 1 and EVF = 1.

### 1.2 Behaviour

| Action | Result |
|---|---|
| Write CR with PE = 0 | Stops a transfer, clears SR1 and SR2. |
| Write CR with START (PE = 1) | SB, M/SL, BUSY set; BTF and TRA cleared. Also a repeated start. |
| Write DR while SB = 1 (address byte: 7-bit address << 1, bit 0 = 1 for read) | SB cleared. A chip at the address acknowledges: ENDAD set, and TRA set for a write. No chip: AF set. |
| Read SR2, then write CR (with PE = 1) while ENDAD = 1 | ENDAD cleared. Transmitter: BTF set (DR empty). Receiver: the first byte is clocked in at once and BTF set; CR.ACK at this write tells the chip whether more bytes will be read. |
| Write DR as transmitter | The byte is sent. BTF set. If the chip does not acknowledge: AF set. |
| Read DR as receiver while BTF = 1 | Returns the byte, clears BTF. If still master (no STOP yet), the next byte is clocked in at once and BTF is set again. |
| Write CR with STOP | Stop condition: M/SL, BUSY, TRA, SB, ENDAD cleared. A received byte stays readable in DR. |

Sequences (validated on both buses [VALIDATED]; the test read DR before the STOP, the order given below avoids the extra byte):

- Write register R of chip A with value V: CR = 0x20; CR = 0x28; wait SB; DR = A << 1; read SR2 (expect ENDAD); CR = 0x20; wait BTF; DR = R; wait BTF; DR = V; wait BTF; CR = 0x22.
- Read register R of chip A: as above up to DR = R and wait BTF; then CR = 0x28 (repeated start); wait SB; DR = (A << 1) | 1; read SR2 (expect ENDAD); CR = 0x20 (ACK = 0: one byte); wait BTF; CR = 0x22 (STOP); read DR.
- For several bytes: write CR with ACK = 1 (0x24) at the ENDAD step and before each DR read except the last; before reading the last byte write CR = 0x22. Reading DR before STOP clocks one more byte out of the chip (harmless for the register chips below, but it moves their register pointer).

### 1.3 Register-file chips

Unless a chip says otherwise: after the write address byte, the first data byte is the register pointer; the next bytes are written to the pointer, which goes up by 1 after each byte. A read transfer returns bytes from the pointer, which goes up by 1 after each byte. The pointer survives a repeated start.

## 2. Power-management chip (I2C0 0x48)

A mixed-signal power-management chip. Its registers follow the ST-Ericsson AB3100 [UNCONFIRMED: inferred match]. Register-file protocol (1.3). A register that the model does not know reads 0.

### 2.1 Registers

| Register | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| 0x20 | CHIP_ID | R | 0xC8 | Chip identification |
| 0x21 | EVENT1 | R, cleared by reading | 0x01 | Bit 0 power key, bit 1 accessory, bit 3 charger plugged or unplugged, bit 6 USB plugged or unplugged, bit 7 [UNCONFIRMED: not raised]. Bit 0 is set at power-on as the power-on cause [MOCK]. |
| 0x22 | EVENT2 | R, cleared by reading | 0 | Bit 6 battery removed, bit 7 alarm (never raised by the model) |
| 0x23 | EVENT3 | R, cleared by reading | 0 | Bit 4 battery voltage below trigger level 0, bit 5 below trigger level 1 |
| 0x24-0x26 | EVENT_MASK1-3 | RW | 0xFF | 1 = event bit masked (no interrupt). Events are latched even when masked. |
| 0x27 | STATUS | R | 0x00 | Live levels: bit 3 charger present, bit 6 battery absent, bit 7 USB voltage present |
| 0x2B-0x2D | - | S | 0xFF | Second set of masks: no effect |
| 0x40-0x4B | Regulators | RW | 0x40: 0x16, 0x41: 0x10, 0x42: 0x10, 0x43: 0x10, 0x44: 0x00, 0x45: 0xD0, 0x46: 0x00, 0x47: 0x18, 0x48: 0x00, 0x49: 0x00, 0x4A: 0x7D, 0x4B: 0xAC | Bit 4 = regulator on. 0x42 = system supply: see power off below. Others: stored, no effect. Reset values [MOCK: values of the public Linux driver for this chip] |
| 0x52 | BATTERY_DATA_SOURCE | RW | 0 | Current source on the battery data contact, bits 2:0: 3 = 10 uA, 7 = 4 uA, other = off [MOCK] |
| 0x53 | CLOCK_CONTROL | RW | 0x01 | Bit 0 = time valid (1 at power-on [MOCK]). Bit 2 = alarm enable (stored, no alarm is modelled). |
| 0x5A-0x5F | CLOCK | RW | see 2.3 | 48-bit clock, little-endian (0x5A = bits 7:0) |
| 0x73 | ADC_CONTROL | RW | 0 | Bits 3:0 channel, bits 6:5 source. A write converts at once (2.4). |
| 0x74 | ADC_RESULT_HIGH | R | 0 | Result bits 15:8 |
| 0x75 | ADC_RESULT_LOW | R | 0 | Result bits 7:0 |
| 0x79 | AUTO_MEASURE_CONTROL | RW | 0 | Bit 2 = battery-voltage triggers armed (bit 7 = enable, stored) |
| 0x7A, 0x7B, 0x7C | VBAT8 | R | live | Battery voltage code (2.4) bits 15:8 |
| 0x7D | VBAT_HIGH | R | live | Battery voltage code bits 15:8 |
| 0x7E | VBAT_LOW | R | live | Bits 1:0 = bits 7:6 of the battery voltage code |
| 0x7F-0x81 | - | R | 0 | Charger measurements: no charger [MOCK] |
| 0x94, 0x95 | VBAT_TRIGGER0, 1 | RW | 0 | Trigger levels, compared with VBAT8 |
| 0x9C-0x9F | - | R | 0 | Charge counter: no current [MOCK] |
| other | | RW | 0 | Storage |

Writes to the read-only registers (0x20-0x23, 0x27, 0x74, 0x75) are ignored.

### 2.2 Events and interrupt

- An event sets its bit in EVENT1-3. A read of an event register returns the bits and clears them.
- Line 0 is high while (EVENTn & ~EVENT_MASKn) is not 0 for any n. Writing a mask register re-evaluates the line.
- Usual handling: unmask the wanted bits; in the line 0 handler read registers 0x21-0x23 in one transfer (the read clears them and the line); read 0x27 for the levels.
- Events: viewer switch `charger` changes STATUS bit 3 and raises EVENT1 bit 3; switch `usb` changes STATUS bit 7 and raises EVENT1 bit 6. A battery removal raises EVENT2 bit 6. When 0x79 bit 2 is set and VBAT8 is below a non-zero trigger level, EVENT3 bit 4 (level 0x94) or bit 5 (level 0x95) is raised once until the trigger is written or re-armed.

### 2.3 Clock

- 48-bit count in units of 1/65536 s. Bytes 2-5 (registers 0x5C-0x5F) are the Unix time in seconds; bytes 0-1 (0x5A, 0x5B) are the fraction.
- Value at power-on: 2008-10-20 12:00:00 UTC [MOCK], or the host time when the simulator runs with `EMU_PMIC_RTC=host`, or a number of Unix seconds given in that variable.
- The clock runs with emulated time. A write to one of 0x5A-0x5F replaces that byte of the current count; the count runs on from there.
- The clock is not kept between runs [MODEL].

### 2.4 Converter

- Writing ADC_CONTROL starts and ends a conversion of the channel in bits 3:0. Read 0x74 and 0x75 afterwards.
- Result: a 10-bit code left-aligned in 16 bits (code << 6). Code = round((V - Vlow) x 1023 / (Vhigh - Vlow)), limited to 0-1023.
- What the inputs carry is the phone's board, given by the device profile (`PMIC_ANALOG` in `native/devices/myna/__init__.py`), all values our own [MOCK]: the battery has a 47 kOhm NTC thermistor (B = 4050 K, R = 47 kOhm x exp(4050 x (1/T - 1/298.15 K))) between the battery data contact and ground; the phone's temperature sensor is the same thermistor type below a 47 kOhm pull-up from 1800 mV.

| Channel | Input | Vlow-Vhigh (mV) | Value in the model |
|---|---|---|---|
| 5 | Phone temperature sensor | 0-2500 | 1800 mV x R / (R + 47 kOhm): 900 mV at 25 C [MOCK] |
| 6 | Not known | 0-2500 | 1325 mV [MOCK] |
| 8 | Charger voltage | 0-16000 | 5000 mV with charger, else 0 |
| 9 | Not known | 0-2500 | 0 |
| 10 | Battery voltage | 2500-4500 [MOCK] | 3950 mV (code 742) [MOCK] |
| 11 | Battery data contact (identification and temperature resistor) | 0-2500 | source current x resistor: 470 mV with the 10 uA source at 25 C (47 kOhm), 2103 mV with the 4 uA source at -20 C; 2500 mV (open) with no battery [MOCK] |
| 12 | Not known | 0-2500 | 1975 mV [MOCK] |
| 13 | Signed channel | - | 0x8000 (zero) [MOCK] |
| other | - | 0-2500 | 0 |

The battery-voltage registers 0x7A-0x7E use the channel 10 code.

### 2.5 Power off

Writing register 0x42 with bit 4 = 0 while it was 1 switches off the system supply: the run ends ("powered off by the phone") [VALIDATED]. The simulator option `EMU_POWER_OFF=0` only records it.

## 3. Second register page (I2C0 0x49)

Register-file protocol, storage only, reset 0. Writing register 0x02 = 0x08 selects the 32 kHz clock for the chip's clock on the real part [UNCONFIRMED]; no effect in the model.

## 4. Accelerometer (I2C1 0x1D)

A 3-axis accelerometer, ST LIS302DL [UNCONFIRMED: inferred from its identification value]. Register pointer protocol as 1.3, but the pointer goes up only when bit 7 of the pointer byte is 1 (auto-increment); the pointer is 7 bits.

| Register | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| 0x0F | WHO_AM_I | R | 0x3B | [VALIDATED] |
| 0x20 | CTRL_REG1 | RW | 0x07 | Bit 6 = active (power-down when 0); bit 5 = full scale (72 mg per digit instead of 18) |
| 0x21, 0x22 | CTRL_REG2, CTRL_REG3 | RW | 0 | Stored |
| 0x27 | STATUS | R | 0 | 0x0F while active (new data on every axis), else 0 |
| 0x29 | OUT_X | R | 0 | Signed 8-bit, 0 while powered down |
| 0x2B | OUT_Y | R | 0 | |
| 0x2D | OUT_Z | R | 0 | |
| other | | RW | 0 | Storage |

- Readings [MOCK]: a phone at rest, 1 g on the axis that points up, set by the viewer's `orientation` switch. Value = g x 1000 / (18 or 72), limited to -128..127.
- Phone axes: x to the right side, y to the top, z out of the screen. Chip axes on the board:

  | Variant | Chip X | Chip Y | Chip Z |
  |---|---|---|---|
  | A | phone +y | phone -x | phone +z |
  | B | phone -x | phone -y | phone +z |

- `orientation` states: upright (y up), side (x up), side_other (-x up), flat (z up), face_down (-z up). Start: upright.
- The chip's interrupt pins are not connected.

## 5. FM tuner (I2C1 0x10)

A Silicon Labs Si470x-family FM tuner [UNCONFIRMED: inferred]. No sound and no stations are modelled.

Bus protocol (no register pointer): a write transfer fills the 16-bit registers 0x02, 0x03, 0x04, ... in order, high byte first. A read transfer returns registers 0x0A, 0x0B, ..., 0x0F, 0x00, 0x01, ... in order, high byte first. Registers 0x0A-0x0F, 0x00, 0x01 are read-only.

| Register | Name | Meaning in the model |
|---|---|---|
| 0x00 | DEVICE_ID | 0x1242 [MOCK] |
| 0x01 | CHIP_ID | 0x1253 when powered, 0x1200 when not [MOCK] |
| 0x02 | POWER_CONFIG | Bit 0 ENABLE, bit 6 DISABLE: powered when bit 0 = 1 and bit 6 = 0. Bit 8 = seek. |
| 0x03 | CHANNEL | Bit 15 = tune, bits 9:0 = channel |
| 0x04 | SYSCONFIG1 | Bit 14 = seek/tune-complete interrupt enable; bits 3:2 = 01: the interrupt pin signals completion |
| 0x05-0x09 | | Stored |
| 0x0A | STATUS_RSSI | Bit 14 = seek/tune complete (STC), bit 13 = seek failed / band limit. RSSI 0, no stereo, no RDS. |
| 0x0B | READ_CHANNEL | Bits 9:0 = channel after a tune |

- Tune: with the chip powered, set CHANNEL bit 15. 60 ms later [MOCK] STATUS_RSSI bit 14 is set and READ_CHANNEL = channel. Clearing the tune bit clears bits 14 and 13.
- Seek: set POWER_CONFIG bit 8. 60 ms later STATUS_RSSI bits 14 and 13 are set: no station is ever found. Clearing the bit clears them.
- Interrupt pin: at completion, if SYSCONFIG1 bit 14 = 1 and bits 3:2 = 01, the pin goes low for 5 ms [MOCK]. On variant B the pin is GPIO bank 0 pin 0. On variant A it is not connected to anything: poll STATUS_RSSI.

## 6. Port expander (I2C1 0x58 and 0x68)

A MAX7327 port expander with two addresses. What its pins drive on the phone is not known.

- 0x58 (open-drain ports P2-P5): a write stores the byte as the output latch. A read returns (latch & inputs & 0x3C), then the transition flags (0), alternately. External inputs are 1 [MOCK].
- 0x68 (push-pull outputs): a write stores the first byte as outputs 0-7 and the second as outputs 8-15, alternately. A read returns them in the same order. Reset 0xFF, 0xFF.

## 7. Illumination driver (I2C1 0x4A)

- Write only: one or more single-byte commands per transfer. A read is not acknowledged (AF).
- The model splits each byte into a command and a value: if bits 7:5 are 001, 010, 011, 100 or 110, the command is bits 7:5 and the value bits 4:0; otherwise the command is bits 7:4 and the value bits 3:0. It stores the last value of each command. Nothing else happens.
- The part and the meaning of the commands are not known. It drives the display and key lights [UNCONFIRMED].

## 8. Flash-LED driver (variant B only, I2C1 0x53)

A TI LM3554 flash-LED driver. Register-file protocol (1.3), storage only, all registers reset to 0 [MOCK].

## 9. SPI master, base 0xC0006000

Register layout of the ARM PrimeCell PL022 (SSP). Line 23. One chip: the multimedia chip (section 10).

| Offset | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| +0x00 | CR0 | RW (16 bits) | 0 | Frame format. Stored: frames are always 16 bits in the model. Use 0x000F (16-bit frames, SPI format, mode 0). |
| +0x04 | CR1 | RW (4 bits) | 0 | Bit 1 SSE (enable). A change 0 -> 1 selects the chip and sends the frames queued in the transmit FIFO. A change 1 -> 0 deselects the chip. |
| +0x08 | DR | RW | 0 | Write: one 16-bit frame. With SSE = 1 it is sent at once and the frame clocked back goes into the receive FIFO. With SSE = 0 it waits in the transmit FIFO (8 frames; more are dropped). Read: the oldest received frame, 0 if empty. |
| +0x0C | SR | R | 0x03 | Bit 0 TFE = 1, bit 1 TNF = 1, bit 2 RNE (receive FIFO not empty), bit 3 RFF (8 frames), bit 4 BSY = 0. |
| +0x10 | CPSR | RW (8 bits) | 0 | Clock prescaler. No effect. |
| +0x14 | IMSC | RW (4 bits) | 0 | Interrupt mask: bit 0 overrun, bit 1 receive timeout, bit 2 receive, bit 3 transmit |
| +0x18 | RIS | R | 0x08 | Bit 0 overrun; bit 1 receive timeout = receive FIFO not empty (at once [MODEL]); bit 2 = 4 or more frames received; bit 3 = 1 always |
| +0x1C | MIS | R | 0 | RIS & IMSC |
| +0x20 | ICR | W | - | Bit 0 clears the overrun |
| +0x24 | DMACR | RW (2 bits) | 0 | Bit 0 receive DMA, bit 1 transmit DMA |
| +0xFE0-+0xFFC | IDs | R | 0x22, 0x10, 0x34, 0x00, 0x0D, 0xF0, 0x05, 0xB1 | PrimeCell identification |

- Line 23 is high while MIS is not 0.
- A ninth received frame is lost and sets the overrun bit.
- There is no bit timing: transfers complete at once [MODEL].
- Chip select: on the phone the chip select is GPIO bank 0 pin 5 (active low). The model ignores the pin and treats each SSE period (CR1 bit 1 set, then cleared) as one chip-select period. REQUIRED: set SSE at the start of each transaction and clear it at the end. Driving the GPIO pin as well is harmless.

DMA (see `13-dma.md`):

- DR (0xC0006008) is a DMA port. Transmit: the DMA channel may write while SSE = 1 and DMACR bit 1 = 1; bytes are taken as 16-bit frames, low byte first in memory. Receive: while DMACR bit 0 = 1, received frames go to a DMA buffer instead of the receive FIFO, and a receive channel with source 0xC0006008 takes them (2 bytes per frame, low byte first). Clearing DMACR bit 0 drops what is in that buffer.
- IMSC (0xC0006014) is also a DMA port: a DMA item that writes 2 or more bytes there sets IMSC from the first two bytes.

## 10. Multimedia chip (SPI)

A companion processor that decodes video and sends the pictures to the camera interface of the display controller (`12-video-camera-other.md`). Its type and maker are not known.

Interface at the pins:

- 16-bit SPI frames. Chip select: see section 9.
- Interrupt request: GPIO bank 2 pin 0, active low (1 = idle).
- Register write: one SSE period with two frames: 0x8000 | r, then the 16-bit value.
- Register read: one SSE period with one frame r (bit 15 = 0); then a second SSE period with one dummy frame (0xFFFF): the frame clocked back during it is the value.

| Register | Meaning |
|---|---|
| 0x0A | Identification. Reads 0x012F. A firmware should check (value & 0x033F) == 0x012F. |
| 0x20 | Power and output latch: bit 7 = 26 MHz clock stopped, bit 6 = one supply on, bit 5 = PLL / core supply on, bit 4 = a level output to the chip (on = 1), bits 3:0 = four general outputs. The chip runs only while bits 7:4 = 0111. 0x0080 = clock stopped, all off (sleep). Reset 0. |
| other | Storage, read 0 |

Message port and video service: the chip has no program of its own; the host must download one into it at every power-up, and the chip then talks through a message port (register 0) in a protocol defined by that program. Section 12 describes that protocol as the model implements it. A firmware that does not use video should write 0x0080 to register 0x20 (chip asleep) and leave the chip alone; the stock software does this at start after checking register 0x0A.

## 11. Stock driver notes [STOCK]

I2C masters:

- Two drivers: the first-stage loader polls; the main software has one process per bus with an interrupt handler behind it. The bus process switches the controller's clock on for a transfer and off again after 5 ms without one.
- The loader's first hardware action, 5.6 ms after reset, is one write to the power chip on I2C0.

Power-management chip (0x48):

- Reads CHIP_ID first. Accepts 0xC2-0xC8 (printed as revisions P1C-P2B); stops for 0xC0 and 0xC1.
- Writes 0x02 = 0x08 to the second page (0x49) to select the 32 kHz clock (chip revisions 0xC4-0xC8).
- Writes the masks: 0x24 = 0x00, 0x25 = 0xFF, 0x26 = 0x01. With EVENT2 masked, a battery removal or an alarm is seen only with the next EVENT1 event.
- The interrupt handler masks line 0 and signals the driver; the driver reads 0x21-0x23 and 0x27 in one transfer and unmasks line 0 again. The read is also the acknowledgement. During operation the power-key event is ignored (only the start cause counts).
- Uses the registers through its own table of logical registers (191 entries with physical register, copy and access flags).
- Clock: reads 0x53; if bit 0 (time valid) is 0 it sets the time to its default and reports a power failure. Reads 0x5A-0x5F for the time.
- Converter: writes the channel to 0x73 and reads 0x74/0x75 in the next transfer (no start or ready signal). Battery identification: source 142 uA or 75 uA into the battery data contact (0x52 = 3 or 7), channel 11, R = mV x 10000 / I (the ranges that mean a battery type are the firmware's own choice; Myna uses its own); the same resistor is a thermistor for the battery temperature. Battery voltage from the automatic registers 0x7A-0x7E, calibrated per phone (this phone: 2650 mV at code 0, 4420 mV at full scale). Low-battery warning: trigger levels in 0x94/0x95, armed with 0x79 bit 2, events EVENT3 bits 4/5.
- Charger and USB: STATUS bits 3 and 7 for the levels, EVENT1 bits 3 and 6 for changes.
- Power off: 0x42 = 0 (see `07-gpio-power.md`).

Other I2C1 chips:

- Illumination driver 0x4A: write only, one command byte per transfer; first write about 4 s after power-on. Commands 0x20, 0x40, 0x60, 0x80 carry a 5-bit value; 0x00, 0xE0, 0xF0 a 4-bit value; 0xC0 a 5-bit value. Meanings not known.
- Port expander: write only, 0x00 to one address and 0x0C to the other, about 4 s after power-on.
- Accelerometer: reads WHO_AM_I and requires 0x3B. Nothing else until an application needs it: then CTRL_REG1 = 0x47 (active), five bytes read from 0x29 with auto-increment (OUT_X, -, OUT_Y, -, OUT_Z) every 50 ms, used as x = -OUT_Y, y = OUT_X, z = OUT_Z in mg (18 mg per digit, 70 with full scale); CTRL_REG1 = 0x07 again after 30 s without use. The interrupt pins are not used.
- FM tuner: at start one 10-byte write that powers it down: registers 0x02 = 0x0041 (ENABLE and DISABLE), 0x03 = 0, 0x04 = 0x0004 (GPIO2 = interrupt), 0x05 = 0, 0x06 = 0. For a tune or seek it sets the bit, waits for the interrupt pin, reads the status and clears the bit; band = bits 7:6 of register 0x05.

SPI master:

- CR0 = 0x000F (16-bit frames, SPI, mode 0), CPSR = 2. At the start of every transfer: chip select low (GPIO bank 0 pin 5), CR1 = 2 (SSE); at the end CR1 = 0 and chip select high.
- Polled frames: wait for RIS bit 3 before each write to DR; read the frame that came back (SR bit 2); wait for BSY clear (at most 0x65 tries).
- DMA path for every message to the multimedia chip: a transmit chain memory -> DR and for a read a receive chain DR -> memory, then DMACR. A transmit-only transfer ends with a DMA item that writes IMSC = 2 (receive timeout); the interrupt then comes and the handler clears IMSC bit 1 and drains DR. A read ends with the receive channel's terminal count; the driver then requires TFE = 1, RNE = 0 and no overrun (ICR = 1 after a DMA receive).

## 12. Multimedia chip message protocol (simulator model) [STOCK, MODEL]

This is the protocol that the stock software and the chip's program use. The model implements it. On a real phone it needs the chip program that the stock software downloads (a file of the stock firmware, about 117 KB), which a clean firmware cannot use. In the simulator the model does not run the downloaded bytes: it only counts them. So in the simulator a clean firmware can use the video decoder with any bytes as the "program" (see `90-gaps.md`, G16). Decoding needs the FFmpeg libraries on the host; without them the pictures are black.

### 12.1 Transport

- Message to the chip: one SSE period: a 32-bit header word whose bits 15:0 are 0x8000 and bits 27:16 the message length in bytes including the header, then the payload. Sent as 16-bit frames, low half first (the bytes in memory order). The stock software sends it by DMA.
- Message from the chip: the chip pulls its interrupt pin low. The host sends a 0x80-byte block whose header has bits 15:0 = 0x0000 and length 0x80 (one SSE period). The chip then pulls the pin low again (after 100 us in the model). The host reads, in one SSE period, 0x80 bytes with dummy frames 0xFFFF, takes the length from bits 27:16 of the first word, and reads the rest in the same period. Messages from the chip are at least 0x80 bytes.
- Selecting the chip (SSE 0 -> 1) releases a pending request on the pin [MODEL].

### 12.2 Start-up

1. Write register 0x20 with bits 7:4 = 0111 (clock running, supplies on). 2 ms later the chip makes request 1 (pin low, no message to fetch).
2. Send the configuration message (36 bytes in the stock software; the model ignores its content). The chip makes request 2.
3. Send the program in messages (0x400 bytes each in the stock software). The first 12 bytes of the program are a header: word 0 = 0, word 1 = number of bytes after the header, word 2 = 0. When the chip has received header + that many bytes it makes request 3: it is running.

Writing register 0x20 with bits 7:4 not 0111 switches the chip off; it forgets its state.

### 12.3 Messages while running

Word layout (32-bit words, w0 = header):

| Word | Meaning |
|---|---|
| w1 | bits 31:28 flags, bits 20:16 class, bits 15:0 length in bytes from w1 to the end |
| w2 | 0 |
| w3 | bits 15:0 message id |
| w4... | parameters |

Requests (host to chip, class 5); each is answered with id + 0x100, class 2, w4 = 0 (status):

| Id | Function | Parameters |
|---|---|---|
| 0x1000 | Close | |
| 0x1001 | Set up a session | w4 = codec: 6 MPEG-4 part 2, 7 H.264 (other values: guessed from the stream) |
| 0x1002 | Start | |
| 0x1003 | Stop | |
| 0x1004 | Picture request: output the next decoded picture | w4 = mode (4: full raster, picture turned a quarter if its orientation differs; 2: upright picture of size w10 x w11 at the raster's origin, rest black); w5 = raster pixels per line, w6 = raster lines; w10, w11 = picture size |
| 0x1005 | Pause | |
| 0x1006 | (answered, no other effect) | |
| 0x1007 | Resume | |

Stream data (host to chip): w1 bit 31 = 1, w1 bits 15:0 = length from w1; w1 bit 30 = 1 on the last message of an access unit; w2 = the access unit's time stamp in ms; the data start at byte 12 of the message, at most 2036 bytes per message. A message with no data = end of stream.

Events (chip to host, class 2):

| Id | Meaning |
|---|---|
| 0x1200 | Send stream (the chip holds fewer than 2 decoded pictures) |
| 0x1201 | A picture is ready (send 0x1004) |
| 0x1203 | Play finished (end of stream, all pictures output) |
| 0x1104 | Answer to 0x1004 after the picture went out. Parameters from w4: +0x00 source height, +0x04 source width, +0x08 / +0x0C the same again, +0x1C type (0x10 intra, 0x08 predicted), +0x40 and +0x44 the raster (pixels per line, lines), +0x50 / +0x54 the valid part, +0x58 the picture time in ms. |

The picture leaves through the chip's picture port into the camera interface of the display controller (`12-video-camera-other.md`): arm the capture with the raster size and FRAME_BYTES = pixels x lines x 3 / 2 (planar YUV 4:2:0). If the capture is not armed, the picture is lost. The model's raster defaults to 240 x 320 when the camera interface gives none.

The stock software sends one access unit per message group, paces the pictures by the time in 0x1104, and shows the stored picture as the display's video plane.
