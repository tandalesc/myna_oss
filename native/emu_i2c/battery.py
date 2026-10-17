"""Battery and converter-input model behind the AB3100 PMIC.

What the board puts on the converter's inputs belongs to the phone, so it comes from the device profile: PMIC_ANALOG is
either the parameters of an Analog (a dict, a board of our own) or the name of a module whose ANALOG is used (a board whose
values are kept elsewhere). A profile without it gets Analog() as it is below. Tags: [V] verified, [I] inferred, [MOCK]
stand-in value.

- Identification and temperature both come from ONE resistance on the battery's BDATA contact, measured on GPADC channel 11
  with a PMIC current source (reg 0x52 bits 2:0 select it, 0 = off).
- Battery voltage: auto-measurement registers 0x7d/0x7e (10 bit) and 0x7a/0x7b (8 bit), the channel-10 code.
- Phone temperature: GPADC channel 5.
"""
import importlib, math

ADC_FULL = 0xFFC0                       # 10-bit result, left justified in 16 bits [V]
KELVIN = 273.15


def beta_ohms(temp_c, r25, beta):
    """Resistance of an NTC thermistor at `temp_c` by the Beta equation: R = R25 * exp(B * (1/T - 1/298.15 K))."""
    return r25 * math.exp(beta * (1.0 / (temp_c + KELVIN) - 1.0 / (25.0 + KELVIN)))


class Analog:
    """The board side of the converter: what each input carries and each channel's range. The generic board (all values ours):
      - battery: a 47 kOhm NTC thermistor, B = 4050 K (a common 0402 part), between BDATA and ground, fed by the PMIC's
        current source: reg 0x52 = 3 gives 10 uA (470 mV at 25 C), = 7 gives 4 uA (for the cold end: 2103 mV at -20 C);
      - phone temperature (channel 5): the same thermistor type below a 47 kOhm pull-up from a 1800 mV reference (900 mV at 25 C);
      - converter ranges, mV at code 0 and at full scale: battery voltage (channel 10) 2500..4500, charger (8) 0..16000,
        every other channel 0..2500. An open BDATA contact reads full scale.
    Every value is a keyword argument, so a profile states its own: PMIC_ANALOG = dict(ntc_r25=..., ...)."""

    def __init__(self, ntc_r25=47000, ntc_beta=4050, bdata_source_ua=None, board_ntc_r25=47000, board_ntc_beta=4050,
                 board_pullup_ohms=47000, board_ref_mv=1800, scales=None, default_scale=(0, 2500)):
        self.ntc_r25, self.ntc_beta = ntc_r25, ntc_beta
        self.bdata_source_ua = dict(bdata_source_ua or {3: 10, 7: 4})
        self.board_ntc_r25, self.board_ntc_beta = board_ntc_r25, board_ntc_beta
        self.board_pullup_ohms, self.board_ref_mv = board_pullup_ohms, board_ref_mv
        self.scales = dict(scales or {10: (2500, 4500), 8: (0, 16000)})
        self.default_scale = tuple(default_scale)

    def scale(self, ch):
        """(mV at code 0, mV at full scale) of GPADC channel `ch`."""
        return self.scales.get(ch, self.default_scale)

    def ntc_ohms(self, temp_c):
        """The battery thermistor's resistance at `temp_c`."""
        return beta_ohms(max(-40.0, min(125.0, temp_c)), self.ntc_r25, self.ntc_beta)

    def bdata_mv(self, ohms, mode):
        """Voltage on BDATA with the current source `mode` (reg 0x52 bits 2:0) and `ohms` on the contact (None = open)."""
        full = self.scale(11)[1]
        if ohms is None:
            return full                 # open contact: the current source saturates at full scale [I]
        return min(full, self.bdata_source_ua.get(mode, 0) * ohms / 1000.0)

    def board_temp_mv(self, temp_c):
        """Channel 5: the phone's temperature sensor at `temp_c`."""
        r = beta_ohms(max(-40.0, min(125.0, temp_c)), self.board_ntc_r25, self.board_ntc_beta)
        return self.board_ref_mv * r / (r + self.board_pullup_ohms)

    def mv_to_raw(self, ch, mv):
        lo, hi = self.scale(ch)
        code = int(round((mv - lo) * 1023.0 / (hi - lo)))
        return max(0, min(1023, code)) << 6


def analog(profile):
    """The Analog of a device profile: its PMIC_ANALOG (a dict of parameters, or a module name with ANALOG), else Analog()."""
    spec = getattr(profile, 'PMIC_ANALOG', None)
    if spec is None:
        return Analog()
    if isinstance(spec, dict):
        return Analog(**spec)
    if isinstance(spec, str):
        return importlib.import_module(spec).ANALOG
    return spec


class Battery:
    """A Li-ion cell as the PMIC sees it. Defaults [MOCK]: present, 3950 mV, 25 C.

        pmic.battery.set(voltage_mv=3600, temp_c=40, present=True)

    `bdata_ohms` overrides the resistance on the third contact (default: the thermistor of the board's Analog at `temp_c`);
    None with present=False is an open contact."""

    def __init__(self, on_change=None, analog=None):
        self.analog = analog or Analog()
        self.voltage_mv = 3950
        self.temp_c = 25.0
        self.present = True
        self.bdata_ohms = None
        self.on_change = on_change or (lambda what: None)

    def set(self, voltage_mv=None, temp_c=None, present=None, bdata_ohms=None):
        changed = []
        if voltage_mv is not None and voltage_mv != self.voltage_mv:
            self.voltage_mv = voltage_mv; changed.append('voltage')
        if temp_c is not None and temp_c != self.temp_c:
            self.temp_c = float(temp_c); changed.append('temp')
        if bdata_ohms is not None:
            self.bdata_ohms = bdata_ohms or None; changed.append('bdata')
        if present is not None and bool(present) != self.present:
            self.present = bool(present); changed.append('present')
        for c in changed:
            self.on_change(c)
        return self

    def resistance(self):
        """Ohms on BDATA, None = open (no battery)."""
        if not self.present:
            return None
        return self.bdata_ohms if self.bdata_ohms else self.analog.ntc_ohms(self.temp_c)

    def bdata_mv(self, mode):
        return self.analog.bdata_mv(self.resistance(), mode)

    def vbat_mv(self):
        return self.voltage_mv if self.present else 0

    def describe(self):
        r = self.resistance()
        return 'battery %s, %d mV, %.0f C, BDATA %s' % ('present' if self.present else 'ABSENT', self.voltage_mv, self.temp_c,
                                                        'open' if r is None else '%.0f ohm' % r)
