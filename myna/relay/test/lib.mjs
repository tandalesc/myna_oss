// lib.mjs: what the tests share. A scripted phone that speaks the relay's protocol by hand (so that it can also lie),
// a wrangler dev process per configuration, and the page's own cell.js loaded as the page loads it.
// SPDX-License-Identifier: MIT
import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync, rmSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

export const HERE = dirname(fileURLToPath(import.meta.url)), ROOT = resolve(HERE, '..');
export const sleep = ms => new Promise(r => setTimeout(r, ms));
vm.runInThisContext(readFileSync(resolve(ROOT, 'client', 'cell.js'), 'utf8'), { filename: 'cell.js' });
export const R = globalThis.cellRelay;

const ECDSA = { name: 'ECDSA', namedCurve: 'P-256' }, SIGN = { name: 'ECDSA', hash: 'SHA-256' };

/** An identity as a test makes it: the keys can be used for anything, also for lying. `prefix`: grind until the number starts so. */
export async function identity(prefix = '', not = '') {
  for (;;) {
    const id = await crypto.subtle.generateKey(ECDSA, true, ['sign', 'verify']);
    const idPub = new Uint8Array(await crypto.subtle.exportKey('raw', id.publicKey));
    const number = await R.numberOf(idPub);
    if (!number.startsWith(prefix) || (not && number.startsWith(not))) continue;
    const en = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
    const encPub = new Uint8Array(await crypto.subtle.exportKey('raw', en.publicKey));
    const encSig = new Uint8Array(await crypto.subtle.sign(SIGN, id.privateKey, R.encText(number, R.b64(encPub))));
    return { v: 1, number, idPriv: id.privateKey, idPub, encPriv: en.privateKey, encPub, encSig };
  }
}

/** A phone driven by hand. Every frame it gets is kept; next(type) waits for one. */
export class Phone {
  constructor(base, who) { this.base = base; this.who = who; this.got = []; this.waiters = []; this.closed = null; this.nextId = 1; }

  open({ n = this.who.number, v = 1, headers } = {}) {
    const url = `${this.base.replace(/^http/, 'ws')}/ws?n=${n}&v=${v}`;
    this.host = new URL(url).host;
    this.ws = headers ? new WebSocket(url, { headers }) : new WebSocket(url);
    this.ws.onmessage = e => { const m = e.data === 'pong' ? { t: 'pong' } : JSON.parse(e.data); this.got.push(m); this.pump(); };
    this.ws.onclose = e => { this.closed = { code: e.code, reason: e.reason }; this.pump(); };
    this.ws.onerror = () => {};
    return this;
  }

  pump() {
    for (const w of [...this.waiters]) {
      const i = this.got.findIndex(w.test);
      if (i >= 0) { this.waiters.splice(this.waiters.indexOf(w), 1); clearTimeout(w.timer); w.res(this.got.splice(i, 1)[0]); }
      else if (this.closed && w.orClose) { this.waiters.splice(this.waiters.indexOf(w), 1); clearTimeout(w.timer); w.res(null); }
    }
  }

  /** The next frame of this type (or matching the function). Rejects after `ms`. */
  next(type, ms = 5000) {
    const test = typeof type === 'function' ? type : m => m.t === type;
    return new Promise((res, rej) => {
      const w = { test, res, timer: setTimeout(() => { this.waiters.splice(this.waiters.indexOf(w), 1); rej(new Error(`${this.who.number}: no "${type}" frame in ${ms} ms; have ${JSON.stringify(this.got).slice(0, 300)}; closed ${JSON.stringify(this.closed)}`)); }, ms) };
      this.waiters.push(w); this.pump();
    });
  }

  /** True when no frame of this type comes within `ms`. */
  async none(type, ms = 400) { try { const m = await this.next(type, ms); this.got.unshift(m); return false; } catch (e) { return true; } }

  async untilClosed(ms = 5000) { for (let t = 0; t < ms && !this.closed; t += 20) await sleep(20); if (!this.closed) throw new Error('still open'); return this.closed; }

  send(m) { this.ws.send(typeof m === 'string' ? m : JSON.stringify(m)); }

  /** The honest join, unless `over` changes fields or `signer` / `signHost` / `nonce` make it a lie. */
  async join({ over = {}, signer = this.who, signHost, nonce, open } = {}) {
    if (!this.ws) this.open(open);
    const c = await this.next('challenge');
    this.challenge = c;
    const sig = await crypto.subtle.sign(SIGN, signer.idPriv, R.joinText(signHost || c.relay, this.who.number, nonce || c.nonce));
    this.send({ t: 'join', v: 1, id: R.b64(this.who.idPub), sig: R.b64(sig), ek: R.b64(this.who.encPub), es: R.b64(this.who.encSig), ticket: this.ticket, ...over });
    const m = await this.next(x => x.t === 'joined' || x.t === 'error');
    if (m.t === 'joined') this.ticket = m.ticket;
    return m;
  }

  /** Send a text; the plain payload is kind 1 + an SMS-SUBMIT. Returns the message id. */
  text(to, body = submit(to, 'Hi'), extra = {}) { const id = this.nextId++; this.send({ t: 'msg', id, to, enc: 0, body: R.b64(R.cat([1], body)), ...extra }); return id; }

  close() { try { this.ws.close(); } catch (e) { /* closed */ } }
}

/** An SMS-SUBMIT with 7-bit text to a number (as the phone builds it: relative validity period). */
export function submit(to, text) {
  const septets = Array.from(text, c => c.charCodeAt(0) & 0x7f), ud = new Uint8Array(Math.ceil(septets.length * 7 / 8));
  septets.forEach((v, i) => { for (let k = 0; k < 7; k++) if (v >> k & 1) { const bit = i * 7 + k; ud[bit >> 3] |= 1 << (bit & 7); } });
  return R.cat([0x11, 0x01], R.addressField(to), [0x00, 0x00, 0xff, septets.length], ud);
}

/** A worker as cell.js sees it: keeps what the page posts to it; the test plays the phone. */
export function fakeWorker() {
  const w = { posted: [], waiters: [], postMessage(m) { w.posted.push(m); for (const f of w.waiters.splice(0)) f(); } };
  w.next = async (t, ms = 8000) => {
    const end = Date.now() + ms;
    for (;;) {
      const i = w.posted.findIndex(m => m.t === t);
      if (i >= 0) return w.posted.splice(i, 1)[0];
      if (Date.now() > end) throw new Error(`the worker got no "${t}" in ${ms} ms`);
      await Promise.race([new Promise(r => w.waiters.push(r)), sleep(100)]);
    }
  };
  return w;
}

// ---- wrangler dev, one process per configuration ----
export async function relay(name, port, { vars = {}, joinLimit = 100000 } = {}) {
  const cfg = readFileSync(resolve(ROOT, 'wrangler.jsonc'), 'utf8').replace(/"limit": \d+/, `"limit": ${joinLimit}`);
  const cfgPath = resolve(ROOT, `wrangler.test-${name}.jsonc`), envPath = resolve(ROOT, `.test-${name}.env`), state = resolve(ROOT, '.wrangler', `test-${name}`);
  writeFileSync(cfgPath, cfg);
  writeFileSync(envPath, Object.entries({ DEV: '1', TICKET_SECRET: 'test-ticket-secret', TURNSTILE_SECRET: 'off', ADMIN_SECRET: 'test-admin', ...vars }).map(([k, v]) => `${k}=${v}`).join('\n') + '\n');
  rmSync(state, { recursive: true, force: true }); mkdirSync(state, { recursive: true });
  const log = [];
  const p = spawn(resolve(ROOT, 'node_modules', '.bin', 'wrangler'), ['dev', '-c', cfgPath, '--port', String(port), '--ip', '127.0.0.1', '--inspector-port', String(port + 1000),
    '--env-file', envPath, '--persist-to', state, '--show-interactive-dev-session=false', '--log-level', 'info'], { cwd: ROOT, env: { ...process.env, WRANGLER_SEND_METRICS: 'false', CI: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
  p.stdout.on('data', d => log.push(String(d))); p.stderr.on('data', d => log.push(String(d)));
  const base = `http://127.0.0.1:${port}`;
  for (let i = 0; ; i++) {
    try { if ((await fetch(base + '/info')).ok) break; } catch (e) { /* not yet */ }
    if (i > 150 || p.exitCode !== null) throw new Error('wrangler dev did not start:\n' + log.join(''));
    await sleep(200);
  }
  return {
    base, log,
    admin: async (path, body, headers = { authorization: 'Bearer test-admin' }) => {
      const res = await fetch(`${base}/admin/api/${path}`, { method: body ? 'POST' : 'GET', headers: { ...headers, ...(body ? { 'content-type': 'application/json' } : {}) }, body: body ? JSON.stringify(body) : undefined });
      return { status: res.status, body: res.status === 200 ? await res.json() : await res.text() };
    },
    stop: async () => { p.kill('SIGTERM'); for (let i = 0; i < 50 && p.exitCode === null && p.signalCode === null; i++) await sleep(100); rmSync(cfgPath, { force: true }); rmSync(envPath, { force: true }); },
  };
}

// ---- a tiny test runner ----
export const results = [];
export async function test(name, f) {
  const t = Date.now();
  try { await f(); results.push([true, name]); console.log(`ok    ${name}  (${Date.now() - t} ms)`); }
  catch (e) { results.push([false, name]); console.log(`FAIL  ${name}\n      ${String(e && e.stack || e).split('\n').slice(0, 4).join('\n      ')}`); }
}
export function eq(a, b, what = '') { const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) throw new Error(`${what}: got ${x}, want ${y}`); }
export function ok(v, what = '') { if (!v) throw new Error('not true: ' + what); }
