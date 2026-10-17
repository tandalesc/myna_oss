// typing.mjs: predictive text typed with taps on the keys of the phone (drawn in 3D: each tap lands where app.where() finds
// the key on the 3D phone), as a person types, in headless Chrome with the
// loopback network. A tap of 60 to 150 ms must reach the phone as a tap: no key may come to the firmware held (700 ms;
// # held is the next input method, a digit held its digit), after the phone has rested, on a CPU five times slower
// (as an iPhone's can be), and with the touch of a phone's screen.
//
//   MYNA_PYODIDE=DIR node myna/web/test/typing.mjs        (after make -C myna/firmware and sh native/core/build.sh)
//
// Each round: from standby a new message to a number, the words with one press a letter (# the space), Send; the text
// that comes back on loopback must be the sentence, and the worker's key log (?keylog=1) gives each press's length on the
// phone's clock. Exit status 0 when every step passed. Environment: lib.mjs.
// SPDX-License-Identifier: MIT
import { start, tab, check, summary, sleep } from './lib.mjs';

const T9 = { a: 2, b: 2, c: 2, d: 3, e: 3, f: 3, g: 4, h: 4, i: 4, j: 5, k: 5, l: 5, m: 6, n: 6, o: 6, p: 7, q: 7, r: 7, s: 7, t: 8, u: 8, v: 8,
  w: 9, x: 9, y: 9, z: 9, ' ': 'hash' };
let seed = 7;
const rnd = (a, b) => { seed = (seed * 1103515245 + 12345) % 2147483648; return a + (seed / 2147483648) * (b - a); };

// One phone in a tab: touch with an iPhone's screen, or the mouse. slow: the worker takes that many times as long for each
// step (?slow=; DevTools slows the page's CPU but not a worker's), and the page's CPU is slowed as much.
async function phone(env, touch, slow = 1) {
  const t = await tab(env.cdp, touch);
  if (touch) {
    await t.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 3, mobile: true });
    await t.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
  }
  if (slow > 1) await t.send('Emulation.setCPUThrottlingRate', { rate: slow });
  await t.go(env.base + '?p=myna&keylog=1' + (slow > 1 ? '&slow=' + slow : ''));
  await sleep(1000);
  // the phone is drawn in 3D (the page's default): the taps find their keys on the 3D phone
  const up = await t.waitFor(`window.app && (app.frames > 0 || app.error)`, 240000) && !(await t.evaluate('app.error')) && await t.waitFor('app.three()', 30000);
  check(up, `${touch ? 'touch' : 'mouse'}: the phone is up, drawn in 3D: ${await t.evaluate('window.app && app.error') || 'no error'}`);
  check(await t.waitLine(/network: registration 1/, 30000), `${touch ? 'touch' : 'mouse'}: the phone registers`);
  // every console line from here on (app.lines keeps the last 200)
  await t.evaluate(`window.all = []; { const l = app.lines, push = l.push.bind(l); l.push = (...a) => { all.push(...a); return push(...a); }; } 0`);
  await t.evaluate(`app.slide(true)`); await sleep(1500);
  // a finger on the middle of a key's area for ms, then off it
  t.tap = async (name, ms) => {
    const [x, y] = await t.evaluate(`app.where(${JSON.stringify(name)})`);
    if (touch) {
      await t.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y, id: 1 }] });
      await sleep(ms);
      await t.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    } else {
      await t.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1 });
      await sleep(ms);
      await t.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1 });
    }
  };
  t.k = async (name, pause = 0) => { if (pause) await sleep(pause); await t.tap(name, rnd(60, 150)); await sleep(rnd(100, 300)); };
  return t;
}

// A round: the message, typed after `idle` ms with nothing pressed; `think` ms before each space (a person between words).
async function round(t, what, sentence, { idle = 0, think = 0 } = {}) {
  await t.k('soft_left'); await t.k('select', 400); await t.k('select', 400);
  for (const d of '5551234') await t.k(d);
  await t.k('select'); await sleep(800);
  await sleep(idle);
  const from = await t.evaluate('all.length');
  for (const ch of sentence) await t.k(String(T9[ch]), ch === ' ' ? think : 0);
  await sleep(400);
  // the presses on the phone's clock, and what the firmware took as held
  const lines = await t.evaluate(`all.slice(${from})`);
  const at = {}, lens = [];
  for (const s of lines) {
    const m = /^\[keys\] (\S+) (down|up) at ([\d.]+) ms/.exec(s);
    if (!m) continue;
    if (m[2] === 'down') at[m[1]] = +m[3]; else if (at[m[1]] !== undefined) { lens.push(+m[3] - at[m[1]]); delete at[m[1]]; }
  }
  const held = lines.filter(s => /ui: key \S+ held/.test(s)).map(s => s.replace(/^.*\| /, ''));
  const longest = lens.length ? Math.max(...lens) : NaN;
  check(lens.length === sentence.length && longest < 200, `${what}: ${lens.length} presses of 60-150 ms are ${Math.min(...lens).toFixed(0)}-${longest.toFixed(0)} ms on the phone`);
  check(!held.length, `${what}: no key held: ${held.join(' / ') || 'none'}`);
  await t.k('select');
  const re = /message \d+ from \S+ received: "(.*)"/i;
  const back = await t.waitFor(`all.slice(${from}).find(s => ${re}.test(s)) || ''`, 30000);
  const got = back ? re.exec(back)[1] : null;
  const want = sentence[0].toUpperCase() + sentence.slice(1);
  check(got === want, `${what}: the text comes back as typed: ${JSON.stringify(got)}`);
  await t.k('end'); await sleep(500);
}

const env = await start();
try {
  const m = await phone(env, false);
  await round(m, 'mouse, after 4 s at rest', 'what is up', { idle: 4000 });
  await round(m, 'mouse, 1.2 s before each space', 'where are you now', { idle: 2000, think: 1200 });
  if (m.logs.length) console.log('--- page ---\n' + m.logs.join('\n'));
  m.close();
  const p = await phone(env, true, 5);
  await round(p, 'touch on an iPhone screen, 5x slower, after 5 s at rest', 'what is up', { idle: 5000 });
  await round(p, 'touch on an iPhone screen, 5x slower, 1 s before each space', 'where are you now', { idle: 3000, think: 1000 });
  if (p.logs.length) console.log('--- page ---\n' + p.logs.join('\n'));
  p.close();
} catch (e) {
  check(false, 'the test ran: ' + (e.message || e));
} finally {
  await env.stop();
}
process.exit(summary());
