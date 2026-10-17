# 03 Interrupts

## 1. Two interrupt controllers

The platform has two vectored interrupt controllers with the register layout of the ARM PrimeCell PL190.

| Controller | Base | Lines |
|---|---|---|
| VIC0 | 0xA0001000 | 0-31 (bit n = line n) |
| VIC1 | 0xA0002000 | 32-63 (bit n = line 32 + n) |

The IRQ output of the CPU is high while VIC0 or VIC1 has an active IRQ (see section 3). The FIQ output is computed but is not connected to the CPU: an FIQ is never taken.

## 2. Registers (each controller)

| Offset | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| +0x000 | IRQSTATUS | R | 0 | RAWINTR & INTENABLE & ~INTSELECT |
| +0x004 | FIQSTATUS | R | 0 | RAWINTR & INTENABLE & INTSELECT |
| +0x008 | RAWINTR | R | 0 | Source lines OR SOFTINT, before enable |
| +0x00C | INTSELECT | RW | 0 | 1 = the line is an FIQ source. Keep 0: an FIQ is never delivered, and a line selected as FIQ is removed from IRQSTATUS. |
| +0x010 | INTENABLE | W1S, read = current enable | 0 | Enable lines |
| +0x014 | INTENCLEAR | W1C (of INTENABLE) | - | Disable lines |
| +0x018 | SOFTINT | W1S, read = current | 0 | Software interrupt: raises the line as if its source were high |
| +0x01C | SOFTINTCLEAR | W1C (of SOFTINT) | - | |
| +0x020 | PROTECTION | RW, bit 0 | 0 | S: no effect |
| +0x030 | VECTADDR | R / W | 0 | See section 4. |
| +0x034 | DEFVECTADDR | RW | 0 | Value read from VECTADDR when no vectored interrupt is active |
| +0x100-+0x13C | VECTADDR0-15 | RW | 0 | Vector value of slot 0-15 (any 32-bit value) |
| +0x200-+0x23C | VECTCNTL0-15 | RW, bits 5:0 | 0 | Bit 5 = slot enabled, bits 4:0 = line number within this controller |
| +0xFE0-+0xFEC | PERIPHID0-3 | R | 0x90, 0x11, 0x04, 0x00 | PrimeCell identification |
| +0xFF0-+0xFFC | PCELLID0-3 | R | 0x0D, 0xF0, 0x05, 0xB1 | PrimeCell identification |
| other | - | R | 0 | |

## 3. Behaviour

- All lines are level-sensitive. A line stays high until the device that drives it is serviced. Each device file says what clears its line.
- A controller asserts IRQ when IRQSTATUS is not 0, unless the priority logic (section 4) holds it off.
- The CPU takes the IRQ at an instruction boundary while CPSR.I = 0 (see `00-machine.md`, sections 5.1 and 5.4 for latency and for a source that stays high).

Simplest use (recommended):

1. Leave all VECTCNTL slots at 0 (no vectored interrupts). Then the priority logic is never active.
2. Enable the wanted lines in INTENABLE of both controllers.
3. In the IRQ handler read IRQSTATUS of VIC0 and of VIC1, service every source whose bit is set (the service clears its line), and return.

## 4. Vectored interrupts and priority

This logic follows the PL190. A firmware does not need it.

- Slot i is active when VECTCNTL i bit 5 = 1 and IRQSTATUS bit (VECTCNTL i bits 4:0) = 1. Slot 0 has the highest priority.
- A read of VECTADDR returns VECTADDR i of the active slot with the highest priority and marks that slot "in service". While a slot is in service, the controller holds off: active slots of lower priority (higher number), and all non-vectored lines. Slots of higher priority still assert the IRQ.
- A write (any value) to VECTADDR ends the service of the slot read last.
- Chain: VIC1 is chained behind VIC0. A read of VIC0 VECTADDR when VIC0 has no active slot returns the vector of the active slot of VIC1 with the highest priority (and marks it in service in VIC1), or VIC0 DEFVECTADDR when VIC1 has none. A write to VIC0 VECTADDR ends the service in VIC0, or in VIC1 when VIC0 has nothing in service.

## 5. Interrupt lines

"Raised" says whether a model drives the line in the simulator.

| Line | Source | Raised | Cleared by |
|---|---|---|---|
| 0 | Power-management chip interrupt | Yes | Reading the chip's event registers, or masking the events (`08-i2c-spi-chips.md`) |
| 1 | External interrupt 1 | No | |
| 2 | DMA controller: terminal count or error of any channel | Yes | DMA TC clear register (`13-dma.md`) |
| 3, 4 | Video encoder 0, 1 | No (not modelled) | |
| 5 | Link: receive | Yes | `11-modem-link.md` |
| 6 | Link: transmit | Yes | `11-modem-link.md` |
| 7 | - | No | |
| 8 | Link: wake-up from the modem side | Yes | `11-modem-link.md` |
| 9 | - | No | |
| 10 | I2S0 | No | |
| 11 | - | No | |
| 12 | I2S1 | No | |
| 13 | Display controller: bus/memory controller | No | |
| 14 | Display controller: camera data interface | Yes (bit never set by the model) | `12-video-camera-other.md` |
| 15 | Display controller: camera interface controller (frame stored) | Yes | `12-video-camera-other.md` |
| 16 | - | No | |
| 17 | Display controller: panel bus engine | No | |
| 18 | Display controller: refresh controller (update done) | Yes | `05-display.md` |
| 19 | Display controller: 2D accelerator | No | |
| 20 | Display controller: motion-compensation / inverse-DCT block | Yes, profile of variant B only | `12-video-camera-other.md` |
| 21 | Sound-synthesis block | No | |
| 22 | UART | No | |
| 23 | SPI master | Yes | `08-i2c-spi-chips.md` |
| 24-27 | General timers 0-3 | No | |
| 28 | OS timer event 0 | Yes | `04-timers-clock.md` |
| 29 | OS timer event 1 | No | |
| 30 | Keypad: key down | Yes | `06-keypad.md` |
| 31 | Keypad: all keys up | Yes | `06-keypad.md` |
| 32-36 | GPIO bank 0-4 | Yes | `07-gpio-power.md` |
| 37 | Watchdog | No (no watchdog model) | |
| 38 | Event history | No | |
| 39 | Memory Stick | No | |
| 40, 41 | Memory-card host | No | |
| 42 | I2C0 master | Yes | `08-i2c-spi-chips.md` |
| 43 | I2C1 master | Yes | `08-i2c-spi-chips.md` |
| 44 | Real-time clock alarm | Yes | `04-timers-clock.md` |
| 45 | NAND controller | No | |
| 46 | - | No | |
| 47 | System controller | No | |
| 48-63 | - | No | |

The source names of lines that no model raises are given for information only [UNCONFIRMED]; nothing in the simulator drives them.

## 6. Stock driver notes [STOCK]

- The stock software does not use the PL190 priority logic as intended. It writes small numbers (not handler addresses) into some VECTADDR slots. Its interrupt entry reads IRQSTATUS of both controllers and VECTADDR of VIC0; if that gives a number it uses it, otherwise it takes the lowest pending line. Lines without a slot (for example the OS timer) take the second way.
- Priorities are in software: 32 levels and a mask table per controller. At each level change it disables all lines (INTENCLEAR) and enables the lines that the new level allows.
- It selects one line as FIQ: line 37 (watchdog). The simulator never delivers it.
- Its priority numbers per line (lower = more urgent): 0: 9, 2: 1, 3-4: 4-5, 5/6/8: 17, 10/12: 20, 13-15: 26/24/26, 17-20: 25/26/26/26, 21: 26, 22: 16, 23: 26, 24-27: 19, 28-29: 28, 30-31: 30, 32-36: 31, 37: 16, 38-39: 23, 40-41: 31, 42-43: 30, 44: 27, 45: 28, 47: 16.
