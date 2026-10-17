"""Minimal placeholder devices, replaceable by real models. No Unicorn import."""


class FreeRunTimer:
    """Free-running counter at +0x18 (a boot loader's delay loop polls 0xC001A018).
    Advances `step` ticks per read, so delays elapse without real time. Placeholder; unit unknown."""
    name = 'TIMER-stub'

    def __init__(self, step=100):
        self.cnt = 0
        self.step = step

    def read(self, off, size):
        if off == 0x18:
            self.cnt = (self.cnt + self.step) & 0xFFFFFFFF
            return self.cnt
        return 0

    def write(self, off, size, value):
        pass


class NoCardMmci:
    """PL180-style MMC/SD controller (0xC0001000) with no card inserted.
    A card probe writes ARGUMENT +8, COMMAND +0xC (bit10 enable, bit6 response),
    polls STATUS +0x34 and clears via +0x38. Commands without response complete (bit7 CmdSent);
    commands with response time out (bit2). [register layout inferred from the poll code + PL180 TRM]"""
    name = 'MMCI-nocard'

    def __init__(self):
        self.regs = {}
        self.status = 0

    def read(self, off, size):
        if off == 0x34:
            return self.status
        return self.regs.get(off, 0)

    def write(self, off, size, value):
        if off == 0x38:
            self.status &= ~value
        elif off == 0x0C:
            if value & 0x400:
                self.status |= 0x04 if value & 0x40 else 0x80
        self.regs[off] = value
