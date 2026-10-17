"""Myna: an open-source firmware of our own (myna/ at the repository root) on the DB3210 platform: hardware variant A
of myna/spec (README.md).
No stock firmware is used: the launcher loads the ELF file BOOT_ELF and starts the application CPU at its entry (myna/README.md)."""
import os

HERE = os.path.dirname(os.path.abspath(__file__)); NATIVE = os.path.dirname(os.path.dirname(HERE)); ROOT = os.path.dirname(NATIVE)

NAME, TITLE, PLATFORM, FIRMWARE = 'myna', 'Myna', 'DB3210', '0.1.0-dev'

# the firmware: an ELF file whose PT_LOAD segments the launcher loads at their physical addresses (native/sim/db3210.py).
# With BOOT_ELF the launcher reads no stock firmware: no flash image, boot loader, modem image, instrument table, boot-ROM stand-ins
BOOT_ELF = os.path.join(ROOT, 'myna/firmware/build/myna.elf')
BUILD = 'build it with: make -C myna/firmware'         # what the launcher and tools/device.py say when BOOT_ELF is not there
# NAND: the launcher attaches a blank chip (every byte 0xFF) of this geometry, a chip of native/emu_nand/nand_model.py CHIPS;
# the default is the stock phones' chip. The flash state (native/tools/flash_state.py) keeps what the firmware writes, keyed to
# "blank NAND <chip> <pages> pages": it is never applied to a stock flash image, nor a stock state to this chip
NAND_CHIP = 'samsung_k9k2g08r0a'

# add-on chips of the phone that are plain hardware models (no firmware address, no firmware data). Left out:
#   emu_spi     the MP202 behind the SPI master is modelled at the message port of its own program, which the phone downloads
#               into it at start-up; that program is a stock firmware file, which Myna cannot use
#   emu_shim.*  harness stand-ins: they hook addresses of the stock firmware
ATTACH = ('emu_i2c:attach', 'emu_keypad:attach', 'emu_gpio:attach', 'emu_dsp:attach', 'emu_i2s:attach', 'emu_apex:attach')
# the modem: the AT modem stand-in (native/emu_modem_at, myna/spec/14-modem-at.md): 3GPP TS 27.010 multiplexing and TS 27.007 /
# 27.005 AT commands on link channel 0, backed by the cell network of native/emu_cell. The modem CPU is not started
PEER = 'emu_modem_at:attach_peer'

# the PMIC's converter inputs (native/emu_i2c/battery.py, Analog; myna/spec/08-i2c-spi-chips.md 2.4), values of our own:
#   battery: a 47 kOhm NTC thermistor, B = 4050 K, between the battery data contact and ground, fed by the PMIC's current
#            source: 10 uA (reg 0x52 = 3, 470 mV at 25 C) or 4 uA (= 7, for the cold end: 2103 mV at -20 C)
#   phone temperature (channel 5): the same thermistor type below a 47 kOhm pull-up from 1800 mV (900 mV at 25 C)
#   converter ranges (mV at code 0, at full scale): battery voltage 2500-4500, charger 0-16000, the other channels 0-2500
PMIC_ANALOG = dict(ntc_r25=47000, ntc_beta=4050, bdata_source_ua={3: 10, 7: 4},
                   board_ntc_r25=47000, board_ntc_beta=4050, board_pullup_ohms=47000, board_ref_mv=1800,
                   scales={10: (2500, 4500), 8: (0, 16000)}, default_scale=(0, 2500))

# the keys: plain input names at the positions of the keypad matrix (myna/spec/06-keypad.md 4.1), no key codes of the stock firmware
KEYMAP = 'devices.myna.keymap'

# the viewer's skin: the P2 chin slider in Stone, Ink and Ember, drawn by skin/draw.py with the parts in skin/pebble.py
# (design notes: myna/design/STYLE.md). To show another skin folder, start the viewer with SIM_DEVICE=myna SIM_SKIN=FOLDER (docs/SKINS.md)
SKIN = os.path.join(HERE, 'skin')
