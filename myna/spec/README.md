# Myna hardware interface specification

This is the hardware interface of the simulated DB3210 phone platform, for a firmware that is written from scratch.
It describes what the simulated hardware does when a program reads and writes it.
It contains interface facts only: addresses, register layouts, bit meanings, interrupt lines, sizes, timing.

The simulated phone has two hardware variants with the same platform: variant A (the default) and variant B, each the hardware of a stock device profile of the simulator. Where they differ, the text says so.
A third device profile, `myna`, is the hardware of variant A with a firmware of our own (loaded from an ELF file, `00-machine.md` section 6); it attaches fewer models (`01-memory-map.md` section 2).

Version: 2026-10-14. Written from the simulator's models and checked with small clean test programs on both CPU engines.

## Files

| File | Content |
|---|---|
| `00-machine.md` | The CPU, the two CPU engines, exceptions, the MMU, caches and TCM, emulated time, idle, the state at entry, the boot contract |
| `01-memory-map.md` | All memory and device windows, and what an unclaimed address does |
| `02-uart.md` | The debug console |
| `03-interrupts.md` | The two interrupt controllers and every interrupt line |
| `04-timers-clock.md` | The OS timer (the only timer that works), the other timers, the real-time clock, the system controller and the clock block |
| `05-display.md` | The display path from a framebuffer in RAM to the 240 x 320 panel |
| `06-keypad.md` | The keypad controller and the key positions of both phones |
| `07-gpio-power.md` | The GPIO block, the pins that are wired, power on and power off, light, vibration |
| `08-i2c-spi-chips.md` | The I2C masters, the SPI master and every chip behind them |
| `09-audio.md` | Sound output and the audio blocks |
| `10-storage-nand.md` | The NAND flash controller and chip, the ECC engine, the memory-card host |
| `11-modem-link.md` | The link block between the two processors (hardware level only) |
| `12-video-camera-other.md` | Camera interface, video blocks, and the parts that are not modelled |
| `13-dma.md` | The DMA controller |
| `14-modem-at.md` | The AT modem of the `myna` profile: the link channel, the 27.010 multiplexer, the AT commands, text messages |
| `90-gaps.md` | What a clean firmware needs and the models do not give, with suggested model changes |

`SOURCES.md` and `LOG.txt` in the same folder are working files of the writer for the coordinator. They are not part of the specification.

## Conventions

- Numbers that start with `0x` are hexadecimal. A register is named by its address, or by the base of its block and an offset (`+0x18`).
- Register names in this document are descriptive names chosen for this document.
- Bit 0 is the least significant bit. A field `bits 4:0` holds bits 4 to 0.
- All memory is little-endian.
- Access codes in register tables:

  | Code | Meaning |
  |---|---|
  | R | Read only. A write has no effect. |
  | W | Write only. A read gives 0 unless the table says otherwise. |
  | RW | Read and write. A read gives the last value written unless the table says otherwise. |
  | W1C | Write 1 to a bit to clear it. Writing 0 has no effect. |
  | W1S | Write 1 to a bit to set it. Writing 0 has no effect. |
  | S | Storage only: the value is kept and has no effect in the model. |

- "Reset value" is the value at the start of a run.
- "Line N" is interrupt line N of the interrupt controller pair (0 to 63). See `03-interrupts.md`.
- "Emulated time" is the time of the simulated phone. It starts at 0 when the CPU starts. See `00-machine.md`.

## Marks

| Mark | Meaning |
|---|---|
| [MOCK] | A value or a behaviour that the simulator chose. A real phone can be different. A firmware can use it in the simulator, but must not depend on it for a real phone. |
| [UNCONFIRMED] | The writer of this document could not confirm the statement in the model or in a test run. |
| [MODEL] | A simplification of the model that a firmware can see, for example "completes at once". Do not depend on it if the firmware must also run on a real phone. |
| [PROPOSED] | A behaviour that does not exist in the simulator yet. `90-gaps.md` describes the change that it needs. |
| [VALIDATED] | Seen in a test run of a small clean program on the models (both CPU engines), during the writing of this document. |
| [STOCK] | How the phone's original (stock) software drives the device: order, values, timing. For information: it shows a sequence that works on the hardware. The models do not require it unless the text says so. |

## What this document does not contain

- Code, data tables, graphics, sounds, fonts or text of the stock software. ("Stock driver notes" sections describe in words how the stock software drives a device; they copy nothing.)
- The protocol of the stock firmware on the link between the two processors. The stock profiles' modem stand-in speaks it; it is not given here. The `myna` profile has a stand-in with standard protocols instead: `14-modem-at.md`.
- Security functions. Anything that touches them is "not specified (closed area)".

## Glossary

| Term | Meaning |
|---|---|
| application CPU | The ARM926EJ-S processor that runs the firmware described here. |
| modem CPU | The second processor of the platform. The simulator does not execute it. A program of the simulator (the modem stand-in) acts in its place. |
| modem stand-in | The program of the simulator that answers on the modem side of the link. |
| model | The simulator's code for one chip or one block. |
| CPU engine | The code that executes ARM instructions. The simulator has two: Unicorn (the default) and the compiled core (option `--core own`). |
| slice | A group of 20,000 instructions. The simulator runs the CPU one slice at a time and runs the time-driven parts of the models between slices. One slice is 200 us of emulated time. |
| emulated time | Executed instructions x 10 ns, plus the time that the CPU sleeps in wait-for-interrupt. |
| viewer | The web page that shows the screen, plays the sound and sends key presses. |
| run log | The text output of the simulator. |
| GRAM offset | An address in the address space of the display controller: bank number in bits 31:20, offset in bits 19:0. See `05-display.md`. |
| flash state | A file in which the viewer keeps the pages that the firmware programmed or erased, between two runs. |
| input name | The name of a key or switch in the viewer, for example `select` or `slide`. |
