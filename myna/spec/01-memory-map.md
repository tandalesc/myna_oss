# 01 Memory map

Physical addresses of the application CPU.

## 1. Memory

| Address | Size | Content | Notes |
|---|---|---|---|
| 0x00000000-0x0000FFFF | 64 KB | TCM | Ordinary RAM. The exception vectors are here (low vectors). |
| 0x28000000-0x28DFFFFF | 14 MB | Shared memory window | RAM. On the real platform the modem CPU sees this memory too. In the simulator with the modem stand-in, nothing else uses it. Size [MOCK]. Do not depend on it. |
| 0x48000000-0x4BFFFFFF | 64 MB | SDRAM | Main memory. Size [MOCK]: chosen by the simulator. |
| 0xD0100000-0xD010FFFF | 64 KB | Display controller internal RAM (GRAM bank 0) | See `05-display.md`. |

## 2. Device windows

| Address | Size | Block | Lines | File |
|---|---|---|---|---|
| 0x60000000-0x6FFFFFFF | 256 MB | NOR flash window: no chip. Reads give 0. | - | - |
| 0x80000000-0x8000FFFF | 64 KB | NAND data port | - | `10-storage-nand.md` |
| 0x80010000-0x8001FFFF | 64 KB | NAND command latch | - | `10-storage-nand.md` |
| 0x80020000-0x8002FFFF | 64 KB | NAND address latch | - | `10-storage-nand.md` |
| 0x9F800000-0x9F800FFF | 4 KB | NAND controller | 45 (never raised) | `10-storage-nand.md` |
| 0xA0001000-0xA0001FFF | 4 KB | Interrupt controller 0 (lines 0-31) | - | `03-interrupts.md` |
| 0xA0002000-0xA0002FFF | 4 KB | Interrupt controller 1 (lines 32-63) | - | `03-interrupts.md` |
| 0xA0004000-0xA0004FFF | 4 KB | Clock block | - | `04-timers-clock.md` |
| 0xC0001000-0xC0001FFF | 4 KB | Memory-card host (no card) | 40, 41 (never raised) | `10-storage-nand.md` |
| 0xC0002000-0xC0002FFF | 4 KB | I2S0 | 10 (never raised) | `09-audio.md` |
| 0xC0003000-0xC0003FFF | 4 KB | I2S1 (sound output) | 12 (never raised) | `09-audio.md` |
| 0xC0004000-0xC0004FFF | 4 KB | I2C0 master (internal bus) | 42 | `08-i2c-spi-chips.md` |
| 0xC0005000-0xC0005FFF | 4 KB | I2C1 master (external bus) | 43 | `08-i2c-spi-chips.md` |
| 0xC0006000-0xC0006FFF | 4 KB | SPI master | 23 | `08-i2c-spi-chips.md` |
| 0xC0011000-0xC0011FFF | 4 KB | System controller | 47 (never raised) | `04-timers-clock.md` |
| 0xC0013000-0xC0013FFF | 4 KB | Console UART | 22 (never raised) | `02-uart.md` |
| 0xC0014000-0xC0014FFF | 4 KB | Four general timers (storage only) | 24-27 (never raised) | `04-timers-clock.md` |
| 0xC0015000-0xC0015FFF | 4 KB | Keypad controller | 30, 31 | `06-keypad.md` |
| 0xC0016000-0xC0016FFF | 4 KB | GPIO, 5 banks | 32-36 | `07-gpio-power.md` |
| 0xC0017000-0xC0017FFF | 4 KB | Real-time clock | 44 | `04-timers-clock.md` |
| 0xC001A000-0xC001AFFF | 4 KB | OS timer | 28 (29 never raised) | `04-timers-clock.md` |
| 0xC0020000-0xC0020FFF | 4 KB | DMA controller | 2 | `13-dma.md` |
| 0xC0022000-0xC0023FFF | 8 KB | Link block (to the modem CPU) | 5, 6, 8 | `11-modem-link.md` |
| 0xC0038000-0xC003AFFF | 12 KB | Sound-synthesis block (work memory and command port) | 21 (never raised) | `09-audio.md` |
| 0xC0040000-0xC0047FFF | 32 KB | Signal-processing block ("AVE") | - | `09-audio.md` |
| 0xD0000000-0xD01FFFFF | 2 MB | Display controller ("XGAM") | 13-15, 17-20 | `05-display.md` |

Which models exist depends on the device profile. The blocks above are attached for the stock profiles of both hardware variants (README.md), except:

- The display controller is attached only when the simulator runs with a display (the viewer always does).
- The motion-compensation and inverse-DCT block inside the display controller (`12-video-camera-other.md`) is attached in the profile of variant B only.
- The `myna` profile (a firmware of our own, `00-machine.md` 6.2) does not attach the NAND chip and controller (yet) and the SPI master: those windows then read 0.

## 3. Unclaimed addresses

| Address | Behaviour |
|---|---|
| In a device window (0x60000000-0x6FFFFFFF, 0x80000000-0x9FFFFFFF, 0xA0000000-0xAFFFFFFF, 0xC0000000-0xCFFFFFFF, and 0xD0000000-0xD01FFFFF with the display) with no model | A read gives 0. A write is ignored. The simulator logs the first access of each kind. No abort. |
| A register offset of a model that the model does not know | Usually storage: a read gives the last value written, else 0. See each file. |
| Any other address that is not memory | Becomes zero-filled RAM at the first data access. No abort. The simulator logs the first access of each 4 KB page. |
| Instruction fetch from an address that is not memory | The run stops. |

A real phone gives a bus error or garbage for most of these. Do not depend on them.

## 4. Access sizes

- Models get 1, 2 or 4 byte accesses. LDM, STM, LDRD and STRD reach a model as one 4-byte access per word, in ascending address order.
- Use 32-bit accesses to 32-bit registers.
- Exceptions: the keypad and GPIO registers are 16-bit registers (16-bit or 32-bit accesses both work); the NAND command and address latches take 8-bit writes; the NAND data port takes 8, 16 or 32-bit accesses (`10-storage-nand.md`).
- On the compiled core, the system controller keeps one value per byte address: a word written at +0x28 is not what a read at +0x29 gives. Use aligned 32-bit accesses there.
