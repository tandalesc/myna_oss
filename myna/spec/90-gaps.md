# 90 Gaps

What a from-scratch firmware needs and the simulator does not give, or gives only in a way that is tied to the stock firmware. Each gap names the place in the simulator, what a clean firmware would hit, and a suggested change.

The "Where" lines name files of the simulator (MIT code) for the people who change it. They contain no firmware facts. A clean implementer does not need them and must not open those files.

Priority: A = blocks a clean firmware from running at all; B = blocks a feature; C = fidelity or convenience.

## A. Blocking

### G1 (A) No way to start a non-stock image

- Where: `native/sim/db3210.py`, `build()`: the application side always reads the stock loader image out of the flash image (`native/devices/__init__.py` `image()`, `native/devices/source.py`), loads it with the stock-loader format reader of `native/emu/loaders.py`, plants the boot stubs (`Machine.plant_boot_stubs()` in `native/emu/machine.py`) and starts at the entry address that `native/devices/__init__.py` reads from the stock loader.
- A clean firmware: cannot be loaded at all with the committed launcher.
- Status at the time of writing: a change in the working tree (not committed) adds `BOOT_ELF` to device profiles (`native/devices/myna/__init__.py`), `load_elf()` in `native/emu/loaders.py`, and an ELF branch in `build()` that loads the PT_LOAD segments, skips the stock loader, the boot stubs, the modem, the tracer and the boot-ROM hook, and starts at the ELF entry. It covers this gap once committed; the remaining items are G2 and the viewer (skin, start of the `myna` profile).
- Original suggestion: options `--image FILE [--load-addr 0x48000000] [--entry ADDR]` (raw binary; optionally ELF). When given: skip the stock-loader loading, `plant_boot_stubs()` and the entry hook on the boot-ROM stub; call `Machine.load(addr, data)`; set the start address of the application side (`Side.entry`). The same for `--core own` (`core/python/machine.py` has `load`). Validated by a hand-built harness during the writing of this spec: a clean program loaded at 0x48000000 and entered there runs on both engines with all models.

### G2 (A) No way to start without a stock flash image

- Where: `db3210.py` `build()` -> `boot.chip_path()` -> `devices.source.chip()`: the flash image is made from the stock firmware containers. `emu_nand/nand_model.py` `NandSystem(image_path)` needs an image. `tools/flash_state.py` keys the flash state to the base image's SHA-1.
- A clean firmware: the run stops before the first instruction when the stock files are absent; when present, the chip holds stock content.
- Status: the working-tree `myna` profile attaches no NAND at all (a TODO in `build()`): the NAND windows read 0 and the firmware has no storage. Also, `native/tools/flash_state.py` `FlashState.__init__()` looks for the NAND model on the bus with `next(...)`: with no NAND model, attaching the flash state (which the viewer does) raises `StopIteration`.
- Suggested change: `NandSystem(bytearray())` gives an all-0xFF chip of the right geometry (tested); attach it for a `BOOT_ELF` profile, with the flash state keyed to "blank" in `native/tools/flash_state.py`. Optionally a profile field for a clean base image.

### G3 (A) The device profile and the launcher act on stock firmware addresses

- Where:
  - `--standard` attaches the profile's `STAND_INS` (`native/emu_shim/`): entry hooks at fixed code addresses of the stock software that read and rewrite guest memory when execution reaches them.
  - `native/sim/db3210.py` `build()`: an entry hook on the profile's fatal-error address (prints a fatal-error line), an entry hook on the boot-ROM stub, the default tracer (`--trace key`, a module in `native/tools/`) with hooks and memory reads at the profile's addresses; `report()` reads memory at further profile addresses; `--extcc-bypass` writes memory at a profile address.
  - The key map modules (`native/emu_keypad/keymap.py` and that of variant B's stock profile) carry the stock key codes; `native/emu_keypad/inputs.py` prints them in every input log line.
- A clean firmware: if its code or data lies at one of these addresses, a hook fires and changes its memory or floods the log. The log shows stock-derived values.
- Status: the working-tree `myna` profile has no firmware addresses, no `STAND_INS`, `PEER = None`, and the ELF branch forces `--trace none`. Remaining: it has no `KEYMAP`, so the default key map (variant A's, with stock key codes in the log lines) is used; it has no skin, so the viewer cannot show it.
- Suggested change: a `KEYMAP` module for `myna` with the same matrix positions (`06-keypad.md`) and no stock codes; a skin.

### G4 (A for telephony, B otherwise) The modem stand-in speaks only the stock protocol

- Where: `native/emu_modem_mock/` (`peer.py` `LinkPeer`, `services/`): the link protocol, the frame format and every service follow the stock firmware.
- A clean firmware: no modem services at all (no SIM card, no cellular network); the stand-in may also write bytes into the application's receive channels and send wake-up kicks (`11-modem-link.md`).
- Status: closed for the `myna` profile. It selects a second stand-in, `native/emu_modem_at/` (`PEER = 'emu_modem_at:attach_peer'`): 3GPP TS 27.010 multiplexing and TS 27.007 / 27.005 AT commands on link channel 0, backed by the same cell network as the stock stand-in. The interface is `14-modem-at.md`. Open: the audio service on DLC 2, packet data.
- Original suggestion: a clean peer (a separate class beside `LinkPeer`) with a documented protocol of its own (for example AT-style text lines on one link channel), selected by the clean profile.

### G7 (A) Idle without an armed timer ends the run

- Where: `emu/machine.py` `Machine.run()` ("idle callback has nothing scheduled"); `emu_irq/system.py` `IrqTimerSystem.idle()`; `db3210.py` `Side.key()` and `run()` ("nothing scheduled on any CPU"). The viewer's real-time pacing (`Pace.idle`) only walks towards a scheduled event.
- A clean firmware: a phone that waits for a key press with no timer armed is stopped; the key press from the viewer never arrives.
- Suggested change: when nothing is scheduled and the run is paced by the host clock (viewer), let emulated time follow the host clock and keep polling the key control file. Until then: `00-machine.md` 5.2 makes an armed timer a requirement.

## B. Features

### G5 (B) IRQ always at virtual 0x18 on Unicorn; FIQ never delivered

- Where: `emu/machine.py` `Machine.irq_vector = 0x18` and `inject_irq()` (ignores SCTLR.V; `enter_exception()` honours it for the other exceptions); `emu_irq/system.py` `IrqTimerSystem._fiq()` is empty; the compiled core computes the FIQ output but does not connect it.
- A clean firmware: must use low vectors; cannot use FIQ.
- Suggested change: in `inject_irq()` use `0xFFFF0018` when SCTLR bit 13 is set; add FIQ delivery (`inject_fiq`, CPSR.F) on both engines.

### G6 (B) A level interrupt still asserted after the handler is re-taken at different times on the two engines

- Where: `emu/machine.py` `inject_irq()` sets `irq_pending = False`; the VIC (`emu_irq/vic.py` `VicPair.update`) calls `on_irq` only when its output changes; `IrqTimerSystem.step()` re-asserts it once per slice. The compiled core re-takes it at once.
- A clean firmware: a handler that does not clear its source runs again 200 us later on Unicorn but locks up the CPU on the compiled core (seen in a test).
- Suggested change: after `inject_irq()`, keep `irq_pending` equal to `vic.irq_out` (re-sample at the exception return or at the next instruction boundary).

### G8 (B) Branch-to-self is treated as a halt

- Where: `emu/machine.py` `Machine.run()`, `_spinning()`: a slice ending on `b .` with no IRQ pending (or IRQs masked) ends the run.
- A clean firmware: an idle loop `b .` with interrupts enabled is stopped.
- Suggested change: none needed if documented (`00-machine.md` 5.3). Optionally treat `b .` with IRQs enabled like WFI.

### G9 (B) Time accounting artefacts of the Unicorn engine

- Where: `emu/machine.py` `Machine.run()`: `self.insns += 1 if at_wfi else n`: a slice that ends at a WFI is charged 1 instruction; a slice ended by an abort or SWI is charged in full. All devices see the time of the slice start (`IrqTimerSystem.step()` syncs the clock between slices).
- A clean firmware: timing differs between the engines by up to a slice per event; polling a timer has 200 us resolution; SWI-heavy code runs "slower" in emulated time on Unicorn.
- Suggested change: count the instructions actually executed before the WFI (the compiled core does); document `--core own` as the reference for timing.

### G10 (B) Display panel and bus engine are simplified

- Where: `emu_lcd/lcd_model.py`: `XgamDisplay._pdi_run()` ignores the engine program and takes the byte count from bits 31:16 of +0x100C; `start_update()` shows a picture whatever the panel's sleep/display state; `Panel.read_reg()` answers only 0x0A; `_accel_word()` records 2D commands without executing them; `_irq_update()` drives only line 18 (13, 17, 19 never).
- A clean firmware: works in the simulator, but cannot be checked for a correct panel power sequence; the panel bus engine's instruction set (needed on a real phone) is unknown; no 2D acceleration; no vsync / tearing signal.
- Suggested change: show a black screen while the panel is asleep or off; optional: execute the 2D accelerator's copy command.

### G11 (B) Backlight, key lights, vibrator, LEDs have no visible effect

- Where: `emu_i2c/devices.py` `LedCommandDriver` stores commands only; `Max7327` stores outputs only; no vibrator model; the viewer always shows the screen lit.
- A clean firmware: cannot see whether its backlight or vibration code works.
- Suggested change: a backlight level in the frame stream (dim the picture) and a vibration indicator in the viewer; the illumination driver's command meanings need research.

### G12 (B) Sound output is narrow

- Where: `emu_i2s/i2s.py`: `I2s.write()` stores CPU writes to +0x14 without playing them; `RATE` is fixed (`EMU_I2S_RATE`, default 44100) whatever the dividers; lines 10/12 never raised; no receive side; `I2s` has no `dma_avail()` (a DMA channel with an I2S data address as its source would raise an exception inside the DMA model); the viewer plays only `i2s1_tx.pcm` (`native/tools/live_view.py`). The synthesis block's command format (`emu_apex/apex.py`) is stock-derived; its waveforms are substitutes.
- A clean firmware: only DMA-fed 44.1 kHz stereo on I2S1; no microphone, no hardware volume.
- Suggested change: accept CPU writes to the transmit register (paced like DMA, with a FIFO level and an interrupt); derive the rate from the dividers or document fixed 44.1 kHz; add `dma_avail()` returning 0.

### G13 (B) NAND: no interrupt, no bad blocks, flash state tied to the base image

- Where: `emu_nand/nand_model.py`: line 45 never driven; `NandChip.ready()` is busy for 3 polls regardless of time; no bad-block marks; `fail_next` only as a test hook; the ECC accumulator does not restart at 512 bytes. `tools/flash_state.py` refuses a state of another base image.
- A clean firmware: cannot test interrupt-driven flash access or bad-block handling.
- Suggested change: optional ready interrupt; a configurable list of bad blocks; a blank base (G2).

### G14 (B) No memory card

- Where: `emu/stubs.py` `NoCardMmci` (every command with a response times out); `emu_gpio/gpio.py` Memory Stick detect pin fixed "no card".
- A clean firmware: no removable storage.
- Suggested change: an SD card model behind the PL180-style host, backed by a host file.

### G15 (B) FM tuner interrupt pin not wired on variant A

- Where: `emu_i2c/devices.py` `Si470x.set_int` defaults to a no-op; only the chip module of variant B's stock profile (`attach_gpio()`) wires it (GPIO bank 0 pin 0). Variant A's pin is not known.
- A clean firmware: on variant A it must poll the tuner. No radio sound or stations in either profile.
- Suggested change: find and wire variant A's pin, or document polling (done in `08-i2c-spi-chips.md`).

### G16 (B) Multimedia chip usable only through the stock protocol

- Where: `native/emu_spi/mp202.py` (message port), `native/emu_spi/mp202_api.py` (imitation of the program that the stock software downloads into the chip).
- A clean firmware: in the simulator it can use the decoder with the protocol of `08-i2c-spi-chips.md` section 12 and any bytes as the "program" (the model only counts them), but the `myna` profile does not attach the SPI model, and on a real phone the chip needs the stock chip program. No camera.
- Suggested change: attach `emu_spi` in the clean profile if simulator-only video is wanted, and say in the log that the downloaded program is ignored; otherwise decode in software (the motion-compensation / IDCT block helps; it is attached in the profile of variant B only, G24).

### G17 (B) Only one hardware timer; other timers are storage

- Where: `emu_irq/timer.py` `AppTimers` (0xC0014000: storage, no events); `SleepTimer`: event 1 (line 29) never fires.
- A clean firmware: one timer for tick, sleep and everything else; must multiplex in software.
- Suggested change: model the four general timers (down-counters with interrupt) once their register layout is known.

### G18 (B) Real-time clock and alarm

- Where: `emu_i2c/soc_rtc.py` `SocRtc` counter starts at 0; `emu_i2c/devices.py` `Ab3100` has no alarm (EVENT2 bit 7 never raised) and its clock is not kept between runs.
- A clean firmware: must load the SoC clock from the power chip at every start; a power-chip alarm never fires; time restarts at the fixed date [MOCK] every run (unless `EMU_PMIC_RTC=host`).
- Suggested change: keep the power chip's clock offset in the flash state or a side file; model its alarm.

### G19 (B) Console UART is transmit-only

- Where: `emu/uart.py` `Uart`: no receive, no interrupt.
- A clean firmware: no debug shell.
- Suggested change: a receive FIFO fed from a host file or socket, with line 22.

## C. Fidelity and convenience

### G20 (C) Watchdog, reset, power-on key

- Where: no watchdog model (line 37); no reset register; `emu_keypad/inputs.py` `Inputs.pmic_on_key = False` (the END key never raises the power chip's power-key event during operation); `emu_i2c/__init__.py` latches the power-key event at every start [MOCK].
- Suggested change: a watchdog model when its registers are known; a reset path (restart the run with RAM cleared but flash kept).

### G21 (C) Accesses that a real phone would fault

- Where: `emu/machine.py` `_unmapped()`: any address outside RAM and device windows becomes zero RAM; `emu/bus.py`: unclaimed device addresses read 0. Unaligned loads return unrotated bytes on both engines; alignment faults only on Unicorn.
- A clean firmware: wild pointers and unaligned accesses go unnoticed.
- Suggested change: an option `--strict-memory` that turns such accesses into data aborts and logs them.

### G22 (C) CP15 in user mode differs between engines

- Where: `emu/machine.py` `_invalid()` steps over CP15 accesses that Unicorn rejects (also in user mode), unless `undef_cp15_to_guest`; the compiled core raises undefined.
- Suggested change: set `undef_cp15_to_guest` for user-mode accesses.

### G23 (C) System controller storage differs between engines

- Where: `native/core/src/dev/sysctl.rs` keeps one register per byte offset; `db3210.py` `AppSysCtrl` (Python) per access offset.
- Suggested change: none needed if aligned 32-bit accesses are required (done in `01-memory-map.md`).

### G24 (C) Motion-compensation / IDCT block only in the profile of variant B

- Where: the `ATTACH` list of variant B's stock profile has `emu_idct:attach`; that of variant A does not.
- Suggested change: attach it in the clean profile if video decoding in software is wanted.

### G25 (C) Link channel 7 interrupts cannot be enabled

- Where: `emu_link/aaif.py` `AaifSide.write()`: `chan_en |= v & 0x7f7f`.
- Suggested change: document (done) or widen the mask if the hardware allows it (not known).

### G26 (C) Model values derived from stock calibration

- Where: `native/emu_i2c/battery.py`: `ADC_SCALE`, `NTC_TABLE` and `PCB_TEMP_TABLE` are derived from calibration data and tables of the stock software. They decide what the converter returns.
- A clean firmware: the specification gives only the resulting values ([MOCK] in `08-i2c-spi-chips.md`); the battery identification and temperature curves are not given.
- Suggested change: replace the tables by generic, documented values (a generic 10 kOhm NTC, a linear scale), so that the specification can state them fully.
- Done: the tables are the stock profiles' only (`native/emu_i2c/battery_stock.py`, not in Myna's release). The model takes the board from the device profile (`PMIC_ANALOG`); Myna's has values of its own: a 47 kOhm, B = 4050 K thermistor, linear converter ranges (`08-i2c-spi-chips.md` 2.4).

### G27 (C) Display model shows frames whatever the panel state; no backlight level in the stream

See G10, G11.

### G28 (C) Key map holes

- Variant A's index 8 and variant B's indexes 7, 8, 31, 32, 35 have no key; variant A's `operator`, `game_a`, `game_b`, `media`, `media2`, `camera_onoff` positions are not confirmed as physical keys (`emu_keypad/keymap.py` comments).
- Suggested change: research with photographs of the real keypads.
