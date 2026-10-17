#!/usr/bin/env python3
"""DB3210 simulator: run the application CPU and the modem ("access") CPU of a DB3210 phone together. The phone model and firmware
release come from a device profile (native/devices, --device, default devices.DEFAULT).

  native/.venv/bin/python -I native/sim/db3210.py [options]

  --device NAME          device profile, a module of native/devices (default: SIM_DEVICE, else devices.DEFAULT). The profile says where the
                         flash images are. SIM_CHIP=FILE: another flash image. A profile with BOOT_ELF runs a firmware of our own
                         instead (an ELF file, myna/README.md): its segments are loaded into memory and the application CPU starts
                         at its entry; no flash image, boot loader, modem image, instrument table or boot-ROM stand-in, no modem CPU.
                         Its NAND is a blank chip (all 0xFF) of the geometry the profile names in NAND_CHIP (default: the stock phones' chip).
                         The tracer, the stand-ins of native/emu_shim, the stock modem stand-in and --extcc-bypass are refused or
                         left out for it: they act on addresses and protocols of the stock firmware
  --main FILE --fs FILE  REQUIRED for the first run of a device, unless the files are in firmware/NAME/: the two firmware
                         containers as downloaded (.mbn, .fbn). The factory flash image is made from them once and kept
                         (native/devices/source.py); later runs read no container. A file that is not in the supported
                         list (docs/SUPPORTED.md) is used with a warning: untested, and its image has its own name
  --pack FILE            the customization pack (.zip): REQUIRED for a phone with a SIM card, not needed for a phone with no
                         SIM card. The run then starts from the custom flash image
  --custom               start from the custom flash image (the pack from firmware/NAME/); default: the factory flash image
  --log-dir DIR          where the UART logs of the two CPUs go (default: SIM_LOG_DIR, else run/ at the repository root; a
                         directory DIR/<device> is made on demand)
  --standard             attach the profile's add-on chips (its ATTACH list) and its modem stand-in (PEER) unless --peer is given
  --mode full|shortcut   full (default): the stock boot loader boots from the emulated NAND as in native/boot.py and loads the
                         modem image itself; the modem is released when it calls the boot-ROM "start access CPU" service (vector
                         at TCM 0x44). shortcut: platform image started directly as in emu_link/run_app.py (seconds instead of
                         minutes); the modem image is copied from the file and the modem is released at --start-acc-at app
                         instructions.
  --seconds N            host time limit (default 600)          --emu-seconds S   emulated time limit (default none)
  --trace none|key|all   application-side tracer of the stock firmware's OS: key = hunts, errors, console (default); all = also every
                         send/receive
  --wire                 print every control byte and every MSL frame crossing the link (always counted and checked)
  --report               print the stock application's process table at the stop
  --hw-report            list the application hardware addresses that no device model claimed
  --no-modem             never release the modem (single-CPU baseline under the same scheduler)
  --display              attach the XGAM display model (native/emu_lcd) to the application CPU at 0xD0000000
  --frames-dir DIR       implies --display; every display refresh is written to DIR/frame_NNNN.png
  --frame-stream PATH    implies --display; every display refresh goes to the Unix socket PATH, where a viewer listens
                         (native/tools/live_view.py). Only the newest picture is kept for a slow viewer; the run never waits.
  --attach MOD:FUNC      extra application-side device models (repeatable). MOD is imported with native/ on sys.path and
                         FUNC(machine, irq_system) is called once, after IrqTimerSystem.install() and before the run; it attaches
                         its devices with machine.attach(base, size, dev, name) and raises interrupts with
                         irq_system.vic.set_line(line, level). If it returns an object with summary(), that is printed at the stop.
                         Example: --attach emu_i2c:attach
  --attach-acc MOD:FUNC  the same for the modem CPU. Example: --attach-acc emu_uart_acc:attach
  --extcc-bypass         EXPERIMENT, off by default, stock firmware only: at 10 s emulated write the profile's EXTCC_PID into its EXTCC_PID_SLOT
  --no-spin-skip         turn off the default skipping of whole periods of a verified pure polling loop (same registers each period, no stores, only
                         unchanged reads): bit-identical to executing it, counted in Machine.spin_skipped
  --fast                 watch mode: no tracer (--trace none), no wire sniffer, no per-access
                         bus accounting; --wire/--report/--hw-report are ignored. Kept: UART console, display frames, modem console, fatal-error detection, progress line.
  --mmio / --no-mmio     hardware windows as Unicorn MMIO regions (default with --fast) or as hooked RAM pages (default otherwise). Same behaviour;
                         MMIO regions keep RAM loads and stores of the guest on Unicorn's fast path and let the NAND ready polls, timing registers
                         and address cycles be served from compiled code
  --block-slices         OPT-IN, changes timing by microseconds: application CPU slices end at the first translation-block boundary at or after --slice
                         instructions instead of exactly there, so Unicorn needs no per-instruction hook (about 1.3x faster while the CPU is busy).
                         Emulated time still counts executed instructions and a run is repeatable; no spin skip on the application CPU.
                         --slice-log FILE records the slice lengths (and where an interrupt was taken inside a slice); --slice-replay FILE (without --block-slices) runs exact slices of those lengths,
                         which must give the same output: the check that the block accounting is exact.
  --async-frames         OPT-IN (viewer): the frame PNGs are compressed and written by a second thread. Same files; each "display frame" line
                         is printed when its file is complete, so a few ms later in the log than with the default
  --keep-going           keep running the other CPU after one of them halts
  --idle stop|wait       what happens when the application CPU sleeps (WFI) with nothing scheduled on any CPU, no timer event
                         and no interrupt: stop = the run ends ("nothing scheduled on any CPU"; the default, for batch runs);
                         wait = the run waits for the host: emulated time follows the host clock, the device pollers (the key
                         control file, a stop request of the flash state) run on the way, and the host sleeps in between. A key
                         press, or anything else that raises an interrupt, wakes the CPU. The viewer gives it for a device with
                         BOOT_ELF. run(..., hold=True) of a program (a page) also waits: it ends at the end of the time asked for
  --slice N              instructions per scheduling slice (default 20000 = 200 us emulated)
  --dis SIDE:ADDR:LEN:a|t / --mem SIDE:ADDR:LEN   disassemble / hex-dump live memory of APP or ACC at the stop

Both CPUs are native/emu Machines with their own emu_irq VIC pair, timer and clock. They share one host buffer mapped at
application 0x28000000 and modem 0x48000000 (the window the stock boot loader loads the modem image into) and are joined by one emu_link.AaifLink
plus one Dmac per side. Scheduling: the started, awake side with the smaller emulated clock runs one slice; a side in WFI
sleeps until its own next timer event or an interrupt from the peer, and never skips past the peer's clock.

For a program (a page, a test) the launcher is three calls; main() is built on them:
  phone = build(device, chip=..., flash=..., peer_config=..., options=[...], out=..., on_frame=...)   the machine of this phone
  run(phone, ns) -> {'why', 'ended', 'now_ns', 'insns', 'rest_ns'}   run it for ns of emulated time; no sleep, no host clock
                                                             (hold=True: a phone asleep with nothing scheduled is held, not stopped;
                                                             rest_ns: how long a held phone has nothing to do, for a caller that waits)
  report(phone, why)                                         the lines main() prints at the stop
  phone.press(name), phone.release(name), phone.inputs       keys by the names of the keypad's control file; phone.flash_state()
With --core own and a modem stand-in nothing of this imports Unicorn, and with --no-uart-log and without --frames-dir,
--frame-stream, --async-frames it starts no thread and writes no file.
"""
import argparse, collections, ctypes, mmap, os, struct, sys, time

HERE = os.path.dirname(os.path.abspath(__file__)); NATIVE = os.path.dirname(HERE); ROOT = os.path.dirname(NATIVE)
for p in (NATIVE, os.path.join(NATIVE, 'emu_nand'), os.path.join(NATIVE, 'tools'), os.path.join(NATIVE, 'acc')):
    sys.path.insert(0, p)
from emu.stubs import NoCardMmci
from emu import loaders
from emu_irq import IrqTimerSystem
from emu_link import AaifLink, Dmac
import boot as appboot
import nand_model

import devices                                  # devices.source (the stock firmware files) only where a stock run needs it
UC_PROT_ALL, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0 = 7, 10, 11, 66     # Unicorn's numbers (unicorn, unicorn.arm_const). Unicorn
                                                                             # itself is imported only for a CPU that runs on it
AAIF_BASE, DMA_BASE = 0xC0022000, 0xC0020000
SHARED_APP, SHARED_ACC, SHARED_SIZE = 0x28000000, 0x48000000, 0x00E00000     # the modem's SDRAM window, 14 MB
ROM_START_ACC = 0x44            # TCM vector of the boot-ROM service that starts the access CPU, r0 = its entry
CTL = {0: '?0', 1: '?1', 2: 'hello', 3: 'pm-notify', 4: 'err4', 5: 'err5', 6: 'sleep-proposal', 7: 'wake-request', 8: 'wake-ack'}
INF = float('inf')


class ClockProfile:
    """Application 0xA0004000 [I]: a clock-switch routine (entered when both link managers agree to sleep) polls +0x04 bit2
    until it equals the request bit2 it wrote to +0x20."""
    name = 'CLKPROF'
    def __init__(self): self.r = {}
    def read(self, off, size):
        v = self.r.get(off & ~3, 0)
        if (off & ~3) == 4: return (v & ~5) | (self.r.get(0x20, 0) & 4)
        return v
    def write(self, off, size, v): self.r[off & ~3] = v


class AppSysCtrl(appboot.SysCtrl):
    """native/boot.py SysCtrl plus [I]: +0x4d0 bit3 reads as set (the clock-switch routine waits for it after writing bit2),
    and [MOCK] +0x004 bit1 = PLL locked, instantly, unless clock select +0x000 bits 2:0 = 4 (PLL off). A clock manager
    waits for it when a fast clock is requested again after everything went idle."""
    def read(self, off, size):
        v = self.regs.get(off, 0)
        if off == 0x004 and (self.regs.get(0x000, 0) & 7) != 4:
            v |= 2
        return v | 8 if (off & ~3) == 0x4d0 else v


class AccSysCon:
    """Modem 0xC0012000 (SYSCON). Storage, plus [I]: +0x300 bit2 follows bit1. A sleep routine sets bit1 and polls until bit2 is
    set; the wake routine clears it and polls until bit2 is clear."""
    name = 'ACC-SYSCON'
    def __init__(self): self.r = {}
    def read(self, off, size):
        v = self.r.get(off & ~3, 0)
        if (off & ~3) == 0x300: v = (v & ~4) | (4 if v & 2 else 0)
        return v
    def write(self, off, size, v): self.r[off & ~3] = v


class Side:
    def __init__(self, name, m, irq):
        self.name, self.m, self.irq = name, m, irq
        self.started = True
        self.asleep = False        # in WFI, waiting for an interrupt or its next timer event
        self.rt_gate = None        # --realtime: callable giving the emulated time (ns) the wall clock allows
        self.dead = None           # stop reason once the CPU has halted for good
        self.entry = None
        self.slices = self.wakes = 0
        self.slice_end = 0         # instruction count at which the last slice was to end
        self.gated = False         # asleep because rt_gate said so: by the host's clock, not by anything emulated
        self.peer = None

    @property
    def now(self):
        return self.irq.clock.now_ns

    def key(self):
        """Emulated time at which this side wants to run next."""
        if not self.started or self.dead:
            return INF
        if not self.asleep or self.irq.vic.irq_out:
            return self.now
        t = self.irq.next_event_ns()
        return INF if t is None else max(t, self.now)

    def try_wake(self):
        """Side is at a WFI. Advance its clock to the wake-up cause if there is one that the peer's clock allows. True = resume."""
        irq, peer = self.irq, self.peer
        if irq.vic.irq_out:
            if peer.started and peer.now > self.now:      # the interrupt was raised by the peer: cannot be taken in the past
                irq.clock.skip_to(peer.now); irq.timer.advance()
            self.m.irq_pending = irq.vic.irq_out
            return True
        t = irq.next_event_ns()
        if t is None or t > peer.key():
            return False
        if self.rt_gate and t > self.rt_gate() + 2e6:     # --realtime: the wall clock has not reached that event yet; the main
            self.gated = True                             # loop walks emulated time there (and keeps polling for key presses)
            return False
        before = self.now
        if t > before:
            irq.clock.skip_to(int(t)); irq.idle_count += 1; irq.idle_skipped_ns += self.now - before
        irq.timer.advance()
        self.m.irq_pending = irq.vic.irq_out
        return True

    def idle_cb(self):
        self.asleep = not self.try_wake()
        return not self.asleep


class NoModem:
    """Stands for the modem's interrupt system where no modem machine is made: the clock of a CPU that never ran (the link's
    sniffer reads it)."""
    class clock:
        now_ns = 0


class Wire:
    """Sniffer fed by AaifLink.trace: control bytes on channel 0, MSL frames (28-byte header + payload) on channel 2."""
    def __init__(self, sides, out, verbose):
        self.sides, self.out, self.verbose = sides, out, verbose
        self.buf = {'A': bytearray(), 'B': bytearray()}
        self.ctl = {'A': [], 'B': []}
        self.frames = {'A': 0, 'B': 0}; self.bad = {'A': 0, 'B': 0}; self.paybad = {'A': 0, 'B': 0}; self.paychk = {'A': 0, 'B': 0}
        self.other = collections.Counter(); self.kicks = collections.Counter()
        self.log = []
        self.lead_max = 0          # largest (receiver clock - sender clock) seen when a byte was sent to an awake receiver, ns

    def append(self, item):                      # list-like interface used by emu_link
        name, s = item
        if s.startswith('tx ch'):
            self.feed(name, int(s[5]), bytes.fromhex(s.split('+', 1)[1]))
        elif s.startswith('wake kick'):
            self.kicks[name] += 1
            self.note(name, 'wake kick')

    def note(self, name, text, always=False):
        t = max(x.now for x in self.sides.values() if x.started)      # a stalled DMA can resume while its own CPU sleeps on a stale clock
        line = '[wire %10.3f ms] %s %s' % (t / 1e6, 'APP>ACC' if name == 'A' else 'ACC>APP', text)
        if len(self.log) < 400: self.log.append(line)
        if self.verbose or always: self.out(line)

    def feed(self, name, ch, data):
        snd = self.sides[name]; rcv = snd.peer
        if rcv.started and not (rcv.asleep or snd.asleep or rcv.dead) and rcv.now - snd.now > self.lead_max:
            self.lead_max = rcv.now - snd.now
        if ch == 0:
            for b in data:
                self.ctl[name].append((self.sides[name].now, b))
                self.note(name, 'ch0 control %#04x (%s)' % (b, CTL.get(b, '?')), always=len(self.ctl[name]) <= 4)
            return
        if ch != 2:
            self.other[(name, ch)] += len(data); return
        buf = self.buf[name]; buf += data
        while len(buf) >= 28:
            h = struct.unpack('<7I', bytes(buf[:28]))
            if (sum(h[:5]) + h[6]) & 0xFFFFFFFF != h[5]:
                self.bad[name] += 1
                self.note(name, 'ch2 BAD HEADER CHECKSUM ' + ' '.join('%08x' % x for x in h), always=True)
                buf.clear(); return
            n = h[3]
            if len(buf) < 28 + n:
                return
            pay = bytes(buf[28:28 + n]); del buf[:28 + n]
            self.frames[name] += 1
            chk = ''
            if h[6]:
                self.paychk[name] += 1
                words = struct.unpack('<%dI' % ((n + 3) // 4), pay + bytes(-n % 4))
                ok = sum(words) & 0xFFFFFFFF == h[6]
                chk = ' paysum ok' if ok else ' PAYLOAD CHECKSUM BAD'
                if not ok: self.paybad[name] += 1
            txt = b' '.join(r for r in pay.replace(b'\0', b'\n').split(b'\n') if len(r) >= 3 and all(32 <= c < 127 for c in r)).decode('latin1')
            first = self.frames[name] <= 3
            self.note(name, 'ch2 frame #%d w1=%#x w2=%#x len=%d hdr ok%s %s %r' % (self.frames[name], h[1], h[2], n, chk, pay[:24].hex(), txt[:60]),
                      always=first)

    def summary(self):
        f = lambda name: ' '.join('%x' % b for _, b in self.ctl[name][:40]) + (' ...' if len(self.ctl[name]) > 40 else '')
        return ['[wire] ch0 control bytes APP>ACC: %d (%s)' % (len(self.ctl['A']), f('A')),
                '[wire] ch0 control bytes ACC>APP: %d (%s)' % (len(self.ctl['B']), f('B')),
                '[wire] ch2 MSL frames APP>ACC: %d (bad header checksum %d, payload checksums present %d, bad %d, partial %d bytes)'
                % (self.frames['A'], self.bad['A'], self.paychk['A'], self.paybad['A'], len(self.buf['A'])),
                '[wire] ch2 MSL frames ACC>APP: %d (bad header checksum %d, payload checksums present %d, bad %d, partial %d bytes)'
                % (self.frames['B'], self.bad['B'], self.paychk['B'], self.paybad['B'], len(self.buf['B'])),
                '[wire] wake kicks: %s; bytes on other channels: %s' % (dict(self.kicks), dict(self.other)),
                '[wire] largest lead of an awake receiver over the sender when data crossed: %.1f us' % (self.lead_max / 1e3)]


def line_sink(log):
    buf = bytearray()
    def feed(c):
        if c == 10:
            s = buf.decode('latin1').rstrip('\r'); buf.clear()
            if s.strip(): log(s)
        elif c != 13:
            buf.append(c)
    feed.flush = lambda: (log(buf.decode('latin1')), buf.clear()) if buf.strip() else None
    return feed


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--device', default=devices.selected(), help='device profile (module of native/devices)')
    ap.add_argument('--main', help='REQUIRED for the first run unless it is in firmware/NAME/: the main firmware container as downloaded (.mbn)')
    ap.add_argument('--fs', help='REQUIRED for the first run unless it is in firmware/NAME/: the file-system container as downloaded (.fbn)')
    ap.add_argument('--pack', help='the customization pack as downloaded (.zip): REQUIRED for a phone with a SIM card, not needed for a phone with no SIM card; implies --custom')
    ap.add_argument('--custom', action='store_true', help='start from the custom flash image (factory image + customization pack) instead of the factory flash image')
    ap.add_argument('--log-dir', help='directory of the UART logs (default SIM_LOG_DIR, else run/)')
    ap.add_argument('--standard', action='store_true', help="attach the profile's add-on chips and modem stand-in")
    ap.add_argument('--mode', choices=('full', 'shortcut'), default='full')
    ap.add_argument('--seconds', type=float, default=600)
    ap.add_argument('--emu-seconds', type=float, default=0)
    ap.add_argument('--slice', type=int, default=20000)
    ap.add_argument('--trace', choices=('none', 'key', 'all'), default='key')
    ap.add_argument('--wire', action='store_true')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--hw-report', action='store_true', help='list application hardware addresses no model claimed (top 60 by access count)')
    ap.add_argument('--extcc-bypass', action='store_true')
    ap.add_argument('--display', action='store_true')
    ap.add_argument('--frames-dir')
    ap.add_argument('--frame-stream', metavar='PATH', help='send every display refresh to the viewer that listens on this Unix socket (see module doc)')
    ap.add_argument('--attach', action='append', default=[], metavar='MOD:FUNC')
    ap.add_argument('--attach-acc', action='append', default=[], metavar='MOD:FUNC', help='like --attach, for the modem CPU: FUNC(modem_machine, modem_irq_system)')
    ap.add_argument('--spin-skip', action=argparse.BooleanOptionalAction, default=True, help='fast-forward verified pure polling loops (bit-identical, see Machine._spin_skip)')
    ap.add_argument('--realtime', action='store_true', help='interactive use: sleep whenever emulated time would run ahead of the wall clock (idle phases otherwise run several times faster than real time)')
    ap.add_argument('--progress-seconds', type=float, default=30, help='host seconds between progress lines')
    ap.add_argument('--fast', action='store_true', help='watch mode: no tracer, wire sniffer or bus accounting (see module doc)')
    ap.add_argument('--mmio', action=argparse.BooleanOptionalAction, default=None, help='hardware windows as Unicorn MMIO regions instead of hooked RAM pages (faster while the CPU is busy, same behaviour, see Machine.add_hw_region); default: on with --fast')
    ap.add_argument('--native-nand', action=argparse.BooleanOptionalAction, default=True, help='with --fast: serve NAND data-port reads and program data from compiled code (emu/native_port.py; falls back to Python without a C compiler)')
    ap.add_argument('--block-slices', action='store_true', help='opt-in: slices end on translation-block boundaries, no per-instruction count hook (see module doc)')
    ap.add_argument('--core', choices=('unicorn', 'own'), default='unicorn', help='the application CPU: unicorn (default), or own = the compiled core of native/core (build it first: native/core/build.sh). Same models and options; --block-slices and the polling-loop skip have no meaning there and are ignored, --mode shortcut and --slice-replay are refused')
    ap.add_argument('--slice-log', help='with --block-slices: write the length of every slice to this file')
    ap.add_argument('--slice-replay', help='exact slices with the lengths of a --slice-log file')
    ap.add_argument('--async-frames', action='store_true', help='opt-in: frame PNGs written by a second thread (see module doc)')
    ap.add_argument('--keep-going', action='store_true')
    ap.add_argument('--idle', choices=('stop', 'wait'), default='stop', help='a WFI with nothing scheduled on any CPU: stop the run (default) or wait for the host (see module doc)')
    ap.add_argument('--no-modem', action='store_true', help='never release the modem (single-CPU baseline under the same scheduler)')
    ap.add_argument('--peer', metavar='MOD:FUNC', help='Python stand-in for the modem CPU: FUNC(link.b, app_irq_system, out) is called once the link exists; '
                    'implies --no-modem. Example: --peer emu_modem_at:attach_peer')
    ap.add_argument('--dis', action='append', default=[])
    ap.add_argument('--mem', action='append', default=[])
    ap.add_argument('--platform', type=lambda x: int(x, 0), default=0xE8)
    ap.add_argument('--start-acc-at', type=int, default=3_000_000, help='shortcut mode: release the modem at this many application instructions')
    ap.add_argument('--uart-log', action=argparse.BooleanOptionalAction, default=True, help='write the UART log of the application CPU (app-uart.log in the log directory)')
    return ap


class Phone:
    """What build() gives: the machine of one phone. app, acc: the two CPUs (Side); inputs: the keypad's Inputs object, when the
    keypad is attached; attached: {MOD:FUNC: what the attachment returned}; a: the options; now: emulated time, ns."""
    def __init__(self, **kw):
        self.__dict__.update(kw)

    @property
    def now(self):
        return max(x.now for x in self.order if x.started)

    def press(self, name):
        self.inputs.press(name)

    def release(self, name):
        self.inputs.release(name)

    def flash_state(self):
        """The flash as the bytes of a state file, for the flash= of the next build (tools/flash_state.py, FlashState.state)."""
        return self.attached['flash_state:attach'].state()


def build(device=None, chip=None, flash=None, peer_config=None, options=(), out=None, on_frame=None):
    """The machine of a phone, ready to run: a Phone.
    device       name of the device profile (default: --device of the options)
    chip         the flash image: a file name, or the image itself as bytes, bytearray or memoryview (default: SIM_CHIP,
                 else the profile's, made from the downloaded firmware containers when it is not in place)
    flash        the flash state the caller keeps (tools/flash_state.py): the bytes of a state, b'' for none yet; the new
                 state is Phone.flash_state(). None: no state, unless --attach flash_state:attach and SIM_FLASH_STATE say so
    peer_config  the choices of the modem stand-in as an object with the keys of its configuration file (default: that file)
    options      the options of the command line as a list of words (or as parsed by parser())
    out          out(line) gets every line the launcher prints: its own, the UART console of the application ("APP uart| ..."),
                 the modem's. Default: print. Lines that device models print themselves go to sys.stdout
    on_frame     on_frame(width, height, rgb, number) for every display refresh, rgb = 3 bytes per pixel; implies --display"""
    ap = parser()
    a = options if isinstance(options, argparse.Namespace) else ap.parse_args(list(options))
    if device: a.device = device
    if a.log_dir: os.environ['SIM_LOG_DIR'] = os.path.abspath(a.log_dir)
    for role, path in (('main', a.main), ('fs', a.fs), ('pack', a.pack)):       # the downloaded files, for devices/source.py
        if path:
            from devices import source
            os.environ[source.ENV[role]] = os.path.abspath(path)
    profile = devices.select(a.device)          # also for the models: devices.load() gives this profile from here on
    elf = getattr(profile, 'BOOT_ELF', None)    # a firmware of our own instead of the stock one: everything below that needs the
                                                # stock firmware (flash image, boot loader, modem, tracer, release of the modem) is left out
    if elf:
        if a.mode != 'full': ap.error('--mode shortcut starts the stock platform image; device %s runs its own firmware' % profile.NAME)
        # what acts on addresses or protocols of the stock firmware never attaches to a firmware of our own
        stock = [x for x in a.attach + list(getattr(profile, 'STAND_INS', ())) if x.split(':')[0].startswith('emu_shim')]
        stock += ['--extcc-bypass'] * a.extcc_bypass + ['--attach-acc'] * bool(a.attach_acc)
        stock += ['--peer ' + p for p in (a.peer, getattr(profile, 'PEER', None)) if p and p.split(':')[0].startswith('emu_modem_mock')]
        if stock:
            ap.error('device %s runs its own firmware: %s act(s) on the stock firmware and cannot be used with it' % (profile.NAME, ', '.join(stock)))
        if a.trace == 'all':                    # key (the default) and none need no word
            print('[sim] device %s runs its own firmware: --trace %s is ignored (the tracer reads addresses of the stock firmware)' % (profile.NAME, a.trace), flush=True)
        a.trace = 'none'                        # the tracer reads addresses of the stock firmware
        a.report = False                        # the process table is the tracer's
    if flash is not None and 'flash_state:attach' not in a.attach:
        a.attach = a.attach + ['flash_state:attach']
    if a.standard:
        a.attach = list(profile.ATTACH) + a.attach + list(getattr(profile, 'STAND_INS', ()))     # stand-ins last: they chain to hooks already in place
        a.peer = a.peer or profile.PEER
    if a.fast:
        a.trace = 'none'
        a.wire = a.hw_report = a.report = False         # these need the tracer / sniffer / accounting that --fast removes
    if a.peer: a.no_modem = True
    if a.peer and peer_config is not None:         # the stand-in's choices from the caller instead of its configuration file
        import importlib
        importlib.import_module(a.peer.split(':')[0] + '.config').use(peer_config)
    # the modem CPU's machine (Unicorn) is not made when the compiled core runs the application, a stand-in plays the modem
    # and nothing asks for the modem's devices or memory
    modem = not elf and (not (a.core == 'own' and a.peer) or bool(a.attach_acc) or any(d.upper().startswith('ACC:') for d in a.dis + a.mem))
    if a.mmio is None: a.mmio = a.fast
    if a.block_slices and (a.trace != 'none' or a.mode != 'full'):
        ap.error('--block-slices needs --fast (or --trace none) and --mode full: the tracer adds block hooks of its own')

    out = out or (lambda s: print(s, flush=True))
    say = lambda s: out('[sim] ' + s)
    out('[sim] device %s (%s, %s platform, firmware %s)' % (profile.NAME, profile.TITLE, profile.PLATFORM, profile.FIRMWARE))
    for field in () if elf else devices.missing(profile, devices.WATCHES):
        out('[sim] profile %s has no %s: %s' % (profile.NAME, field, devices.WATCHES[field]))
    if elf:
        if not os.path.isfile(elf):
            sys.exit('[sim] not there: the firmware %s of device %s (%s)' % (os.path.relpath(elf, ROOT), profile.NAME, getattr(profile, 'BUILD', 'build it first')))
        chip = filedata = None
    else:
        from devices import source
        try:
            if chip is None:
                try:
                    chip = appboot.chip_path(profile, 'custom' if a.custom or a.pack else 'factory', say)
                except source.Missing:
                    if a.mode == 'full': raise                      # shortcut mode starts from the firmware images, with no flash
            if a.mode == 'full' and isinstance(chip, str) and not os.path.isfile(chip):
                sys.exit('[sim] not there: the flash image %s' % chip)
            made_of = source.untested(chip)                         # an image with a file that is not in the supported list: say so, every run
            for line in source.warnings(profile, made_of): say(line)
            if source.foreign_main(made_of): profile.WAVES = None   # the instrument bank's address belongs to the supported main container
            pcore = devices.image(profile, 'PCORE.CXC', chip)       # the unpacked file of a set-up, else read from the flash image
            try:
                filedata = devices.image(profile, 'phone_acc.cxc', chip)
            except source.Missing:
                if a.mode != 'full': raise
                filedata = None                                     # full mode only compares what the boot loader loaded with it
            source.waves(profile, chip, say)                        # the instrument table, made once from a firmware image
            if a.peer:                                              # a SIM card and a flash image without the pack: say what the phone will show
                import importlib
                try:
                    card = importlib.import_module(a.peer.split(':')[0] + '.config').load()[0].get('sim.present')
                except (ImportError, AttributeError):
                    card = False
                note = card and source.sim_note(profile, chip)
                if note: say(note)
        except source.Missing as e:
            sys.exit('\n'.join('[sim] ' + line for line in str(e).splitlines()))
    if a.extcc_bypass and devices.missing(profile, ('EXTCC_PID_SLOT', 'EXTCC_PID')):
        ap.error('--extcc-bypass needs EXTCC_PID_SLOT and EXTCC_PID in the profile')
    class NullTrace:
        def append(self, item): pass
    shared = mmap.mmap(-1, SHARED_SIZE)
    shared_ptr = ctypes.addressof(ctypes.c_char.from_buffer(shared))

    # ---------------- application side ----------------
    if a.core == 'own':                            # the compiled core behind the same interface (native/core/python/machine.py)
        sys.path.insert(0, os.environ.get('DBCORE_PY') or os.path.join(NATIVE, 'core', 'python'))     # DBCORE_PY: another copy of the adapter
        import machine as own_machine
        try:
            AppMachine = own_machine.for_launcher(a, out)
        except (OSError, ValueError) as e:
            sys.exit('[sim] --core own: %s' % e)
    else:
        from emu.machine import Machine as AppMachine
    if a.mode == 'full':
        am = AppMachine(uart_log=devices.run_file('app-uart.log', profile) if a.uart_log else None, echo=False, log=lambda s: None, mmio=a.mmio, block_slices=a.block_slices)
        if elf:                                    # the PT_LOAD segments at their addresses; the CPU starts at the ELF entry
            entry, segments = loaders.load_elf(elf)
            for addr, data in segments:
                am.load(addr, data, os.path.basename(elf))
            say('firmware %s: entry %#010x, %s' % (os.path.relpath(elf, ROOT), entry, ', '.join('%#010x..%#010x' % (ad, ad + len(d)) for ad, d in segments)))
        else:
            am.load_pcore(pcore)
            am.plant_boot_stubs()
        am.attach(0xC0001000, 0x1000, NoCardMmci())
        if elf:                                    # a blank chip (every byte 0xFF) of the geometry the profile asks for
            kind = getattr(profile, 'NAND_CHIP', None) or nand_model.DEFAULT_CHIP
            if kind not in nand_model.CHIPS:
                sys.exit('[sim] profile %s: NAND_CHIP %r is not a chip of emu_nand/nand_model.py (%s)' % (profile.NAME, kind, ', '.join(nand_model.CHIPS)))
            nand = nand_model.NandSystem(bytearray(), chip=kind, platform_version=a.platform)
            say('NAND: a blank chip %s (%d pages of %d + %d bytes), every byte 0xFF' % (kind, nand.chip.pages, nand_model.PAGE_DATA, nand_model.PAGE_SPARE))
        else:
            nand = nand_model.NandSystem(chip, platform_version=a.platform)
        for base, size, dev in nand.windows():
            am.attach(base, size, dev)
    else:
        from emu_link import run_app
        am = run_app.build(a.platform, profile=profile, chip=chip)
        am.bus.ranges = [r for r in am.bus.ranges if r[0] != 0xC0011000]; am.bus._cache.clear()
    if a.fast: am.bus.set_accounting(False)
    if a.fast and a.mode == 'full' and a.native_nand:      # NAND page data without a Python call per word (identical bytes, ECC and timing)
        nand.port = am.add_native_port(nand_model.BUS_BASE, nand_model.OFF_CLE)
        if nand.port is not None and a.mmio:               # ... and ready polls, timing registers and address cycles
            regs = (nand, nand_model.CTRL_BASE, nand_model.BUS_BASE + nand_model.OFF_ALE, nand_model.R_READY, nand_model.R_TIM0, nand_model.R_TIM1)
            if hasattr(am, 'attach_nand_regs'):            # a machine that serves these windows without the helper's C entries
                am.attach_nand_regs(*regs)
            else:
                from emu import native_port
                native_port.attach_nand_regs(am, *regs)
    am.attach(0xC0011000, 0x1000, AppSysCtrl(a.platform))
    am.attach(0xA0004000, 0x1000, ClockProfile())
    # a core outside the host's address space (the compiled core as WebAssembly) takes the buffer instead of its address
    am.uc.mem_map_ptr(SHARED_APP, SHARED_SIZE, UC_PROT_ALL, shared_ptr if getattr(getattr(am, 'core', None), 'HOST_POINTERS', True) else shared)
    airq = IrqTimerSystem(am).install()
    am.profile = profile                           # for device models: values of this phone and firmware release
    if flash is not None: am.flash_state = flash   # for tools/flash_state.py: the caller keeps the state
    app = Side('APP', am, airq); app.entry = entry if elf else devices.pcore_entry(profile, chip)
    xgam = None
    if a.display or a.frames_dir or a.frame_stream or on_frame:
        sys.path.insert(0, os.path.join(NATIVE, 'emu_lcd'))
        from lcd_model import XgamDisplay, FrameStream
        def got_frame(w, h, rgb, n):
            line = '[sim] display frame %d %dx%d at %.1f ms, non-zero bytes %d' % (n, w, h, app.now / 1e6, len(rgb) - rgb.count(0))
            if xgam.writer is None:
                out(line)
            else:                                 # after the file, from the writer thread: one write() of the whole line, past the print buffer
                xgam.after_write(lambda: os.write(sys.stdout.fileno(), (line + '\n').encode()))
            if on_frame: on_frame(w, h, rgb, n)
        xgam = XgamDisplay(read_mem=lambda addr, n: bytes(am.uc.mem_read(addr, n)), irq_cb=airq.vic.set_line, out_dir=a.frames_dir, on_frame=got_frame,
                           async_out=a.async_frames, stream=FrameStream(a.frame_stream) if a.frame_stream else None)
        am.attach(0xD0000000, 0x200000, xgam, 'XGAM')
    extras = []
    for spec in a.attach:
        import importlib
        mod, fn = spec.split(':')
        extras.append((spec, getattr(importlib.import_module(mod), fn)(am, airq)))
        out('[sim] attached %s' % spec)
    feed = line_sink(lambda s: out('APP uart| ' + s))
    def app_putc(c, _o=am.uart.putc):
        _o(c); feed(c)
    am.uart.echo = False
    am.uart.putc = app_putc

    # ---------------- link + modem side (built now, started at release) ----------------
    sides = {}
    link = AaifLink(lines_a=(5, 6, 8), lines_b=(34, 35, 36),
                    set_line_a=airq.vic.set_line, set_line_b=(lambda n, l: sides['B'].irq.vic.set_line(n, l)) if modem else None)
    adma = Dmac(lambda ad, n: bytes(am.uc.mem_read(ad, n)), lambda ad, d: am.uc.mem_write(ad, bytes(d)), airq.vic.set_line, 2, 'dmaA')
    link.a.connect_dma(adma, AAIF_BASE)
    am.attach(AAIF_BASE, 0x2000, link.a, 'AAIF')
    am.attach(DMA_BASE, 0x1000, adma, 'DMA')

    def attach_link_acc(m, irq):
        dm = Dmac(lambda ad, n: bytes(m.uc.mem_read(ad, n)), lambda ad, d: m.uc.mem_write(ad, bytes(d)), irq.vic.set_line, 25, 'dmaB')
        link.b.connect_dma(dm, AAIF_BASE)
        m.attach(AAIF_BASE, 0x2000, link.b, 'AAIF')
        m.attach(DMA_BASE, 0x1000, dm, 'DMA')
        m.dmac = dm
    class A: loopback = False
    acc_lines = []
    def acc_out(s):
        acc_lines.append(s)
        out('ACC %10.3f ms| %s' % (acc.now / 1e6, s.split('] ', 1)[-1]))
    cm = cirq = None
    if modem:
        import boot_acc
        cm, cirq = boot_acc.build(A(), link=attach_link_acc, out=acc_out, image=False, mmio=a.mmio, profile=profile)
        if a.fast: cm.bus.set_accounting(False)
        cm.attach(0xC0012000, 0x1000, AccSysCon())
        for spec in a.attach_acc:
            import importlib
            mod, fn = spec.split(':')
            extras.append((spec, getattr(importlib.import_module(mod), fn)(cm, cirq)))
            out('[sim] attached (modem) %s' % spec)
        cm.uc.mem_unmap(SHARED_ACC, SHARED_SIZE)                       # replace the modem's private RAM by the shared window
        cm.uc.mem_map_ptr(SHARED_ACC, SHARED_SIZE, UC_PROT_ALL, shared_ptr)
    acc = Side('ACC', cm, cirq if modem else NoModem); acc.started = False; acc.entry = SHARED_ACC
    app.peer, acc.peer = acc, app
    sides.update(A=app, B=acc)
    am.idle_cb = app.idle_cb; am.spin_skip = a.spin_skip
    if modem: cm.idle_cb = acc.idle_cb; cm.spin_skip = a.spin_skip
    if a.slice_log and am.block is not None: am.slice_log = open(a.slice_log, 'w')
    if a.slice_replay:
        import itertools
        am.slice_plan = itertools.chain((tuple(map(int, l.split())) for l in open(a.slice_replay)), itertools.repeat((a.slice, 1)))     # past the end of the log: plain slices
    wire = None if a.fast else Wire(sides, out, a.wire)
    link.trace = wire or NullTrace()
    if a.peer:                                   # the modem CPU stays stopped; a Python object plays its end of the link
        import importlib
        mod, fn = a.peer.split(':')
        extras.append((a.peer, getattr(importlib.import_module(mod), fn)(link.b, airq, out)))
        out('[sim] modem peer %s attached to the link (modem CPU not used)' % a.peer)

    # ---------------- release of the modem ----------------
    state = {'released': False, 'extcc': False, 'limit': None, 'rt': False}
    if filedata is not None:
        hdr, fsize, faddr = struct.unpack_from('<III', filedata, 0x44)
        fileimg = filedata[hdr:hdr + fsize]

    def release(reason, entry=SHARED_ACC):
        state['released'] = True
        if a.mode == 'shortcut':
            shared[:fsize] = fileimg
            out('[sim] shortcut: phone_acc copied from the file into the shared window (%#x bytes)' % fsize)
        elif filedata is None:
            out('[sim] shared window app 0x28000000 = modem 0x48000000 holds what pCore loaded (not compared: phone_acc.cxc could not be read from the flash image)')
        else:
            same = bytes(shared[:fsize]) == fileimg
            out('[sim] shared window app 0x28000000 = modem 0x48000000 holds what pCore loaded: %#x bytes, identical to the file image: %s' % (fsize, same))
        if a.no_modem:
            out('[sim] --no-modem: release ignored (%s)' % reason); return
        cirq.clock.skipped_ns = app.now          # the modem's clock starts at the release time
        acc.started = True; acc.entry = entry
        out('[sim] modem released at app t=%.3f ms, app insns %s, entry %#x (%s)' % (app.now / 1e6, format(am.insns, ','), entry, reason))

    if a.mode == 'full' and not elf:             # a firmware of our own does not call the boot-ROM stand-in: the modem stays stopped
        last_w = collections.deque(maxlen=4)
        orig_write = am.bus.write
        def traced_write(addr, size, value, pc):
            if not state['released'] and (addr & 0xFFFFF000) in (0xC0011000, 0xC0016000):
                last_w.append((addr, value, pc()))
            orig_write(addr, size, value, pc)
        am.bus.write = traced_write
        def rom_start_acc(uc, addr, size, _):
            r = [uc.reg_read(UC_ARM_REG_R0 + i) for i in range(4)]; lr = uc.reg_read(UC_ARM_REG_LR)
            out('[sim] boot-ROM service [0x44] called: r0-r3 = %s lr=%#x' % (' '.join('%#x' % x for x in r), lr))
            if not state['released'] and SHARED_ACC <= r[0] < SHARED_ACC + SHARED_SIZE:
                feed.flush()
                out('[sim] pCore hardware writes just before the call: ' + '; '.join('%#010x <= %#x (pc %#x)' % w for w in last_w))
                am.bus.write = orig_write
                release('pCore -> boot-ROM start-access-CPU service, r0 = entry', r[0])
        am.add_entry_hook(am.stubs['cb44'], rom_start_acc)

    # the stock firmware's fatal-error handler (profile): every hit is a fatal error; the report text is printed at the stop
    def plat_err(uc, addr, size, _):
        out('[sim] APP %.3f ms: Platform Error handler %#x entered (lr %#x)' % (app.now / 1e6, profile.PLATFORM_ERROR_HANDLER, uc.reg_read(UC_ARM_REG_LR)))
    if getattr(profile, 'PLATFORM_ERROR_HANDLER', None) is not None:
        am.add_entry_hook(profile.PLATFORM_ERROR_HANDLER, plat_err)

    # ---------------- tracer (application side) ----------------
    tr = None
    if a.trace != 'none':
        from ose_trace import OseTrace
        keep = None if a.trace == 'all' else ('HUNT', 'HUNTW', 'HUNTR', 'ERROR', 'SYSER', 'PRINT')
        def tr_out(s):
            if keep is None or s[14:19].strip() in keep:
                out('APP %10.3f ms| %s' % (app.now / 1e6, s[14:]))
        tr = OseTrace(am, payload=True, console=True, out=tr_out).attach()
        if not tr.hooked:
            out('[sim] profile %s has no OSE_TRACE: the application-side tracer shows nothing (--trace %s)' % (profile.NAME, a.trace))

    # ---------------- scheduler ----------------
    t0 = time.time(); order = [app, acc]
    skew = {'max': 0}              # largest clock difference between the two CPUs while both are awake, ns

    def run_slice(s):
        m = s.m
        if s.asleep:                              # resume from WFI exactly as Machine.run does after a successful idle callback
            s.asleep = False; s.wakes += 1
            m.uc.reg_write(UC_ARM_REG_PC, m.uc.reg_read(UC_ARM_REG_PC))
            if m.irq_pending and m._step_until_unmasked():
                m.inject_irq()
        pc = s.entry if s.slices == 0 else m.uc.reg_read(UC_ARM_REG_PC)
        end = m.insns + a.slice
        if s.gated and m.insns < s.slice_end:     # the host's clock chose between waking the CPU inside Machine.run and here:
            end = s.slice_end                     # the slice ends where it would have ended there
        s.gated = False; s.slice_end = end
        if acc.started and hasattr(m, 'touched'): m.touched = True      # the other CPU reaches the link and the DMA controller too
        if (s is app and not acc.started and getattr(m, 'max_quanta', 1) > 1 and s.irq.steppers_rest()
                and (state['released'] or a.mode != 'shortcut') and (state['extcc'] or not a.extcc_bypass)):
            # One CPU, and a machine that can go through several quanta in one call while this loop would do nothing between
            # them but call it again (Machine.run): up to the end of this run; with --realtime at most 2 ms, the pacing's step.
            irq = s.irq
            r = m.run(pc, max_insns=end, slice_insns=a.slice, step=irq.step, quanta=10 if state['rt'] else m.max_quanta,
                      due=lambda: irq.step_due, until_ns=state['limit'])
            s.irq.clock.sync(m.insns)
            s.slices += m.quanta
            if m.quanta > 1: s.slice_end = m.quantum_end
        else:
            r = m.run(pc, max_insns=end, slice_insns=a.slice, step=s.irq.step)
            s.irq.clock.sync(m.insns)             # Machine.run skips step() after an abort/SWI delivery: keep the clock exact
            s.slices += 1
        if r == 'max-insns' or (r and s.asleep and r.startswith('WFI')):
            return None
        return r

    def run(ns=0, pace=None, hold=False):
        """The scheduler: run for ns of emulated time (0: no limit). Returns why it stopped. pace: the host clock's part (Pace).
        A run with a limit (not --realtime, which has its own): the end of the run is the gate of the application CPU
        (Side.rt_gate, as the wall clock is with --realtime), so a CPU that sleeps until a timer event after the end does not
        jump there inside its slice (a firmware that sleeps for a minute would otherwise end a 20 ms run a minute later);
        it stops at the end below. The gate decides only where a run returns, not what the phone does (the same as with
        --realtime): a timer event past the end is taken in the next run, at the same emulated time."""
        limit = max(x.now for x in order if x.started) + ns if ns else None
        gate = limit is not None and app.rt_gate is None
        if gate: app.rt_gate = lambda: INF if acc.started else limit
        try:
            return loop(limit, pace, hold, gate)
        finally:
            if gate: app.rt_gate = None

    def loop(limit, pace, hold, gate):
        state['limit'], state['rt'] = limit, bool(pace and a.realtime)
        while True:
            if a.mode == 'shortcut' and not state['released'] and am.insns >= a.start_acc_at:
                release('shortcut: fixed instruction count')
            if a.extcc_bypass and not state['extcc'] and app.now > 10e9:
                state['extcc'] = True
                old = struct.unpack('<I', bytes(am.uc.mem_read(profile.EXTCC_PID_SLOT, 4)))[0]
                if old == 0:
                    am.uc.mem_write(profile.EXTCC_PID_SLOT, struct.pack('<I', profile.EXTCC_PID))
                out('[sim] --extcc-bypass: [%#x] was %#x at %.1f ms%s' % (profile.EXTCC_PID_SLOT, old, app.now / 1e6, ', wrote %#x' % profile.EXTCC_PID if old == 0 else ', left alone'))
            s = min(order, key=lambda x: (x.key(), x.asleep))
            k = s.key()
            # nothing scheduled: the application CPU sleeps with no timer event and no interrupt, the modem CPU never started.
            # Only the host can wake it (a key, a stop request): --idle wait and hold wait for that, everything else stops
            idle = k == INF and app.asleep and not app.dead and not acc.started and not app.irq.vic.irq_out
            if k == INF and not (idle and ((hold and limit is not None) or (pace and a.idle == 'wait'))):
                why = 'nothing scheduled on any CPU (' + '; '.join('%s: %s' % (x.name, x.dead or ('asleep, no timer event' if x.started else 'not started')) for x in order) + ')'
                break
            if idle: s = app
            if ((hold or (gate and k != INF)) and limit is not None and s is app and s.asleep and not acc.started
                    and not s.irq.vic.irq_out and k > limit):
                # asleep until a timer event past the end of this run (hold: or with nothing scheduled). Do not jump there: stop
                # at the end with the device pollers run, so that a key pressed between two runs wakes a sleeping phone at once.
                if limit > s.now: s.irq.clock.skip_to(int(limit))
                s.irq.step()
                s.m.irq_pending = s.irq.vic.irq_out
                why = 'emu-seconds'; break
            if idle:
                pace.wait(app)                    # --idle wait: emulated time follows the host clock until something wakes the CPU
            elif pace and pace.idle(s, k):
                pass
            elif s.asleep and not s.try_wake():
                why = 'scheduler: %s cannot wake (internal error)' % s.name; break
            else:
              r = run_slice(s)
              if r:
                  s.dead = r
                  out('[sim] %s stopped at %.3f ms emulated: %s' % (s.name, s.now / 1e6, r))
                  if s is app or not a.keep_going:
                      why = '%s: %s' % (s.name, r); break
            if acc.started and not (app.asleep or acc.asleep or acc.dead) and abs(app.now - acc.now) > skew['max']:
                skew['max'] = abs(app.now - acc.now)
            if pace and pace.over():
                why = 'max-seconds'; break
            if limit is not None and max(x.now for x in order if x.started) > limit:
                why = 'emu-seconds'; break
            if pace: pace.after()

        return why

    # ---------------- report ----------------
    def report(why):
        if xgam is not None: xgam.drain()
        feed.flush()
        if am.slice_log is not None: am.slice_log.close()
        out('[sim] stopped: %s; host %.1f s' % (why, time.time() - t0))
        for s in order:
            if s.started:
                out('[sim] %s: %s insns, emulated %.1f ms, %d slices, %d wake-ups, %s; %s' % (s.name, format(s.m.insns, ','), s.now / 1e6, s.slices, s.wakes,
                                                                                       'asleep' if s.asleep else 'running', s.irq.summary()))
                out('        ' + s.m.dump_regs().replace('\n', '\n        '))
                if s.m.spin_skipped: out('        spin skip: %s instructions not executed' % format(s.m.spin_skipped, ','))
                if s.m.block is not None: out('        block slices: %s blocks, %d count look-ups, %d counted without their code' % (format(s.m.block.blocks, ','), s.m.block.misses, s.m.block.guessed))
                if s.m.spin_wfi_guess: out('        spin skip: %d chunk boundaries at a WFI not seen before, taken as halted (see Machine._halted_at)' % s.m.spin_wfi_guess)
                out('        ' + s.irq.describe().replace('\n', '\n        '))
            else:
                out('[sim] %s: never started' % s.name)
        out('[sim] link stats app %s modem %s' % (link.a.stats, link.b.stats))
        out('[sim] DMA completions (channel, bytes): app %d, modem %d' % (len(adma.completed), len(cm.dmac.completed) if modem else 0))
        for l in (wire.summary() if wire else ()): out(l)
        out('[sim] largest clock difference between the CPUs while both were awake: %.1f us (slice = %.1f us)' % (skew['max'] / 1e3, a.slice * airq.clock.ns_per_insn / 1e3))
        for key in () if elf else ('Starting Remote Synchronization', 'Synchronization complete'):
            hit = [l for l in acc_lines if key in l]
            out('[sim] modem console "%s": %s' % (key, 'seen (%s)' % hit[0].strip() if hit else 'NOT seen'))
        try:                                          # the stock application's start-up script position
            if getattr(profile, 'PCP_JOB_SLOT', None) is None: raise LookupError('the profile has no PCP_JOB_SLOT')
            u32 = lambda ad: struct.unpack('<I', bytes(am.uc.mem_read(ad, 4)))[0]
            job = u32(profile.PCP_JOB_SLOT); idx, script = u32(job + 4), u32(job + 12)
            t, arg = u32(script + idx * 8) & 0xff, u32(script + idx * 8 + 4)
            out('[sim] PCP script: job %#x state %d index %d (step type %#x arg %#x)' % (job, u32(job) & 0xff, idx, t, arg))
        except Exception as e:
            if not elf: out('[sim] PCP script position unavailable: %s' % e)     # a firmware of our own has no such script
        if xgam is not None:
            out('[sim] display: %d frame(s)%s' % (xgam.frame_count, ' written to ' + a.frames_dir if a.frames_dir else ''))
        for spec, obj in extras:
            if hasattr(obj, 'summary'):
                out('[sim] %s:\n        %s' % (spec, str(obj.summary()).replace('\n', '\n        ')))
        halt, report = getattr(profile, 'PLATFORM_ERROR_STOP', None), getattr(profile, 'PLATFORM_ERROR_REPORT', None)
        if app.dead and None not in (halt, report) and '%#x' % halt in app.dead:
            try:
                txt = bytes(am.uc.mem_read(report, 0x300)).split(b'\0\0')[0].decode('latin1')
                out('[sim] application Platform Error report:\n        ' + txt.replace('\n', '\n        '))
            except Exception as e:
                out('[sim] error report unreadable: %s' % e)
        get = lambda sd: (app if sd.upper() == 'APP' else acc).m
        for d in a.dis:
            from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
            sd, ad, ln, md = d.split(':'); ad, ln = int(ad, 16), int(ln, 16)
            for i in Cs(CS_ARCH_ARM, CS_MODE_THUMB if md == 't' else CS_MODE_ARM).disasm(bytes(get(sd).uc.mem_read(ad, ln)), ad):
                out('  %s %08x: %s %s' % (sd, i.address, i.mnemonic, i.op_str))
        for d in a.mem:
            sd, ad, ln = d.split(':'); ad, ln = int(ad, 16), int(ln, 16)
            data = bytes(get(sd).uc.mem_read(ad, ln))
            for o in range(0, ln, 16):
                out('  %s %08x: %s' % (sd, ad + o, data[o:o + 16].hex(' ', 4)))
        if a.hw_report:
            un = sorted(((v[2], k, v) for k, v in am.bus.touched.items() if not v[4]), reverse=True)
            out('[sim] application hardware addresses with no model: %d' % len(un))
            for n, addr, v in un[:60]:
                out('  %#010x %-2s x%-7d first pc %#010x last value %#x' % (addr, v[1], n, v[0], v[3]))
        if tr and a.report:
            tr.report(sys.stdout)
        return dict(app=app, acc=acc, link=link, wire=wire, tr=tr, why=why)

    return Phone(a=a, profile=profile, app=app, acc=acc, order=order, link=link, wire=wire, tr=tr, xgam=xgam, attached=dict(extras),
                 inputs=next((x.inputs for _, x in extras if hasattr(x, 'inputs')), None), out=out, t0=t0, _run=run, _report=report)


def run(phone, ns, hold=False, pace=None):
    """Run the phone for ns of emulated time (0: until it stops by itself). No sleep and no look at the host clock in here.
    Returns {'why': the reason of the stop, 'ended': False when it is only that the time is used up ('emu-seconds': call again),
    'now_ns': emulated time, 'insns': instructions of the application CPU}.
    The run ends after the slice in which the time is used up; a phone that sleeps past the end is stopped at the end (its
    clock is moved there) and takes its wake-up in a later run, at the same emulated time.
    hold=True: a sleeping phone is not taken past the end of this run, so a key pressed between two runs is seen at once.
    'rest_ns' (hold=True): when the run ends with the application CPU asleep (WFI, no interrupt, the modem CPU not started),
    the emulated ns from the end of the run until the CPU or a device model next has work by itself: its next timer event
    or the earliest due time of the device pollers; inf when nothing is scheduled. Until then the next runs only move
    the clock, so a caller on a host clock may sleep that long (a key, or anything else from outside, ends the sleep).
    0 when the phone is awake or something is due now."""
    m = phone.app.m
    if hasattr(m, 'touched'): m.touched = True      # keys and commands given since the last run: the device pollers look after the first slice
    why = phone._run(ns, pace, hold)
    app, rest = phone.app, 0
    if hold and why == 'emu-seconds' and app.asleep and not app.dead and not phone.acc.started and not app.irq.vic.irq_out:
        irq = app.irq
        due = min(app.key(), irq.steppers_due() if irq.steppers else INF)
        rest = max(0, due - app.now)
    return dict(why=why, ended=why not in ('emu-seconds', 'max-seconds'), now_ns=phone.now, insns=phone.app.m.insns, rest_ns=rest)


def report(phone, why):
    """The lines main() prints at the stop. Returns {'app', 'acc', 'link', 'wire', 'tr', 'why'}."""
    return phone._report(why)


class Pace:
    """The host clock's part of main(): the limit of host time, the progress lines and --realtime."""
    def __init__(self, phone):
        self.p, self.a = phone, phone.a
        self.t0 = self.now = self.last_report = phone.t0
        self.waiting, self.waits = None, 0       # --idle wait: (emulated ns, host s, instruction count) at the start of the wait; how many
        self.rt = rt = {'emu': 0, 'host': phone.t0}
        if self.a.realtime:
            acc = phone.acc
            phone.app.rt_gate = lambda: INF if acc.started else rt['emu'] + (time.time() - rt['host']) * 1e9

    def idle(self, s, k):
        """True: the wall clock has not reached the wake-up of the sleeping application CPU; time was walked there instead."""
        rt = self.rt
        if self.a.realtime and s is self.p.app and s.asleep and not self.p.acc.started and not s.irq.vic.irq_out:
            # Asleep until a timer event at k. Do not jump there: let emulated time follow the wall clock in small steps and
            # run the device pollers on the way, so a key press from the viewer wakes a sleeping phone at once.
            wall = rt['emu'] + (time.time() - rt['host']) * 1e9
            if k > wall + 2e6:
                time.sleep(min(0.01, (k - wall) / 1e9 - 0.001))     # not past the event: a fixed 10 ms made every wake-up up to 8 ms late (uneven frames)
                wall = min(k - 1, rt['emu'] + (time.time() - rt['host']) * 1e9)     # short of the event: try_wake goes there, as in a run that does not sleep
                if wall > s.now: s.irq.clock.skip_to(int(wall))
                s.irq.step()
                s.m.irq_pending = s.irq.vic.irq_out
                return True
        return False

    def wait(self, s):
        """--idle wait: the application CPU sleeps with nothing scheduled (no timer event, no interrupt; the modem CPU not
        started). Only the host can wake it. Emulated time follows the host clock from the moment the wait began; the host
        sleeps until the next time a device poller has work (the keypad's look at its control file, every 20 ms emulated by
        default), at most 50 ms, then the pollers run (Side.key() sees an interrupt they raised). Called again and again by
        the scheduler while nothing changes; a run of the CPU in between starts a new wait."""
        now = time.time()
        if self.waiting is None or self.waiting[2] != s.m.insns:
            self.waiting = (s.now, now, s.m.insns)        # emulated and host time at the start of this wait
            self.waits += 1
        wall = self.waiting[0] + (now - self.waiting[1]) * 1e9
        due = s.irq.steppers_due() if s.irq.steppers else INF
        target = min(max(due, s.now), wall + 50e6)
        time.sleep(max((target - wall) / 1e9, 0.002))     # at least 2 ms: a poller that is always due does not make a busy loop
        wall = self.waiting[0] + (time.time() - self.waiting[1]) * 1e9
        if wall > s.now: s.irq.clock.skip_to(int(wall))
        s.irq.step()
        s.m.irq_pending = s.irq.vic.irq_out

    def over(self):
        self.now = time.time()
        return self.now - self.t0 > self.a.seconds

    def after(self):
        a, rt, now, app, order = self.a, self.rt, self.now, self.p.app, self.p.order
        if a.realtime:                           # never run ahead of the wall clock; time lost while slower is not made up
            ahead = (app.now - rt['emu']) / 1e9 - (now - rt['host'])
            if ahead < -0.25 or ahead > 0.5: rt['emu'], rt['host'] = app.now, now      # fell behind, or jumped ahead: start level again
            elif ahead > 0.002: time.sleep(min(ahead, 0.05))
        if now - self.last_report > a.progress_seconds:
            self.last_report = now
            self.p.out('[sim] progress: host %.0f s; ' % (now - self.t0) + '; '.join('%s %.1f ms %s insns%s' % (x.name, x.now / 1e6, format(x.m.insns, ','), ' (asleep)' if x.asleep else '') for x in order if x.started))


def main():
    phone = build(options=parser().parse_args())
    return report(phone, run(phone, phone.a.emu_seconds * 1e9, pace=Pace(phone))['why'])


if __name__ == '__main__':
    main()
