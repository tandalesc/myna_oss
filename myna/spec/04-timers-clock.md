# 04 Timers, clocks and the system controller

Summary for a firmware:

- The OS timer (0xC001A000) is the only timer that raises interrupts. Use it for the system tick and for idle wake-ups.
- The real-time clock (0xC0017000) counts seconds and has an alarm interrupt.
- The power-management chip has a battery-backed clock (`08-i2c-spi-chips.md`). Load the real-time clock from it at start.
- The system controller and the clock block can be ignored.

## 1. OS timer, base 0xC001A000

### 1.1 Time base

- One time base of 4.094 MHz [MOCK: inferred rate], counted from the start of the run (emulated time 0).
- A coarse step is 0x3FF8 (16376) counts = exactly 4 ms.
- counts = coarse x 0x3FF8 + (0x3FF7 - fine).

### 1.2 Registers

| Offset | Name | Width | Access | Reset | Meaning |
|---|---|---|---|---|---|
| +0x04 | COARSE | 32 | R | 0 | Number of 4 ms steps since power-on. Reads 0 until the first write to any register of the block (section 1.4). |
| +0x08 | FINE | 15 | R | 0x3FF7 | Counts down from 0x3FF7 to 0 within each coarse step; COARSE goes up when it wraps. Reads 0x3FF7 until the first write to the block. |
| +0x0C | MODE | 32 | S | 0 | Mode, bits 1:0. No effect in the model. |
| +0x10 | EVENT0_INTERVAL | 32 (bits 15:0 used) | RW | 0 | Event 0 delay in coarse steps (section 1.3). |
| +0x18 | FREERUN | 32 | R | - | Free-running count of the time base since power-on. [MOCK] Each read also adds 100 counts (24 us), so that a busy-wait on this register ends even inside one slice. Not held before the first write. |
| +0x1C | EVENT1_ENABLE | 32 | S | 0 | No effect. |
| +0x24 | WAKE_LEAD | 32 | S | 0 | No effect. |
| +0x28 | EVENT_STATUS | 2 | R, W1C | 0 | Bit 0 = event 0 pending, bit 1 = event 1 pending (never set). |
| +0x2C | EVENT_ENABLE | 32 | RW | 0 | Bit 0 = event 0 enabled. Bit 1 = event 1 enabled (no effect). |
| other | - | - | S | 0 | |

Line 28 is high while EVENT_STATUS bit 0 = 1. Line 29 (event 1) is never raised: event 1 has no compare register in the model.

### 1.3 Event 0

- Arming happens at a write. Set EVENT_ENABLE bit 0 first, then write EVENT0_INTERVAL. A write to EVENT0_INTERVAL while EVENT_ENABLE bit 0 = 0 arms nothing.
- EVENT0_INTERVAL = n, 1 <= n <= 65535: one-shot. The event comes n x 4 ms after the write (counted from the write, not from a step boundary). It does not repeat. Write the register again for the next event.
- EVENT0_INTERVAL = 0: periodic. The event comes at every 4 ms step boundary of COARSE, from the next one on.
- A write of EVENT_ENABLE with bit 0 = 1, when no event is armed and EVENT0_INTERVAL bits 15:0 = 0, starts the periodic event.
- A write of EVENT_ENABLE with bit 0 = 0 cancels the armed event.
- When the event comes and EVENT_ENABLE bit 0 = 1, EVENT_STATUS bit 0 is set and line 28 goes high. Write 1 to EVENT_STATUS bit 0 to clear it and the line.
- A new one-shot write replaces an armed event.
- While the CPU sleeps in wait-for-interrupt, emulated time jumps to the armed event (`00-machine.md`, 5.2). An armed event 0 is the normal way to keep an idle firmware alive.

Examples [VALIDATED]:

| Wanted | Writes |
|---|---|
| 4 ms system tick | +0x2C = 1, then +0x10 = 0; enable line 28; in the handler: +0x28 = 1 |
| Sleep 200 ms | +0x2C = 1, +0x10 = 50, wait-for-interrupt; then +0x10 = 0 to return to the tick |

### 1.4 Before the first write

Until the first write to any register of the block, COARSE reads 0 and FINE reads 0x3FF7 (the pair looks stopped) [MOCK: what the hardware does is not known]. After the first write they show the count since power-on. FREERUN runs from power-on.

### 1.5 Time resolution

All reads within one slice of 20,000 instructions see the same time (`00-machine.md`, 5.1). A delay loop on COARSE/FINE ends at a slice boundary, so short delays last at least to the next boundary (up to 200 us).

## 2. General timers, base 0xC0014000

Four units of 0x40 bytes (unit n at 0xC0014000 + 0x40 x n), lines 24-27.

[MODEL] Storage only: every register keeps what is written, no counter runs, no interrupt is raised. Do not use.

## 3. Real-time clock, base 0xC0017000

Present when the I2C model is attached (always, in both profiles).

| Offset | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| +0x00 | ALARM | RW | 0 | Alarm time in seconds. A write re-arms the alarm. 0 = no alarm. |
| +0x04 | LOAD | W | - | A write sets the counter to the value written, from this moment on, and re-arms the alarm. A read gives 0. |
| +0x0C | COUNTER | R | 0 | Seconds: the value of the last LOAD + whole seconds since that write. Starts at 0 at power-on [MOCK]. |
| +0x10 | PENDING | R, W1C bit 0 | 0 | Bit 0 = alarm pending. |
| +0x14 | ALARM_ENABLE | RW (16 bits) | 0 | Bit 0 = alarm interrupt enabled. |
| other | | S | 0 | |

- The alarm fires once when ALARM != 0, ALARM_ENABLE bit 0 = 1 and COUNTER >= ALARM: PENDING bit 0 is set. A new alarm needs a write to ALARM or LOAD.
- Line 44 is high while PENDING bit 0 = 1 and ALARM_ENABLE bit 0 = 1.
- An enabled alarm in the future is a wake-up event for an idle CPU.
- The counter rate is 1 Hz of emulated time [MOCK: inferred].
- The counter is not kept between runs. Load it at start from the clock of the power-management chip (`08-i2c-spi-chips.md`), which counts in 1/65536 s and holds Unix seconds in its bytes 2-5.

## 4. System controller, base 0xC0011000

| Offset | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| +0x000 | CLOCK_SELECT | RW | 0 | Bits 2:0 select the CPU clock source. Value 4 = PLL off. No effect on speed in the simulator. |
| +0x004 | CLOCK_STATUS | R (stored value with bit 1 forced) | 0x2 | Bit 1 = PLL locked: reads 1 unless CLOCK_SELECT bits 2:0 = 4 [MOCK: locks at once]. Other bits: the last value written. |
| +0x400 | PLATFORM_REVISION | RW | 0xE8 | Low byte = platform revision. Known values 0xC8, 0xD8, 0xE8, 0xF0 for revisions 1 to 4. The launcher sets 0xE8 (option `--platform`). |
| +0x4D0-+0x4D3 | CLOCK_SWITCH_STATUS | R (stored value with bit 3 forced) | 0x8 | Bit 3 always reads 1. |
| other | | S | 0 | Gates and settings: storage, no effect. |

Line 47 is never raised. A firmware may leave this block alone.

## 5. Clock block, base 0xA0004000

| Offset | Access | Meaning |
|---|---|---|
| +0x04 | R | Bit 2 = bit 2 of the value written at +0x20 (a clock-switch request is acknowledged at once). Bit 0 reads 0. Other bits: the last value written to +0x04. |
| +0x20 | RW | Clock-switch request, bit 2. |
| other | S | Storage per 32-bit word. |

A firmware may leave this block alone.

## 6. Stock driver notes [STOCK]

- OS timer: the stock kernel uses only event 0. Its set-up writes MODE (+0x0C, bits 1:0), then EVENT_ENABLE (+0x2C), then EVENT_STATUS (+0x28). While processes run it takes the periodic 4 ms tick (EVENT0_INTERVAL = 0). When nothing can run, it writes the number of 4 ms steps to its next timeout into EVENT0_INTERVAL, sleeps (wait-for-interrupt), and writes 0 again after the wake-up. Before sleeping it reads EVENT_STATUS to catch an event that came while it computed the delay. The interrupt handler writes 1 to EVENT_STATUS bit 0.
- It reads COARSE and FINE until two readings agree, and computes microseconds from counts = COARSE x 0x3FF8 + (0x3FF7 - FINE).
- Its first-stage loader uses FREERUN (+0x18) for short busy-wait delays, before anything is written to the block.
- General timers (0xC0014000): untouched during a start; the four handlers write 0x80 to unit +0x20.
- Real-time clock: at start the stock software copies the Unix seconds of the power chip's clock into LOAD (+0x04) and then waits 100 ms. It reads the time from COUNTER (+0x0C). For an alarm it writes ALARM (+0x00) and sets ALARM_ENABLE bit 0; the interrupt handler reads PENDING and writes it back with bit 0 set, and clears ALARM_ENABLE.
- System controller and clock block: when no process needs the fast CPU clock (104 or 208 MHz), the stock clock manager writes CLOCK_SELECT = 4 (PLL off). When a fast clock is needed again it sets the clock source and waits for CLOCK_STATUS bit 1 (PLL locked). The clock-switch routine in TCM writes the request in clock block +0x20 bit 2 and polls clock block +0x04 bit 2 until it matches; it also waits for system controller +0x4D0 bit 3. A firmware that does not touch the clocks needs none of this.
- The first-stage loader reads PLATFORM_REVISION and selects the images to start by it.
