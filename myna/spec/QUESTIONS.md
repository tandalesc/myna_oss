# Questions on the specification

Questions from the Myna firmware work, for the writer of the specification. Each one says what Myna does meanwhile.
Black-box observations of the simulator are marked as such: they were seen in runs, not read in its source.

## Q1 Display: colour order bit of DCS 0x36 (05-display.md 5.1, 8)

The stock set-up writes 0x36 = 0x18 (bit 3 = BGR). Black box: the model gives the same picture with 0x36 = 0x00 and
0x08 (frames compared byte for byte), so the bit has no effect in the simulator. On the real panel, which value shows
a little-endian RGB565 framebuffer (red in bits 15:11) with the right colours? Bit 4 (vertical refresh order) of the
stock value: needed?
Meanwhile: Myna writes 0x08.

## Q2 Display: wait after sleep out (05-display.md 5.1)

The specification asks for 120 ms after 0x11 before 0x3A, 0x36, 0x29. In MIPI DCS panels the 120 ms usually applies
before a following *sleep in*; further commands are often allowed 5 ms after sleep out. Which holds for the S6D14A0?
It sets Myna's first-frame time: 120.6 ms now; about 6 ms with a 5 ms wait.
Meanwhile: 120 ms.

## Q3 Display: panel bus engine program (05-display.md 5, gap G10)

Myna loads no program into the engine memory (the model does not need one). For hardware: is anything known of the
engine's instruction set, or of a minimal "send n bytes" program?

## Q4 Backlight (07-gpio-power.md 3, 08-i2c-spi-chips.md 7 and 11, gap G11)

Which command byte of the illumination driver at I2C1 0x4A switches the display backlight on, and at which level? The
stock notes list the command groups (0x20, 0x40, 0x60, 0x80 with a 5-bit value, ...) without meanings.
Meanwhile: Myna checks that the chip answers its address and sends no command.

## Q5 OS timer: arming at enable (04-timers-clock.md 1.3)

"A write of EVENT_ENABLE with bit 0 = 1, when no event is armed and EVENT0_INTERVAL bits 15:0 = 0, starts the periodic
event." When EVENT0_INTERVAL holds a non-zero value at that write, does the enable write also arm a one-shot of that
length, or nothing?
Meanwhile: Myna writes EVENT0_INTERVAL = 0xFFFF, then EVENT_ENABLE = 1, then EVENT0_INTERVAL = 0xFFFF again, so that
either way one event (262 s) is armed and the periodic tick never starts.

## Q6 OS timer: resolution of the one-shot (04-timers-clock.md 1.3)

A one-shot counts whole 4 ms steps from the write, so a deadline is met up to 4 ms late (the minute of the clock
changes at hh:mm:00.004). Is there a finer compare on the hardware (event 1 has none in the model)?
Meanwhile: rounding up, never early.

## Q7 Simulator observation: --emu-seconds with a sleeping firmware

Black box, firmware asleep on a one-shot 60 s ahead, launcher started with `--display --emu-seconds N`:

| N | Unicorn stops at | compiled core stops at |
|---|---|---|
| 1 | 600 s | 120 s |
| 61 | 600 s | 120 s |
| 130 | 600 s | 180 s |

The limit is overshot by one or more timer events (on Unicorn up to 600 s). Not a firmware matter; noted for whoever
works on the launcher.

## Q8 Simulator observation: instruction count of an idle run

The stop line's `insns` is a multiple of the slice length on both engines (for example 240,000 = 12 slices of 20,000
for a run of 3 wake-ups), also on the compiled core, which the specification says counts exactly (00 5.1). It looks
like whole slices are charged when the CPU goes to sleep. So `insns` overstates the work of an idle firmware.
Meanwhile: Myna measures its own awake time with the OS timer, run with `--slice 100` so that device time steps by
1 us (myna/README.md, "Measurements").

## Q9 NAND: the end of a busy operation (10-storage-nand.md 3)

In the model the chip is busy for three polls of READY and line 45 is never raised. On the hardware a page read takes
tens of microseconds, a program hundreds and an erase milliseconds. Does the controller raise line 45 on the chip's
ready edge, and with which enable and clear bits? Myna would then sleep through an erase instead of polling.
Meanwhile: Myna polls READY after every busy command (at most 100,000 polls, then an error).

## Q10 NAND: partial programs of a page (10-storage-nand.md 2.1)

The model allows any number of programs of a page before an erase (each one ANDs). Myna programs the four 512-byte
sectors of a page in separate operations when littlefs writes them separately, each with its three code bytes in the
spare area: up to four programs per page, and one more on pages 0 and 1 of a block to mark it bad. How many partial
programs per page does the real chip allow?
Meanwhile: as described; Myna never programs a sector twice.

## Q11 NAND: factory bad-block marks (10-storage-nand.md 1)

The model has no bad blocks. Where does the factory mark a bad block on this chip: byte 0 of the spare area of page 0
and page 1 (what Myna checks), or another page or byte?
Meanwhile: Myna treats a block as bad when spare byte 0 of page 0 or page 1 is not 0xFF, never uses or erases it,
and marks a block whose program or erase fails the same way.

## Q12 NAND: a DMA path for the data port (13-dma.md 4)

13-dma.md lists no port for the NAND data register, so Myna moves page data with the CPU (LDM/STM of eight words at
the data port). Does the platform have a DMA request for the NAND controller (the stock driver uses CPU loops,
10-storage-nand.md 6)?
Meanwhile: CPU loops: a 2 KB page is about 400 instructions.

## Q13 NAND: the ECC engine's done bit (10-storage-nand.md 3)

STATUS (+0x44) reads 0x40 ("ECC / FIFO done") at all times in the model. On the hardware, must the firmware wait for
bit 6 after the 512th byte before it reads ECC (+0x54)?
Meanwhile: Myna reads ECC right after the last word of a sector.

## Q14 Flash state and power off (10-storage-nand.md 4, 07-gpio-power.md 2.3)

Black box: a Myna build that switched the supply off 500 ms after its last flash program (Unicorn, command line,
`--attach flash_state:attach`) found that program in the flash state at the next start. Is the 1.5 s quiet time also
needed before a power off by the phone, or only when the simulator is stopped from outside (viewer, time limit)?
Meanwhile: Myna writes what is pending and switches off no sooner than 1.6 s after its last flash write.

## Q15 Text: the myna profile and the NAND chip (01-memory-map.md 2)

01-memory-map.md section 2 says the `myna` profile "does not attach the NAND chip and controller (yet)". The simulator
now gives such a device a blank chip of variant A's geometry and the controller (Myna reads ID ec aa 10 15 44, and
the flash state keeps what it writes). The sentence wants an update.

## Q16 Slide switch (07-gpio-power.md 1.3, 06-keypad.md 4.1)

Does the slide's pin bounce on the hardware (the model changes it once), and can the keys under a closed slide be
pressed at all on the real phone?
Meanwhile: no debounce (the interrupt takes the level it finds and waits for the other one); presses of 0-9, * and #
are ignored while the slide is closed.

## Q17 DMA: the last bytes of a transfer to the link (13-dma.md 3, 11-modem-link.md 5)

"Peripheral transfers move multiples of 4 bytes when 4 or more bytes can move." Black box: an item of 23 or 359 bytes
to the transmit port of link channel 0 arrives whole at the modem (the AT stand-in sees every character), so the model
moves the last 1-3 bytes as well. Is the hardware's link port byte-granular for DMA too, or must an item's count be a
multiple of 4 (with the message boundary carrying the true length)?
Meanwhile: Myna sends AT lines and PDUs of any length by DMA, one item per contiguous stretch of its ring.

## Q18 Link: receive interrupt while the link sleeps (11-modem-link.md 2.3, 4)

Myna never sets SLEEP bit 0: the receive interrupt (line 5) wakes the CPU from wait-for-interrupt by itself, in the
model. On the hardware, does line 5 still work when the platform is in its low-power state, or is line 8 (WAKE, with
SLEEP bit 0) the only path then?
Meanwhile: line 5 only; line 8 stays disabled.

## Q19 AT modem: the network's time zone (14-modem-at.md 6.8)

`+CCLK?` always ends in "+00" [MOCK], and there is no unsolicited time-zone report. Real modems report the network's
time and zone (NITZ) with `+CTZR` / `+CTZE` (27.007 8.41) or `+CTZV`. Will the stand-in have one of them, with a
configurable zone?
Meanwhile: Myna reads `+CCLK?` at each new registration and, with the setting `net_time`, sets the clock offset to that
local time (when it differs by more than 2 s). It never sets the modem's clock.

## Q20 AT modem: status reports (14-modem-at.md 1, 6.9)

Status reports are outside the interface (`+CNMI` takes ds = 0 only). What does the network do with an SMS-SUBMIT
whose TP-SRR is 1: ignore the request, or send an SMS-STATUS-REPORT that the stand-in drops?
Meanwhile: Myna never sets TP-SRR. It decodes SMS-STATUS-REPORT (`+CDS`, matched to the sent message by TP-MR) for a
modem that sends them.

## Q21 Simulator observation: run(..., hold=True) and a sleeping Myna

Black box, `db3210.build()` / `db3210.run(phone, 300 ms, hold=True)` with Myna asleep on its minute timer, on both
engines: each call returns with the phone's time at the next minute (60 s later), not 300 ms later; a
`phone.inputs.set_switch('slide', 'open')` given between two runs acts at the next run's start, and the slide
interrupt reaches Myna 1.5 s later. The docstring of `run` says that hold=True stops a sleeping phone at the end of
the run. Not a firmware matter; noted for whoever works on the launcher. The telephony harness
(`firmware/test/sim_telephony.py`) does not depend on it: it waits for console lines, and measures the 10 s retry from
the phone's own time.

Answered (simulator, main 2481e97): a run with a limit now stops a sleeping phone at its end. Checked 2026-10-14 on
both engines: the 3b harness (run(..., hold=True) in 20-300 ms steps) sees keys and network events at once, and a key
script with `at_ms` presses between minute wake-ups (5, 20, 61, 95, 130.5, 131 s) is applied at each time without
`--realtime`.
