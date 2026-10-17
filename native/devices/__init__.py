"""Device profiles of the DB3210 simulator. The platform (two ARM CPUs, link, interrupt controller, timers, NAND, display controller)
lives in native/emu* and native/sim/db3210.py. What belongs to one phone model and one firmware release lives in a device folder
here, native/devices/<name>/:
    __init__.py   the profile: names, where the firmware files and flash images of this device are, the add-on chips to attach,
                  the modem stand-in, firmware addresses the launcher watches
    firmware.json the firmware files, images and flash images: names, sizes, checksums, flash addresses of the partitions
    skin/         the viewer's pictures of the phone and skin.json (screen position, views, clickable key areas)
A device that runs a firmware of our own instead of the stock one (native/devices/myna) has BOOT_ELF in its profile, the ELF file
the launcher loads, and no firmware.json: no firmware files, flash images or firmware addresses. Its NAND is a blank chip of the
geometry NAND_CHIP names (default: nand_model.DEFAULT_CHIP, the stock phones' chip); KEYMAP gives plain key names; docs/DEVELOPING.md, section 6, has the fields.
The device folder is the one place that says where a device's files are. Every tool takes the paths from the profile:
    native/images/<name>_nand_chip.bin, _nand_custom.bin, <name>_waves.json      the flash images and the instrument table: made
                                                    from the downloaded firmware files when a run first needs them (source.py)
    extracted/<name>/main, extracted/<name>/fs      the unpacked containers: only tools/device.py setup makes them, for development
image(profile, NAME) -> a stock firmware image as bytes, from the unpacked file or from inside the flash image
load(NAME) -> the profile module;  load() -> the selected one (SIM_DEVICE, else DEFAULT);  available() -> all folder names
run_file('app-uart.log') -> a path in the run directory, which is made on demand"""
import importlib, json, os, struct

HERE = os.path.dirname(os.path.abspath(__file__)); NATIVE = os.path.dirname(HERE); ROOT = os.path.dirname(NATIVE)

# fields a profile needs before the launcher can start the device, and what each one is (tools/device.py check, db3210.py)
WATCHES = {'PLATFORM_ERROR_HANDLER': 'fatal errors of the application CPU are not reported',
           'EXTCC_PID_SLOT': '--extcc-bypass is not available', 'EXTCC_PID': '--extcc-bypass is not available',
           'PCP_JOB_SLOT': 'the start-up script position is not reported'}


def available():
    return sorted(d for d in os.listdir(HERE) if os.path.exists(os.path.join(HERE, d, '__init__.py')))


def _default():
    """The device taken when none is named: the first one (by name) with a stock firmware (a firmware.json), else the first
    one; None in a tree with no device."""
    names = available()
    return next((d for d in names if os.path.isfile(os.path.join(HERE, d, 'firmware.json'))), names[0] if names else None)


DEFAULT = _default()


def selected():
    return os.environ.get('SIM_DEVICE') or DEFAULT


def load(name=None):
    return importlib.import_module('devices.' + (name or selected()))


def select(argv_or_name=None):
    """Profile for a tool without an option parser of its own needs: `--device NAME` is taken out of the argument list if it is
    there, else SIM_DEVICE, else the default. A name selects that device for every later load() in this process."""
    name = argv_or_name
    if isinstance(argv_or_name, list):
        name = None
        if '--device' in argv_or_name[:-1]:
            i = argv_or_name.index('--device')
            name = argv_or_name[i + 1]
            del argv_or_name[i:i + 2]
    if name:
        os.environ['SIM_DEVICE'] = name
    return load()


def extracted(name, legacy=False):
    """The directory of a device's unpacked containers: extracted/<name>. legacy: extracted/ itself is read when it holds the
    containers and extracted/<name> does not (the layout before a second device existed)."""
    new, old = os.path.join(ROOT, 'extracted', name), os.path.join(ROOT, 'extracted')
    if legacy and not os.path.isdir(os.path.join(new, 'main')) and os.path.isdir(os.path.join(old, 'main')):
        return old
    return new


def firmware(profile):
    with open(os.path.join(HERE, profile.NAME, 'firmware.json'), encoding='utf-8') as f:
        return json.load(f)


def partitions(profile):
    """[(partition image path, flash address)] of the factory flash, from firmware.json."""
    out = []
    for role, e in firmware(profile)['partitions'].items():
        out.append((os.path.join(profile.EXTRACTED, role, os.path.basename(e['file'])), int(e['flash_address'], 0)))
    return out


def image(profile, name, chip=None):
    """A stock firmware image of the device as bytes: the unpacked file when
    the set-up tool left one (VOL1), else the file of that name in the main partition of the flash image `chip` (a path or the
    bytes; default: the factory image). Raises devices.source.Missing with a text for the user."""
    from devices import source
    path = os.path.join(profile.VOL1, name)
    if os.path.isfile(path) and not source.foreign_main(source.untested(chip)):     # such an image has firmware images of its own
        with open(path, 'rb') as f:
            return f.read()
    return source.image(profile, name, chip)


def pcore_entry(profile, chip=None):
    """The reset entry of the device's stock boot loader: slot 0 of the service table at the start of the image is
    `ldr pc, [pc, #n]`, and the word it loads is the entry."""
    from emu import loaders
    base, mem = loaders.load_pcore(image(profile, 'PCORE.CXC', chip))
    insn, = struct.unpack_from('<I', mem, 0)
    if insn & 0xFFFFF000 != 0xE59FF000:
        raise ValueError('pCore slot 0 is %#010x, not ldr pc, [pc, #n]: the entry of this pCore is not known' % insn)
    return struct.unpack_from('<I', mem, 8 + (insn & 0xFFF))[0]


def missing(profile, fields):
    """The names of `fields` that the profile does not have or has not filled in."""
    return [f for f in fields if getattr(profile, f, None) in (None, 'TODO', ())]


def run_dir(profile=None):
    """Where a run writes its logs: SIM_LOG_DIR, default run/ at the repository root, then the device name. Made on demand."""
    path = os.path.join(os.environ.get('SIM_LOG_DIR') or os.path.join(ROOT, 'run'), (profile or load()).NAME)
    os.makedirs(path, exist_ok=True)
    return path


def run_file(name, profile=None):
    return os.path.join(run_dir(profile), name)
