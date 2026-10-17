// phone_worker.js: the worker of Myna's phone page (index.html, app.js). It holds a whole phone: the WebAssembly build of
// the core (dbcore.wasm, through pycore.js) and, under Pyodide in this same worker, the Python device models, the AT modem
// stand-in and the launcher of the simulator, which are unpacked from one archive (phone_src.json) into Pyodide's
// in-memory file system. The phones are those with a firmware of our own (a profile with BOOT_ELF, such as myna): the
// ELF file comes from the page (m.elf) or, when the page gives none, from the server (firmware/NAME.elf), and is put
// where the profile looks for it in Pyodide's file system; the NAND is a blank chip, so the flash state, which the page
// keeps, is the only thing that lasts. A device without BOOT_ELF is not offered.
// The page carries the text messages of the cell network "host" (cell_take, cell_result, cell_incoming, cell_state).
// It builds the machine with the launcher's build(), then runs it in steps of emulated time with run(), paced against
// performance.now(), and posts pictures, console lines and a line of numbers per emulated second. A phone that sleeps with
// nothing to do (run()'s rest_ns) is left alone until it has work or the page sends something: no step while it rests.
// A classic worker: pyodide.js is a classic script (it loads its own module with import(), which a classic worker may do).
// One worker runs one phone once; the page makes a new one for the next start.
// SPDX-License-Identifier: MIT
'use strict';

const STEP_NS = 20e6;                 // emulated time per call of run()
const MAX_DEBT_MS = 500;              // paced: how far the phone may be behind and still try to catch up
const REST_MAX_MS = 1000;             // the longest wait of a resting phone (the page still gets its line per emulated second)
const KEY_STEP_NS = 4e6;              // the longest step while a key is down: its release lands within a few ms
const KEY_SLACK_NS = 0.5e6;           // a key this close to its emulated time is given now
let py = null, api = null;            // Pyodide; the Python functions of GLUE below
let infos = {};                       // device_info(): what each phone needs
let lines = [], errLines = [];        // console lines since the last post
let running = false, paused = false, fast = false, wantStop = false;
let keylog = false, slow = 1;          // tests: the key log in the console lines; every step `slow` times as long (a slow phone)
let convMs = 0, convN = 0;            // RGB -> RGBA: time spent, pictures
const keyq = [];                      // the page's keys not given to the phone yet: { name, down, h: host ms on this worker's clock }
let keyH = 0;                         // h of the last key queued (the queue keeps the page's order)
const times = {};                     // host ms of each stage

const post = (m, transfer) => postMessage(m, transfer || []);
const fail = (stage, e) => { running = false; post({ t: 'error', stage, text: String(e && e.message ? e.message : e) }); };
const flush = () => {
  if (lines.length) { post({ t: 'lines', lines }); lines = []; }
  if (errLines.length) { post({ t: 'lines', lines: errLines, err: true }); errLines = []; }
};

// Let a queued message (a key, pause) in between two steps. A message channel, because nested timers are held back to 4 ms.
const chan = new MessageChannel();
const breathe = () => new Promise(r => { chan.port1.onmessage = r; chan.port2.postMessage(0); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
// The wait of the paced loop. A key ends it early (true), so that a phone that is ahead of the host clock answers at once.
let wake = null;
const nap = ms => new Promise(r => { const t = setTimeout(() => { wake = null; r(false); }, ms); wake = () => { clearTimeout(t); wake = null; r(true); }; });

// The Python side: paths, the launcher, and the few functions this file calls. Everything else is the simulator's own code.
const GLUE = `
import hashlib, json, os, sys
sys.dont_write_bytecode = True
ROOT = '/phone'; N = ROOT + '/native'
sys.path[:0] = [N + '/sim', N + '/core/python']
os.environ.update(DBCORE_DEVICES='all', MOCK_AUDIO_PCM='host', SIM_BUILD_DIR='/tmp/cbuild')
import db3210, machine, dbcore_wasm, devices
from pyodide.ffi import to_js
phone = None; glue = None

def has_api():
    return all(hasattr(db3210, f) for f in ('build', 'run', 'report'))

def _own():
    """{name: profile} of the devices with a firmware of our own (BOOT_ELF); the others are not offered here."""
    out = {}
    for d in sorted(os.listdir(N + '/devices')):
        if os.path.isfile(N + '/devices/' + d + '/__init__.py'):
            try:
                p = devices.load(d)
            except Exception:
                continue
            if getattr(p, 'BOOT_ELF', None):
                out[d] = p
    return out

def device_names():
    return to_js(sorted(_own()))

def device_info():
    """For the page: each phone's title, firmware version, the name of its ELF file, its blank NAND chip and its modem
    stand-in (PEER, '' for none: no cell network)."""
    return json.dumps({d: {'title': getattr(p, 'TITLE', d), 'firmware': getattr(p, 'FIRMWARE', ''), 'own': True, 'elf': os.path.basename(p.BOOT_ELF),
                           'chip': getattr(p, 'NAND_CHIP', None) or '', 'peer': getattr(p, 'PEER', None) or ''} for d, p in _own().items()})

def start(device, module, flash, config, keys, line, frame, hashes, elf):
    global phone, glue
    path = devices.load(device).BOOT_ELF        # the firmware: where the profile looks for it
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f: f.write(elf.to_bytes())
    glue = dbcore_wasm.load(module)
    machine.Machine.make_core = staticmethod(dbcore_wasm.Core)
    def on_frame(w, h, rgb, n):
        frame(w, h, rgb, n, phone.app.now / 1e6, hashlib.sha1(rgb).hexdigest() if hashes else '')
    phone = db3210.build(device, flash=flash.to_bytes() if flash is not None else b'',
                         peer_config=json.loads(config) if config else None,
                         options=['--core', 'own', '--fast', '--standard', '--no-uart-log'], out=line, on_frame=on_frame)
    bad = [k for k in keys if not phone.inputs.command(k)]
    if bad: raise ValueError('scripted keys: not understood: ' + bad[0])
    km = phone.inputs.km
    return to_js(sorted(set(km.KEY_INDEX) | set(km.ALIASES)))

def step(ns, hold):
    r = db3210.run(phone, ns, hold=hold)
    return to_js([r['now_ns'], r['insns'], r['ended'], r['why'], r.get('rest_ns', 0)])

def key(name, down):
    (phone.press if down else phone.release)(name)
    return phone.now

def command(text):
    return phone.inputs.command(text)

# The cell network "host" of the modem stand-in (emu_cell/cell.py, class Host): the page carries the text messages.
def _cell():
    for v in phone.attached.values():
        c = getattr(v, 'cell', None)
        if c is not None and hasattr(c, 'take'):
            return c
    return None

def cell_result(n, ok, cause):
    c = _cell()
    if c: c.result(n, ok, cause)

_cell_reports = []

def cell_take():
    _cell_apply()
    c = _cell()
    out = [[n, sc.hex(), t.hex()] for n, sc, t in c.take()] if c else []
    reports = _cell_reports[:]
    del _cell_reports[:]
    return json.dumps([out, reports])

# k: the page's number for this message; the phone's answer (taken, or refused with an RP cause) goes back under it.
def cell_incoming(sc, tpdu, k=-1):
    c = _cell()
    report = None if k < 0 else (lambda accepted, cause=0: _cell_reports.append([k, bool(accepted), int(cause)]))
    if c: c.incoming(bytes.fromhex(sc), bytes.fromhex(tpdu), report)
    elif report: report(False, 0)

# Service or no service, as the page's link to the network has it; for a cell network that can show it.
# The page says it once, and that can be before the modem's link is up and the network is there: what it said is kept and
# given at the first cell_take() that finds the network.
_cell_want = None

def cell_state(up):
    global _cell_want
    _cell_want = bool(up)
    _cell_apply()

def _cell_apply():
    global _cell_want
    c = _cell()
    if _cell_want is None or c is None or not hasattr(c, 'set_service') or getattr(c, 'port', None) is None: return
    c.set_service(_cell_want)
    _cell_want = None

def state():
    return to_js(phone.flash_state())

def finish(why):
    db3210.report(phone, why)
    machine.report(phone.app.m, print)

def memory():
    return glue.memory_bytes()
`;

async function load() {
  let t = performance.now();
  try { importScripts('pycore.js'); } catch (e) { throw new Error('pycore.js could not be loaded from the server'); }
  try { importScripts('pyodide/pyodide.js'); } catch (e) {
    throw new Error('Pyodide is not there. Start the server with --pyodide DIR, where DIR is a folder with an unpacked Pyodide release (pyodide.js, pyodide.asm.mjs, pyodide.asm.wasm, python_stdlib.zip, pyodide-lock.json).');
  }
  py = await loadPyodide({ indexURL: new URL('pyodide/', self.location.href).href, env: { HOME: '/home/pyodide' },
    stdout: s => lines.push(s), stderr: s => errLines.push(s) });
  times.pyodide = performance.now() - t; t = performance.now();
  post({ t: 'stage', text: 'Pyodide is up; unpacking the simulator' });

  const res = await fetch('phone_src.json').catch(() => null);
  if (!res || !res.ok) throw new Error('The server has no Python source of the simulator to give (phone_src.json): myna/web/serve.py makes it from the files of myna/web/platform.txt.');
  const src = (await res.json()).files;
  const made = new Set();
  for (const name of Object.keys(src)) {
    const path = '/phone/' + name, dir = path.slice(0, path.lastIndexOf('/'));
    if (!made.has(dir)) { py.FS.mkdirTree(dir); made.add(dir); }
    py.FS.writeFile(path, src[name]);
  }
  times.unpack = performance.now() - t; t = performance.now();
  try { py.runPython(GLUE); } catch (e) {
    throw new Error('The simulator does not import under Pyodide. Its launcher must be the one with build() and run() and no import of Unicorn at the top.\n' + e.message);
  }
  api = {};
  for (const f of ['has_api', 'device_names', 'device_info', 'start', 'step', 'key', 'command', 'cell_take', 'cell_result', 'cell_incoming', 'cell_state', 'state', 'finish', 'memory']) api[f] = py.globals.get(f);
  if (!api.has_api()) throw new Error('The launcher of this tree (sim/db3210.py) has no build() and run(): the phone page needs a tree whose launcher has them.');
  times.imports = performance.now() - t; t = performance.now();

  const wres = await fetch('dbcore.wasm').catch(() => null);
  if (!wres || !wres.ok) throw new Error('dbcore.wasm could not be loaded from the server');
  self.coreModule = await WebAssembly.compile(await wres.arrayBuffer());
  times.core = performance.now() - t;
  flush();
  infos = JSON.parse(api.device_info());
  post({ t: 'ready', devices: api.device_names(), info: infos, files: Object.keys(src).length, times });
}

// A picture from the display model: rgb is a Python bytes object, 3 bytes per pixel. It is read where it lies in
// Pyodide's memory and written as RGBA into a buffer that goes to the page without another copy.
function onFrame(w, h, rgb, n, ms, sha) {
  const t = performance.now();
  const b = rgb.getBuffer('u8'), s = b.data, px = w * h;
  const out = new Uint32Array(px);
  for (let i = 0, j = 0; i < px; i++, j += 3) out[i] = 0xFF000000 | s[j + 2] << 16 | s[j + 1] << 8 | s[j];
  b.release(); rgb.destroy();
  convMs += performance.now() - t; convN++;
  flush();                                         // the lines before it first, as they were printed
  post({ t: 'frame', w, h, n, ms, sha, rgba: out.buffer, host: performance.now() }, [out.buffer]);
}

async function start(m) {
  let t = performance.now();
  fast = !!m.fast; keylog = !!m.keylog; slow = Math.max(1, +m.slow || 1);
  if (!infos[m.device]) { flush(); return fail('firmware', 'No phone ' + m.device + ' here: only a device with a firmware of our own (BOOT_ELF) runs on this page.'); }
  if (!m.elf) {                                    // its ELF file from the server, when the page has none
    post({ t: 'stage', text: 'loading the firmware ' + infos[m.device].elf });
    const res = await fetch('firmware/' + m.device + '.elf').catch(() => null);
    if (!res || !res.ok) { flush(); return fail('firmware', 'The server has no firmware for ' + m.device + ' (firmware/' + m.device + '.elf). Build it (make -C myna/firmware) or give the ELF file.'); }
    m.elf = await res.arrayBuffer();
    times.elf = performance.now() - t; t = performance.now();
  }
  try {
    post({ t: 'stage', text: 'building the machine' });
    const keys = api.start(m.device, self.coreModule, m.flash ? new Uint8Array(m.flash) : undefined,
      m.config || '', m.keys || [], s => { lines.push(s); }, onFrame, !!m.hashes, new Uint8Array(m.elf));
    m.flash = m.elf = null;
    times.build = performance.now() - t;
    flush();
    post({ t: 'built', keys, times, mem: memory() });
  } catch (e) { flush(); return fail('build', e); }
  run(m).catch(e => { flush(); fail('run', e); });
}

const memory = () => ({ core: api.memory(), pyodide: py._module.HEAPU8.buffer.byteLength });

// A key from the page, with the moment the page saw it (m.at: ms since the epoch of performance.timeOrigin, as the page's
// clock and this one share it). The loop gives it to the phone at the matching emulated time (run(), the keys).
function keyIn(m) {
  const t = performance.now();
  const h = typeof m.at === 'number' ? m.at - performance.timeOrigin : t;
  keyH = Math.min(t, Math.max(h, keyH));
  keyq.push({ name: String(m.name), down: !!m.down, h: keyH });
}

// The loop. Paced: after each step the phone waits until the host clock has caught up with it; when the host is too slow
// the phone runs step after step, and what it is behind by more than MAX_DEBT_MS is given up and counted (lost).
// A sleeping phone can come back from a step ahead of the host clock (the launcher jumps to its wake-up); the loop then waits.
// Fast: no waiting. Either way every step ends with a turn of the event loop, so keys and pause arrive.
// Rest (with hold; by default, m.rest says otherwise): when a step ends with the
// phone asleep and nothing due for rest_ns, the loop waits on the host clock that long (at most REST_MAX_MS), fast or
// not, and the next step brings the phone up to the host clock: no step at all while it sleeps. A key or another message
// from the page ends the wait at once.
// The keys: a key is given to the phone at the emulated time of the moment the page saw it, and while a key is down the
// phone runs in short steps and never past the host clock from that moment on, so a press lasts on the phone what it
// lasted on the page. (The phone used to take a key at the end of its last step and then catch up with the host clock with
// the key down: after a rest that was up to a second, and a tap of 100 ms became a held key, 700 ms: # held is the next
// input method, a digit held its digit.) The first key of a press is due where the host clock is (a resting phone is brought
// there first, which costs nothing); a phone that is behind because it is slow takes it at once instead of making it wait.
// The keys after it keep the page's spacing from it, however late the first one was given.
async function run(m) {
  const limit = m.limit_s > 0 ? m.limit_s * 1e9 : 0, hold = !!m.hold;
  const rest = hold && (m.rest !== undefined ? !!m.rest : true);
  let now = 0, insns = 0, steps = 0, why = '', lost = 0, worst = 0, ask = STEP_NS, rests = 0;
  const t0 = performance.now();
  let pt = t0, pe = 0;                             // origin of the pacing: host ms, emulated ns
  let next = 1e9, busy = 0;                        // the next whole emulated second to report; host ms spent inside run()
  let keyAt = null, resting = false;               // the last key given while keys are down or waiting: {e: emulated ns, h: host ms}
  const keysDown = new Set();
  const give = (k, late) => {
    try {
      const at = api.key(k.name, k.down);
      if (k.down) keysDown.add(k.name); else keysDown.delete(k.name);
      if (keylog) lines.push(`[keys] ${k.name} ${k.down ? 'down' : 'up'} at ${(at / 1e6).toFixed(1)} ms` + (late > 1e6 ? ` (${(late / 1e6).toFixed(0)} ms late)` : ''));
    } catch (err) { flush(); post({ t: 'error', stage: 'key', text: String(err.message || err), soft: true }); }
  };
  keyq.length = 0;
  running = true;
  post({ t: 'running', host: t0 });
  while (!wantStop) {
    if (paused) { const p0 = performance.now(); await sleep(50); if (keyAt) keyAt.h += performance.now() - p0; pt = performance.now(); pe = now; continue; }
    if (keyq.length || keysDown.size) {
      let until = Infinity;                        // the emulated time the phone may not pass now
      while (keyq.length) {
        const k = keyq[0];
        const due = keyAt ? keyAt.e + (k.h - keyAt.h) * 1e6 : resting ? pe + (k.h - pt) * 1e6 : now;
        if (due > now + KEY_SLACK_NS) { until = due; break; }
        keyq.shift(); give(k, now - due);
        keyAt = { e: now, h: k.h };
      }
      if (keysDown.size) until = Math.min(until, keyAt.e + (performance.now() - keyAt.h) * 1e6);
      else if (!keyq.length) keyAt = null;
      if (until - now < KEY_SLACK_NS) { flush(); await nap(Math.max(1, (now + KEY_STEP_NS - until) / 1e6)); continue; }
      if (until < Infinity) ask = Math.max(1, Math.min(ask, until - now, keysDown.size ? KEY_STEP_NS : Infinity));
    }
    const ts = performance.now();
    const r = api.step(limit ? Math.max(1, Math.min(ask, limit - now)) : ask, hold);
    ask = STEP_NS;
    if (slow > 1) { const end = performance.now() + (performance.now() - ts) * (slow - 1); while (performance.now() < end); }
    busy += performance.now() - ts;
    now = r[0]; insns = r[1]; steps++; resting = rest && r[4] > 0;
    if (rest || steps % 10 === 0) {         // resting, a step can be a second long: look every step
      const [out, reports] = JSON.parse(api.cell_take());
      for (const [n, sc, tpdu] of out) post({ t: 'cell', n, sc, tpdu });
      for (const [k, ok, cause] of reports) post({ t: 'cell_in_result', k, ok, cause });
    }
    flush();
    if (now >= next) {
      post({ t: 'second', emu: now / 1e9, host: (performance.now() - t0) / 1000, busy: busy / 1000, insns, steps, lost: lost / 1000, worst: worst / 1000,
        conv: convN ? convMs / convN : 0, rests });
      next = (Math.floor(now / 1e9) + 1) * 1e9; worst = 0;
    }
    if (r[2] || (limit && now > limit)) { why = r[3]; break; }
    if (rest && r[4] > 0) {
      if (fast) { pt = performance.now(); pe = now; }
      const wait = (now - pe) / 1e6 + Math.min(r[4] / 1e6, REST_MAX_MS) - (performance.now() - pt);
      rests++;
      if (wait > 1) await nap(wait); else await breathe();
      const host = pe + (performance.now() - pt) * 1e6;     // the emulated time the host clock has reached
      ask = Math.max(1, Math.min(host - now, 2 * REST_MAX_MS * 1e6));
      continue;
    }
    if (fast) { await breathe(); pt = performance.now(); pe = now; continue; }
    const ahead = (now - pe) / 1e6 - (performance.now() - pt);
    if (ahead > 1) { if (await nap(ahead)) { pt = performance.now(); pe = now; } }
    else {
      if (-ahead > worst) worst = -ahead;
      if (-ahead > MAX_DEBT_MS) { lost += -ahead; pt = performance.now(); pe = now; }
      await breathe();
    }
  }
  running = false;
  const host = (performance.now() - t0) / 1000;
  let bytes = null;
  try {
    api.finish(why || 'stopped on the page');
    const s = api.state(); bytes = s.buffer;
  } catch (e) { errLines.push('the end-of-run report failed: ' + e.message); }
  flush();
  post({ t: 'end', why: why || 'stopped on the page', emu: now / 1e9, host, busy: busy / 1000, insns, steps, lost: lost / 1000, mem: memory(),
    conv: convN ? convMs / convN : 0, frames: convN, state: bytes }, bytes ? [bytes] : []);
}

onmessage = e => {
  const m = e.data;
  try {
    if (m.t === 'start') start(m);
    else if (m.t === 'key') { if (running) { keyIn(m); if (wake) wake(); } }
    else if (m.t === 'cell_result') { if (running) api.cell_result(m.n, !!m.ok, m.cause || 0); }
    else if (m.t === 'cell_in') {
      if (running) { api.cell_incoming(m.sc, m.tpdu, m.k === undefined ? -1 : m.k); if (wake) wake(); }
      else if (m.k !== undefined) post({ t: 'cell_in_result', k: m.k, ok: false, cause: 27 });
    }
    else if (m.t === 'cell_state') { if (running) { api.cell_state(!!m.up); if (wake) wake(); } }
    else if (m.t === 'input') { if (running) { if (!api.command(m.command)) throw new Error('input not understood: ' + m.command); flush(); if (wake) wake(); } }
    else if (m.t === 'pause') { paused = !!m.on; if (wake) wake(); }
    else if (m.t === 'fast') { fast = !!m.on; if (wake) wake(); }
    else if (m.t === 'stop') { wantStop = true; if (wake) wake(); }
    else if (m.t === 'state') { const s = api.state(); post({ t: 'state', bytes: s.buffer, why: m.why, mem: memory() }, [s.buffer]); }
  } catch (err) { flush(); post({ t: 'error', stage: m.t, text: String(err.message || err), soft: m.t === 'key' || m.t === 'input' || m.t === 'state' }); }
};

load().catch(e => fail('load', e));
