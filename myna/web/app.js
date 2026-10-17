// app.js: pick a phone, then hold it. The phone is drawn from its skin (native/devices/NAME/skin/) at its true size: the
// screen of the simulator lies in the skin's screen rectangle, every key area takes the finger, and a swipe on the face
// slides the phone open and closed. The phones are those with a firmware of our own (Myna: a profile with BOOT_ELF, listed
// in devices.json): the ELF file (open source, small) comes from the server at each start, the NAND starts blank, and the
// flash state the phone writes is kept in this browser (IndexedDB), under its blank chip. The phone itself runs in
// phone_worker.js. Texts: through the relay (myna/relay; config.json or ?relay= names it), or the modem stand-in's
// loopback network when there is no relay (a text comes back to the phone that sent it). A phone with no modem
// stand-in ("peer" empty) has no network. Diagnostic lines go to the server only with ?log=1 (myna/web/serve.py --log).
// SPDX-License-Identifier: MIT
'use strict';

const $ = id => document.getElementById(id);
const mb = n => (n / 1048576).toFixed(0) + ' MB';
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const A = window.app = { phones: [], phone: null, ready: false, running: false, frames: 0, emu: 0, rate: 0, error: '', skins: {} };
let worker = null, link = null, readyWait = null, stateKey = '', keyNames = null, last = null, lines = [];
const recent = [];
const calm = matchMedia('(prefers-reduced-motion: reduce)');
const ASKED = new URLSearchParams(location.search);
const standalone = navigator.standalone === true || matchMedia('(display-mode: standalone)').matches || matchMedia('(display-mode: fullscreen)').matches;
const iPhone = /iPhone|iPod/.test(navigator.userAgent);

// The lines name this phone's own number: they go to the server only when asked for (a development server, never a public one).
const LOG = ASKED.get('log') === '1';
let RELAY = ASKED.get('relay') || '';            // the text-message relay; else config.json's, read at start-up
function report(s) { if (!LOG) return; try { fetch('log', { method: 'POST', body: s, keepalive: true }).catch(() => {}); } catch (e) { /* no server log */ } }
// The line on the phone's dark screen while it is made ready. `said` is what the server log gets when it differs.
function status(s, said) { $('status').textContent = s; report(said || s); }
function fail(s) { A.error = s; $('error').textContent = s; $('veil').classList.remove('gone'); $('bar').hidden = true; $('again').hidden = false; report('ERROR ' + s); }
// The bar: a part of the whole way from the tap to the first picture; `wait` marks a step whose length is not known.
function progress(v, wait) {
  const bar = $('bar');
  bar.hidden = v === null;
  if (v === null) return;
  bar.classList.toggle('wait', !!wait);
  bar.firstElementChild.style.width = (clamp(v, 0, 1) * 100).toFixed(1) + '%';
  bar.setAttribute('aria-valuenow', Math.round(v * 100));
}
let toastTimer = 0;
function toast(s, ms) {
  const t = $('toast');
  t.textContent = s; t.hidden = false; void t.offsetWidth; t.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.classList.remove('on'); }, ms || 2600);
}

// ---- small things this browser remembers about the look (the phone's own data is in IndexedDB below) ----
const pref = {
  get(k, d) { try { const v = localStorage.getItem('phone-ui.' + k); return v === null ? d : v; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('phone-ui.' + k, v); } catch (e) { /* not kept */ } },
};

// ---- what this browser keeps: one store, string keys ----
const open = () => new Promise((res, rej) => {
  const q = indexedDB.open('myna-phone', 1);
  q.onupgradeneeded = () => q.result.createObjectStore('kv');
  q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error);
});
async function kv(mode, f) {
  const d = await open();
  return new Promise((res, rej) => {
    const tx = d.transaction('kv', mode), q = f(tx.objectStore('kv'));
    tx.oncomplete = () => { d.close(); res(q && q.result); }; tx.onerror = tx.onabort = () => { d.close(); rej(tx.error || new Error('aborted')); };
  });
}
const get = k => kv('readonly', s => s.get(k)).catch(() => undefined);
const put = (k, v) => kv('readwrite', s => s.put(v, k));
const del = k => kv('readwrite', s => s.delete(k)).catch(() => {});

// ---- the flash state: what the phone wrote to its NAND, kept here between visits ----
// The bar: the firmware takes it to UNPACKED, the simulator and the build to BUILT, the first picture ends it.
const UNPACKED = 0.8, BUILT = 0.92;
async function flashState() {
  const saved = await get(stateKey);
  if (saved && saved.bytes) { report(`flash state: saved here ${new Date(saved.when).toISOString()}`); return saved.bytes; }
  return null;
}
async function keep(bytes, why) {
  if (!stateKey || !bytes || !bytes.byteLength) return;
  try { await put(stateKey, { bytes, when: Date.now(), emu: A.emu }); report(`flash state kept (${why}, ${mb(bytes.byteLength)})`); }
  catch (e) { fail('The phone\'s memory could not be kept in this browser: ' + e); }
}

// ---- the skin: the pictures and where the screen and the keys are in them ----
// S is the skin of the phone on the stage, in picture pixels ("units") of its open view:
//   W, Ho  the picture; T the travel of the face; Hc = Ho - T, the height of the closed phone's picture
//   glass  the screen, on the face; faceKeys ride on the face, baseKeys stay on the back half
//   faceRect  the body of the face in the face's own picture; upm  units per millimetre
// A skin with "hinge" (and no "slide") is a flip: T is then the open picture's height less the closed one's, the face is the
// lid (it turns about the line y = axis of the open picture), and the closed picture is the lid's outside (flip below).
let S = null;
async function skinOf(p) {
  if (A.skins[p.name]) return A.skins[p.name];
  const res = await fetch(`skin/${p.name}/skin.json`);
  if (!res.ok) throw new Error('the server has no drawing of this phone');
  const skin = await res.json(), views = {};
  for (const v of skin.views) views[v.id] = v;
  const sl = skin.slide && views[skin.slide.open] && views[skin.slide.closed] ? skin.slide : null;
  const hg = !sl && skin.hinge && views[skin.hinge.open] && views[skin.hinge.closed] && skin.hinge.axis_y > 0 ? skin.hinge : null;
  const vo = sl ? views[sl.open] : hg ? views[hg.open] : views[skin.default_view] || skin.views[0], vc = sl ? views[sl.closed] : hg ? views[hg.closed] : vo;
  const T = sl ? sl.travel : hg ? vo.size[1] - vc.size[1] : 0, body = skin.body && skin.body.rect && skin.body.mm ? skin.body : null;
  const s = { name: p.name, skin, sl, T, W: vo.size[0], Ho: vo.size[1], Hc: vo.size[1] - T, glass: vo.glass, panel: skin.panel,
    closedImage: vc.image, baseImage: sl ? sl.base : vo.image, faceImage: sl ? sl.face : '',
    faceRect: body && (!sl || body.view === sl.closed) ? body.rect : [0, 0, vc.size[0], vc.size[1]],
    upm: body ? body.rect[2] / body.mm[0] : vo.glass[2] / (skin.panel.w * 25.4 / 160), mm: body ? body.mm : null,
    faceKeys: {}, baseKeys: {}, hidden: new Set() };
  for (const [name, r] of Object.entries(vo.keys || {})) (sl && name in (vc.keys || {}) ? s.faceKeys : s.baseKeys)[name] = r;
  if (!sl) { s.faceKeys = s.baseKeys; s.baseKeys = {}; }
  // A key of the back half whose middle lies under the closed face cannot be reached while the phone is closed.
  const f = s.faceRect;
  for (const [name, r] of Object.entries(s.baseKeys)) {
    const cx = r[0] + r[2] / 2, cy = r[1] + r[3] / 2 - T;
    if (cx > f[0] && cx < f[0] + f[2] && cy > f[1] && cy < f[1] + f[3]) s.hidden.add(name);
  }
  // Where the face ends, in its own picture. The closed body is the face only when nothing of the back half shows under
  // it: the Myna chin slider's chin stays in view, so its closed body reaches below the face, and the open phone's top
  // row of keys (1 2 3) was taken as under the face: no finger reached it. The face uncovers every key it hides when closed, so it ends at the latest
  // at the middle of the highest of them. (A slider whose closed body is its face: the body's lower edge.)
  s.faceBottom = f[1] + f[3];
  for (const name of s.hidden) { const r = s.baseKeys[name]; s.faceBottom = Math.min(s.faceBottom, r[1] + r[3] / 2); }
  const ids = (skin.variants || []).map(v => v.id);
  s.variant = pref.get('variant.' + p.name, skin.default_variant || ids[0] || '');
  if (!ids.includes(s.variant)) s.variant = skin.default_variant || ids[0] || '';
  if (hg) flipSkin(s, hg, vo, vc);
  return A.skins[p.name] = s;
}
// The address of a picture: the colour's id goes before the file ending.
function picture(s, name) {
  const skin = s.skin, ids = (skin.variants || []).map(v => v.id), ending = /(\.[a-z0-9]+)$/i;
  if (s.variant && s.variant !== (skin.default_variant || ids[0])) name = name.replace(ending, '.' + s.variant + '$1');
  return `skin/${s.name}/${name}`;
}

// ---- the true size ----
// CSS pixels per millimetre cannot be asked of a browser; this is the estimate by the kind of device, times the user's correction.
function estimate() {
  const ua = navigator.userAgent, dpr = devicePixelRatio || 1;
  let ppi = 96, what = 'a display of 96 CSS pixels per inch';
  if (/iPhone|iPod/.test(ua)) { ppi = dpr >= 3 ? 460 / 3 : 163; what = dpr >= 3 ? 'an iPhone display of 460 pixels per inch at 3x' : 'an iPhone display of 326 pixels per inch at 2x'; }
  else if (/iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) { ppi = 132; what = 'an iPad display of 264 pixels per inch at 2x'; }
  else if (/Android/.test(ua)) { ppi = 160; what = 'an Android display of 160 units per inch'; }
  else if (/Macintosh/.test(ua) && dpr >= 2) { ppi = screen.width <= 1800 ? 127 : 109; what = `a Mac display of ${ppi} points per inch`; }
  return { pxmm: ppi / 25.4, what };
}
const EST = estimate();
let cal = clamp(parseFloat(pref.get('cal', '1')) || 1, 0.7, 1.4);
const pxmm = () => EST.pxmm * cal;

// ---- the stage: where the phone is ----
// L.p is the position of the slide, 0 closed to 1 open. The two layers are laid out at the scale L.kL (CSS pixels per
// unit) and, while the slide moves, shown at another scale through a transform; when it rests they are laid out again.
const L = { p: 0, kL: 1, k: 1, x: 0, y: 0, mode: pref.get('size', 'true') === 'fit' ? 'fit' : 'true', moving: false };
const rig = $('rig'), base = $('base'), face = $('face'), glass = $('glass'), cv = $('screen');
const src = document.createElement('canvas');        // the last picture of the phone, at its own size
let havePicture = false;
const keyEls = {};

// The height there really is: the window (innerHeight). A home-screen app on an iPhone can report a window that is short by
// the status bar; what lies below it is cut off, so the window is what the phone is fitted to. With ?log=1 every new set
// of numbers goes to the server log.
let fitSaid = '';
function measure(why) {
  document.documentElement.style.setProperty('--stage-h', innerHeight + 'px');
  if (!LOG) return;
  const vv = window.visualViewport, n = v => Math.round(v * 10) / 10;
  let s = `inner ${innerWidth}x${innerHeight}, visual ${vv ? `${n(vv.width)}x${n(vv.height)} at ${n(vv.offsetTop)}` : '?'}, display ${screen.width}x${screen.height}, ` +
    `${standalone ? 'home-screen app' : 'in the browser'}, stage ${$('stage').clientWidth}x${$('stage').clientHeight}`;
  if (S) {
    const a = room(), f = S.faceRect, one = pxmm() / S.upm, line = p => { const k = scaleAt(p, a); return `${Math.round((f[3] + S.T * p) * k)} px at ${Math.round(k / one * 100)}%`; };
    s += `, room ${Math.round(a.w)}x${Math.round(a.h)}; ${S.name} closed ${line(0)}, open ${line(1)} (${L.mode})`;
  }
  if (s !== fitSaid) { fitSaid = s; report(`fit (${why}): ${s}`); }
}
function room() {
  const st = $('stage'), cs = getComputedStyle(st);
  const l = parseFloat(cs.paddingLeft) || 0, r = parseFloat(cs.paddingRight) || 0, t = parseFloat(cs.paddingTop) || 0, b = parseFloat(cs.paddingBottom) || 0;
  return { x: l, y: t, w: Math.max(50, st.clientWidth - l - r), h: Math.max(50, st.clientHeight - t - b) };
}
// The scale at slide position p. True size: 1 mm of the phone is 1 mm of the display, made smaller only as far as the
// phone at that position does not fit. Fit: the largest scale at which the open phone fits, the same at every position.
function scaleAt(p, a) {
  const kTrue = pxmm() / S.upm;
  const f = S.faceRect;                               // the body of the phone is what must fit; the empty rim of the picture may go over the edge
  if (L.mode === 'fit') return Math.min(a.w / f[2], a.h / (f[3] + S.T), kTrue * 3);
  return Math.min(kTrue, a.w / f[2], a.h / (f[3] + (S.hinge ? flipGrow(p) : S.T * clamp(p, 0, 1))));
}
function place() {
  const a = room(), p = L.p, k = L.k = scaleAt(p, a);
  const f = S.faceRect, mid = f[1] + S.T + f[3] / 2 - (S.hinge ? flipGrow(p) : S.T * p) / 2;      // the middle of the phone as it is now, in units from the top of the open picture
  let x = a.x + a.w / 2 - (f[0] + f[2] / 2) * k, y = a.y + a.h / 2 - mid * k;
  if (!L.moving) { const d = devicePixelRatio || 1; x = Math.round(x * d) / d; y = Math.round(y * d) / d; }
  L.x = x; L.y = y;
  rig.style.transform = `translate(${x}px, ${y}px) scale(${k / L.kL})`;
  if (S.hinge) flipPose(p, mid);
  else face.style.transform = $('shFace').style.transform = `translateY(${S.T * (1 - p) * L.kL}px)`;
  $('shTouch').style.opacity = S.sl ? clamp(p * 5, 0, 1) * 0.9 : 0;       // closed, the face lies on nothing that shows
  if (v3) { v3.setSlide(p); v3.setView({ k, x, y }); }
  ruler(a);
}
const px = (el, r, k) => Object.assign(el.style, { left: r[0] * k + 'px', top: r[1] * k + 'px', width: r[2] * k + 'px', height: r[3] * k + 'px' });
function layout(why) {
  if (!S) return;
  measure(typeof why === 'string' ? why : 'layout');
  const k = L.kL = scaleAt(L.p, room());
  for (const el of [rig, base, face]) { el.style.width = S.W * k + 'px'; el.style.height = S.Ho * k + 'px'; }
  const f = S.faceRect;
  const all = [-PAD, -PAD, S.W + 2 * PAD, S.Ho + 2 * PAD];
  px($('shBase'), all, k); px($('shTouch'), all, k);
  px($('shFaceClip'), [-PAD, -PAD, S.W + 2 * PAD, PAD + S.T + f[1] + FADE], k);
  px($('shFace'), [0, 0, S.W + 2 * PAD, S.Ho + 2 * PAD], k);
  $('shFaceClip').style.setProperty('--fade', FADE * k + 'px');
  px(glass, S.glass, k);
  for (const [name, el] of Object.entries(keyEls)) px(el, S.faceKeys[name] || S.baseKeys[name], k);
  if (S.hinge) flipLayout(k);
  place();
  screenSize();
  sizeText();
}
function sizeText() {
  const part = L.k / (pxmm() / S.upm);
  $('sizeText').textContent = Math.abs(part - 1) < 0.005 ? '1:1' : Math.round(part * 100) + '%';
  $('size').setAttribute('aria-label', (Math.abs(part - 1) < 0.005 ? 'Shown at true size' : `Shown at ${Math.round(part * 100)}% of true size`) + '. Change the size');
  for (const b of document.querySelectorAll('[data-size]')) b.setAttribute('aria-pressed', String(b.dataset.size === L.mode));
  $('sizeNote').textContent = `True size takes this screen for ${EST.what}` + (cal !== 1 ? `, corrected by ${Math.round(cal * 100)}%` : '') +
    `. The open phone is made smaller when it is taller than the screen.`;
  $('calBar').style.width = 53.98 * pxmm() + 'px';
}

// The ruler beside the phone: millimetres at the scale of the drawing, from the top of the phone to its lower end.
let rulerOn = pref.get('ruler', '') === '1';
function ruler(a) {
  const c = $('ruler'), d = devicePixelRatio || 1, st = $('stage');
  c.hidden = !rulerOn;
  if (!rulerOn) return;
  const w = 34, h = st.clientHeight;
  if (c.width !== Math.round(w * d) || c.height !== Math.round(h * d)) { c.width = Math.round(w * d); c.height = Math.round(h * d); c.style.width = w + 'px'; c.style.height = h + 'px'; }
  const f = S.faceRect, p = clamp(L.p, 0, 1), k = L.k;
  const left = L.x + f[0] * k - w - 5;
  c.style.transform = `translateX(${Math.max(0, left)}px)`;
  const g = c.getContext('2d');
  g.setTransform(d, 0, 0, d, 0, 0); g.clearRect(0, 0, w, h);
  if (left < -6) return;                                // no room beside the phone
  const cs = getComputedStyle(document.documentElement), ink = cs.getPropertyValue('--graphite').trim(), sig = cs.getPropertyValue('--signal').trim();
  const grown = S.hinge ? flipGrow(p) : S.T * p, top = L.y + (f[1] + S.T - grown) * k, mm = k * S.upm, total = (f[3] + grown) / S.upm;
  g.font = '500 9px system-ui, -apple-system, sans-serif'; g.textAlign = 'right'; g.textBaseline = 'middle';
  g.strokeStyle = ink; g.fillStyle = ink; g.lineWidth = 1 / d * Math.max(1, Math.round(d / 2));
  const line = (y, len) => { const yy = Math.round(y * d) / d + 0.5 / d; g.beginPath(); g.moveTo(w, yy); g.lineTo(w - len, yy); g.stroke(); };
  g.globalAlpha = 0.55;
  for (let i = 0; i <= Math.floor(total); i++) {
    const y = top + i * mm;
    if (mm < 3 && i % 5) continue;
    line(y, i % 10 === 0 ? 10 : i % 5 === 0 ? 7 : 4);
  }
  g.globalAlpha = 0.9;
  for (let i = 10; i <= total - 4; i += 10) g.fillText(String(i), w - 13, top + i * mm + 0.5);
  g.strokeStyle = sig; g.fillStyle = sig; g.globalAlpha = 1; g.lineWidth = 1.5;
  line(top + total * mm, 14);
  g.font = '600 10px system-ui, -apple-system, sans-serif';
  g.fillText(String(Math.round(total)), w - 13, top + total * mm - 7);
  g.fillStyle = ink; g.font = '500 9px system-ui, -apple-system, sans-serif'; g.globalAlpha = 0.9;
  g.fillText('mm', w - 13, top + 1);
}

// ---- the screen ----
// Sharp bilinear, as the desktop viewer does: the picture is enlarged by a whole number with nearest neighbour (the smallest
// one that gives at least the device pixels of the glass), and the browser scales that to the glass smoothly.
function screenSize() {
  const n = clamp(Math.ceil(S.glass[2] * L.kL * (devicePixelRatio || 1) / S.panel.w - 0.02), 1, 6);
  const w = (src.width || S.panel.w) * n, h = (src.height || S.panel.h) * n;
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  blit();
}
function blit() {
  if (!havePicture || three) return;               // the 3D phone shows the picture itself
  const c = cv.getContext('2d');
  c.imageSmoothingEnabled = false; c.drawImage(src, 0, 0, cv.width, cv.height);
}
function draw(m) {
  const fresh = src.width !== m.w || src.height !== m.h || !havePicture;
  if (src.width !== m.w || src.height !== m.h) { src.width = m.w; src.height = m.h; }
  src.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(m.rgba), m.w, m.h), 0, 0);
  havePicture = true;
  if (fresh) screenSize(); else blit();
  if (v3) v3.frame();
}

// ---- the slide ----
let slideSent = 'closed', anim = 0;
const slideState = () => (L.p > 0.5 ? 'open' : 'closed');
function tellSlide() {
  const st = slideState();
  $('slide').setAttribute('aria-pressed', String(st === 'open'));
  $('slide').setAttribute('aria-label', S.hinge ? (st === 'open' ? 'Close the lid' : 'Open the lid') : st === 'open' ? 'Slide the phone closed' : 'Slide the phone open');
  if (!A.running || !(S.sl || S.hinge) || st === slideSent) return;
  slideSent = st;
  worker.postMessage({ t: 'input', command: JSON.stringify({ switch: 'slide', state: st }) });
  report('slide ' + st);
  if (st === 'closed') for (const name of [...down.keys()]) if (S.hidden.has(name)) { down.delete(name); mark(name, false); sendKey(name, false); }
}
function rest(p) {
  cancelAnimationFrame(anim); anim = 0;
  L.p = p; L.moving = false; rig.classList.remove('held');
  layout(); tellSlide();
}
// The face runs to its end as a spring-loaded slide does: pulled by the spring, stopped by the end stop with a small bounce.
// A flip's lid is heavier and softer: it swings a little past open on its hinge spring, and bounces on the keypad when it shuts.
function run(to, v) {
  cancelAnimationFrame(anim);
  if (!S.sl && !S.hinge) return;
  if (calm.matches) return rest(to);
  L.moving = true;
  let x = L.p, t0 = performance.now();
  const W = S.hinge ? 20 : 30, Z = S.hinge ? 0.7 : 0.86, stop1 = !S.hinge;
  const step = now => {
    let dt = Math.min(0.05, (now - t0) / 1000); t0 = now;
    for (; dt > 0; dt -= 0.004) {
      const h = Math.min(0.004, dt);
      v += (-W * W * (x - to) - 2 * Z * W * v) * h; x += v * h;
      if ((to === 1 && x > 1 && stop1) || (to === 0 && x < 0)) { x = to; v = -v * 0.3; }
    }
    if (Math.abs(x - to) < 0.002 && Math.abs(v) < 0.05) return rest(to);
    L.p = x; place();
    anim = requestAnimationFrame(step);
  };
  anim = requestAnimationFrame(step);
}
function toggleSlide() { if (S && (S.sl || S.hinge)) { pref.set('slid', '1'); run(slideState() === 'open' && L.p > 0.5 ? 0 : 1, 0); } }
A.slide = to => run(to ? 1 : 0, 0);
// The slide (a flip's lid) held part of the way, as a finger holds it, for tests and pictures; A.slide() lets it go.
A.hold = p => { cancelAnimationFrame(anim); anim = 0; L.p = p; L.moving = true; place(); };

// ---- the flip: a lid on a hinge ----
// The skin's "hinge" block names the closed and open views, the pictures of the lid (its inner face, with the screen) and of
// the base (the keypad half), both in the open picture's frame, a picture drawn over both at the hinge (barrel, optional),
// the lid's outside (lid_back, optional: in the closed picture's frame, default the closed picture) and the hinge's line
// (axis_y, in the open picture). Without lid and base the open picture is cut at the line. L.p is the lid's position: the
// angle between lid and base is 180 x p degrees as drawn (the open picture shows the lid flat; open_deg is for 3D). The lid
// turns about the line in CSS 3D, toward the eye, with the eye over the middle of the phone; past 90 degrees its back shows
// the closed picture. The base does not move. Keys answer only with the lid open; a key whose middle is above the line is on
// the lid. The switch is the slide's ("slide": the same switch on the same board).
const FLIP_EYE = 1100;                     // the eye's distance in units (about 31 cm at 3.5 units a millimetre)
function flipSkin(s, hg, vo, vc) {
  s.hinge = hg; s.axis = hg.axis_y;
  s.baseImage = hg.base || vo.image; s.faceImage = hg.lid || vo.image; s.cut = !hg.base || !hg.lid;
  s.lidBackImage = hg.lid_back || vc.image; s.barrelImage = hg.barrel || '';
  s.lidLen = s.axis - s.faceRect[1];        // the lid open: from its free end (the top of the body) to the line
  s.faceKeys = {}; s.baseKeys = {};
  for (const [name, r] of Object.entries(vo.keys || {})) (r[1] + r[3] / 2 < s.axis ? s.faceKeys : s.baseKeys)[name] = r;
  s.hidden = new Set([...Object.keys(s.faceKeys), ...Object.keys(s.baseKeys)]);       // closed, the lid covers every key
  s.faceBottom = s.faceRect[1] + s.faceRect[3];
}
// How much the phone at p is taller than closed (0 .. T): the lid's free end against the top of the closed phone.
function flipGrow(p) {
  const top = S.axis - S.lidLen * Math.cos(Math.PI * (1 - clamp(p, 0, 1)));
  return clamp(S.T + S.faceRect[1] - top, 0, S.T);
}
function flipPose(p, mid) {
  const deg = 180 * (1 - p), c = Math.cos(deg * Math.PI / 180);
  face.style.transform = `rotateX(${(-deg).toFixed(3)}deg)`;
  rig.style.perspectiveOrigin = `${(S.W / 2 * L.kL).toFixed(1)}px ${(mid * L.kL).toFixed(1)}px`;
  $('shFace').style.transform = '';
  $('shFace').style.opacity = clamp((c - 0.9) * 10, 0, 1);      // the open lid's shadow on the paper: gone once it rises 25 degrees
}
function flipLayout(k) {
  face.style.transformOrigin = `${S.W * k / 2}px ${S.axis * k}px`;
  rig.style.perspective = FLIP_EYE * k + 'px';
  const back = $('lidBack'), img = back.querySelector('img'), ac = S.axis - S.T;      // the line in the closed picture
  px(back, [0, S.axis, S.W, S.Ho - S.axis], k);
  Object.assign(img.style, { top: -ac * k + 'px', width: S.W * k + 'px', height: (S.Ho - S.T) * k + 'px' });
  const bar = $('barrel'); bar.style.width = S.W * k + 'px'; bar.style.height = S.Ho * k + 'px';
  px($('shFaceClip'), [-PAD, -PAD, S.W + 2 * PAD, PAD + S.axis], k);
  $('shFaceClip').style.setProperty('--fade', '0px');
  // no layers of their own: the open picture cut at the line
  face.querySelector('img').style.clipPath = S.cut ? `inset(0 0 ${(S.Ho - S.axis) * k}px 0)` : '';
  base.querySelector('img').style.clipPath = S.cut ? `inset(${S.axis * k}px 0 0 0)` : '';
}
function flipPaint() {
  $('lidBack').querySelector('img').src = picture(S, S.lidBackImage);
  const b = $('barrel').querySelector('img');
  b.hidden = !S.barrelImage; if (S.barrelImage) b.src = picture(S, S.barrelImage);
}
// The flip's parts on the stage: the lid's back inside the lid, the barrel over everything. A flip starts open: its screen
// (and the page's words on it while the phone starts) is on the inside of the lid.
function flipStage() {
  rig.classList.toggle('flip', !!S.hinge);
  for (const id of ['lidBack', 'barrel']) { const el = $(id); if (el) el.hidden = !S.hinge; }
  if (!S.hinge) return;
  if (!$('lidBack')) {
    const back = document.createElement('div'); back.id = 'lidBack'; back.append(Object.assign(document.createElement('img'), { alt: '', draggable: false }));
    face.append(back);
    const bar = document.createElement('div'); bar.id = 'barrel'; bar.className = 'layer'; bar.append(Object.assign(document.createElement('img'), { alt: '', draggable: false }));
    rig.append(bar);
  }
  L.p = 1;
}
// What is under a finger on a flip: with the lid open a key (of either half), else the lid to swipe; closed, the lid.
function flipUnder(cx, cy) {
  const k = L.k, [u, v] = at(cx, cy, 'still'), f = S.faceRect, open = L.p > 0.98 && !L.moving;
  const top = open ? f[1] : S.T + f[1], onPhone = u >= f[0] && u <= f[0] + f[2] && v >= top && v <= S.T + f[1] + f[3];
  if (open) {
    // the 3D lid stands at its own angle: a point on it is found on its face (the base's keys on the base's)
    const [ul, vl] = three ? at(cx, cy, 'moving') : [u, v];
    let best = null, bd = Infinity;
    const slack = Math.max(2, 5 / k);
    for (const [set, x, y] of [[S.faceKeys, ul, vl], [S.baseKeys, u, v]]) for (const [name, r] of Object.entries(set)) {
      const d = Math.hypot(Math.max(r[0] - x, 0, x - r[0] - r[2]), Math.max(r[1] - y, 0, y - r[1] - r[3])), thin = Math.min(r[2], r[3]) < 8;
      if (d <= (onPhone || !thin ? slack : Math.max(slack, 14 / k)) && d < bd) { best = name; bd = d; }
    }
    if (best) return { key: best };
    if (three) return ul >= f[0] && ul <= f[0] + f[2] && vl >= f[1] && vl <= S.axis ? { face: vl } : null;
    return onPhone && v <= S.axis ? { face: v } : null;
  }
  return onPhone ? { face: v } : null;
}
// The lid's position for a finger at the height y of the page: the point it took (at d.grab, units in the open picture) stays
// under the finger as the lid turns, measured from where the drag took hold; past the ends the lid gives a little.
function flipFor(d, y) {
  if (d.r === undefined) { d.r = Math.max(24, Math.abs(d.grab - S.axis)); d.yh = y; d.kh = L.k; d.ch = Math.cos(Math.PI * (1 - clamp(L.p, 0, 1))); }
  const c = d.ch + (d.yh - y) / d.kh / d.r, over = e => 0.05 * (1 - Math.exp(-e * d.r * d.kh / 60));
  if (c > 1) return 1 + over(c - 1);
  if (c < -1) return -over(-1 - c);
  return 1 - Math.acos(c) / Math.PI;
}

// ---- fingers on the phone ----
// One listener on the phone finds what is under each finger: a key (pressed until that finger lifts) or the face (a drag
// that slides it). The key areas are small at true size, so a touch a little beside a key still takes the nearest one.
// The tick under the finger. Where the browser can vibrate, it does. Safari on an iPhone cannot, but it ticks when a switch
// is toggled: a label with a switch inside is made, put into the document, clicked and removed (the form of the trick that
// is known to work). Safari wants this inside an event that counts as the user's action: the release of a finger does, the
// touch going down may not, so keys tick at both. The first ticks go to the server log with their path and their event.
let feel = pref.get('feel', '1') === '1';
const canFeel = typeof navigator.vibrate === 'function' || /iPhone|iPod|iPad/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
const canVibrate = typeof navigator.vibrate === 'function';
let ticks = 0;
function tick(strong, from) {
  if (!feel) return;
  let path = 'vibrate';
  try {
    if (canVibrate) navigator.vibrate(strong ? 18 : 8);
    else {
      path = 'switch';
      for (let i = 0; i < (strong ? 2 : 1); i++) {
        const label = document.createElement('label'), input = document.createElement('input');
        label.ariaHidden = 'true'; label.style.display = 'none';
        input.type = 'checkbox'; input.setAttribute('switch', '');
        label.appendChild(input); document.head.appendChild(label); label.click(); document.head.removeChild(label);
      }
    }
  } catch (e) { path = 'failed (' + e + ')'; }
  if (ticks++ < 12 || from === 'test button') report(`tick: ${path} from ${from}${strong ? ', strong' : ''}`);
}
// The tick at the release of a finger is given in the touchend event, which follows the pointerup that lift() handles.
let upTick = null, touchEnded = 0;
function releaseTick(strong) {
  if (performance.now() - touchEnded < 80) tick(strong, 'pointerup after touchend'); else upTick = { strong, at: performance.now() };
}
const down = new Map();                    // key name -> how many fingers and keyboard keys hold it
const fingers = new Map();                 // pointer id -> key name, or the drag
let drag = null;
function mark(name, on) {
  const el = keyEls[name]; if (el) el.classList.toggle('down', on); for (const b of $('sideKeys').children) if (b.dataset.key === name) b.classList.toggle('down', on);
  if (v3) v3.setKey(name, on);                                       // the key sinks in the 3D view too
}
// A key goes to the worker with the moment it went down or up (performance.timeOrigin + now: the worker's clock reads the
// same), and the worker gives it to the phone at that moment of the phone's time: a tap stays a tap however busy the worker is.
const sendKey = (name, isDown) => worker.postMessage({ t: 'key', name, down: isDown, at: performance.timeOrigin + performance.now() });
function key(name, isDown) {
  if (!A.running || (keyNames && !keyNames.has(name))) return;
  const n = (down.get(name) || 0) + (isDown ? 1 : -1);
  if (n < 0) return;
  if (n) down.set(name, n); else down.delete(name);
  if ((isDown && n === 1) || (!isDown && n === 0)) { mark(name, isDown); sendKey(name, isDown); }
}
A.key = key;
// Every finger and keyboard key lets go: the page is hidden or loses the focus (a phone's home screen, another app), where a
// browser may never send the pointerup.
function letGo() {
  for (const [id, f] of fingers) if (typeof f === 'string') { fingers.delete(id); key(f, false); }
  for (const n of held.values()) key(n, false);
  held.clear();
  for (const b of $('sideKeys').children) if (b.dataset.on) { delete b.dataset.on; key(b.dataset.key, false); }
  if (v3) v3.release();
}
// The middle of a key on the display (for tests): on the 3D phone where its face shows it, else its area on the 2D one.
A.where = name => {
  if (three && v3) {
    const onFace = name in S.faceKeys, r = onFace ? S.faceKeys[name] : S.baseKeys[name], off = onFace && !S.hinge ? S.T * (1 - L.p) : 0;
    const q = v3.project(r[0] + r[2] / 2, r[1] + r[3] / 2 + off, onFace ? 'moving' : 'still');
    if (q) return q;
  }
  const r = keyEls[name].getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2];
};
A.lines = lines;                           // the phone's last console lines (for tests)
// Where a point of the display is on the phone, in units of the open picture (the 2D layout's): on the 3D phone, the point
// of the face of that part (the moving face or lid, or the still base) under it; on the 2D phone, the layout's.
function at(cx, cy, which) {
  const q = three && v3 ? v3.pick(cx, cy, which) : null;
  return q || [(cx - L.x) / L.k, (cy - L.y) / L.k];
}
function under(cx, cy) {
  if (S.hinge) return flipUnder(cx, cy);
  const k = L.k, [u, v] = at(cx, cy, 'moving'), [ub, vb] = three ? at(cx, cy, 'still') : [u, v], off = S.T * (1 - L.p), f = S.faceRect;
  const onFace = u >= f[0] && u <= f[0] + f[2] && v - off >= f[1] && v - off <= S.faceBottom;
  let best = null, bd = Infinity;
  const far = (r, dy, x, y) => Math.hypot(Math.max(r[0] - x, 0, x - r[0] - r[2]), Math.max(r[1] + dy - y, 0, y - r[1] - dy - r[3]));
  const slack = Math.max(2, 5 / k);
  for (const [name, r] of Object.entries(S.faceKeys)) { const d = far(r, off, u, v); if (d <= (onFace ? slack : 0) && d < bd) { best = name; bd = d; } }
  for (const [name, r] of Object.entries(S.baseKeys)) {
    const cxu = r[0] + r[2] / 2, cyu = r[1] + r[3] / 2 - off;
    if (cxu > f[0] && cxu < f[0] + f[2] && cyu > f[1] && cyu < S.faceBottom) continue;          // under the face now
    const d = far(r, 0, ub, vb), thin = Math.min(r[2], r[3]) < 8;
    if (d <= (onFace ? 0 : thin ? Math.max(slack, 14 / k) : slack) && d < bd) { best = name; bd = d; }
  }
  if (best) return { key: best };
  return onFace ? { face: v - off } : null;
}
// The slide position at which the point `grab` of the face (units from the top of its picture) is at the height y of the page.
function slideFor(grab, y) {
  const a = room(), at = p => a.y + a.h / 2 + scaleAt(p, a) * (grab - S.faceRect[1] - S.faceRect[3] / 2 - S.T * p / 2);
  let lo = 0, hi = 1;
  if (y >= at(0)) return -0.05 * (1 - Math.exp(-(y - at(0)) / 60));       // past the ends the face gives a little
  if (y <= at(1)) return 1 + 0.05 * (1 - Math.exp(-(at(1) - y) / 60));
  for (let i = 0; i < 22; i++) { const m = (lo + hi) / 2; if (at(m) > y) lo = m; else hi = m; }
  return (lo + hi) / 2;
}
// The listeners are on the whole stage: the thin keys on the edges of a phone are touched from beside it.
const stage = $('stage');
stage.addEventListener('pointerdown', e => {
  if (!S || (e.pointerType === 'mouse' && e.button !== 0) || e.target.closest('button')) return;
  e.preventDefault();
  const h = under(e.clientX, e.clientY);
  if (!h) { if (v3) v3.grab(e); return; }
  try { stage.setPointerCapture(e.pointerId); } catch (x) { /* fine */ }
  if (h.key) { const was = fingers.get(e.pointerId); if (typeof was === 'string') key(was, false);
    fingers.set(e.pointerId, h.key); if (e.pointerType !== 'mouse') tick(false, 'pointerdown'); key(h.key, true); return; }
  if (drag || (!S.sl && !S.hinge)) return;
  cancelAnimationFrame(anim); anim = 0;
  drag = { id: e.pointerId, grab: h.face, x0: e.clientX, y0: e.clientY, moved: false, from: L.p, trail: [[performance.now(), L.p]] };
  fingers.set(e.pointerId, drag);
});
stage.addEventListener('pointermove', e => {
  if (!drag || e.pointerId !== drag.id) return;
  if (!drag.moved) {
    const dx = Math.abs(e.clientX - drag.x0);
    if (v3 && dx > 12 && dx > 2 * Math.abs(e.clientY - drag.y0)) { fingers.delete(drag.id); drag = null; v3.grab(e); return; }
    if (Math.abs(e.clientY - drag.y0) < 6) return;
    drag.moved = true; L.moving = true; rig.classList.add('held');
    drag.grab += (e.clientY - drag.y0) / L.k;           // no jump when the drag takes hold
  }
  L.p = S.hinge ? flipFor(drag, e.clientY) : slideFor(drag.grab, e.clientY); place();
  drag.trail.push([performance.now(), L.p]);
  if (drag.trail.length > 6) drag.trail.shift();
});
function lift(e) {
  const f = fingers.get(e.pointerId);
  if (f === undefined) return;
  fingers.delete(e.pointerId);
  if (typeof f === 'string') { if (e.type === 'pointerup' && e.pointerType === 'touch' && !canVibrate) releaseTick(false); return key(f, false); }
  drag = null;
  if (!f.moved) return;
  // The speed of the last tenth of a second decides: a flick carries the face on, a slow hand leaves it at the nearer end.
  const now = performance.now(), t = f.trail.filter(s => now - s[0] < 120), a = t[0], b = t[t.length - 1];
  const v = t.length > 1 && b[0] > a[0] ? (b[1] - a[1]) / ((b[0] - a[0]) / 1000) : 0;
  pref.set('slid', '1');
  if (e.type === 'pointerup' && e.pointerType === 'touch') releaseTick(true);       // the snap follows at once; later there is no touch to tick in
  else if (e.type === 'pointerup' && e.pointerType === 'pen') tick(true, 'pointerup');
  run(Math.abs(v) > 0.9 ? (v > 0 ? 1 : 0) : L.p > 0.5 ? 1 : 0, clamp(v, -8, 8));
}
for (const ev of ['pointerup', 'pointercancel', 'lostpointercapture']) stage.addEventListener(ev, lift);
// Safari: no page scroll, no magnifier, no pinch and no double-tap zoom while a finger is on the stage.
// (?touch=plain leaves the touch alone, to find out whether this is what keeps Safari from ticking.)
if (ASKED.get('touch') !== 'plain') $('stage').addEventListener('touchstart', e => { if (!e.target.closest('button')) e.preventDefault(); }, { passive: false });
$('stage').addEventListener('touchend', () => {
  if (upTick && performance.now() - upTick.at < 300) tick(upTick.strong, 'touchend'); else touchEnded = performance.now();
  upTick = null;
});
$('stage').addEventListener('touchmove', e => e.preventDefault(), { passive: false });
for (const ev of ['gesturestart', 'gesturechange', 'contextmenu', 'dragstart', 'selectstart']) $('stage').addEventListener(ev, e => e.preventDefault());

// The computer keyboard. With the slide closed the keypad is under the face and takes no key.
const KEYS = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', Enter: 'select', F1: 'soft_left', F2: 'soft_right', F3: 'call',
  F4: 'end', Backspace: 'clear', Escape: 'soft_right', '*': 'star', '#': 'hash', ' ': 'hash' };
for (let d = 0; d < 10; d++) KEYS[String(d)] = String(d);
const held = new Map();
const typing = e => !$('sheet').hidden || (e.target && e.target.closest && e.target.closest('input, summary, a'));
addEventListener('keydown', e => {
  if (!$('sheet').hidden && e.key === 'Escape') { e.preventDefault(); return sheet(false); }
  if (!S || typing(e) || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === 'Escape' && v3 && v3.active) { e.preventDefault(); v3.exit(); return; }
  // Space is the phone's space key (#, as on the keypad phones of the era) while the keypad is out; with the slide closed it
  // opens the phone. O slides it either way.
  if (e.key === 'o' || e.key === 'O' || (e.key === ' ' && slideState() === 'closed')) { e.preventDefault(); if (!e.repeat) toggleSlide(); return; }
  const n = KEYS[e.key];
  if (!n || !A.running) return;
  e.preventDefault();
  if (e.repeat || held.has(e.code) || (slideState() === 'closed' && S.hidden.has(n))) return;
  held.set(e.code, n); key(n, true);
});
addEventListener('keyup', e => { const n = held.get(e.code); if (n) { held.delete(e.code); key(n, false); } });
addEventListener('blur', letGo);
addEventListener('pagehide', letGo);
document.addEventListener('visibilitychange', () => { if (document.hidden) letGo(); });

// ---- the text-message network: its state on the stage and in settings ----
// 'relay' when a relay is named (config.json or ?relay=) and not switched off here, else 'loopback'. Set in netChoice().
let net = 'loopback';
function netChoice() {
  const want = ASKED.get('net') || pref.get('net', 'relay');
  net = RELAY && want !== 'loopback' ? 'relay' : 'loopback';
  $('netSeg').hidden = !RELAY;
}
const group = n => n.length === 12 ? n.replace(/(\d{4})(?=\d)/g, '$1 ') : n.replace(/^(\d{3})(\d{4})$/, '$1 $2');
const NET_WORDS = { starting: 'Getting a number', idle: 'Not connected: the phone is off', connecting: 'Connecting', online: 'Connected', offline: 'No service. Trying again', stopped: 'No service',
  loopback: 'Loopback: a text comes back to this phone', none: 'No network: this phone has no modem software' };
let noNet = false;                 // a phone with no modem: the network's link is not used, and says nothing more
function cellState(s) {
  if (noNet && s.state !== 'none') return;
  const was = A.cell;
  A.number = s.number || ''; A.cell = s.state;
  const look = s.state === 'online' || s.state === 'loopback' ? 'on' : s.state === 'offline' || s.state === 'stopped' || s.state === 'none' ? 'off' : 'wait';
  const words = NET_WORDS[s.state] + (s.state === 'stopped' && s.text ? ': ' + s.text : '');
  $('number').textContent = A.number ? group(A.number) : '…';
  $('numberRow').hidden = s.state === 'loopback';
  $('net').dataset.state = look; $('net').setAttribute('aria-label', 'Text-message network: ' + words);
  $('netState').textContent = words + '.';
  $('textSec').classList.toggle('nonet', s.state === 'none');
  $('netWho').textContent = s.state === 'none' ? `${A.phone ? A.phone.title : 'This phone'} has no modem stand-in: no number and no texts.`
    : net === 'loopback' ? 'Every text this phone sends comes back to it, from the number it was sent to.' + (RELAY ? '' : ' This page has no relay to other phones.')
    : 'Other phones on the relay can text it; a text to 3246 comes back to you.';
  for (const b of document.querySelectorAll('[data-net]')) b.setAttribute('aria-pressed', String(b.dataset.net === net));
  if (s.state !== was) {
    report(`cell: ${s.state}${s.reason ? ' (' + s.reason + ')' : ''} ${A.number}`);
    if (A.running && (look === 'off' || (s.state === 'online' && (was === 'offline' || was === 'stopped')))) toast(look === 'off' ? 'No service' : 'Connected again');
  }
}
$('net').addEventListener('click', () => toast($('net').getAttribute('aria-label').replace('Text-message network: ', '') + (A.number ? `, ${group(A.number)}` : ''), 3200));
for (const b of document.querySelectorAll('[data-net]')) b.addEventListener('click', () => {
  if (b.dataset.net === net) return;
  pref.set('net', b.dataset.net);
  const again = () => { const q = new URLSearchParams(location.search); q.delete('net'); location.href = location.pathname + '?' + q; };
  if (!A.running) return again();
  A.after = again; sheet(false); $('veil').classList.remove('gone'); $('bar').hidden = true; status('Changing the network', 'stopping to change the network');
  worker.postMessage({ t: 'stop' });
});

// ---- the worker ----
function onMessage(m) {
  if (link) link.onMessage(m);
  if (m.t === 'stage') report(m.text);
  else if (m.t === 'ready') { A.ready = true; report(`worker ready: Pyodide ${(m.times.pyodide / 1000).toFixed(1)} s, source ${((m.times.unpack + m.times.imports) / 1000).toFixed(1)} s`); if (readyWait) readyWait(); }
  else if (m.t === 'built') {
    keyNames = new Set(m.keys);
    report(`machine built in ${(m.times.build / 1000).toFixed(1)} s; memory: core ${mb(m.mem.core)}, Pyodide ${mb(m.mem.pyodide)}`);
  } else if (m.t === 'running') { A.running = true; status('Switching on', 'starting up'); progress(BUILT, true); tellSlide(); }
  else if (m.t === 'frame') {
    draw(m);
    if (!A.frames++) { report(`first picture at ${(m.ms / 1000).toFixed(1)} emulated s`); progress(1); $('veil').classList.add('gone'); hint(); }
  } else if (m.t === 'second') {
    // the speed over the last five seconds: one second alone jumps about when the phone sleeps and wakes
    recent.push(m); if (recent.length > 6) recent.shift();
    last = recent[0]; A.emu = m.emu;
    A.rate = recent.length > 1 ? (m.emu - last.emu) / (m.host - last.host) : m.emu / m.host;
    const slow = A.rate < 0.85 && recent.length > 5 && !$('fast').checked;
    $('slow').hidden = !slow;
    $('speed').textContent = `${Math.round(A.rate * 100)}% of real speed, on for ${clock(m.emu)}`;
    $('numbers').textContent = `Details: ${m.emu.toFixed(0)} s on the phone, ${A.rate.toFixed(2)}x, ${A.frames} pictures`;
    if (Math.floor(m.emu) % 10 === 0) report(`emu ${m.emu.toFixed(0)} s host ${m.host.toFixed(0)} s rate ${A.rate.toFixed(2)} frames ${A.frames}`);
  } else if (m.t === 'lines') {
    for (const s of m.lines) lines.push(s);
    for (const s of m.lines) if (/CELL |message received|message send/.test(s)) report('phone: ' + s.replace(/^.*?ms\| /, '').slice(0, 170));
    if (lines.length > 200) lines.splice(0, lines.length - 200);
    if ($('log').open) $('console').textContent = lines.join('\n');
    if (m.err) report('stderr: ' + m.lines.slice(-2).join(' / ').slice(0, 300));
  } else if (m.t === 'state') { keep(m.bytes, m.why).then(() => { if (m.why === 'save') { report('saved'); toast('Its memory is kept in this browser'); } }); }
  else if (m.t === 'end') {
    A.running = false;
    keep(m.state, 'end').then(() => {
      report(`stopped (${m.why})`);
      if (A.after) return A.after();
      $('veil').classList.remove('gone'); $('bar').hidden = true; $('status').textContent = 'The phone is off.'; $('again').hidden = false;
    });
  } else if (m.t === 'error') { if (m.soft) { report('ERROR ' + m.text); toast(m.text, 4000); } else { fail(m.text); A.running = false; report('stopped by an error'); } }
}
const clock = s => s < 90 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min`;
function newWorker() {
  worker = new Worker('phone_worker.js');
  worker.onerror = e => fail('The worker failed: ' + (e.message || 'it could not be loaded'));
  worker.onmessage = e => onMessage(e.data);
  // The text-message network: the relay (a number of 12 digits, made from this browser's key; it comes a moment later),
  // or the stand-in's loopback network (no number: a text comes back from the number it was sent to). The person check
  // of the relay is not set up here: where the relay asks for one, `turnstile` must be a function (site key) -> promise
  // of a token (myna/relay/DEPLOY.md, section 8).
  if (net === 'relay') link = cellLink(worker, () => A.emu, report, { url: RELAY, onState: cellState, turnstile: null });
  else { link = null; cellState({ state: 'loopback', number: '' }); }
}

// The first time, say how the phone opens (and let the face move a little, once).
function hint() {
  if (!S.sl || pref.get('slid', '') || L.p !== 0) return;
  setTimeout(() => {
    if (pref.get('slid', '') || L.p !== 0 || drag || !$('sheet').hidden) return;
    toast('Swipe the screen up to open it', 4200);
    if (!calm.matches && !anim) { L.moving = true; run(0, 5); }
  }, 1400);
}

// A firmware of our own: its ELF file, from this server (it is open source: any server may give it).
async function firmware(p) {
  status('Loading its software', `${p.title}: loading its firmware`);
  progress(0, true);
  const res = await fetch(`firmware/${p.name}.elf`, { cache: 'no-store' });
  if (!res.ok) throw new Error('the server did not give the firmware (' + res.status + ')');
  const b = await res.arrayBuffer();
  progress(UNPACKED);
  return b;
}
async function start(p) {
  A.phone = p; stateKey = `state:${p.name}:${p.etag}`;
  ASKED.set('p', p.name); history.replaceState(null, '', '?' + ASKED);
  try {
    S = await skinOf(p);
    stageFor(p);
    // No modem stand-in: no link to a network (it would give a number the phone cannot use). The profile's PEER is the hook:
    // with a stand-in that carries texts (the worker's _cell() finds its cell network) the phone is linked like the others.
    if (!p.peer) { link = null; cellState({ state: 'none', number: '' }); noNet = true; }
    const elf = await firmware(p);
    const flash = await flashState();
    if (!A.ready) { status('Loading the simulator'); progress(UNPACKED, true); await new Promise(r => { readyWait = r; }); }
    if (A.error) return;
    status('Building the phone'); progress((UNPACKED + BUILT) / 2, true);
    // The AT stand-in's choices (native/emu_modem_at/config.py), and the number the relay gave this browser, for +CNUM.
    const config = { 'sim.present': true, 'cell.network': net === 'relay' ? 'host' : 'loopback' };
    if (p.peer && link && link.number) config['phone.number'] = link.number;
    const m = { t: 'start', device: p.name, fast: $('fast').checked, hold: true, hashes: false, config: JSON.stringify(config), limit_s: 0, keys: [], elf, keylog: ASKED.get('keylog') === '1', slow: +ASKED.get('slow') || 1 };
    if (S.hinge) { slideSent = slideState(); m.keys.push(JSON.stringify({ switch: 'slide', state: slideSent })); }
    if (flash) m.flash = flash.slice(0);
    worker.postMessage(m, [m.elf, m.flash].filter(b => b));
  } catch (e) { document.body.dataset.screen = 'phone'; $('stage').hidden = false; fail('Could not start: ' + (e.message || e)); }
}

// ---- the stage for one phone: its pictures, key areas and settings ----
// ---- the shadows ----
// Each is the outline of a picture, blurred and moved down a little, drawn once per picture into a small canvas (a canvas
// shadow with the picture itself drawn outside the canvas leaves only the shadow). Nothing is filtered while the slide moves.
const PAD = 18, FADE = 14, FINE = 2;       // units round the picture for the blur; the fade of the face's paper shadow; canvas pixels per unit
function shade(cv, img, passes, from) {
  const w = (S.W + 2 * PAD) * FINE, h = (S.Ho + 2 * PAD) * FINE;
  cv.width = w; cv.height = h;
  const c = cv.getContext('2d');
  if (!img || !img.naturalWidth) return;
  try {
    c.save();
    for (const [blur, dy, alpha] of passes) {
      c.shadowColor = `rgba(8, 12, 20, ${alpha})`; c.shadowBlur = blur * FINE; c.shadowOffsetX = 3 * w; c.shadowOffsetY = dy * FINE;
      c.drawImage(img, PAD * FINE - 3 * w, PAD * FINE, S.W * FINE, S.Ho * FINE);
    }
    c.restore();
    if (from) {                                      // only from there down, coming in softly
      const g = c.createLinearGradient(0, (PAD + from) * FINE, 0, (PAD + from + 9) * FINE);
      g.addColorStop(0, 'rgba(0, 0, 0, 0)'); g.addColorStop(1, '#000');
      c.globalCompositeOperation = 'destination-in'; c.fillStyle = g; c.fillRect(0, 0, w, h); c.globalCompositeOperation = 'source-over';
    }
  } catch (e) { report('no shadow: ' + e); }
}
const PAPER = [[11, 5, 0.26], [2.5, 0.8, 0.22]], TOUCH = [[4, 2, 0.42]];
function shades() {
  const b = base.querySelector('img'), f = face.querySelector('img'), s = S;
  const when = (img, go) => { if (img.complete && img.naturalWidth) go(); else img.addEventListener('load', () => { if (S === s) go(); }, { once: true }); };
  when(b, () => shade($('shBase'), b, PAPER));
  if (S.faceImage) when(f, () => { shade($('shFace'), f, PAPER); shade($('shTouch'), f, TOUCH, S.faceRect[1] + S.faceRect[3] - 10); });
  else { shade($('shFace'), null); shade($('shTouch'), null); }
}
function paint() {
  base.querySelector('img').src = picture(S, S.baseImage);
  if (S.hinge) flipPaint();
  const f = face.querySelector('img');
  f.hidden = !S.faceImage; if (S.faceImage) f.src = picture(S, S.faceImage);
  shades();
  for (const b of $('colours').children) b.setAttribute('aria-pressed', String(b.dataset.variant === S.variant));
}
function stageFor(p) {
  const skin = S.skin;
  document.title = p.title;
  document.body.dataset.screen = 'phone'; $('stage').hidden = false;
  for (const el of Object.values(keyEls)) el.remove();
  for (const k of Object.keys(keyEls)) delete keyEls[k];
  for (const [set, layer] of [[S.faceKeys, face], [S.baseKeys, base]]) for (const name of Object.keys(set)) {
    const el = document.createElement('div'); el.className = 'key'; layer.appendChild(el); keyEls[name] = el;
  }
  $('slide').hidden = !S.sl && !S.hinge;
  $('flatRow').hidden = $('flatNote').hidden = !skin.body3d;
  flipStage();
  $('sheetTitle').textContent = p.title;
  $('sheetSub').textContent = (p.firmware ? 'Software ' + p.firmware + ' (open source)' : '') + (S.mm ? `${p.firmware ? ', ' : ''}${S.mm[1]} × ${S.mm[0]} mm closed` : '');
  // keys that the drawing does not show, or shows only as a thin edge
  const side = (skin.side_keys || []);
  $('sideSec').hidden = !side.length;
  $('sideKeys').replaceChildren(...side.map(k => {
    const b = document.createElement('button');
    b.dataset.key = k.key; b.textContent = k.label; if (k.title) b.title = k.title;
    b.addEventListener('pointerdown', e => { e.preventDefault(); try { b.setPointerCapture(e.pointerId); } catch (x) { /* fine */ } if (!b.dataset.on) { b.dataset.on = '1'; if (e.pointerType !== 'mouse') tick(false, 'pointerdown'); key(k.key, true); } });
    b.addEventListener('click', () => { if (!canVibrate) tick(false, 'click'); });
    for (const ev of ['pointerup', 'pointercancel', 'lostpointercapture']) b.addEventListener(ev, () => { if (b.dataset.on) { delete b.dataset.on; key(k.key, false); } });
    b.addEventListener('contextmenu', e => e.preventDefault());
    return b;
  }));
  const vs = skin.variants || [];
  $('colourSec').hidden = vs.length < 2;
  $('colours').replaceChildren(...vs.map(v => {
    const b = document.createElement('button');
    b.dataset.variant = v.id; b.title = v.label || v.id; b.setAttribute('aria-label', v.label || v.id); b.style.background = v.swatch || '#888';
    b.addEventListener('click', () => { S.variant = v.id; pref.set('variant.' + S.name, v.id); paint(); if (v3) v3.setVariant(v.id); });
    return b;
  }));
  paint(); layout();
  view3d();
}

// ---- the phone in 3D (core/web/phone3d.js), for a skin with body3d ----
// The 3D view draws the phone, at rest too: facing front at its true size, where the 2D layout puts it (place() gives it k,
// x, y and the slide's position: the slide and a flip's lid move in 3D with the page's spring, the switch goes to the phone
// as ever). The 2D drawing stays laid out but hidden: its geometry is the page's (the size, the ruler, the springs), and
// the words over the screen while the phone starts lie on the 3D screen (fitVeil). A finger finds its key on the face it
// touches in 3D (at(): the point of that face under it, in the 2D layout's units), so the rules of under() hold as they
// were. Turned (the turn button, two fingers off the keys, a drag beside the phone or sideways across its face), the 3D
// view takes the fingers itself and springs back to the front when let go. Without WebGL, if the module does not load, or
// with the setting "Flat drawing (2D)", the 2D drawing is the phone, as before.
let v3 = null, three = false, flat = pref.get('flat', '') === '1', standIn = 0, stoodIn = false;
A.v3 = () => v3;                           // the 3D view, for tests
A.three = () => three;                     // whether the phone on the stage is the 3D one
const veil = $('veil');
const want3d = s => !!(s && s.skin.body3d) && !flat;
async function view3d() {
  if (v3) { v3.dispose(); v3 = null; }
  show3d(false);
  $('turn').hidden = true;
  const s = S;
  clearTimeout(standIn); stoodIn = false;
  if (!want3d(s)) { stage.classList.remove('wait3d'); return; }
  // the 2D phone is not shown while the 3D one is made, unless that takes long: then it stands in until the 3D one comes
  stage.classList.add('wait3d');
  standIn = setTimeout(() => { stoodIn = true; stage.classList.remove('wait3d'); }, 700);
  const t0 = performance.now();
  let v = null;
  try {
    const P3 = await import('./phone3d.js');
    if (S !== s) return;
    if (!P3.supports(s.skin) || (s.hinge && !P3.hinges)) throw new Error('this phone has no 3D body');
    v = await P3.create(stage, { main: true, skinUrl: `skin/${s.name}/`, skinJson: s.skin, variant: s.variant, screenCanvas: src, before: rig });
    if (S !== s) { v.dispose(); return; }
    v3 = v;
    v.onKey = (name, isDown) => { if (isDown) tick(false, '3d key'); key(name, isDown); };
    v.onMode = on => {
      $('turn').setAttribute('aria-pressed', String(on));
      $('ruler').style.visibility = on ? 'hidden' : '';
      if (!on) return;
      for (const f of fingers.values()) if (typeof f === 'string') key(f, false);     // the fingers on the face let go
      fingers.clear();
      if (drag) { drag = null; rig.classList.remove('held'); run(L.p > 0.5 ? 1 : 0, 0); }
      report('3D view turned');
    };
    v.onLost = lost => { report(lost ? '3D view: the graphics context is lost; the 2D drawing stands in' : '3D view: back'); show3d(!lost); };
    v.onRender = fitVeil;
    if (stoodIn) v.layer.classList.add('fade');                   // over the 2D phone that stood in: it comes in softly
    place();
    await v.start();
    if (v3 !== v) return;
    clearTimeout(standIn);
    show3d(true);
    $('turn').hidden = false;
    report(`3D view drawn in ${Math.round(performance.now() - t0)} ms: ${JSON.stringify(v.stats())}`);
  } catch (e) {
    if (v) v.dispose();
    if (v3 === v) v3 = null;
    clearTimeout(standIn);
    show3d(false);
    report('no 3D view, the 2D drawing: ' + (e.message || e));
  }
}
// The 3D phone shown (the 2D one hidden), or the 2D one again (no WebGL, its context lost, the flat drawing).
function show3d(on) {
  three = !!(on && v3);
  stage.classList.remove('wait3d');
  if (three) {
    // after the 3D phone has come in over a 2D one that stood in for it, the 2D one goes
    if (v3.layer.classList.contains('fade')) setTimeout(() => { if (three) stage.classList.add('three'); }, 240);
    else stage.classList.add('three');
    if (veil.parentNode !== stage) rig.after(veil);
  } else {
    stage.classList.remove('three');
    $('ruler').style.visibility = '';
    if (veil.parentNode !== glass) { glass.append(veil); Object.assign(veil.style, { transform: '', width: '', height: '', padding: '', visibility: '' }); }
  }
  if (S) { place(); screenSize(); }
}
// The words over the screen (#veil) on the 3D screen: its box mapped onto the four corners the screen has on the display
// (a projective transform, so it lies on the screen when the lid leans or the phone is turned); not shown from behind.
function fitVeil() {
  if (!three || !v3 || veil.classList.contains('gone')) return;
  const q = v3.screenQuad();
  if (!q) return;
  const w = S.glass[2] * L.k, h = S.glass[3] * L.k;
  Object.assign(veil.style, { width: w + 'px', height: h + 'px', padding: 0.1 * w + 'px', visibility: q.facing ? '' : 'hidden', transform: quadMatrix(q.pts, w, h) });
}
// The CSS matrix3d that takes a box w x h (top left at 0 0) to the corners p (top left, top right, bottom right, bottom left).
function quadMatrix(p, w, h) {
  const [[x0, y0], [x1, y1], [x2, y2], [x3, y3]] = p;
  const dx1 = x1 - x2, dx2 = x3 - x2, dx3 = x0 - x1 + x2 - x3, dy1 = y1 - y2, dy2 = y3 - y2, dy3 = y0 - y1 + y2 - y3;
  let g = 0, i = 0;
  const den = dx1 * dy2 - dx2 * dy1;
  if (Math.abs(den) > 1e-9 && (Math.abs(dx3) > 1e-9 || Math.abs(dy3) > 1e-9)) { g = (dx3 * dy2 - dx2 * dy3) / den; i = (dx1 * dy3 - dx3 * dy1) / den; }
  const a = x1 - x0 + g * x1, b = x3 - x0 + i * x3, d = y1 - y0 + g * y1, e = y3 - y0 + i * y3;
  return `matrix3d(${[a / w, d / w, 0, g / w, b / h, e / h, 0, i / h, 0, 0, 1, 0, x0, y0, 0, 1].map(n => +n.toFixed(9)).join(',')})`;
}
$('turn').addEventListener('click', () => { if (!v3) return; tick(true, 'click'); if (v3.active) v3.exit(); else v3.enter({ pose: 'three' }); });
$('flatOn').checked = flat;
$('flatOn').addEventListener('change', () => { flat = $('flatOn').checked; pref.set('flat', flat ? '1' : ''); report('flat drawing ' + (flat ? 'on' : 'off')); if (S) view3d(); });

// ---- the settings sheet ----
function sheet(on) {
  const sh = $('sheet'), sc = $('scrim');
  $('menu').setAttribute('aria-expanded', String(on));
  if (on) {
    sh.hidden = sc.hidden = false; void sh.offsetWidth; sh.classList.add('on'); sc.classList.add('on');
    $('freshAsk').hidden = true; $('fresh').hidden = false;
    $('closeSheet').focus({ preventScroll: true });
  } else {
    sh.classList.remove('on'); sc.classList.remove('on');
    setTimeout(() => { if (!sh.classList.contains('on')) sh.hidden = sc.hidden = true; }, calm.matches ? 0 : 340);
    $('menu').focus({ preventScroll: true });
  }
}
$('menu').addEventListener('click', () => sheet($('sheet').hidden));
$('closeSheet').addEventListener('click', () => sheet(false));
$('scrim').addEventListener('click', () => sheet(false));
$('slide').addEventListener('click', () => { tick(true, 'click'); toggleSlide(); });
$('feelTest').addEventListener('click', () => { const was = feel; feel = true; tick(false, 'test button'); feel = was; });
$('feelNote').hidden = canVibrate;
$('feelSec').hidden = !canFeel; $('feel').checked = feel;
$('feel').addEventListener('change', () => { feel = $('feel').checked; pref.set('feel', feel ? '1' : ''); });
function setSize(mode) { L.mode = mode; pref.set('size', mode); layout(); }
$('size').addEventListener('click', () => { setSize(L.mode === 'fit' ? 'true' : 'fit'); toast(L.mode === 'fit' ? 'Fitted to the screen' : $('sizeText').textContent === '1:1' ? 'True size' : `True size does not fit here: ${$('sizeText').textContent}`); });
for (const b of document.querySelectorAll('[data-size]')) b.addEventListener('click', () => setSize(b.dataset.size));
$('copyNumber').addEventListener('click', async () => {
  let ok = false;
  try { await navigator.clipboard.writeText(A.number); ok = true; } catch (e) { /* no clipboard here: the number can be selected */ }
  $('copyNumber').textContent = ok ? 'Copied' : 'Select it to copy';
  setTimeout(() => { $('copyNumber').textContent = 'Copy'; }, 1800);
});
$('rulerOn').checked = rulerOn;
$('rulerOn').addEventListener('change', () => { rulerOn = $('rulerOn').checked; pref.set('ruler', rulerOn ? '1' : ''); if (S) place(); });
// Full screen: the browser's own where it has one; on an iPhone the page becomes a home-screen app instead, and says how.
const root = document.documentElement, goFull = root.requestFullscreen || root.webkitRequestFullscreen;
const isFull = () => !!(document.fullscreenElement || document.webkitFullscreenElement);
if (!standalone && iPhone) { $('fullSec').hidden = false; $('homeHint').hidden = false; }
else if (!standalone && goFull) {
  $('fullSec').hidden = false; $('full').hidden = false;
  $('full').addEventListener('click', () => {
    try {
      const r = isFull() ? (document.exitFullscreen || document.webkitExitFullscreen).call(document) : goFull.call(root, { navigationUI: 'hide' });
      if (r && r.catch) r.catch(e => toast('This browser did not go to full screen'));
    } catch (e) { toast('This browser did not go to full screen'); }
    sheet(false);
  });
  for (const ev of ['fullscreenchange', 'webkitfullscreenchange']) document.addEventListener(ev, () => { $('full').textContent = isFull() ? 'Leave full screen' : 'Fill the screen'; if (S) layout(); });
}
$('cal').value = cal;
$('cal').addEventListener('input', () => { cal = clamp(parseFloat($('cal').value) || 1, 0.7, 1.4); pref.set('cal', String(cal)); layout(); });
$('calReset').addEventListener('click', () => { cal = 1; $('cal').value = 1; pref.set('cal', '1'); layout(); });
$('fast').addEventListener('change', () => { if (worker) worker.postMessage({ t: 'fast', on: $('fast').checked }); $('slow').hidden = true; });
$('save').addEventListener('click', () => { if (A.running) worker.postMessage({ t: 'state', why: 'save' }); sheet(false); });
const home = () => { location.href = location.pathname; };
$('off').addEventListener('click', () => {
  if (!A.running) return home();
  A.after = home;
  sheet(false); $('veil').classList.remove('gone'); $('bar').hidden = true; status('Switching off', 'stopping');
  worker.postMessage({ t: 'stop' });
});
$('fresh').addEventListener('click', () => { $('fresh').hidden = true; $('freshAsk').hidden = false; $('freshNo').scrollIntoView({ block: 'nearest' }); });
$('freshNo').addEventListener('click', () => { $('fresh').hidden = false; $('freshAsk').hidden = true; });
$('freshYes').addEventListener('click', async () => {
  if (worker) worker.terminate();
  await del(stateKey);
  report('start over: the kept flash state is forgotten');
  location.reload();
});
$('again').addEventListener('click', () => location.reload());
$('log').addEventListener('toggle', () => { $('console').textContent = lines.join('\n'); });
document.addEventListener('visibilitychange', () => { if (document.hidden && A.running) worker.postMessage({ t: 'state', why: 'hidden' }); });
addEventListener('resize', () => { if (S && !L.moving) layout('resize'); if (!S) shelf(); });
if (window.visualViewport) visualViewport.addEventListener('resize', () => { if (S && !L.moving) layout('visual viewport'); });
addEventListener('orientationchange', () => setTimeout(() => { if (S && !L.moving) layout('turned'); }, 350));
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (S) place(); });
if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { if (S) place(); });
addEventListener('error', e => report('page error: ' + e.message));
addEventListener('unhandledrejection', e => report('page rejection: ' + (e.reason && e.reason.message || e.reason)));

// ---- the shelf: the phones, drawn closed, at one scale ----
function shelf() {
  const box = $('phones'), picks = [...box.querySelectorAll('.pick')];
  if (!picks.length) return;
  const wide = picks.reduce((s, b) => s + b.skinW, 0), tall = Math.max(...picks.map(b => b.skinH));
  const roomW = box.clientWidth - (picks.length - 1) * 28 - 16, roomH = Math.max(220, innerHeight * 0.52);
  const part = Math.min(1, roomW / (wide * pxmm()), roomH / (tall * pxmm()));
  const shown = part >= 0.995 ? 1 : part >= 0.5 ? 0.5 : part;
  for (const b of picks) Object.assign(b.querySelector('.pic').style, { width: b.skinW * pxmm() * shown + 'px', height: b.skinH * pxmm() * shown + 'px' });
  $('shelfNote').textContent = (shown === 1 ? 'Drawn here at true size.' : shown === 0.5 ? 'Drawn here at half size. In the hand they are at true size.' : 'In the hand they are drawn at true size.') +
    ' What a phone stores is kept in this browser.';
}
async function card(p) {
  const s = await skinOf(p), saved = await get(`state:${p.name}:${p.etag}`);
  const b = document.createElement('button');
  b.className = 'pick'; b.dataset.name = p.name;
  b.skinW = s.W / s.upm; b.skinH = s.Hc / s.upm;       // millimetres of the closed picture
  const pic = document.createElement('span'), img = document.createElement('img');
  pic.className = 'pic'; img.alt = ''; img.src = picture(s, s.closedImage); pic.append(img);
  const t = document.createElement('b'); t.textContent = p.title;
  const mm = document.createElement('span'); mm.className = 'mm'; mm.textContent = s.mm ? `${s.mm[1]} × ${s.mm[0]} mm` : '';
  const k = document.createElement('span'); k.className = 'kept';
  k.textContent = `Open-source software, ${Math.max(1, Math.round(p.size / 1024))} kB`;
  const l = document.createElement('span'); l.className = 'last';
  l.textContent = saved ? 'Last held ' + new Date(saved.when).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';
  b.append(pic, t, mm, k, l);
  b.addEventListener('click', () => start(p));
  return b;
}

(async () => {
  // The page's settings from its server: {"relay": "wss://..."} names the relay ("" or no file: none, loopback only).
  if (!RELAY) try { const c = await (await fetch('config.json', { cache: 'no-store' })).json(); RELAY = typeof c.relay === 'string' ? c.relay : ''; } catch (e) { /* no relay */ }
  netChoice();
  newWorker();
  report(`page open: ${navigator.userAgent}; memory ${navigator.deviceMemory || '?'} GB; secure ${isSecureContext}; view ${innerWidth}x${innerHeight} at ${devicePixelRatio}x; true size as ${EST.what} (${pxmm().toFixed(2)} px/mm); network ${net}; ${standalone ? 'home-screen app' : 'in the browser'}`);
  // How fast this browser runs plain JavaScript and a small WebAssembly loop (100 million additions each): tells a
  // browser without a compiler (very slow at both) from one that is slow only with the simulator's large functions.
  setTimeout(() => {
    try {
      let t = performance.now(), s = 0;
      for (let i = 0; i < 1e8; i++) s = (s + i) | 0;
      const js = performance.now() - t;
      const mod = new WebAssembly.Module(new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0, 1, 6, 1, 96, 1, 127, 1, 127, 3, 2, 1, 0, 7, 5, 1, 1, 102, 0, 0,
        10, 30, 1, 28, 1, 2, 127, 3, 64, 32, 2, 32, 1, 106, 33, 2, 32, 1, 65, 1, 106, 34, 1, 32, 0, 72, 13, 0, 11, 32, 2, 11]));
      const f = new WebAssembly.Instance(mod).exports.f;
      t = performance.now(); const w = f(1e8);
      report(`speed check: JavaScript ${js.toFixed(0)} ms, WebAssembly ${(performance.now() - t).toFixed(0)} ms (same sum: ${w === s}); cores ${navigator.hardwareConcurrency}`);
    } catch (e) { report('speed check failed: ' + e); }
  }, 300);
  try {
    A.phones = await (await fetch('devices.json')).json();
  } catch (e) { $('phones').textContent = ''; const m = document.createElement('p'); m.textContent = 'The server did not answer. Check that it is running, then load the page again.'; $('phones').append(m); $('phones').removeAttribute('aria-busy'); return; }
  const want = new URLSearchParams(location.search).get('p'), p = A.phones.find(x => x.name === want);
  if (p) return start(p);
  const cards = [];
  for (const q of A.phones) try { cards.push(await card(q)); } catch (e) { report(`no card for ${q.name}: ${e.message || e}`); }
  $('phones').replaceChildren(...cards);
  $('phones').removeAttribute('aria-busy');
  if (!cards.length) { const m = document.createElement('p'); m.textContent = 'This server has no phone to give.'; $('phones').append(m); }
  shelf();
})();
