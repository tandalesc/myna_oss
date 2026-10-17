# 07 GPIO, power, light and vibration

## 1. GPIO block, base 0xC0016000

Five banks of 8 pins. Bank n starts at 0xC0016000 + 0x30 x n. 16-bit registers (16-bit or 32-bit accesses). Line 32 + n belongs to bank n.

### 1.1 Registers of bank n (offset from the bank start)

| Offset | Name | Width | Access | Reset | Meaning |
|---|---|---|---|---|---|
| +0x00 (bank 0 only, = 0xC0016000) | CONTROL | 16 | S | 0 | No effect. |
| +0x04 | DATA_IN | 8 | R | external levels (section 1.3) | Pin levels: for an output pin its DATA_OUT bit, for an input pin the external level. Writes are ignored. |
| +0x08 | DATA_OUT | 8 | RW | 0 | Output latch. |
| +0x0C | DIRECTION | 16 | RW | 0 | Two bits per pin (pin p at bits 2p+1:2p): 01 = output, 00 = input. Values 10 and 11 act as input in the model; their meaning on the hardware is not known. |
| +0x10 | - | 16 | S | 0 | Pin function select (presumed). No effect. |
| +0x14 | IRQ_STATUS | 8 | R, W1C | 0 | Bit p = an interrupt of pin p is pending. |
| +0x18 | IRQ_ENABLE | 8 | RW | 0 | Bit p = pin p may interrupt. |
| +0x1C | - | 16 | S | 0 | No effect. |
| +0x20 | IRQ_POLARITY | 8 | RW | 0 | Bit p = 1: the pin interrupts when it becomes high; 0: when it becomes low. |
| +0x24 | - | 16 | S | 0 | No effect. |
| 0xC00160F0 and above | - | | S | 0 | |

### 1.2 Interrupts

- IRQ_STATUS bit p is set when: the external level of pin p changes, pin p is an input, IRQ_ENABLE bit p = 1, and the new level equals IRQ_POLARITY bit p (edge detection) [MODEL: inferred edge type].
- A change made by the firmware through DATA_OUT never sets IRQ_STATUS.
- Line 32 + n is high while (IRQ_STATUS & IRQ_ENABLE) of bank n is not 0. Clear with a write of 1 to the bit in IRQ_STATUS.
- To catch both edges: after each interrupt, set IRQ_POLARITY bit p to the opposite of the level just read.
- A pin that is already at the selected level when IRQ_ENABLE is set does not interrupt until it changes.

### 1.3 Pins that are wired

| Bank | Pin | Direction | Function | Levels | Level at power-on |
|---|---|---|---|---|---|
| 0 | 0 | input | Variant B: FM tuner interrupt (`08-i2c-spi-chips.md`) | 1 = idle, low pulse of 5 ms at the end of a tune or seek. Variant A: not wired. | Variant B: 1. Variant A: 0. |
| 0 | 3 | input | Variant A: camera lens cover | 1 = closed, 0 = open | 1 (closed) [MOCK] |
| 0 | 4 | input | Slide | Variant A: 1 = closed, 0 = open. Variant B: 0 = closed, 1 = open. | closed [MOCK] |
| 0 | 5 | output | Chip select of the multimedia chip, active low. The model of the chip does not look at this pin: see `08-i2c-spi-chips.md`. | | - |
| 1 | 4 | input | Memory Stick card detect, active low | 1 = no card. A card cannot be inserted. | 1 |
| 2 | 0 | input | Interrupt request of the multimedia chip, active low | 1 = idle | 1 (when the SPI model is attached) |
| 3 | 1:0 | input | Board ID strap of the Myna boards, tied by resistors: 00 = P2 chin slider, 01 = P2 flip (its lid's switch is pin 4 of bank 0, with the slide's levels); 10 and 11 not given out. Read once at start. | fixed | the device profile's `GPIO_STRAPS` [MOCK]: 00 unless it says otherwise (the flip: `{(3, 0): 1}`) |

Every other input pin reads 0. External levels at power-on: bank 0 = 0x18 on variant A [VALIDATED], 0x09 on variant B; bank 1 = 0x10; bank 2 = 0x01 (with the SPI model); banks 3 and 4 = 0.

## 2. Power

### 2.1 Power-management chip

The power-management chip is on I2C0 at address 0x48 (`08-i2c-spi-chips.md`). It supplies the voltages, measures the battery, keeps a clock and reports events on line 0.

### 2.2 Power on

- Power on is the start of a run.
- The chip has event register 1 bit 0 ("power key") set at the start, as the reason for the power-on [MOCK].

### 2.3 Power off [VALIDATED]

- Regulator registers 0x40-0x4B of the chip: bit 4 = regulator on.
- Register 0x42 (regulator "LDO D") is the system supply. Reset value 0x10 (on).
- REQUIRED for power off: write a value with bit 4 = 0 to register 0x42 (for example 0x00). The model records the moment and ends the run: "powered off by the phone". The viewer then shows the phone off and keeps the flash state.
- Before that, finish all flash writes and leave the flash idle (`10-storage-nand.md`, flash state).
- Clearing bit 4 of the other regulators has no effect in the model.

### 2.4 Restart

There is no reset register in the model [UNCONFIRMED: none found]. To restart, the firmware can jump to its entry point. A full power cycle is a power off followed by the viewer's power control.

### 2.5 Battery and charger

See `08-i2c-spi-chips.md`: battery voltage 3950 mV, 25 C, present, no charger, no USB at power-on [MOCK]. The viewer's `charger` and `usb` switches change the chip's status bits and raise its events.

## 3. Light, vibration, LEDs

| Function | Hardware | Model |
|---|---|---|
| Display backlight and key lights | An illumination driver chip on I2C1 at address 0x4A (one-byte commands, `08-i2c-spi-chips.md`) | The commands are stored. No visible effect: the viewer always shows the screen lit. The meaning of the commands is not known. |
| Port expander outputs | MAX7327 on I2C1 at 0x58 / 0x68 | Stored. No visible effect. What its outputs drive is not known. |
| Camera flash LED (variant B) | LM3554 on I2C1 at 0x53 | Register storage. No visible effect. |
| Vibrator | Not known | Not modelled. |
| Indicator LEDs | Not known | Not modelled. |

## 4. Watchdog

Not modelled. Line 37 is never raised. Nothing resets the phone.

## 5. Stock driver notes [STOCK]

- GPIO: all registers are accessed as 16-bit halfwords. Set-up: bank 0 CONTROL bit 0 set (the first-stage loader also sets bit 2); register +0x10 of banks 0-4 written once with 0x73, 0xFE, 0x2E, 0, 0; register +0x1C written 0; the first-stage loader sets bank 1 +0x24 bit 0. DATA_OUT is written whole from a copy in RAM. DIRECTION: 01 output, 00 input.
- "Both edges" is done in software: after each interrupt the driver writes IRQ_POLARITY to the opposite of the level it reported.
- The GPIO interrupt handler scans IRQ_STATUS of all five banks and stops with an assertion if a pending pin has no subscriber. So never leave IRQ_ENABLE set for a pin without a handler.
- With all external pins at 0, the stock software sees a Memory Stick inserted (the detect pin is active low): the levels of section 1.3 matter.
- Power off: the stock shut-down closes the file systems, writes a small block with the stop reason into RAM, and as its last action writes 0 to power-chip register 0x42. The last flash write is about 130 ms before that. If a charger is connected it restarts instead of cutting the power.
- Power-on cause: at start the stock software reads the power chip's event registers. Bit 0 of EVENT1 means "power key", other bits alarm, accessory, charger. With no bit set the cause is "unknown" and the stock software shuts down again 17 ms later; this is why the model latches the power-key bit at power-on.
