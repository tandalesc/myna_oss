"""Slave models for the devices on the phone's two I2C buses.

    I2C0 "internal" (0xC0004000)   0x48  AB3100 mixed-signal ASIC (PMIC), main register page
                                   0x49  AB3100 test register page
    I2C1 "external" (0xC0005000)   0x58  MAX7327 port expander, I/O ports P2..P5
                                   0x68  MAX7327 port expander, push-pull outputs
                                   0x4a  LED / illumination driver, write-only single-byte commands (part not identified)
                                   0x1d  LIS302DL accelerometer (WHO_AM_I 0x3b)
                                   0x10  Si470x FM tuner

Every model represents a normally powered phone: battery present and healthy, no charger, no accessory, no event pending.
"""
import collections

from .bus import RegisterSlave
from .battery import Analog, Battery

# ---- AB3100 register addresses (names from the Linux ab3100 MFD / regulator drivers) ----
AB_DIS, AB_D0C, AB_D1C, AB_D2C, AB_D3C = 0x00, 0x01, 0x02, 0x03, 0x04
AB_CID = 0x20
AB_EVENTA1, AB_EVENTA2, AB_EVENTA3 = 0x21, 0x22, 0x23
AB_IMRA1, AB_IMRA2, AB_IMRA3 = 0x24, 0x25, 0x26
AB_IMRB1, AB_IMRB2, AB_IMRB3 = 0x2B, 0x2C, 0x2D
AB_MCA, AB_MCB = 0x2E, 0x2F
AB_LDO_A, AB_LDO_C, AB_LDO_D, AB_LDO_E, AB_LDO_E_SLEEP, AB_LDO_F = 0x40, 0x41, 0x42, 0x43, 0x44, 0x45
AB_LDO_G, AB_LDO_H, AB_LDO_K, AB_LDO_EXT, AB_BUCK, AB_BUCK_SLEEP = 0x46, 0x47, 0x48, 0x49, 0x4A, 0x4B
AB_SUP = 0x50
AB_REG_ON = 0x10
AB_IRQ_LINE = 0                       # EXT_IRQ0 [V]: the PMIC's interrupt pin is VIC line 0

# chip id -> revision, as the Linux ab3100 MFD driver names them
#  Chip revision %s."; 0xc0 / 0xc1 make it halt]
AB_REVISIONS = {0xC0: 'P1A', 0xC1: 'P1B', 0xC2: 'P1C', 0xC3: 'P1D', 0xC4: 'P1E', 0xC5: 'P1F/R1A', 0xC6: 'P1G/R1A', 0xC7: 'P2A/R2A',
                0xC8: 'P2B/R2B'}


# registers the Linux drivers do not name: status, converter, clock, automatic measurement
AB_STATUS = 0x27                      # live levels: bit3 DCIO charger, bit7 VBUS, bit6 battery absent [V]
ST_CHARGER, ST_NOBATT, ST_USB = 0x08, 0x40, 0x80
EV1_ONKEY, EV1_ACCESSORY, EV1_CHARGER, EV1_USB, EV1_BIT7 = 0x01, 0x02, 0x08, 0x40, 0x80
EV2_BATT_REMOVED, EV2_ALARM = 0x40, 0x80
EV3_VBAT_TRIG0, EV3_VBAT_TRIG1 = 0x10, 0x20
AB_BDATA_MODE = 0x52                  # 3 / 7 = current source on the battery data contact, 0 = off [V write, I meaning]
AB_RTC, AB_TI0 = 0x53, 0x5A           # RTC control (bit0 = time valid) and the 48-bit time, units 1/65536 s, bytes 2..5 = Unix seconds [V]
AB_ADC_CTRL, AB_ADC_HI, AB_ADC_LO = 0x73, 0x74, 0x75      # GPADC: channel | source << 5; result high / low byte [V]
AB_AUTO_CTRL = 0x79                   # auto-measurement control: 0x80 enable, 0x04 VBAT trigger armed [V write, I bit meaning]
AB_VBAT_MAX, AB_VBAT_MIN, AB_AUTO_7C, AB_VBAT_HI, AB_VBAT_LO2 = 0x7A, 0x7B, 0x7C, 0x7D, 0x7E
AB_TRIG0, AB_TRIG1 = 0x94, 0x95       # VBAT trigger levels (high 8 bits of the ADC code) [V write]
RTC_DEFAULT_EPOCH = 1224504000        # 2008-10-20 12:00:00 UTC, a fixed start so that runs are reproducible [MOCK]


class Ab3100(RegisterSlave):
    """AB3100 main page (7-bit address 0x48). Register file with:
    - CID 0x20 read-only (default 0xc8 = P2B/R2B, the newest revision);
    - EVENTA1..3 (0x21..0x23) clear on read; raise_event() latches bits and drives the interrupt line (VIC line 0 =
      EXT_IRQ0 [V]) while an unmasked event is pending (IMRA1..3: 1 = masked);
    - status 0x27 (charger / USB / battery-absent levels), GPADC 0x73..0x75, auto-measured battery voltage 0x7a..0x7e with
      a low-voltage trigger (0x94/0x95), RTC 0x53 + 0x5a..0x5f: all driven by `self.battery` and the set_* methods;
    - regulator registers with the reset values of the Linux regulator driver's table (bit 4 = on);
    - power off: LDO_D (0x42) supplies the system. A shut-down ends with writing it with 0x00 (bit 4 clear) [V]; the chip
      then cuts the rails. The model records it (`powered_off_ns`) and calls `on_power_off()` once (emu_i2c.attach stops the
      run there).
    Reads of registers nobody initialised return 0 and are counted in `unknown_reads`."""
    name = 'AB3100'

    def __init__(self, log=None, cid=0xC8, set_irq=None, now_ns=None, rtc_epoch=None, analog=None):
        super().__init__(log, defaults={
            AB_CID: cid,
            AB_EVENTA1: 0, AB_EVENTA2: 0, AB_EVENTA3: 0,
            AB_IMRA1: 0xFF, AB_IMRA2: 0xFF, AB_IMRA3: 0xFF, AB_IMRB1: 0xFF, AB_IMRB2: 0xFF, AB_IMRB3: 0xFF,
            AB_LDO_A: 0x16, AB_LDO_C: 0x10, AB_LDO_D: 0x10, AB_LDO_E: 0x10, AB_LDO_E_SLEEP: 0x00, AB_LDO_F: 0xD0,
            AB_LDO_G: 0x00, AB_LDO_H: 0x18, AB_LDO_K: 0x00, AB_LDO_EXT: 0x00, AB_BUCK: 0x7D, AB_BUCK_SLEEP: 0xAC,
            AB_RTC: 0x01,                                   # time valid: the RTC kept running on the battery [MOCK]
            AB_ADC_HI: 0, AB_ADC_LO: 0,
            0x7F: 0, 0x80: 0, 0x81: 0,                      # charger-side auto measurements: no charger [MOCK]
            0x9C: 0, 0x9D: 0, 0x9E: 0, 0x9F: 0,             # fuel-gauge counter read-out: no current [MOCK]
        })
        self.set_irq = set_irq or (lambda level: None)
        self.irq_level = False
        self.now_ns = now_ns or (lambda: 0)
        self.analog = analog or Analog()        # what the board puts on the converter inputs (battery.analog(profile))
        self.battery = Battery(on_change=self._battery_changed, analog=self.analog)
        self.charger = False            # DCIO wall charger plugged
        self.usb = False                # VBUS present
        self.charger_mv = 5000
        self.pcb_temp_c = 25.0          # phone temperature sensor on GPADC channel 5 [MOCK]
        self.mock_mv = {6: 1325, 12: 1975}      # channels the model does not drive: stand-ins [MOCK]
        self.conversions = collections.Counter()
        self.events_raised = []         # (ns, a1, a2, a3)
        self._trig_fired = set()
        self._rtc_base = (RTC_DEFAULT_EPOCH if rtc_epoch is None else int(rtc_epoch)) << 16     # 48-bit count at now_ns() == _rtc_t0
        self._rtc_t0 = 0
        self.powered_off_ns = None      # emulated time at which the firmware switched LDO_D off
        self.on_power_off = None        # callable, called once at that moment

    # ---- interrupt / events ----
    def _update(self):
        r = self.regs
        level = any(r[e] & ~r[m] & 0xFF for e, m in ((AB_EVENTA1, AB_IMRA1), (AB_EVENTA2, AB_IMRA2), (AB_EVENTA3, AB_IMRA3)))
        if level != self.irq_level:
            self.irq_level = level
            self.set_irq(level)

    def raise_event(self, a1=0, a2=0, a3=0):
        """Latch event bits (EV1_* / EV2_* / EV3_*) and raise the interrupt if any is unmasked."""
        self.regs[AB_EVENTA1] |= a1; self.regs[AB_EVENTA2] |= a2; self.regs[AB_EVENTA3] |= a3
        self.events_raised.append((self.now_ns(), a1, a2, a3)); del self.events_raised[:-64]
        self._update()

    def set_charger(self, plugged):
        """Wall charger on DCIO: status bit3 follows the level, EVENTA1 bit3 fires on every change. [V]"""
        if bool(plugged) != self.charger:
            self.charger = bool(plugged)
            self.raise_event(a1=EV1_CHARGER)

    def set_usb(self, plugged):
        """USB VBUS: status bit7, EVENTA1 bit6 on every change. [V]"""
        if bool(plugged) != self.usb:
            self.usb = bool(plugged)
            self.raise_event(a1=EV1_USB)

    def power_key(self):
        """ON key press: EVENTA1 bit0, also the power-up cause "ON key". [V at start-up, I at runtime]"""
        self.raise_event(a1=EV1_ONKEY)

    def status(self):
        return (ST_CHARGER if self.charger else 0) | (ST_USB if self.usb else 0) | (0 if self.battery.present else ST_NOBATT)

    def _battery_changed(self, what):
        if what == 'present' and not self.battery.present:
            self.raise_event(a2=EV2_BATT_REMOVED)       # [V] removal: EVENTA2 bit6, status bit6 = absent
        self._check_trigger()

    # ---- measurements ----
    def adc_mv(self, ch, source=0):
        """Voltage at the converter input for GPADC channel `ch` (what the firmware's calibration turns the code back into)."""
        b = self.battery
        if ch == 11:
            return b.bdata_mv(self.regs.get(AB_BDATA_MODE, 0) & 7)
        if ch == 10:
            return b.vbat_mv()
        if ch == 8:
            return self.charger_mv if self.charger else 0
        if ch == 5:
            return self.analog.board_temp_mv(self.pcb_temp_c)
        return self.mock_mv.get(ch, 0)

    def adc_raw(self, ch, source=0):
        if ch == 13:
            return 0x8000               # signed channel: mid-scale = zero [MOCK]
        return self.analog.mv_to_raw(ch, self.adc_mv(ch, source))

    def _vbat_raw(self):
        return self.analog.mv_to_raw(10, self.battery.vbat_mv())

    def _check_trigger(self):
        """VBAT below an armed trigger level -> EVENTA3 bit4 (level reg 0x94) / bit5 (0x95), once per arming (reg 0x79 bit2). [I]
       """
        if not self.regs.get(AB_AUTO_CTRL, 0) & 0x04:
            return
        v8 = self._vbat_raw() >> 8
        for reg, bit in ((AB_TRIG0, EV3_VBAT_TRIG0), (AB_TRIG1, EV3_VBAT_TRIG1)):
            lvl = self.regs.get(reg, 0)
            if lvl and v8 < lvl and reg not in self._trig_fired:
                self._trig_fired.add(reg)
                self.raise_event(a3=bit)

    # ---- RTC ----
    def rtc_count(self):
        return (self._rtc_base + (self.now_ns() - self._rtc_t0) * 65536 // 1_000_000_000) & 0xFFFFFFFFFFFF

    def rtc_seconds(self):
        return self.rtc_count() >> 16

    # ---- register semantics ----
    def get(self, reg):
        if reg == AB_STATUS:
            self.regs[reg] = self.status()
        elif AB_TI0 <= reg < AB_TI0 + 6:
            self.regs[reg] = (self.rtc_count() >> (8 * (reg - AB_TI0))) & 0xFF
        elif reg in (AB_VBAT_MAX, AB_VBAT_MIN, AB_AUTO_7C):
            self.regs[reg] = self._vbat_raw() >> 8      # 0x7c: meaning unknown [MOCK]
        elif reg == AB_VBAT_HI:
            self.regs[reg] = self._vbat_raw() >> 8
        elif reg == AB_VBAT_LO2:
            self.regs[reg] = (self._vbat_raw() >> 6) & 3
        v = super().get(reg)
        if reg in (AB_EVENTA1, AB_EVENTA2, AB_EVENTA3):
            self.regs[reg] = 0
            self._update()
        return v

    def put(self, reg, value):
        if reg in (AB_CID, AB_EVENTA1, AB_EVENTA2, AB_EVENTA3, AB_STATUS, AB_ADC_HI, AB_ADC_LO):
            return                      # read-only
        if AB_TI0 <= reg < AB_TI0 + 6:
            sh = 8 * (reg - AB_TI0)
            self._rtc_base = (self.rtc_count() & ~(0xFF << sh)) | (value << sh)
            self._rtc_t0 = self.now_ns()
        was = self.regs.get(reg, 0)
        self.regs[reg] = value
        if reg in (AB_IMRA1, AB_IMRA2, AB_IMRA3):
            self._update()
        elif reg == AB_LDO_D:           # bit 4 = on: clearing it removes the system supply
            if was & AB_REG_ON and not value & AB_REG_ON and self.powered_off_ns is None:
                self.powered_off_ns = self.now_ns()
                self.log('[%s] LDO_D (0x42) = %#04x at %.1f ms: system supply switched off by the firmware' % (self.name, value, self.powered_off_ns / 1e6))
                if self.on_power_off:
                    self.on_power_off()
        elif reg == AB_ADC_CTRL:        # the conversion is done when the firmware reads the result (it reads at once) [V]
            ch, src = value & 0x0F, (value >> 5) & 3
            raw = self.adc_raw(ch, src)
            self.conversions[ch] += 1
            self.regs[AB_ADC_HI], self.regs[AB_ADC_LO] = raw >> 8, raw & 0xFF
        elif reg in (AB_AUTO_CTRL, AB_TRIG0, AB_TRIG1):
            if reg == AB_AUTO_CTRL:
                self._trig_fired.clear()
            else:
                self._trig_fired.discard(reg)
            self._check_trigger()

    def summary(self):
        conv = ' '.join('ch%d:%d' % kv for kv in sorted(self.conversions.items())) or '-'
        off = '' if self.powered_off_ns is None else '; POWERED OFF by the firmware at %.1f ms (LDO_D = 0)' % (self.powered_off_ns / 1e6)
        return (super().summary() + '\n[%s] %s; charger %s, usb %s, status %#04x; ADC conversions %s; RTC %d; events raised %d%s'
                % (self.name, self.battery.describe(), 'in' if self.charger else 'out', 'in' if self.usb else 'out', self.status(), conv,
                   self.rtc_seconds(), len(self.events_raised), off))


class Ab3100Test(RegisterSlave):
    """AB3100 test register page (7-bit address 0x49). The Linux driver (chip id 0xc4) writes register 0x02 = 0x08 here to
    switch the ASIC to the 32 kHz RTC clock. Plain storage."""
    name = 'AB3100-test'


class Max7327:
    """MAX7327 port expander: two slave addresses (0x58 = the four open-drain I/O ports P2..P5, 0x68 = the push-pull outputs).
    A write latches output bytes (first byte = ports 0..7, second = ports 8..15). A read of the I/O address returns the
    port levels (an open-drain port reads low when driven low, else the external level `inputs`) followed by the
    transition flags. Read format is from the data sheet family description, not checked against firmware code. [I]"""

    class _Port:
        def __init__(self, chip, io):
            self.chip, self.io = chip, io
            self.name = 'MAX7327-' + ('io' if io else 'out')
            self.writes = []
            self.nreads = 0

        def start(self, read):
            self._n = 0
            return True

        def write(self, byte):
            c = self.chip
            if self.io:
                c.io_latch = byte
            else:
                c.out[self._n & 1] = byte
            self._n += 1
            self.writes.append(byte); del self.writes[:-16]
            return True

        def read(self, ack):
            c = self.chip
            self.nreads += 1
            self._n += 1
            if not self.io:
                return c.out[(self._n - 1) & 1]
            if self._n & 1:
                level = c.io_latch & c.inputs & 0x3C
                c.flags = 0             # transition flags clear when the ports are read
                return level
            return c.flags

        def stop(self):
            pass

        def summary(self):
            return f'[{self.name}] writes {" ".join("%02x" % b for b in self.writes) or "-"}; reads {self.nreads}'

    def __init__(self, inputs=0xFF):
        self.inputs = inputs            # external levels on P2..P5 (pulled up)
        self.io_latch = 0xFF
        self.out = [0xFF, 0xFF]
        self.flags = 0
        self.io = Max7327._Port(self, True)
        self.outputs = Max7327._Port(self, False)


class LedCommandDriver:
    """Illumination driver at 0x4a on I2C1: write-only, one byte per transfer. Encoding: top bits = command, low bits = value: commands 0x20/0x40/0x60/0x80 carry a 5-bit value,
    0x00/0xe0/0xf0 a 4-bit value, 0xc0 a 5-bit value. The part is not identified; the model records the last value of
    each command in `state`. Reads are not acknowledged (the firmware never reads it)."""
    name = 'LED-0x4a'

    def __init__(self):
        self.state = {}
        self.history = []

    @staticmethod
    def decode(byte):
        if byte & 0xE0 in (0x20, 0x40, 0x60, 0x80, 0xC0):
            return byte & 0xE0, byte & 0x1F
        return byte & 0xF0, byte & 0x0F

    def start(self, read):
        return not read

    def write(self, byte):
        cmd, val = self.decode(byte)
        self.state[cmd] = val
        self.history.append(byte); del self.history[:-32]
        return True

    def read(self, ack):
        return 0xFF

    def stop(self):
        pass

    def summary(self):
        return f'[{self.name}] commands ' + (' '.join(f'{c:02x}:{v:02x}' for c, v in sorted(self.state.items())) or '-')


class Lis302dl:
    """ST LIS302DL 3-axis accelerometer at 0x1d on I2C1 (auto-rotation, shake control). Identity: a driver reads register 0x0f
    and requires 0x3b (the LIS302DL / LIS202DL WHO_AM_I), then reads 0x20, 0x21, 0x22 (CTRL_REG1..3); write address 0x3a,
    read address 0x3b [V]. Part
    name from the data sheet match [I]. Register side per the data sheet: sub-address bit 7 = auto-increment.

    Output registers [MOCK]: a phone lying still, `g` = (x, y, z) in g along the chip's axes, default flat on its back
    (0, 0, +1); 8-bit two's complement, 18 mg per digit (72 mg with CTRL_REG1.FS). While powered down (CTRL_REG1.PD = 0, the reset state and what the firmware leaves until a client
    subscribes) the outputs and STATUS read 0.

    How a driver uses it [V run and code]: nothing is read until it is needed; then CTRL_REG1 = 0x47 powers it up, and
    0x07 powers it down again. While up the driver reads five bytes from 0x29 with auto-increment (OUT_X, -, OUT_Y, -,
    OUT_Z) on its own timer (every 50 ms) and hands them on as x = -OUT_Y, y = OUT_X, z = OUT_Z in mg. It is polling
    only: the driver writes no register but CTRL_REG1, so INT1 / INT2 (free-fall, click) are never enabled and are not
    wired to anything here.
    """
    name = 'LIS302DL'
    WHO_AM_I, CTRL1, CTRL2, CTRL3, STATUS, OUT_X, OUT_Y, OUT_Z = 0x0F, 0x20, 0x21, 0x22, 0x27, 0x29, 0x2B, 0x2D

    def __init__(self, g=(0.0, 0.0, 1.0)):
        self.g = tuple(g)
        self.regs = {self.WHO_AM_I: 0x3B, self.CTRL1: 0x07, self.CTRL2: 0x00, self.CTRL3: 0x00}     # data-sheet reset values
        self.ptr = 0
        self.inc = False
        self._first = False
        self.reads = collections.Counter()
        self.writes = collections.OrderedDict()

    def set_g(self, x, y, z):
        self.g = (x, y, z)

    # How the chip sits on the board: each chip axis as (phone axis, sign), phone axes 0 = x towards the right side,
    # 1 = y towards the top, 2 = z out of the screen. Chip X = phone +y, chip Y = phone -x [V]: it undoes the driver's
    # own turn (x = -OUT_Y, y = OUT_X). Chip Z = phone +z [I].
    AXES = ((1, 1), (0, -1), (2, 1))

    def set_phone_g(self, x, y, z):
        """Readings for a phone at rest, given in the phone's own axes."""
        p = (x, y, z)
        self.g = tuple(p[axis] * sign for axis, sign in self.AXES)

    @property
    def active(self):
        return bool(self.regs[self.CTRL1] & 0x40)

    def get(self, reg):
        if reg in (self.OUT_X, self.OUT_Y, self.OUT_Z):
            if not self.active:
                return 0
            mg = 72.0 if self.regs[self.CTRL1] & 0x20 else 18.0
            return max(-128, min(127, round(self.g[(reg - self.OUT_X) >> 1] * 1000 / mg))) & 0xFF
        if reg == self.STATUS:
            return 0x0F if self.active else 0       # ZYXDA | ZDA | YDA | XDA: a new sample is always there
        return self.regs.get(reg, 0)

    def start(self, read):
        self._first = not read
        return True

    def write(self, byte):
        if self._first:
            self.ptr, self.inc, self._first = byte & 0x7F, bool(byte & 0x80), False
            return True
        if self.ptr != self.WHO_AM_I:
            self.regs[self.ptr] = byte
        self.writes.setdefault(self.ptr, []).append(byte)
        del self.writes[self.ptr][:-8]
        if self.inc:
            self.ptr = (self.ptr + 1) & 0x7F
        return True

    def read(self, ack):
        self.reads[self.ptr] += 1
        v = self.get(self.ptr)
        if self.inc:
            self.ptr = (self.ptr + 1) & 0x7F
        return v

    def stop(self):
        pass

    def summary(self):
        r = ' '.join(f'{k:02x}x{n}' for k, n in sorted(self.reads.items()))
        w = ' '.join(f'{k:02x}={",".join("%02x" % x for x in v)}' for k, v in sorted(self.writes.items()))
        return f'[{self.name}] {"active" if self.active else "powered down"}; read {r or "-"}; written {w or "-"}'


class Si470x:
    """Silicon Labs Si470x FM tuner (Si4702 / Si4703 family) at 0x10 on I2C1: the FM radio. Identity [I]: a driver keeps a
    shadow of 16-bit registers that starts with register 0x02 and uses it the Si470x way: seek = bit 8 of the first word
    (cleared with & 0xfeff), band = bits 7:6 of the fourth word (0x05 SYSCONFIG2; 0x80 / 0x40 / 0x00), status mask 0xc000
    (RDSR | STC); and its first transfer at start-up is
    the 10-byte write `00 41 00 00 00 04 00 00 00 00` = 0x02 POWERCFG ENABLE | DISABLE (the data sheet's power-down
    sequence), 0x04 SYSCONFIG1 GPIO2 = STC / RDS interrupt [V bytes]. The exact part (RDS or not) is not determined.

    Bus protocol of the part: no register pointer; a write fills 0x02, 0x03, ... high byte first, a read returns 0x0a,
    0x0b, ... 0x0f, 0x00, ... high byte first.

    Behaviour [MOCK, no radio signal exists here]: TUNE (0x03 bit 15) while powered up sets STC and READCHAN = CHAN; SEEK
    (0x02 bit 8) sets STC and SF/BL (seek failed, band limit: no station found); clearing the bit clears them. RSSI 0, no
    stereo, no RDS. DEVICEID 0x1242 and CHIPID 0x1253 (0x1200 while powered down) are data sheet values from memory, not
    seen being read by the firmware.

    Time and the interrupt pin (with a clock, `now_ns`): an operation completes OP_NS after the bit is set (60 ms, the data
    sheet's seek / tune time for one channel, from memory [I]; a seek that finds nothing takes the same time [MOCK]). When
    it completes and SYSCONFIG1 (0x04) has STCIEN (bit 14) and GPIO2 = interrupt (bits 3:2 = 01), GPIO2 goes low for
    PULSE_NS (5 ms, data sheet from memory [I]) and high again: `set_int(level)`, which the board wires to a SoC pin.
    A driver may need both: it sets TUNE or SEEK, then waits for that interrupt before it reads the status and clears
    the bit [V run]; an STC that is already there when the write ends is never read. Without a clock (tests) an operation completes at once and the pin is not driven."""
    name = 'Si470x'
    POWERCFG, CHANNEL, SYSCONFIG1, STATUSRSSI, READCHAN = 0x02, 0x03, 0x04, 0x0A, 0x0B
    STC, SFBL = 0x4000, 0x2000
    OP_NS, PULSE_NS = 60_000_000, 5_000_000

    def __init__(self, now_ns=None, set_int=None):
        self.now_ns = now_ns                    # emulated time in ns; None = operations complete at once
        self.set_int = set_int or (lambda level: None)      # GPIO2 pin (1 = idle)
        self.regs = [0] * 16
        self.regs[0] = 0x1242
        self._n = 0
        self.nwrites = self.nreads = 0
        self.last_write = b''
        self._buf = None
        self._op = None                         # 'tune' / 'seek' while its bit is set
        self._done_ns = self._pulse_ns = None   # when the running operation completes / when the pulse on GPIO2 ends
        self.pulses = 0

    @property
    def powered(self):
        return self.regs[self.POWERCFG] & 0x41 == 0x01      # ENABLE without DISABLE

    def _apply(self):
        r = self.regs
        r[1] = 0x1253 if self.powered else 0x1200
        op = None
        if self.powered:
            op = 'tune' if r[self.CHANNEL] & 0x8000 else 'seek' if r[self.POWERCFG] & 0x0100 else None
        if op is None:                                      # the bit is clear: STC and SF/BL go away
            r[self.STATUSRSSI] = r[self.STATUSRSSI] & ~(self.STC | self.SFBL) & 0xFFFF if self.powered else 0
            self._op = self._done_ns = None
        elif self.now_ns is None:
            self._op = op
            self._complete()
        elif self._op is None:                              # an operation starts
            self._op = op
            self._done_ns = self.now_ns() + self.OP_NS

    def _complete(self):
        r = self.regs
        self._done_ns = None
        if self._op == 'tune':
            r[self.STATUSRSSI] |= self.STC
            r[self.READCHAN] = r[self.CHANNEL] & 0x03FF
        else:                                               # seek: nothing to find
            r[self.STATUSRSSI] |= self.STC | self.SFBL
        if self.now_ns is not None and r[self.SYSCONFIG1] & 0x4000 and r[self.SYSCONFIG1] & 0x000C == 0x0004:
            self.pulses += 1
            self._pulse_ns = self.now_ns() + self.PULSE_NS
            self.set_int(0)

    # ---- timer protocol of emu_irq.IrqTimerSystem ----
    def next_event_ns(self):
        ts = [t for t in (self._done_ns, self._pulse_ns) if t is not None]
        return min(ts) if ts else None

    def pending_events(self):
        t = self.next_event_ns()
        return [(t, 'FM tuner: operation complete / end of the interrupt pulse', -1)] if t is not None else []

    def advance(self):
        if self.now_ns is None:
            return
        t = self.now_ns()
        if self._pulse_ns is not None and t >= self._pulse_ns:
            self._pulse_ns = None
            self.set_int(1)
        if self._done_ns is not None and t >= self._done_ns:
            self._complete()

    def start(self, read):
        self._n = 0
        self._buf = None if read else bytearray()
        return True

    def write(self, byte):
        reg = (self.POWERCFG + (self._n >> 1)) & 0x0F
        if reg >= self.POWERCFG and reg < self.STATUSRSSI:  # 0x0a..0x0f, 0x00, 0x01 are read-only
            self.regs[reg] = (self.regs[reg] & 0x00FF | byte << 8) if not self._n & 1 else (self.regs[reg] & 0xFF00 | byte)
        self._n += 1
        self._buf.append(byte)
        self._apply()
        return True

    def read(self, ack):
        reg = (self.STATUSRSSI + (self._n >> 1)) & 0x0F
        v = self.regs[reg] >> 8 if not self._n & 1 else self.regs[reg] & 0xFF
        self._n += 1
        self.nreads += 1
        return v

    def stop(self):
        if self._buf:
            self.nwrites += 1
            self.last_write = bytes(self._buf)
        self._buf = None

    def summary(self):
        return (f'[{self.name}] {"powered up" if self.powered else "powered down"}; {self.nwrites} write(s), last '
                f'{self.last_write.hex(" ") or "-"}; {self.nreads} byte(s) read; {self.pulses} interrupt pulse(s) on GPIO2')


def rtc_epoch():
    """Start value of the PMIC clock: environment EMU_PMIC_RTC = "host" (host clock) or Unix seconds; default the fixed
    2008-10-20 12:00 UTC so that runs are reproducible. [MOCK]"""
    import os, time
    v = os.environ.get('EMU_PMIC_RTC', '')
    if v == 'host':
        return int(time.time())
    return int(v, 0) if v else None


def populate(sys_, log=None, irq_system=None, analog=None):
    """Put the phone's slaves on the two buses of an I2cSystem (emu_i2c.attach result). `analog`: the board's converter
    inputs (battery.analog(profile); default the generic Analog)."""
    set_irq = (lambda level: irq_system.vic.set_line(AB_IRQ_LINE, level)) if irq_system is not None else None
    now_ns = getattr(irq_system, 'now_ns', None)
    sys_.pmic = sys_.bus0.attach(0x48, Ab3100(log, set_irq=set_irq, now_ns=now_ns, rtc_epoch=rtc_epoch(), analog=analog))
    sys_.pmic_test = sys_.bus0.attach(0x49, Ab3100Test(log))
    sys_.expander = Max7327()
    sys_.bus1.attach(0x58, sys_.expander.io)
    sys_.bus1.attach(0x68, sys_.expander.outputs)
    sys_.led = sys_.bus1.attach(0x4A, LedCommandDriver())
    sys_.accel = sys_.bus1.attach(0x1D, Lis302dl())
    sys_.fm = sys_.bus1.attach(0x10, Si470x(now_ns=now_ns))
    return sys_
