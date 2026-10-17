// lib.mjs: what the page tests share: the page's server (myna/web/serve.py) and a headless Chrome on free ports, each
// in a temporary folder, a DevTools-protocol connection to a tab (Node's own WebSocket, no packages), and keys and
// multi-tap text for the phone in the tab.
//   CHROME   another Chrome or Chromium (default: the macOS Google Chrome)   PYTHON  default python3
//   MYNA_PYODIDE  the unpacked Pyodide release for serve.py                  SHOTS   a folder for screenshots
// SPDX-License-Identifier: MIT
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
export const sleep = ms => new Promise(r => setTimeout(r, ms));
export const freePort = () => new Promise(res => { const s = createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });

let passed = 0, failed = 0;
export const check = (ok, what) => { console.log((ok ? 'PASS ' : 'FAIL ') + what); ok ? passed++ : failed++; return ok; };
export const summary = () => { console.log(`${passed} passed, ${failed} failed`); return failed ? 1 : 0; };

/** The page's server and a Chrome. relay: the relay's address for the page, or ''. Returns { base, cdp, stop }. */
export async function start({ relay = '' } = {}) {
  const work = mkdtempSync(join(tmpdir(), 'myna-page-'));
  const page = await freePort(), cdp = await freePort(), procs = [];
  const args = ['-I', join(WEB, 'serve.py'), '--port', String(page)];
  if (process.env.MYNA_PYODIDE) args.push('--pyodide', process.env.MYNA_PYODIDE);
  if (relay) args.push('--relay', relay);
  const server = spawn(process.env.PYTHON || 'python3', args, { stdio: ['ignore', 'pipe', 'inherit'] });
  procs.push(server);
  let said = '';
  server.stdout.on('data', d => { said += d; });
  for (let i = 0; i < 80 && !said.includes('http://'); i++) await sleep(250);
  console.log(said.trim().split('\n').map(s => 'server: ' + s).join('\n'));
  // two tabs run phones at once: no throttling of the one that is not in front
  procs.push(spawn(CHROME, ['--headless=new', `--remote-debugging-port=${cdp}`, `--user-data-dir=${join(work, 'chrome')}`, '--no-first-run',
    '--no-default-browser-check', '--hide-scrollbars', '--window-size=1200,900', '--disable-background-timer-throttling',
    '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows', 'about:blank'], { stdio: 'ignore' }));
  return {
    base: `http://127.0.0.1:${page}/`, other: `http://localhost:${page}/`, cdp,
    stop: async () => { for (const p of procs) try { p.kill(); } catch (e) { /* gone */ } await sleep(500); rmSync(work, { recursive: true, force: true }); },
  };
}

/** A tab: the first one of the Chrome on port `cdp`, or a new one (fresh). */
export async function tab(cdp, fresh = false) {
  let target;
  for (let i = 0; i < 80 && !target; i++) {
    try {
      target = fresh ? await (await fetch(`http://127.0.0.1:${cdp}/json/new?about:blank`, { method: 'PUT' })).json()
        : (await (await fetch(`http://127.0.0.1:${cdp}/json`)).json()).find(x => x.type === 'page');
    } catch (e) { await sleep(250); }
  }
  if (!target) throw new Error('Chrome did not start');
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0; const waits = new Map(), logs = [];
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && waits.has(m.id)) { const [res, rej] = waits.get(m.id); waits.delete(m.id); m.error ? rej(new Error(m.error.message)) : res(m.result); }
    else if (m.method === 'Runtime.exceptionThrown') logs.push('EXCEPTION ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
  };
  const send = (method, params = {}) => new Promise((res, rej) => { waits.set(++id, [res, rej]); ws.send(JSON.stringify({ id, method, params })); });
  await send('Runtime.enable'); await send('Page.enable');
  // no animation: the slide jumps (a tab that is not in front draws no animation frames)
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  const t = {
    send, logs, close: () => ws.close(),
    go: url => send('Page.navigate', { url }),
    front: () => send('Page.bringToFront'),
    async evaluate(expr) {
      const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
      return r.result.value;
    },
    async waitFor(expr, ms = 60000) {
      const t0 = Date.now();
      for (;;) { const v = await t.evaluate(expr); if (v) return v; if (Date.now() - t0 > ms) return null; await sleep(250); }
    },
    async shot(name) {
      if (!process.env.SHOTS) return;
      const r = await send('Page.captureScreenshot', { format: 'png' });
      mkdirSync(process.env.SHOTS, { recursive: true }); writeFileSync(join(process.env.SHOTS, name + '.png'), Buffer.from(r.data, 'base64'));
    },
    // a key of the phone, pressed and released as a finger would; the phone runs at the speed of the host clock
    async key(name, ms = 90, after = 160) {
      await t.evaluate(`app.key(${JSON.stringify(name)}, true)`); await sleep(ms);
      await t.evaluate(`app.key(${JSON.stringify(name)}, false)`); await sleep(after);
    },
    async type(text) {
      let last = null;
      for (const ch of text) {
        const [k, n] = MULTITAP[ch];
        if (k === last) await t.key('right', 60, 80);
        for (let i = 0; i <= n; i++) await t.key(k, 50, 70);
        last = k;
      }
      await t.key('right', 60, 120);
    },
    async dial(number) { for (const d of number) await t.key(d === '+' ? 'star' : d, 50, 80); },
    // from standby: Messages, New message, Enter number, the number, the conversation; # held for letters (the box
    // starts in predictive text), then the text, Send
    async text(number, words) {
      await t.key('soft_left'); await t.key('select'); await t.key('select');
      await t.dial(number); await t.key('select', 90, 600);
      await t.key('hash', 900, 300);
      await t.type(words); await t.key('select');
    },
    line: re => t.evaluate(lineWith(re)),
    waitLine: (re, ms) => t.waitFor(lineWith(re), ms),
  };
  return t;
}
const lineWith = re => `(app.lines || []).find(s => ${re}.test(s)) || ''`;
const MULTITAP = { a: ['2', 0], b: ['2', 1], c: ['2', 2], d: ['3', 0], e: ['3', 1], f: ['3', 2], g: ['4', 0], h: ['4', 1], i: ['4', 2],
  j: ['5', 0], k: ['5', 1], l: ['5', 2], m: ['6', 0], n: ['6', 1], o: ['6', 2], p: ['7', 0], q: ['7', 1], r: ['7', 2], s: ['7', 3],
  t: ['8', 0], u: ['8', 1], v: ['8', 2], w: ['9', 0], x: ['9', 1], y: ['9', 2], z: ['9', 3], ' ': ['hash', 0] };
