"""Myna flip: Myna (myna/ at the repository root) on the P2 flip, the clamshell of the pebble family. The same DB3210 board as
the P2 chin slider (devices.myna) and the same firmware: one ELF file for both. The board tells the firmware which phone it is
in by a board-ID strap (GPIO_STRAPS below; myna/spec/07-gpio-power.md, section 1.3), and the firmware makes the slide switch
the lid's switch: closed, the phone sleeps (dark panel, only the side keys); open, it is where it was."""
import os

from .. import myna as _slider          # devices.myna

HERE = os.path.dirname(os.path.abspath(__file__))

NAME, TITLE, PLATFORM, FIRMWARE = 'myna_flip', 'Myna flip', _slider.PLATFORM, _slider.FIRMWARE

# the firmware and its blank NAND: the slider's (one build serves both boards). The flash state is still this phone's own: the
# viewer keeps it under the phone's name (RUN_DIR/myna_flip/flash_state_blank.bin) and the phone page under
# "state:myna_flip:..." in the browser, so the flip never shares the slider's messages or settings
BOOT_ELF = _slider.BOOT_ELF
BUILD = _slider.BUILD
NAND_CHIP = _slider.NAND_CHIP

# the same add-on chips, modem stand-in, converter inputs and keypad matrix as the slider
ATTACH = _slider.ATTACH
PEER = _slider.PEER
PMIC_ANALOG = _slider.PMIC_ANALOG
KEYMAP = _slider.KEYMAP              # the lid is the switch "slide" of that key map: the same switch on the same board

# the board-ID strap: GPIO bank 3 pin 0 tied high (pins 1:0 = 01, the flip); the slider leaves both low (emu_gpio.apply_straps)
GPIO_STRAPS = {(3, 0): 1}

# the viewer's skin: the flip in Stone, Ink and Ember; its skin.json has a "hinge" block (myna/web/app.js) instead of "slide"
SKIN = os.path.join(HERE, 'skin')
