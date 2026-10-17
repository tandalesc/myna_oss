"""The choices of the AT modem stand-in. One file serves both stand-ins: the configuration file of the stock stand-in
(emu_modem_mock/config.py, the variable MOCK_CONFIG or the object a program gives with use()) is read here too, with the
keys this stand-in uses checked as the stock loader checks them. Nothing of the stock stand-in is imported.

Keys this stand-in reads:
    "sim.present"   card in the holder: false = +CPIN? and the card's commands answer +CME ERROR: 10 and nothing registers.
                    MOCK_SIM=0 / MOCK_SIM=1 in the environment overrides it
    "sim.imsi"      +CIMI, and MCC and MNC of the network (+COPS numeric): 15 digits
    "sim.spn"       [MOCK] the network's name in +COPS: at most 16 ASCII characters
    "cell.network"  "off", "loopback" or "host" (emu_cell/cell.py). MOCK_CELL in the environment overrides it
    "phone.number"  this stand-in only: the phone's own number for +CNUM ("+" in front: international); "" = none known.
                    A program can also give it at run time (AtModem.set_number). MOCK_NUMBER in the environment overrides it
The other keys of the stock stand-in's file (OTHER_KEYS) are accepted and have no effect here; any other key is reported as
unknown. The stock stand-in does not know "phone.number": in its file the key is reported as unknown and ignored.
"""
import json, os

DEFAULTS = {'sim.present': False, 'sim.imsi': '001010123456789', 'sim.spn': 'Simulator', 'cell.network': 'off',
            'phone.number': ''}
CELL_NETWORK = ('off', 'loopback', 'host')
# the keys of the stock stand-in's file that this one does not use (emu_modem_at/selftest.py test_config keeps the list whole)
OTHER_KEYS = ('sim.lock_ok', 'sim.iccid', 'sim.pin_enabled', 'sim.pin', 'phone.lock', 'sim.lock', 'net.bridge', 'net.pace',
              'net.account', 'net.proxy', 'net.proxy.port')
GIVEN = None


def use(data):
    """Take the configuration from this object instead of the MOCK_CONFIG file; None: the file again."""
    global GIVEN
    GIVEN = data


def _number_ok(n):
    d = n[1:] if n.startswith('+') else n
    return n == '' or (d.isdigit() and len(d) <= 20)


def load(env=None):
    """(configuration, remarks) with the keys of DEFAULTS. Never raises: a bad file leaves the defaults."""
    env = os.environ if env is None else env
    cfg, notes = dict(DEFAULTS), []
    path = env.get('MOCK_CONFIG')
    if path or GIVEN is not None:
        try:
            if GIVEN is not None:
                data = GIVEN
            else:
                with open(path) as f:
                    data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError('top level is not an object')
            for k, v in data.items():
                if k in OTHER_KEYS:
                    continue
                if k not in DEFAULTS:
                    notes.append('unknown key %r ignored' % k)
                elif type(v) is not type(DEFAULTS[k]):
                    notes.append('%s: wrong type, default kept' % k)
                elif k == 'phone.number' and not _number_ok(v):
                    notes.append('%s: must be a number as text: default kept' % k)
                else:
                    cfg[k] = v
        except FileNotFoundError:
            notes.append('MOCK_CONFIG file %s not found: defaults' % path)
        except (OSError, ValueError) as e:
            notes.append('MOCK_CONFIG file %s unreadable (%s): defaults' % (path, e))
    if not (cfg['sim.imsi'].isdigit() and len(cfg['sim.imsi']) == 15):
        notes.append('sim.imsi must be 15 digits: default kept'); cfg['sim.imsi'] = DEFAULTS['sim.imsi']
    if not (cfg['sim.spn'].isascii() and len(cfg['sim.spn']) <= 16):
        notes.append('sim.spn must be at most 16 ASCII characters: default kept'); cfg['sim.spn'] = DEFAULTS['sim.spn']
    if cfg['cell.network'] not in CELL_NETWORK:
        notes.append('cell.network must be one of %s: default kept' % ', '.join(CELL_NETWORK)); cfg['cell.network'] = DEFAULTS['cell.network']
    if env.get('MOCK_CELL') in CELL_NETWORK:
        cfg['cell.network'] = env['MOCK_CELL']
        notes.append('cell.network set by MOCK_CELL')
    if env.get('MOCK_SIM') is not None:
        cfg['sim.present'] = env['MOCK_SIM'] != '0'
        notes.append('sim.present set by MOCK_SIM=%s' % env['MOCK_SIM'])
    if env.get('MOCK_NUMBER') is not None and _number_ok(env['MOCK_NUMBER']):
        cfg['phone.number'] = env['MOCK_NUMBER']
        notes.append('phone.number set by MOCK_NUMBER')
    return cfg, notes


def describe(cfg, notes):
    keys = ('sim.present', 'sim.imsi', 'sim.spn', 'cell.network', 'phone.number')
    return 'config ' + ' '.join('%s=%s' % (k, json.dumps(cfg[k])) for k in keys) + (' (' + '; '.join(notes) + ')' if notes else '')
