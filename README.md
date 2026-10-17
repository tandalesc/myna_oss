# Myna

Myna is open-source software for a keypad slider phone: a small kernel, drivers, a file system, a modem driver that
speaks standard AT commands, and a phone UI in its own look (the "Pebble" design). It sends and receives text messages,
keeps contacts, notes and settings, and runs a clock on a phone that sleeps between minutes. It runs on a simulator of
the phone's hardware, in a terminal or in a browser tab, where phones on different pages text each other through a
small relay.

Myna is written for the ST-Ericsson DB3210 platform, the hardware of the Sony Ericsson C905 slider phone (2008), and is tested on the simulator of that hardware in this tree; Sony Ericsson and Sony are trade marks of their owners, this project has no connection with them, and it contains and uses none of their software.

Licence: MIT (`LICENSE`); third-party parts: `THIRD_PARTY.md`.

## What is here

| folder | what |
|---|---|
| `myna/firmware/` | the firmware: C and a little assembly, freestanding, built with clang and rust-lld (`myna/README.md`) |
| `myna/spec/` | the hardware interface Myna is written against: memory map, interrupts, timers, display, keypad, power, I2C chips, NAND, the link to the modem, the AT modem |
| `myna/web/` | the phone page: Myna in a browser tab (`myna/web/README.md`) |
| `myna/relay/` | the text-message relay between pages: a Cloudflare Worker (`myna/relay/README.md`) |
| `myna/assets/`, `myna/tools/`, `myna/third_party/` | the design's drawings, the fonts, the build-host tools, littlefs and stb_truetype |
| `native/` | the part of the DB3210 simulator that Myna runs on: the launcher (`native/sim/db3210.py`), the device models, the AT modem stand-in and its cell network, Myna's device profile and skin (`native/devices/myna/`), and the compiled CPU core (`native/core/`) |

## Quick start

Needs: clang with the ARM target and Rust (rustup: `rust-lld`, `rust-objcopy`, `cargo`) for the builds, Python 3.10 or
later (standard library only), `make`. On a Mac with Xcode's command-line tools and rustup nothing else is needed.

```
make -C myna/firmware                            # the firmware: myna/firmware/build/myna.elf
make -C myna/firmware host-test                  # the codecs on the host
sh native/core/build.sh                          # the compiled core (and dbcore.wasm when the wasm32 target is there)
python3 -I myna/firmware/test/stock_free.py      # the telephony test, driven by keys on Myna's screens
python3 -I native/sim/db3210.py --device myna --standard --display --core own --emu-seconds 10 --frames-dir run/frames
```

The phone page (an unpacked Pyodide release is needed, see `myna/web/README.md`):

```
python3 myna/web/serve.py --pyodide DIR          # http://127.0.0.1:8940/
```

Texts between pages go through a relay; without one the page uses a loopback network and a text comes back to the phone
that sent it. `myna/relay/README.md` runs a relay locally and says what must be set before one is put on the internet.

## Tests

| command | what |
|---|---|
| `make -C myna/firmware host-test` | the codecs (SMS PDUs, GSM 7-bit, UCS-2, vCard, phone numbers) with sanitizers |
| `python3 -I myna/firmware/test/stock_free.py` | the telephony through the simulator: Messages, Contacts, the dialer, a power cycle, both cell networks; under an import guard |
| `python3 -I native/emu_modem_at/selftest.py` | the AT modem stand-in: 27.010 framing, AT commands, texts on both networks |
| `node myna/web/test/smoke.mjs`, `node myna/web/test/typing.mjs`, `node myna/web/test/relay.mjs` | the page in headless Chrome: alone, predictive text tapped on the keys, and two phones through a local relay |
| `cd myna/relay && npm install && node test/run.mjs` | the relay |

This tree is exported from the development repository by its `tools/export_release.py`.
