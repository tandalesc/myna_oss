// flip3d.mjs: the Myna flip drawn in 3D on the phone page (core/web/phone3d.js, the main view), in headless Chrome, with
// no relay.
//
//   MYNA_PYODIDE=DIR node myna/web/test/flip3d.mjs       (after make -C myna/firmware and sh native/core/build.sh)
//
// Steps: the flip starts with its lid open and the 3D phone is the phone (the 2D drawing laid out but hidden); at rest it
// faces front with the lid at its true open angle, the base exactly where the 2D layout puts it (the outline on a magenta
// stage); the words over the screen lie on the 3D screen; the lid closed and opened with the page's slide button turns frame
// by frame with the page's spring and the switch reaches the phone; a finger on a key of the 3D keypad presses it and the
// key sinks while held; a swipe down the lid shuts it and one up opens it; a sideways drag turns the phone and it springs
// back to the front when let go; the turn button turns it, a side key pressed in its side reaches the phone, the button again
// brings it back to the front: the 3D phone stays (no swap). Exit status 0 when every step passed. Environment: lib.mjs;
// SHOTS=DIR keeps the pictures.
// SPDX-License-Identifier: MIT
import { inflateSync } from 'node:zlib';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { start, tab, check, summary, sleep } from './lib.mjs';

// An 8-bit RGB(A) PNG (what Chrome gives) to pixels.
function png(b) {
  let o = 8, w, h, ct;
  const idat = [];
  while (o < b.length) {
    const len = b.readUInt32BE(o), type = b.toString('latin1', o + 4, o + 8), d = b.subarray(o + 8, o + 8 + len);
    if (type === 'IHDR') { w = d.readUInt32BE(0); h = d.readUInt32BE(4); ct = d[9]; } else if (type === 'IDAT') idat.push(d);
    o += 12 + len;
  }
  const n = ct === 6 ? 4 : 3, raw = inflateSync(Buffer.concat(idat)), s = w * n, px = Buffer.alloc(h * s);
  for (let y = 0; y < h; y++) {
    const f = raw[y * (s + 1)];
    for (let x = 0; x < s; x++) {
      const a = x >= n ? px[y * s + x - n] : 0, u = y ? px[(y - 1) * s + x] : 0, c = x >= n && y ? px[(y - 1) * s + x - n] : 0;
      let v = raw[y * (s + 1) + 1 + x];
      if (f === 1) v += a; else if (f === 2) v += u; else if (f === 3) v += (a + u) >> 1;
      else if (f === 4) { const p = a + u - c, pa = Math.abs(p - a), pb = Math.abs(p - u), pc = Math.abs(p - c); v += pa <= pb && pa <= pc ? a : pb <= pc ? u : c; }
      px[y * s + x] = v & 255;
    }
  }
  return { w, h, at: (x, y) => { const i = (y * w + x) * n; return [px[i], px[i + 1], px[i + 2]]; } };
}

const env = await start();
try {
  const t = await tab(env.cdp);
  const shot = async keep => {
    const b = Buffer.from((await t.send('Page.captureScreenshot', { format: 'png' })).data, 'base64');
    if (keep && process.env.SHOTS) { mkdirSync(process.env.SHOTS, { recursive: true }); writeFileSync(join(process.env.SHOTS, keep + '.png'), b); }
    return png(b);
  };
  await t.send('Emulation.setDeviceMetricsOverride', { width: 520, height: 860, deviceScaleFactor: 2, mobile: false });
  await t.go(env.base + '?p=myna_flip');
  await sleep(1000);
  const up = await t.waitFor(`window.app && (app.frames > 0 || app.error)`, 240000) && !(await t.evaluate('app.error'));
  check(up, 'the flip starts: ' + (await t.evaluate('app.error') || 'first picture'));
  check(await t.waitLine(/\blid: open/, 10000) && await t.waitFor(`app.three() && app.v3().shown && getComputedStyle(app.v3().layer).opacity === '1'
    && getComputedStyle(document.getElementById('rig')).visibility === 'hidden' && !document.getElementById('turn').hidden`, 30000),
  'its lid is open and the 3D phone is the phone (the 2D drawing hidden, the turn button offered)');
  await sleep(500);
  const angle = () => t.evaluate(`(() => { const v = app.v3(), q = v.groups[v.m.joint.part].quaternion; return +(2 * Math.acos(Math.min(1, Math.abs(q.w))) * 180 / Math.PI).toFixed(2); })()`);

  // at rest: facing front, the lid at its open angle, the base where the 2D layout has it: its sides and its free end on a
  // magenta stage (2 device pixels a CSS pixel)
  const rest = await angle();
  const box = await t.evaluate(`(() => { const v = app.v3(), m = v.m, V = v.view, r = v.container.getBoundingClientRect();
    const X = u => r.left + V.x + u * V.k, Y = w => r.top + V.y + w * V.k;
    return { l: X(m.br[0]), r: X(m.br[0] + m.br[2]), b: Y(m.br[1] + m.T + m.br[3]), mid: Y(m.br[1] + m.T + m.br[3] * 0.6), cx: X(m.br[0] + m.br[2] / 2), yaw: v.yaw, pitch: v.pitch }; })()`);
  await t.evaluate(`(document.getElementById('stage').style.background = '#ff00ff', 1)`);
  await sleep(300);
  const c = await shot('flip3d-01-rest');
  await t.evaluate(`(document.getElementById('stage').style.background = '', 1)`);
  // the stage: magenta, darker in the phone's shadow (no part of the phone is that colour)
  const bg = (x, y) => { const q = c.at(Math.round(x * 2), Math.round(y * 2)); return q[0] > 1.8 * q[1] + 50 && q[2] > 1.8 * q[1] + 50 && Math.abs(q[0] - q[2]) < 50; };
  const edge = (x0, y0, dx, dy) => { let x = x0, y = y0; for (let i = 0; i < 1600 && !bg(x, y); i++) { x += dx; y += dy; } return dx ? x : y; };
  // the shadow lies behind, lower and wider: the side walls are found at the middle of the base, from its middle out
  const left = edge(box.cx, box.mid, -0.25, 0), right = edge(box.cx, box.mid, 0.25, 0);
  const err = Math.max(Math.abs(left - box.l), Math.abs(right - box.r));
  check(Math.abs(rest - 162) < 0.5 && box.yaw === 0 && box.pitch === 0 && err < 2,
    `at rest it faces front, the lid at ${rest} degrees, the base's sides ${left.toFixed(1)} and ${right.toFixed(1)} CSS px where the layout has ${box.l.toFixed(1)} and ${box.r.toFixed(1)} (true size)`);

  // the words over the screen, while the phone starts, lie on the 3D screen
  const veil = await t.evaluate(`(() => { const e = document.getElementById('veil'); e.classList.remove('gone'); app.v3().render();
    const b = e.getBoundingClientRect(), q = app.v3().screenQuad().pts, xs = q.map(p => p[0]), ys = q.map(p => p[1]);
    const d = Math.max(Math.abs(b.left - Math.min(...xs)), Math.abs(b.right - Math.max(...xs)), Math.abs(b.top - Math.min(...ys)), Math.abs(b.bottom - Math.max(...ys)));
    e.classList.add('gone'); return { d: +d.toFixed(2), parent: e.parentNode.id }; })()`);
  check(veil.d < 1 && veil.parent === 'stage', `the words over the screen lie on the 3D screen (within ${veil.d} px)`);

  // every animation frame from here: where the lid is
  await t.evaluate(`(window.__log = [], window.__on = true, (function f() { if (!window.__on) return; requestAnimationFrame(now => {
    const v = app.v3(); __log.push({ t: +now.toFixed(1), p: +v.p.toFixed(4), renders: v.stat.renders }); f(); }); })(), 1)`);
  // the lid closed and opened with the page's slide button, with the page's spring (motion allowed for this part)
  await t.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });
  let from = await t.evaluate('__log.length');
  await t.evaluate(`document.getElementById('slide').click()`);
  check(await t.waitLine(/ui: lid closed: asleep/, 6000) && await t.waitFor(`app.v3().p === 0`, 3000), 'closed with the slide button: the switch reaches the phone, it sleeps');
  await sleep(300);
  let steps = await t.evaluate(`[...new Set(__log.slice(${from}).map(f => f.p))].length`);
  const shut = await angle();
  check(steps > 8 && shut < 0.5, `the lid turned shut on its hinge in ${steps} frames of the page's spring (now at ${shut} degrees)`);
  await t.shot('flip3d-02-closed');
  from = await t.evaluate('__log.length');
  await t.evaluate(`document.getElementById('slide').click()`);
  check(await t.waitLine(/ui: lid open: awake/, 6000) && await t.waitFor(`app.v3().p === 1`, 3000), 'opened again: the phone wakes');
  await sleep(300);
  steps = await t.evaluate(`[...new Set(__log.slice(${from}).map(f => f.p))].length`);
  const open = await angle();
  check(steps > 8 && Math.abs(open - 162) < 0.5, `the lid swung open in ${steps} frames and stands at ${open} degrees`);
  await t.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  await t.evaluate('(window.__on = false, 1)');

  // a finger on the 5 of the 3D keypad: the key goes to the phone and its cap sinks while it is held
  const sunk = name => t.evaluate(`(() => { const v = app.v3(), c = v.capOf[${JSON.stringify(name)}], A = c.mesh.geometry.attributes.position.array; let z = -1e9;
    for (let i = c.range[0]; i < c.range[1]; i++) z = Math.max(z, A[i * 3 + 2]); return z; })()`);
  const lines = () => t.evaluate('app.lines.length');
  const z0 = await sunk('5');
  let n0 = await lines();
  const [x5, y5] = await t.evaluate(`app.where('5')`);
  await t.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: x5, y: y5, button: 'left', clickCount: 1 }); await sleep(150);
  const z1 = await sunk('5');
  await t.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x5, y: y5, button: 'left', clickCount: 1 }); await sleep(300);
  const z2 = await sunk('5');
  check(await t.waitFor(`app.lines.slice(${n0}).some(s => /ui: key 5 down/.test(s))`, 3000) && Math.abs(z0 - z1 - 0.3) < 0.01 && z2 === z0,
    `a finger on the 5 of the 3D keypad presses it; the key sinks ${(z0 - z1).toFixed(2)} mm while held and comes back`);
  await t.key('clear'); await t.key('end');

  // swipes on the lid: down shuts it, up opens it
  const drag = async (x0, y0, x1, y1) => {
    await t.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: x0, y: y0, button: 'left', clickCount: 1 });
    for (let i = 1; i <= 12; i++) { await t.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: x0 + (x1 - x0) * i / 12, y: y0 + (y1 - y0) * i / 12, button: 'left', buttons: 1 }); await sleep(16); }
    await t.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x1, y: y1, button: 'left', clickCount: 1 }); await sleep(400);
  };
  const lid = await t.evaluate(`app.v3().project(88, 60, 'moving')`);
  await drag(lid[0], lid[1], lid[0], lid[1] + 420);
  check(await t.waitFor(`app.v3().p === 0`, 3000) && await t.waitLine(/ui: lid closed: asleep/, 4000), 'a swipe down the lid shuts it');
  const out = await t.evaluate(`app.v3().project(88, 380, 'still')`);         // closed: the lid's outside, over the base
  await drag(out[0], out[1], out[0], out[1] - 420);
  check(await t.waitFor(`app.v3().p === 1`, 3000) && await t.waitLine(/ui: lid open: awake/, 4000), 'a swipe up opens it again');

  // a sideways drag across the face turns the phone; let go, it springs back to the front and stays the 3D phone
  const [gx, gy] = await t.evaluate(`app.v3().project(40, 100, 'moving')`);           // on the lid's glass
  await t.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: gx, y: gy, button: 'left', clickCount: 1 });
  for (let i = 1; i <= 12; i++) { await t.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: gx + 16 * i, y: gy, button: 'left', buttons: 1 }); await sleep(20); }
  const turned = await t.evaluate('({ active: app.v3().active, yaw: +app.v3().yaw.toFixed(3) })');
  await t.shot('flip3d-03-turning');
  await sleep(250);                                  // the finger rests before it lifts: no throw (a throw turns it over)
  await t.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: gx + 192, y: gy, button: 'left', clickCount: 1 });
  check(turned.active && Math.abs(turned.yaw) > 0.1 && await t.waitFor(`!app.v3().active && Math.abs(Math.sin(app.v3().yaw)) < 1e-6 && app.three() && !app.v3().layer.hidden`, 5000),
    `a sideways drag turns the phone (yaw ${turned.yaw}); let go, it springs back to the front, still in 3D`);

  // the turn button; the volume key in the right side pressed in 3D
  await t.evaluate(`document.getElementById('turn').click()`);
  check(await t.waitFor(`app.v3().active && !app.v3().target`, 8000), 'the turn button: the phone turns in 3D');
  await t.shot('flip3d-04-turned');
  await t.evaluate('app.v3().pose(-1.25, 0.1)');
  await sleep(300);
  n0 = await lines();
  const side = await t.evaluate(`(() => { const v = app.v3(), m = v.m, V = v.camera.position.constructor; v.render();
    const k = m.sideKeys.find(k => k.key === 'vol_up'), part = m.parts.find(p => !p.moving), mesh = v.meshes.find(x => x.userData.part === part.id);
    const at = new V(m.br[0] / m.upm + m.br[2] / m.upm + k.proud * 0.6, -(k.y[0] + k.y[1]) / 2 / m.upm, m.depth - (k.z[0] + k.z[1]) / 2);
    const q = mesh.localToWorld(at).project(v.camera), r = v.canvas.getBoundingClientRect(); return [r.left + (q.x + 1) / 2 * r.width, r.top + (1 - q.y) / 2 * r.height]; })()`);
  await t.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: side[0], y: side[1], button: 'left', clickCount: 1 }); await sleep(120);
  await t.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: side[0], y: side[1], button: 'left', clickCount: 1 }); await sleep(400);
  const vol = await t.waitFor(`app.lines.slice(${n0}).find(s => /ui: key vol_up (down|held)/.test(s)) || ''`, 3000);
  check(!!vol, 'a finger on the volume key in the side of the 3D phone presses it: ' + (vol || 'nothing').replace(/^.*\| /, ''));
  await t.evaluate(`document.getElementById('turn').click()`);
  check(await t.waitFor(`!app.v3().active && Math.abs(Math.sin(app.v3().yaw)) < 1e-6 && app.three() && getComputedStyle(app.v3().layer).opacity === '1'`, 8000),
    'the turn button again: back to the front, the 3D phone stays (no swap)');
  const stats = await t.evaluate('app.v3().stats()');
  console.log(`  3D: ${stats.calls} draw calls, ${stats.triangles} triangles, textures ${stats.textureMB} MB, render() CPU ${stats.cpuMsMean} ms (mean), pixel ratio ${stats.pixelRatio}`);
  if (t.logs.length) console.log('--- page ---\n' + t.logs.join('\n'));
  t.close();
} catch (e) {
  check(false, 'the test ran: ' + (e.stack || e.message || e));
} finally {
  await env.stop();
}
process.exit(summary());
