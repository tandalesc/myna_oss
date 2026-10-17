// phone3d.mjs: the chin slider drawn in 3D on the phone page, as on an iPhone (390 x 844 at 3x, touch), in headless Chrome
// with the loopback network; then the setting "Flat drawing (2D)" and a browser with no WebGL.
//
//   MYNA_PYODIDE=DIR node myna/web/test/phone3d.mjs      (after make -C myna/firmware and sh native/core/build.sh)
//
// Steps: the slider starts and the 3D phone is the phone; a swipe up the face slides it open frame by frame with the
// page's spring (the switch reaches the phone); two thumbs typing (each touch landing before the last lifts) write a text
// that comes back as typed, and the phone never leaves its rest for a turn; two fingers on the glass, off the keys, pick it
// up to look round and it springs back to the front when they lift; two fingers on two keys press both and pick nothing up;
// a swipe down slides it closed. The flat drawing: switched on, the 2D phone is the phone (no WebGL used), a tap on its key
// reaches the phone, the setting is kept over a reload, and switched off the 3D phone is back. With no WebGL the page
// draws the 2D phone and its keys work. Exit status 0 when every step passed. Environment: lib.mjs; SHOTS=DIR.
// SPDX-License-Identifier: MIT
import { start, tab, check, summary, sleep } from './lib.mjs';

const MT = { a: ['2', 0], b: ['2', 1], c: ['2', 2], d: ['3', 0], e: ['3', 1], f: ['3', 2], g: ['4', 0], h: ['4', 1], i: ['4', 2], j: ['5', 0], k: ['5', 1],
  l: ['5', 2], m: ['6', 0], n: ['6', 1], o: ['6', 2], p: ['7', 0], q: ['7', 1], r: ['7', 2], s: ['7', 3], t: ['8', 0], u: ['8', 1], v: ['8', 2],
  w: ['9', 0], x: ['9', 1], y: ['9', 2], z: ['9', 3], ' ': ['hash', 0] };

// A tab as an iPhone: its screen, touch. noGL: a browser that gives no WebGL context.
async function iphone(env, query, noGL = false) {
  const t = await tab(env.cdp, true);
  await t.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 3, mobile: true });
  await t.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
  if (noGL) await t.send('Page.addScriptToEvaluateOnNewDocument', { source: `{ const g = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (kind, ...a) { return /webgl/i.test(kind) ? null : g.call(this, kind, ...a); }; }` });
  await t.go(env.base + '?p=myna' + (query || ''));
  await sleep(1000);
  const up = await t.waitFor(`window.app && (app.frames > 0 || app.error)`, 240000) && !(await t.evaluate('app.error'));
  check(up, `the slider is up${noGL ? ' with no WebGL' : ''}: ${await t.evaluate('window.app && app.error') || 'no error'}`);
  t.touch = (type, pts) => t.send('Input.dispatchTouchEvent', { type, touchPoints: pts.map(p => ({ x: p[0], y: p[1], id: p[2] || 1 })) });
  t.tap = async (name, ms = 100) => { const p = await t.evaluate(`app.where(${JSON.stringify(name)})`); await t.touch('touchStart', [p]); await sleep(ms); await t.touch('touchEnd', []); await sleep(220); };
  t.swipe = async (x, y0, y1) => {
    await t.touch('touchStart', [[x, y0]]);
    for (let i = 1; i <= 14; i++) { await t.touch('touchMove', [[x, y0 + (y1 - y0) * i / 14]]); await sleep(16); }
    await t.touch('touchEnd', []); await sleep(200);
  };
  return t;
}
// The phone's console lines from now on.
const collect = t => t.evaluate(`window.all = []; { const l = app.lines, push = l.push.bind(l); l.push = (...a) => { all.push(...a); return push(...a); }; } 0`);
const slideDone = (t, state) => t.waitFor(`all.some(s => /ui: slide ${state}/.test(s))`, 6000);

const env = await start();
try {
  // ---- in 3D ----
  const t = await iphone(env);
  check(await t.waitFor(`app.three() && getComputedStyle(document.getElementById('rig')).visibility === 'hidden'`, 30000), 'the 3D phone is the phone');
  check(await t.waitLine(/network: registration 1/, 30000), 'the phone registers');
  await collect(t);
  await t.shot('phone3d-01-closed');

  // a swipe up the face, with motion: the page's spring slides the 3D face frame by frame
  await t.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });
  await t.evaluate(`(window.__p = [], window.__on = true, (function f() { if (!__on) return; requestAnimationFrame(() => { __p.push(+app.v3().p.toFixed(4)); f(); }); })(), 1)`);
  const face = await t.evaluate(`app.v3().project(88, 140, 'moving')`);
  await t.swipe(face[0], face[1], face[1] - 260);
  check(await slideDone(t, 'open') && await t.waitFor(`app.v3().p === 1`, 3000), 'a swipe up the face slides it open: the switch reaches the phone');
  await sleep(400);
  const frames = await t.evaluate(`(window.__on = false, new Set(__p).size)`);
  check(frames > 10, `the face slid in ${frames} frames of the drag and the page's spring`);
  await t.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  await t.shot('phone3d-02-open');

  // two thumbs: from standby a new message, then the words with each touch landing 40 ms before the last one lifts
  await t.evaluate(`(window.__turned = 0, app.v3().onModeWas = app.v3().onMode, app.v3().onMode = on => { if (on) __turned++; app.v3().onModeWas(on); }, 1)`);
  await t.tap('soft_left'); await sleep(300); await t.tap('select'); await sleep(300); await t.tap('select'); await sleep(300);
  for (const d of '5551234') await t.tap(d);
  await t.tap('select'); await sleep(800);
  await t.tap('hash', 900); await sleep(300);              // # held: letters
  const presses = [];
  for (const ch of 'what is up') { const [k, n] = MT[ch]; for (let i = 0; i <= n; i++) presses.push(k); }
  let held = null, id = 1, overlaps = 0;
  for (const k of presses) {
    const p = await t.evaluate(`app.where(${JSON.stringify(k)})`), me = [p[0], p[1], ++id];
    if (held && held.key !== k) { await t.touch('touchStart', [held.p, me]); overlaps++; await sleep(40); await t.touch('touchEnd', [held.p]); }
    else { if (held) { await t.touch('touchEnd', []); await sleep(110); } await t.touch('touchStart', [me]); }
    held = { key: k, p: me };
    await sleep(90);
  }
  await t.touch('touchEnd', []); await sleep(300);
  await t.tap('select');
  const re = /message \d+ from \S+ received: "(.*)"/i;
  const back = await t.waitFor(`all.find(s => ${re}.test(s)) || ''`, 30000);
  const got = back ? re.exec(back)[1] : null;
  check(got === 'What is up' && await t.evaluate('__turned') === 0,
    `two thumbs (${presses.length} presses, ${overlaps} landing before the last lifts): the text comes back as typed (${JSON.stringify(got)}) and the phone is never picked up`);
  await t.tap('end'); await sleep(500);

  // two fingers on the glass, off the keys: picked up to look round; lifted, it springs back to the front
  const g1 = await t.evaluate(`app.v3().project(60, 60, 'moving')`), g2 = await t.evaluate(`app.v3().project(120, 120, 'moving')`);
  await t.touch('touchStart', [[g1[0], g1[1], 1]]); await sleep(30);
  await t.touch('touchStart', [[g1[0], g1[1], 1], [g2[0], g2[1], 2]]); await sleep(100);
  for (let i = 1; i <= 10; i++) { await t.touch('touchMove', [[g1[0] + 14 * i, g1[1], 1], [g2[0] + 14 * i, g2[1], 2]]); await sleep(20); }
  const peek = await t.evaluate('({ active: app.v3().active, yaw: +app.v3().yaw.toFixed(3) })');
  await t.shot('phone3d-03-peek');
  await sleep(250);                                  // the fingers rest before they lift: no throw (a throw turns it over)
  await t.touch('touchEnd', []);
  check(peek.active && Math.abs(peek.yaw) > 0.1 && await t.waitFor(`!app.v3().active && Math.abs(Math.sin(app.v3().yaw)) < 1e-6`, 5000),
    `two fingers off the keys pick it up and turn it (yaw ${peek.yaw}); lifted, it springs back to the front`);

  // two fingers on two keys: both pressed, nothing picked up
  const from = await t.evaluate('all.length');
  const k5 = await t.evaluate(`app.where('5')`), k9 = await t.evaluate(`app.where('9')`);
  await t.touch('touchStart', [[k5[0], k5[1], 1]]); await sleep(40);
  await t.touch('touchStart', [[k5[0], k5[1], 1], [k9[0], k9[1], 2]]); await sleep(120);
  const both = await t.evaluate('!app.v3().active');
  await t.touch('touchEnd', []); await sleep(400);
  const keys = await t.evaluate(`all.slice(${from}).filter(s => /ui: key (5|9) down/.test(s)).length`);
  check(both && keys === 2, `two fingers on the 5 and the 9: both pressed (${keys}), the phone not picked up`);
  await t.tap('clear'); await t.tap('clear'); await t.tap('end');

  // a swipe down: closed
  const top = await t.evaluate(`app.v3().project(88, 60, 'moving')`);
  await t.swipe(top[0], top[1], top[1] + 260);
  check(await slideDone(t, 'closed') && await t.waitFor(`app.v3().p === 0`, 3000), 'a swipe down the face slides it closed');

  // ---- the flat drawing ----
  await t.evaluate(`(document.getElementById('menu').click(), 1)`); await sleep(500);
  check(await t.evaluate(`!document.getElementById('flatRow').hidden && !document.getElementById('flatOn').checked`), 'the settings offer the flat drawing, off');
  await t.evaluate(`(document.getElementById('flatOn').click(), document.getElementById('closeSheet').click(), 1)`); await sleep(800);
  check(await t.evaluate(`!app.three() && !app.v3() && !document.querySelector('.p3d') && getComputedStyle(document.getElementById('rig')).visibility === 'visible'`),
    'switched on: the 2D phone is the phone, no 3D layer');
  await t.evaluate(`app.slide(true)`); await sleep(600);
  let n0 = await t.evaluate('all.length');
  await t.tap('5');
  check(await t.waitFor(`all.slice(${n0}).some(s => /ui: key 5 down/.test(s))`, 3000), 'a tap on its 5 reaches the phone');
  await t.shot('phone3d-04-flat');
  await t.go(env.base + '?p=myna');
  await sleep(1000);
  check(await t.waitFor(`window.app && app.frames > 0`, 240000) && await t.evaluate(`!app.three() && !app.v3() && document.getElementById('flatOn').checked`),
    'after a reload the flat drawing is kept');
  await t.evaluate(`(document.getElementById('flatOn').click(), 1)`);
  check(await t.waitFor(`app.three() && getComputedStyle(document.getElementById('rig')).visibility === 'hidden'`, 30000), 'switched off: the 3D phone is back');
  if (t.logs.length) console.log('--- page ---\n' + t.logs.join('\n'));
  t.close();

  // ---- no WebGL ----
  const u = await iphone(env, '', true);
  check(await u.waitFor(`!document.getElementById('stage').classList.contains('wait3d')`, 10000) &&
    await u.evaluate(`!app.three() && !app.v3() && getComputedStyle(document.getElementById('rig')).visibility === 'visible'`), 'no WebGL: the 2D phone is the phone');
  await collect(u);
  await u.evaluate(`app.slide(true)`); await sleep(600);
  await u.tap('5');
  check(await u.waitFor(`all.some(s => /ui: key 5 down/.test(s))`, 3000), 'no WebGL: a tap on its 5 reaches the phone');
  await u.shot('phone3d-05-nogl');
  if (u.logs.length) console.log('--- page ---\n' + u.logs.join('\n'));
  u.close();
} catch (e) {
  check(false, 'the test ran: ' + (e.stack || e.message || e));
} finally {
  await env.stop();
}
process.exit(summary());
