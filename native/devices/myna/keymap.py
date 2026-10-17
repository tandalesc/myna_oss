"""Key map of Myna (a firmware of our own) on hardware variant A of myna/spec: plain input names for the positions of the keypad
matrix, and no key codes of the stock firmware. The form is that of a key map module of native/emu_keypad (MATRIX,
KEY_INDEX, ALIASES, SWITCHES); the profile names this module in KEYMAP.

KEY INDEX = row * 6 + column: rows 0..4 of the matrix, columns 0..5; indexes 30..35 are the direct keys (a column pulled low
with no row driven). The positions are those of that hardware (myna/spec/06-keypad.md 4.1). A firmware of our own decides itself what each key does.
Marks: ? = no physical key confirmed at that position (photographs of the keypad would settle it).
"""

# index -> (input name, physical key). Positions without a confirmed key have a name that only says where they are.
MATRIX = [
    ('3', '3'), ('6', '6'), ('1', '1'), ('camera_half', 'shutter, half press'), ('key_4', '? no key known'), ('top_right', '? right key above the screen'),
    ('call', 'call'), ('top_left', '? left key above the screen'), ('key_8', 'no key'), ('clear', 'C (clear)'), ('8', '8'), ('camera_mode', 'photo / video, side'),
    ('2', '2'), ('0', '0'), ('soft_left', 'left soft key'), ('5', '5'), ('camera_review', 'review, side'), ('9', '9'),
    ('activity', 'activity menu'), ('4', '4'), ('7', '7'), ('camera_full', 'shutter, full press'), ('hash', '#'), ('star', '*'),
    ('down', 'navigation down'), ('left', 'navigation left'), ('up', 'navigation up'), ('select', 'navigation centre'),
    ('right', 'navigation right'), ('soft_right', 'right soft key'),
    # direct keys (row "5")
    ('end', 'end; also the power key'), ('media', '? music key, side'), ('camera_onoff', '? camera on / off'),
    ('vol_up', 'volume up, side'), ('vol_down', 'volume down, side'), ('media2', '? media player key, side'),
]
KEY_INDEX = {name: i for i, (name, _key) in enumerate(MATRIX)}
KEY_CODE = {}           # no key codes: the input log names the key, its index, row and column only

ALIASES = {'send': 'call', 'power': 'end', 'c': 'clear', 'ok': 'select', 'center': 'select', 'centre': 'select',
           'volume_up': 'vol_up', 'volume_down': 'vol_down', 'shutter_half': 'camera_half', 'shutter': 'camera_full',
           'shutter_full': 'camera_full', '*': 'star', '#': 'hash', 'game_a': 'top_left', 'game_b': 'top_right'}

# switches: name -> allowed states (first = the state at power-on). The same as for the stock firmware: they are hardware.
SWITCHES = {'slide': ('closed', 'open'), 'lens_cover': ('closed', 'open'), 'headset': ('out', 'in'), 'usb': ('out', 'in'),
            'charger': ('out', 'in'), 'orientation': ('upright', 'side', 'side_other', 'flat', 'face_down')}
# the accelerometer's reading (x, y, z in g) for each position of the switch `orientation` (emu_keypad._connect_accel)
ORIENTATION_G = {'upright': (0.0, 1.0, 0.0), 'side': (1.0, 0.0, 0.0), 'side_other': (-1.0, 0.0, 0.0), 'flat': (0.0, 0.0, 1.0),
                 'face_down': (0.0, 0.0, -1.0)}
