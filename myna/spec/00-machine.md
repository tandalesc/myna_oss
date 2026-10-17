# 00 The machine

## 1. Processor

| Item | Value |
|---|---|
| Core | ARM926EJ-S, architecture ARMv5TE |
| Instruction sets | ARM and Thumb. ARMv5TE extensions: CLZ, QADD/QSUB/QDADD/QDSUB, SMLAxy/SMULxy/SMLAWy/SMULWy/SMLALxy, LDRD/STRD, PLD, BLX. |
| Main ID register (CP15 c0, opcode2 0) | 0x41069265 |
| Cache type register (CP15 c0, opcode2 1) | 0x01DD20D2 |
| Endianness | Little-endian only |
| Speed | 100 million instructions per second of emulated time (10 ns per instruction) [MOCK]. The speed does not change with any clock setting. |

The simulator has two CPU engines. A firmware must run on both.

| Engine | How it is selected | Notes |
|---|---|---|
| Unicorn | Default | The Unicorn engine (QEMU) in its ARM926 mode, with exception delivery added by the simulator. |
| Compiled core | `--core own` | An interpreter written for the simulator. Some devices run inside it (OS timer, interrupt controllers, NAND, system controller, clock block); they behave as the other models. |

### 1.1 Not available

| Feature | Behaviour |
|---|---|
| Jazelle (Java byte code state) | Not modelled. BXJ acts as BX on the compiled core. [UNCONFIRMED] on Unicorn. Do not use. |
| VFP and coprocessors other than CP15 | Not present. On the compiled core: undefined-instruction exception. On Unicorn: undefined, and a load/store to such a coprocessor that faults stops the run. Do not use. |
| BKPT | The compiled core stops the run. Unicorn steps over a Thumb BKPT. Do not use. |
| FIQ | Never delivered on either engine. See `03-interrupts.md`. |
| Unaligned access | A word or halfword load from an address that is not aligned returns the bytes at that address, on both engines [VALIDATED]. This is not the ARMv5 behaviour (a real ARM926 rotates the aligned word). Alignment faults (SCTLR.A) are not modelled on the compiled core. Never make unaligned accesses. |

## 2. Exceptions

| Exception | Vector offset | Mode | LR | Notes |
|---|---|---|---|---|
| Reset | 0x00 | - | - | Not used by the simulator. The CPU starts at the entry address (section 6). |
| Undefined instruction | 0x04 | UND (0x1B) | address of the next instruction | [VALIDATED] |
| SWI | 0x08 | SVC (0x13) | address of the next instruction | [VALIDATED] |
| Prefetch abort | 0x0C | ABT (0x17) | faulting address + 4 | IFSR and FSR are written. |
| Data abort | 0x10 | ABT (0x17) | faulting instruction + 8 | FSR (c5) and FAR (c6) are written [VALIDATED: section translation fault gives FSR 0x5, FAR = the address]. |
| IRQ | 0x18 | IRQ (0x12) | next instruction to execute + 4 | Return with `subs pc, lr, #4`. |
| FIQ | 0x1C | - | - | Never taken. |

On entry the CPSR keeps its flags, the mode changes, the I bit is set, the T bit is cleared (ARM state). SPSR of the new mode = old CPSR.

Vector base:

- Use the low vectors (SCTLR bit 13, V, = 0). The vectors are then at virtual address 0x00000000.
- With V = 1, the compiled core takes all exceptions at 0xFFFF0000 + offset. The Unicorn engine takes undefined, SWI and aborts at 0xFFFF0000 + offset, but takes IRQ at virtual address 0x00000018 [VALIDATED]. See `90-gaps.md`, G5.

Aborted instructions:

- A single load or store that faults does not change any register (no base write-back).
- A block transfer (LDM, STM, PUSH, POP, LDRD, STRD) that faults part-way: the words before the faulting word are transferred, the base register keeps its old value.
- A device register is never accessed by an instruction that aborts, on the compiled core. On Unicorn [UNCONFIRMED].

## 3. CP15

| Register | Behaviour |
|---|---|
| c0 | ID and cache type, read only (section 1). |
| c1 control (SCTLR) | Bits that change behaviour: M (bit 0, MMU on), S (bit 8) and R (bit 9) (access permissions), V (bit 13, high vectors: do not use). A (bit 1, alignment check) acts on Unicorn only. C, W, I have no effect. Write the whole register; do not depend on the value of the other bits. |
| c2 TTBR, c3 DACR | Modelled. |
| c5 FSR, c6 FAR | Written by aborts. |
| c7 cache operations | Accepted, no effect (there are no caches). Wait-for-interrupt: `mcr p15, 0, Rd, c7, c0, 4` (section 5). |
| c8 TLB operations | Accepted. Flush the TLB after a change of the translation table, as on hardware. |
| c9 TCM region registers | No effect. Unicorn rejects writes; the simulator steps over them and logs one line. |
| c13 FCSE PID | Modelled on the compiled core. [UNCONFIRMED] on Unicorn. Do not use. |
| c15 | Reads 0, writes ignored. |
| Any CP15 access in user mode | Compiled core: undefined-instruction exception. Unicorn: the access is stepped over and an MRC gives 0 [VALIDATED]. Do not access CP15 in user mode. |

## 4. Memory management, caches, TCM

- The MMU is the ARMv5 MMU: section, coarse and fine tables; large, small and tiny pages; 16 domains; AP bits with S and R. [VALIDATED: 1 MB sections, a remapped section and a translation fault.]
- There are no caches and no write buffer. Cache and write-buffer bits in descriptors and in SCTLR have no effect. Cache maintenance is not needed for DMA, for code written to memory, or for the display.
- TCM: 64 KB of ordinary RAM at physical address 0x00000000. It is not a separate path: with the MMU on, accesses go through the translation table like any other memory. The TCM region registers have no effect.
- With the MMU on, map virtual address 0x00000000 (the vectors) to physical 0x00000000, or put a copy of the vector code where the vector address translates to.
- Device registers can be mapped with any memory attributes.
- DMA engines and the display controller use physical addresses.

## 5. Emulated time and idle

### 5.1 Time

- Emulated time = executed instructions x 10 ns + the time that the CPU spent asleep in wait-for-interrupt.
- The CPU runs in slices of 20,000 instructions (200 us). The time-driven parts of the models (timer events, key input, sound pacing, the modem stand-in) are run between slices.
- Within one slice, every device sees the same time: the time at the start of the slice. A loop that polls a timer register sees it change only at a slice boundary.
- An interrupt that a device raises during a register access is taken after that instruction (if not masked). An interrupt that comes from time (a timer event, a key press) is raised between slices: up to 200 us late.
- Unicorn engine, model artefacts [MODEL]: a slice that ends at a wait-for-interrupt counts as 1 instruction, whatever ran before the wait in that slice; a slice that ends at an abort or an SWI counts as the whole slice. So time on Unicorn can run a little slow or fast compared with the instructions executed. The compiled core counts every instruction exactly.
- Do not measure time by counting instructions. Use the OS timer (`04-timers-clock.md`).

### 5.2 Wait for interrupt

- `mcr p15, 0, Rd, c7, c0, 4` in ARM state is the only idle instruction. The CPU halts until the IRQ input is high. A halt with IRQs masked (CPSR.I = 1) also ends when an interrupt is pending; the CPU then goes on at the next instruction without taking it.
- While the CPU is halted, emulated time jumps to the next scheduled event: an armed OS timer event, an RTC alarm, a scheduled key action, the end of a sound transfer, an event of a chip model, an event of the modem stand-in.
- REQUIRED: if the CPU halts and no event is scheduled anywhere, the simulator ends the run ("idle callback has nothing scheduled" / "nothing scheduled on any CPU") [VALIDATED]. A firmware must keep a wake-up source armed whenever it idles. The simplest is the OS timer in periodic mode (`04-timers-clock.md`). See `90-gaps.md`, G7.

### 5.3 Loops that the simulator treats as a halt

- REQUIRED: do not wait in a branch-to-self instruction (`b .` in ARM or Thumb). When a slice ends on such an instruction and no interrupt is pending, or IRQs are masked, the Unicorn engine ends the run ("halted in branch-to-self loop"). Use wait-for-interrupt.
- A polling loop that only reads memory or device registers (no stores) can be skipped forward by the simulator. The result is the same as executing it.

### 5.4 Interrupt sampling difference between the engines

Interrupt lines are levels. If an interrupt handler returns while its source is still asserted:

- the compiled core takes the interrupt again at once;
- the Unicorn engine takes it again only at the next slice boundary (up to 200 us later) [VALIDATED].

REQUIRED: clear the source of each interrupt in its handler before the handler returns. See `90-gaps.md`, G6.

## 6. State at entry and the boot contract

### 6.1 How the launcher starts a firmware

The committed launcher can only start the stock software from a stock flash image. At the time of writing, a change in the working tree of the repository (not yet committed) adds a second way: a device profile with an ELF file (`BOOT_ELF`, profile `myna`). Section 6.2 describes that way. It was also tested with the existing models and a small clean program loaded as a raw image at 0x48000000 [VALIDATED].

### 6.2 Boot contract

| Item | Value |
|---|---|
| Image | A 32-bit little-endian ARM ELF executable. |
| Loading | Every PT_LOAD segment is copied to its physical address (p_paddr) before the CPU starts; the part of a segment beyond its file size (.bss) is zero-filled. Put the segments in SDRAM (0x48000000-0x4BFFFFFF) or TCM (0x00000000-0x0000FFFF). |
| Entry | The ELF entry address (e_entry), ARM state. Recommended: 0x48000000. |
| Not done | No stock loader, no boot-ROM stand-in, no modem CPU, no modem stand-in. |
| Flash | [PROPOSED] A blank NAND chip of the geometry in `10-storage-nand.md` (all 0xFF), or the flash state of the last run. Until this exists the `myna` profile has no NAND model: the NAND windows read 0 (`90-gaps.md`, G2). |
| Devices | The `myna` profile attaches: power-management and I2C chips, real-time clock, keypad, GPIO, the signal-processing block, I2S, the sound-synthesis block; always the interrupt controllers, OS timer, link, DMA, system controller, clock block, memory-card host and console; the display controller when the run has a display. It does not attach the SPI master and the multimedia chip (the SPI window reads 0). |

### 6.3 CPU state at entry (both today and under the proposed contract)

| Item | Value |
|---|---|
| Mode | SVC (0x13) |
| CPSR I and F | Set (IRQ and FIQ masked) |
| CPSR T | Clear (ARM state) |
| CPSR flags | Not defined. Unicorn: 0x400001D3 (Z set). Compiled core: 0x000000D3 [VALIDATED]. |
| r0-r14, banked registers, SPSRs | 0. There is no stack: set SP of each mode that the firmware uses. |
| SCTLR | MMU off, alignment check off, V = 0. Unicorn: 0x00090078, compiled core: 0x00000000 [VALIDATED]. |
| TTBR, DACR | 0 |
| Memory | SDRAM and TCM hold zeros, except the loaded image. (When the launcher starts the stock software it also writes values for the stock loader at TCM 0x40-0x47 and SDRAM 0x4BFFE000-0x4BFFE02F: not specified (closed area). The ELF way does not write them.) |
| Devices | All at their reset values (see each file). Interrupt controllers: all lines disabled. |
| Emulated time | 0 |

### 6.4 Validated bring-up order

This order worked on both engines with all models attached [VALIDATED]:

1. Set the stack pointers of SVC and IRQ mode (and ABT, UND if used).
2. Write the exception vectors at physical 0x00000000 (for example `ldr pc, [pc, #0x18]` in each of the eight slots and the eight handler addresses at 0x20-0x3C).
3. Optional: build a translation table, write TTBR, DACR, flush the TLB, set SCTLR.M. Keep virtual 0 = physical 0.
4. Write the console (`02-uart.md`).
5. Enable the OS timer event 0 and the periodic tick, enable line 28 in the interrupt controller, clear CPSR.I (`04-timers-clock.md`, `03-interrupts.md`).
6. Display: point a GRAM bank at a framebuffer and start an update (`05-display.md`).
7. Keys, I2C chips, flash, sound as needed.
8. Idle with wait-for-interrupt in a loop.
9. Power off: switch off the system supply in the power-management chip (`07-gpio-power.md`).

## 7. Power on and off

- Power on = the start of a run. There is no warm reset. The viewer's power control starts a new run; RAM does not survive.
- Power off = the firmware switches off the system supply regulator of the power-management chip (`07-gpio-power.md`, `08-i2c-spi-chips.md`). The run then ends with "powered off by the phone" [VALIDATED].

## 8. Stock start-up order [STOCK]

For information, the order in which the stock software brings the hardware up (times in emulated time from reset):

1. First-stage loader: one write to the power chip on I2C0 (5.6 ms); storage probe (NOR, NAND, memory card); NAND mount; reads the platform revision; starts the other processor (about 3.35 s).
2. Kernel: interrupt controllers, OS timer, link block (about 3.76 s).
3. Drivers, in dependency order: I2C buses, power chip (first interrupt about 3.97 s, the power-on cause), multimedia chip check (about 3.95 s), display controller version check (about 4.05 s), graphics, first picture (about 5.0 s), signal-processing block handshake (about 5.1 s), audio, then the rest.

The stock software runs without a periodic tick when idle: it arms the OS timer for its next timeout and sleeps (`04-timers-clock.md` section 6).
