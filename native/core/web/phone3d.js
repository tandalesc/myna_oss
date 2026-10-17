// phone3d.js: the phone in three dimensions, to turn it round and see its back and sides with the live screen showing.
// An ES module on three.js (vendor/three-0.186.1, MIT). It reads the skin (native/devices/NAME/skin/: skin.json and its
// pictures): a skin with a `body3d` block gets a 3D view, a skin without one does not (supports(skin) says which).
//
//   const v = await Phone3D.create(container, { skinUrl, skinJson, variant, screenCanvas, flat });
//   v.setView({ k, x, y })   where the page draws the 2D phone (CSS px per skin unit; top left of the open picture)
//   v.setSlide(p)            0 closed .. 1 open, set by the page (its spring): the slide, or a flip's lid on its hinge
//   v.setVariant(id)         the colour
//   v.frame()                a new picture on screenCanvas
//   v.setKey(name, down)     a key pressed or let go on the page: it sinks in 3D too (a tap on a key in 3D does it itself)
//   v.enter() / v.exit()     into the 3D view and back: a swap with the 2D phone in one frame, facing front (no cross-fade)
//   v.grab(pointerEvent)     a drag the page hands over: the phone turns while the finger moves, and goes back when let go
//   v.onKey = (name, down) => ...;  v.onMode = on => ...;  v.dispose()
// The main view (opts.main, Myna's phone page): this module draws the phone all the time, at rest too.
//   await v.start()          build, draw the first frame facing front, show it (rejects where there is no WebGL)
//   v.pick(cx, cy, part)     the point of a part's face ('moving' or 'still') under a point of the display, in the page's
//                            units (the open picture), so the page finds keys by its own rules; v.project(u, v, part) back
//   v.screenQuad()           the screen's corners on the display (the page lays its words over the screen on them)
//   v.onLost = lost => ...;  v.onRender = () => ...
// enter() and exit() then only turn it (look round) and bring it back to the front: there is no swap. At rest it faces
// front, the plane of the front at true size where the page's layout puts it, through a long lens (EYE_REST mm: it reads as
// an object); its light is the room's (no flat picture to match); a flip's lid stands at its open angle (restOpen, by
// default body3d's: 162); the side keys stand out of their walls. The screen's picture goes to the GPU at the panel's size
// and is enlarged in the shader (sharp bilinear). The pixel ratio steps down when frames drawn one after another come late
// while this module's CPU time is small (the GPU's fill), not below RATIO_FLOOR.
//
// The model (docs/SKINS_3D.md). Each slab of body3d.slabs is a solid: its plan (`outline`, an SVG path in closed-view px)
// between its depths `z`, with a round front and back edge (`edges`) and, where the skin gives one, a narrow facet of
// another material on the front edge (Myna's satin band). A slab `of` another rides with it (Myna's chin, the back slab's
// raised end). The front of each slab carries its picture (face.svg, base.svg), its back the view of it from behind
// (rear.svg, under.svg), its walls the side pictures (left, right, top, bottom) or the plain material of the colour
// (body3d.materials). A joint moves one slab: a slide along `axis` by its travel, or a hinge (a flip: body3d.hinge) that
// turns the lid about its axis (see JOINTS). The flip's lid is modelled closed; its back is its inner face (lid.svg, the
// screen's side, the picture turned over the hinge line); the barrel, the knuckles and the pin caps are solids of their
// own finishes (hingeGeometry()). The keys are solids: body3d.caps, each its own outline standing on its
// slab's front or in one of its wells (body3d.wells: recesses cut into a front), its top and the round of its top edge
// showing the front picture straight down (so the legends stay where the picture has them), its sides the key's material;
// the side keys of body3d.keys with `proud` stand out of their wall. All of a slab's keys are in the slab's own buffer
// (a draw call for each material, not for each key); a pressed key sinks by moving its few vertices. Flush regions of
// their own material (body3d.inlays: the glass pane, the slide plate) and the camera and flash (body3d.features) are in
// the same buffer, as are the openings: the earpiece's slot, cut through the glass to a fine grille, and the USB-C
// receptacle in an end (body3d.features: earpiece, usb_c). The screen is the emulator's picture on the glass rectangle,
// under cover glass.
//
// The materials are physically based, from the finishes of body3d.materials: soft-touch plastic with a broad sheen, matte
// carrier, glossier keys, brushed and spun metal (anisotropic, the brushing along the vertex tangents: radial on the coin
// and the camera ring, so their highlight is a cone through the middle that turns with the phone), glass that reflects
// the room's light boxes more at a grazing angle, the lens's coloured coating. A face may be several finishes at once
// (a finish map: the flip's lid, high-gloss lacquer with spun-metal pinstripes cut through it; finishFace()): a mask
// picture says which finish where, with a relief, a crown and the brushing's direction (docs/SKINS_3D.md "Finish maps").
// A light window may be a jewel cut (jewelGeometry()). The room is a studio made here (nothing
// is downloaded): light boxes, the key up on the left as in the drawings, a graded floor and ceiling, a faint horizon.
//
// Not the main view (the core's pages, the demo): the 2D page stays in charge while the phone faces front at rest: this
// module draws nothing then (no GPU work), and its layer is not shown. Facing front, every surface that faces the viewer shows its picture exactly (light() puts the
// light in as the phone turns), so entering and leaving is a swap of the two in one frame. A flip's 2D page draws the open
// lid flat (180 degrees); facing front at rest the 3D lid is flat too, and it settles to its true open angle (162) as the
// phone is turned. In the 3D view it draws only while something moves or a new screen picture comes.
// SPDX-License-Identifier: MIT
import * as THREE from './vendor/three-0.186.1/three.module.js';

export const THREE_VERSION = THREE.REVISION;
const DEG = Math.PI / 180;
const PITCH_MAX = 55 * DEG;                 // never further over than this: the phone does not go upside down
const FOV_FLAT = 2, FOV_TURNED = 20;        // degrees: almost flat while it faces front (it matches the 2D page), some depth when turned
// The phone drawn by this module all the time (opts.main): the eye's distance, in millimetres of the phone, facing front at
// rest (a long lens: it reads as an object, the front still at its true size) and turned (a little more depth).
const EYE_REST = 420, EYE_TURNED = 300;
// Lowering the pixel ratio when the GPU cannot keep up: never below this (legends stay readable), one step at a time.
const RATIO_FLOOR = 1.5, RATIO_STEP = 0.5;
// Device pixels per CSS pixel: the display's, at most 3, and at most 2 once the canvas would pass about 3.2 million pixels
// (a phone-sized canvas on a 3x iPhone stays sharp; a large window on a 2x display does not draw more than it shows).
const MAX_RATIO = 3, MAX_PIXELS = 3.2e6;
const BEVEL_STEPS = 6;
const KEY_BEVEL = 4;                        // steps round the top edge of a key
const PRESS = 0.3;                          // mm: how far a pressed key sinks
const DEEP = 0.12;                          // how much of the room the inside of an opening reflects
// The light: the studio's (environment, room()) and a key from the top left, set so that a front facing the viewer,
// turned, is about as light as its picture.
const LIGHT = { env: 1.7, key: 2.5 };
const SIDES = ['left', 'right', 'top', 'bottom'];
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const wrap = a => a - 2 * Math.PI * Math.round(a / (2 * Math.PI));
const num = (v, d) => (typeof v === 'number' && isFinite(v) ? v : d);
const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

/** Whether a skin has a body in three dimensions. */
export function supports(skin) { return !!(skin && skin.body3d && Array.isArray(skin.body3d.slabs) && skin.body3d.slabs.length); }

// ---- the skin, read (docs/SKINS_3D.md) ----
// Everything is kept in the frame of body3d: x, y picture pixels of the closed view, z millimetres from the front face. The
// geometry is built in mm with x right, y up and z out of the front: X = x / px_per_mm, Y = -y / px_per_mm, Z = thickness - z.
// The 2D page draws the open picture, which is the closed one moved down by the travel (the back slab is lower by
// `travel` in it, the moving slab is where it is when open): open-frame y = closed y + travel, less travel * p for the moving slab.
// A flip (skin.hinge with body3d.hinge, docs/SKINS_3D.md "A flip"): the open picture is the closed one with the base moved
// down by T (open height less closed height), and the lid's inner face turned over the hinge line: closed y is open
// turnY - y. The lid is modelled where it is closed and turned about the hinge.
function describe(skin) {
  const b3 = skin.body3d, views = {};
  for (const v of skin.views || []) views[v.id] = v;
  const sl = skin.slide && views[skin.slide.open] && views[skin.slide.closed] ? skin.slide : null;
  const hg = !sl && skin.hinge && views[skin.hinge.open] && views[skin.hinge.closed] && skin.hinge.axis_y > 0 ? skin.hinge : null;
  const two = sl || hg;
  const vo = two ? views[two.open] : views[skin.default_view] || skin.views[0], vc = two ? views[two.closed] : vo;
  const slide = !hg && b3.slide && b3.slide.moves ? b3.slide : null;
  const hinge = hg && b3.hinge && b3.hinge.moves && Array.isArray(b3.hinge.pivot) ? b3.hinge : null;
  const W = vo.size[0], Ho = vo.size[1], Hc = vc.size[1];
  const T = slide ? num(slide.travel, sl ? sl.travel : 0) : hinge ? Ho - Hc : 0;
  const mover = slide ? slide.moves : hinge ? hinge.moves : null;
  const br = skin.body && skin.body.rect ? skin.body.rect.slice() : [0, 0, W, Hc];         // the closed body
  const ppm = num(b3.px_per_mm, skin.body && skin.body.mm ? br[2] / skin.body.mm[0] : 3.5);
  const depth = num(b3.thickness, Math.max(...b3.slabs.map(s => s.z[1])));
  const pieces = b3.slabs.map(s => {
    const e = s.edges || {}, f = e.front || {}, b = e.back || {};
    return {
      id: s.id, of: s.of || null, label: s.label || s.id,
      outline: typeof s.outline === 'string' ? s.outline : softRect(s.rect, s.corners || {}),
      z0: depth - s.z[1], z1: depth - s.z[0],                                       // from the back, for the geometry
      edge: Math.max(0, num(f.radius, 0)), edgeBack: Math.max(0, num(b.radius, 0)),
      chamfer: f.chamfer > 0 && f.material ? f.material : null,
      chamferBack: b.chamfer > 0 && b.material ? b.material : null,
      materials: s.materials || {},
    };
  });
  const parts = pieces.filter(p => !p.of).map(p => ({
    id: p.id, moving: mover === p.id, pieces: [p, ...pieces.filter(q => q.of === p.id)], materials: p.materials,
  }));
  const list = Array.isArray(b3.views) ? b3.views : [];
  const viewOf = test => list.find(test) || null;
  const turnY = hinge ? hg.axis_y + hinge.pivot[1] : 0;
  for (const p of parts) {
    const f = p.materials.front, b = p.materials.back;
    // the lid of a flip: its back is its inner face, seen when open, turned over the hinge line (no mirroring left to right)
    p.backTurned = !!hinge && p.moving;
    p.front = typeof f === 'string' && /\.svg$/i.test(f) ? f : null;
    // the back: the slab's own layer seen from behind (rear.svg, under.svg), else the whole phone's back for the slab that
    // does not move; a material's name otherwise
    const layer = viewOf(v => v.look === 'back' && v.layer === p.id);
    const whole = !p.moving ? viewOf(v => v.look === 'back' && v.state === 'closed') : null;
    p.back = typeof b === 'string' && /\.svg$/i.test(b) ? b : layer ? layer.image : whole ? whole.image : null;
    // the finish of each face: its own material (front_material, back_material), else the walls' (the front) or the
    // shell (the back); a back given as a material's name is that material
    const named = v => (typeof v === 'string' ? v : null), M = p.materials;
    p.backMaterial = named(M.back_material) || (typeof b === 'string' && !/\.svg$/i.test(b) ? b : null);
    p.sideMaterial = named(M.side);
    p.frontMaterial = named(M.front_material) || p.sideMaterial;
    // the picture the 2D page draws of the front, light drawn in, where `front` is its albedo (a flip's closed.svg)
    p.front2d = typeof M.front_2d === 'string' && /\.svg$/i.test(M.front_2d) ? M.front_2d : null;
    // a face of several finishes (finishFace()): its mask, relief and crown
    const fin = f => (f && typeof f === 'object' && (typeof f.mask === 'string' || typeof f.relief === 'string' || Array.isArray(f.crown)) ? f : null);
    p.finishes = { front: fin(M.front_finish), back: fin(M.back_finish) };
  }
  const sides = {};
  for (const s of SIDES) { const v = viewOf(x => x.look === s && (x.state === 'closed' || (!x.state && !x.layer))); if (v) sides[s] = v.image; }
  const keys = {};
  for (const p of parts) keys[p.id] = {};
  const moving = parts.find(p => p.moving) || parts[0], still = parts.find(p => !p.moving) || parts[0];
  // the keys of the front: those that ride on the moving slab are where the open picture has them (the slab's closed
  // place); those of the slab that stays are lower by the travel in the open picture (a flip: every key is on the base)
  for (const [name, r] of Object.entries(vo.keys || {})) {
    if (sl && name in (vc.keys || {})) keys[moving.id][name] = r;
    else keys[still.id][name] = [r[0], r[1] - T, r[2], r[3]];
  }
  // the keys as solids (body3d.caps, the side keys with `proud`) and the wells, each with its slab
  const sideKeys = Array.isArray(b3.keys) ? b3.keys : [];
  for (const piece of pieces) { piece.caps = []; piece.wells = []; piece.bars = []; piece.inlays = []; piece.features = []; piece.lamps = []; piece.pockets = []; piece.openings = []; }
  const pieceOf = id => pieces.find(q => q.id === id);
  for (const w of Array.isArray(b3.wells) ? b3.wells : []) {
    const q = pieceOf(w.slab);
    if (q && typeof w.outline === 'string' && w.depth > 0) q.wells.push({ outline: w.outline, depth: w.depth, material: w.material || 'shell' });
  }
  for (const x of Array.isArray(b3.inlays) ? b3.inlays : []) {
    const q = pieceOf(x.slab);
    if (q && typeof x.outline === 'string') q.inlays.push({ outline: x.outline, back: x.face === 'back', material: x.material || 'shell', brush: x.brush || null });
  }
  // the camera and the flash on the back: on the slab that has the back face (not a part of another, not the one that moves);
  // the light window on a front (`lamp`), the earpiece's slot in a front or the lid's inner face, the USB-C receptacle in a wall
  const rear = pieces.find(x => !x.of && x.id !== mover) || pieces[0];
  for (const f of Array.isArray(b3.features) ? b3.features : []) {
    const q = pieceOf(f.slab);
    if (f.look === 'back' && typeof f.outline === 'string' && f.proud > 0) rear.features.push(f);
    else if (f.id === 'lamp' && q && typeof f.outline === 'string' && f.proud > 0) q.lamps.push(f);
    else if (f.id === 'earpiece' && q && typeof f.outline === 'string' && f.depth > 0) q.pockets.push(Object.assign({ back: f.look === 'inner' }, f));
    else if (f.id === 'usb_c' && q && SIDES.includes(f.side) && Array.isArray(f.z) && Array.isArray(f.size)) q.openings.push(f);
  }
  for (const c of Array.isArray(b3.caps) ? b3.caps : []) {
    const q = pieceOf(c.slab), names = [].concat(c.key || []);
    if (q && names.length && typeof c.outline === 'string' && Array.isArray(c.z))
      q.caps.push({ keys: names, outline: c.outline, z: c.z, edge: Math.max(0, num(c.edge, 0.15)), dome: Math.max(0, num(c.dome, 0)), material: c.material || 'shell' });
  }
  for (const k of sideKeys) {
    const span = k.y || k.x, zm = k.z ? (k.z[0] + k.z[1]) / 2 : NaN;
    if (!(k.proud > 0) || !span || !SIDES.includes(k.side) || !isFinite(zm)) continue;
    const q = pieces.find(x => !x.of && depth - x.z1 <= zm && zm <= depth - x.z0) || pieces.find(x => depth - x.z1 <= zm && zm <= depth - x.z0);
    if (q) q.bars.push({ keys: [k.key], side: k.side, span, z: k.z, proud: k.proud, ends: k.ends || 'both', material: k.material || 'shell' });
  }
  const ids = (skin.variants || []).map(v => v.id);
  let joint = null, hingeParts = null;
  if (slide) joint = { type: 'slide', part: slide.moves, axis: slide.axis || [0, -1, 0], travel: num(slide.travel_mm, T / ppm) };
  else if (hinge) {
    const [px, py, pz] = hinge.pivot, ang = Array.isArray(hinge.angle) ? hinge.angle : [0, num(hg.open_deg, 180)];
    // closed and open as body3d has them; `flat`, the open angle the 2D page draws (the open picture: the lid opened flat)
    joint = { type: 'hinge', part: hinge.moves, axis: hinge.axis || [1, 0, 0], pivot: [px / ppm, -py / ppm, depth - pz],
      closed: num(ang[0], 0), open: num(ang[1], 180), flat: 180 };
    const R = num(hinge.radius, 8 / ppm), round = (v, d) => (Array.isArray(v) ? [num(v[0], d), num(v[1], d)] : [num(v, d), num(v, d)]);
    hingeParts = {
      R, centre: [py, pz],
      barrel: hinge.barrel && Array.isArray(hinge.barrel.x) ? { x: hinge.barrel.x, round: round(hinge.barrel.round, 0.2), material: hinge.barrel.material || 'satin' } : null,
      knuckles: (Array.isArray(hinge.knuckles) ? hinge.knuckles : []).filter(k => Array.isArray(k.x)).map(k => ({ x: k.x, round: round(k.round, 0.2), material: k.material || 'shell' })),
      pin: hinge.pin && hinge.pin.r > 0 ? { r: hinge.pin.r, material: hinge.pin.material || 'spun' } : null,
      strip: hg.base || null, barrelPicture: hg.barrel || null,
    };
  }
  return {
    skin, b3, sl, hg, T, W, Ho, Hc, upm: ppm, depth, br, parts, keys, sides, sideKeys, turnY,
    glass: { part: moving.id, rect: vo.glass, turned: !!hinge },
    joint, hinge: hingeParts,
    // the plane that faces the viewer at rest: the front face, or, for an open flip, the base's front and the lid's inner
    // face, which the lid opened flat brings level with it
    frontAt: p => (hinge ? depth - (depth - still.pieces[0].z1) * clamp(p, 0, 1) : depth),
    // how much taller than closed the phone is at p (the open picture's frame): the slide's travel, or a flip's lid end
    grow: p => {
      if (!hinge) return T * p;
      const len = hg.axis_y - br[1], top = hg.axis_y - len * Math.cos(Math.PI * (1 - clamp(p, 0, 1)));
      return clamp(T + br[1] - top, 0, T);
    },
    materials: b3.materials || {},
    variants: skin.variants || [], defaultVariant: skin.default_variant || ids[0] || '',
  };
}

// The joints: where the moving part is at position p (0 closed .. 1 open), as its group's transform in mm. A slide moves it
// along `axis` (picture x, y and depth z: [0, -1, 0] is up) by `travel` mm. A hinge turns it about `axis` through `pivot`
// (in mm: x right, y up, z out of the front) by closed + (open - closed) * p degrees: the group is turned and moved so
// that the pivot stays where it is (its meshes are where they are when closed). The turn is the one of docs/SKINS_3D.md
// ("The turn"), towards the viewer. s (0 facing front at rest .. 1 turned) mixes the open angle: at rest it is the angle
// the 2D page draws (the lid flat), so that the swap between the two is seamless; turned, the lid stands at its true angle.
const JOINTS = {
  slide(group, j, p) {
    const d = j.travel * p, a = j.axis;
    group.position.set(a[0] * d, -a[1] * d, -a[2] * d);
  },
  hinge(group, j, p, s = 1) {
    const a = hingeAngle(j, p, s) * DEG;
    const axis = new THREE.Vector3(j.axis[0], -j.axis[1], -j.axis[2]).normalize(), P = new THREE.Vector3(...j.pivot);
    group.quaternion.setFromAxisAngle(axis, -a);
    group.position.copy(P).sub(P.clone().applyQuaternion(group.quaternion));
  },
};
/** The angle of a hinge (degrees) at p and s, as JOINTS.hinge turns it. */
export function hingeAngle(j, p, s = 1) { const open = j.flat + (j.open - j.flat) * s; return j.closed + (open - j.closed) * p; }

// ---- outlines: an SVG path (M L H V C S Q T A Z, absolute or relative) to points ----
function pathPoints(d, steps = 18) {
  const tok = d.match(/[MmLlHhVvCcSsQqTtAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?/g) || [];
  const out = [];
  let i = 0, cmd = '', x = 0, y = 0, sx = 0, sy = 0, cx = 0, cy = 0, qx = 0, qy = 0;
  const n = () => parseFloat(tok[i++]);
  const add = (px, py) => { const l = out[out.length - 1]; if (!l || Math.hypot(l[0] - px, l[1] - py) > 1e-6) out.push([px, py]); };
  while (i < tok.length) {
    if (/[A-Za-z]/.test(tok[i])) cmd = tok[i++];
    const rel = cmd === cmd.toLowerCase(), C = cmd.toUpperCase(), ox = rel ? x : 0, oy = rel ? y : 0;
    if (C === 'Z') { x = sx; y = sy; continue; }
    if (C === 'M') { x = ox + n(); y = oy + n(); sx = x; sy = y; if (out.length) break; add(x, y); cmd = rel ? 'l' : 'L'; }
    else if (C === 'L') { x = ox + n(); y = oy + n(); add(x, y); }
    else if (C === 'H') { x = ox + n(); add(x, y); }
    else if (C === 'V') { y = oy + n(); add(x, y); }
    else if (C === 'C' || C === 'S') {
      let x1, y1;
      if (C === 'C') { x1 = ox + n(); y1 = oy + n(); } else { x1 = 2 * x - cx; y1 = 2 * y - cy; }
      const x2 = ox + n(), y2 = oy + n(), x3 = ox + n(), y3 = oy + n();
      for (let k = 1; k <= steps; k++) {
        const t = k / steps, u = 1 - t;
        add(u * u * u * x + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x3, u * u * u * y + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * y3);
      }
      cx = x2; cy = y2; x = x3; y = y3; qx = x; qy = y; continue;
    } else if (C === 'Q' || C === 'T') {
      let x1, y1;
      if (C === 'Q') { x1 = ox + n(); y1 = oy + n(); } else { x1 = 2 * x - qx; y1 = 2 * y - qy; }
      const x2 = ox + n(), y2 = oy + n();
      for (let k = 1; k <= steps; k++) { const t = k / steps, u = 1 - t; add(u * u * x + 2 * u * t * x1 + t * t * x2, u * u * y + 2 * u * t * y1 + t * t * y2); }
      qx = x1; qy = y1; x = x2; y = y2; cx = x; cy = y; continue;
    } else if (C === 'A') {
      const rx = Math.abs(n()), ry = Math.abs(n()), phi = n() * DEG, large = n(), sweep = n(), x2 = ox + n(), y2 = oy + n();
      arcPoints(x, y, rx, ry, phi, large, sweep, x2, y2, add);
      x = x2; y = y2;
    } else { i++; continue; }                                      // anything else: not used by the skins
    cx = x; cy = y; qx = x; qy = y;
  }
  const f = out[0], l = out[out.length - 1];
  if (out.length > 2 && Math.hypot(f[0] - l[0], f[1] - l[1]) < 1e-6) out.pop();
  return out;
}
// An elliptical arc of a path (SVG's endpoint form, converted to its centre), in steps of at most 8 degrees.
function arcPoints(x1, y1, rx, ry, phi, large, sweep, x2, y2, add) {
  if (!rx || !ry || (x1 === x2 && y1 === y2)) { add(x2, y2); return; }
  const c = Math.cos(phi), s = Math.sin(phi), dx = (x1 - x2) / 2, dy = (y1 - y2) / 2;
  const xp = c * dx + s * dy, yp = -s * dx + c * dy, lam = xp * xp / (rx * rx) + yp * yp / (ry * ry);
  if (lam > 1) { rx *= Math.sqrt(lam); ry *= Math.sqrt(lam); }
  const a = rx * rx * yp * yp + ry * ry * xp * xp;
  let k = Math.sqrt(Math.max(0, (rx * rx * ry * ry - a) / a));
  if (!!large === !!sweep) k = -k;
  const cxp = k * rx * yp / ry, cyp = -k * ry * xp / rx;
  const cx = c * cxp - s * cyp + (x1 + x2) / 2, cy = s * cxp + c * cyp + (y1 + y2) / 2;
  const ang = (ux, uy, vx, vy) => Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy);
  const t1 = ang(1, 0, (xp - cxp) / rx, (yp - cyp) / ry);
  let dt = ang((xp - cxp) / rx, (yp - cyp) / ry, (-xp - cxp) / rx, (-yp - cyp) / ry);
  if (!sweep && dt > 0) dt -= 2 * Math.PI; else if (sweep && dt < 0) dt += 2 * Math.PI;
  const steps = Math.max(2, Math.ceil(Math.abs(dt) / (8 * DEG)));
  for (let i = 1; i <= steps; i++) {
    const t = t1 + dt * i / steps, ex = rx * Math.cos(t), ey = ry * Math.sin(t);
    add(c * ex - s * ey + cx, s * ex + c * ey + cy);
  }
}
// A plan [x, y, w, h] with the soft corners of the drawings ({top: [e, k], bottom: [e, k]}: each corner leaves its edges e
// px from the corner point, its control points k * e from it), as a path. Used when a slab gives no `outline`.
function softRect([x, y, w, h], corners) {
  const [et, kt] = corners.top || [Math.min(w, h) / 4, 0.45], [eb, kb] = corners.bottom || [et, kt];
  const ct = et * kt, cb = eb * kb, x1 = x + w, y1 = y + h;
  return `M${x + et} ${y} H${x1 - et} C${x1 - ct} ${y} ${x1} ${y + ct} ${x1} ${y + et} V${y1 - eb} C${x1} ${y1 - cb} ${x1 - cb} ${y1} ${x1 - eb} ${y1} ` +
    `H${x + eb} C${x + cb} ${y1} ${x} ${y1 - cb} ${x} ${y1 - eb} V${y + et} C${x} ${y + ct} ${x + ct} ${y} ${x + et} ${y} Z`;
}

// ---- geometry: one buffer for each slab, with its wells and keys in it ----
// Positions in mm (x right, y up, z out of the front); in picture px x = X * upm, y = -Y * upm. Material slots (groups):
// 0 front, 1 back, 2..5 the walls seen from the left, right, top, bottom (all 2 when there are no side views), 6 the facet
// on the front edge (o.chamfer), 7 and up the plain materials of the keys' sides and the wells' walls (Viewer.slot()).
// uv: the front picture (or, where uvFn says, another: the flip's hinge strip), uv1: the back picture, uv2: the side picture
// of the wall's own side; color: a shade (ambient occlusion low on the sides of keys and wells and inside openings; only
// their materials use it); owner: the key cap of a vertex.
class Builder {
  constructor(o) { this.o = o; this.pos = []; this.nrm = []; this.tan = []; this.uv0 = []; this.uv1 = []; this.uv2 = []; this.col = []; this.own = []; this.groups = []; this.tanFn = null; this.uvFn = null; }
  get count() { return this.pos.length / 3; }
  vert(x, y, z, nx, ny, nz, side, shade = 1, owner = -1) {
    const o = this.o, u = x * o.upm, v = -y * o.upm;
    this.pos.push(x, y, z); this.nrm.push(nx, ny, nz);
    // the tangent: the direction the highlight of an anisotropic metal stretches in (radial on spun metal, across the
    // brushing on brushed metal), made perpendicular to the normal; along x where nothing says
    let t = this.tanFn ? this.tanFn(x, y, z, nx, ny, nz) : [1, 0, 0], d = t[0] * nx + t[1] * ny + t[2] * nz;
    t = [t[0] - d * nx, t[1] - d * ny, t[2] - d * nz];
    let l = Math.hypot(...t);
    if (l < 1e-6) { t = Math.abs(nx) < 0.9 ? [1 - nx * nx, -nx * ny, -nx * nz] : [-ny * nx, 1 - ny * ny, -ny * nz]; l = Math.hypot(...t) || 1; }
    this.tan.push(t[0] / l, t[1] / l, t[2] / l, 1);
    this.uv0.push(...(this.uvFn ? this.uvFn(u, v) : o.frontUV(u, v))); this.uv1.push(...o.backUV(u, v)); this.uv2.push(...o.sideUV(side, u, v, z));
    this.col.push(shade, shade, shade); this.own.push(owner);
    return this.count - 1;
  }
  tri(g, a, b, c, want) {                                           // keep the winding that faces `want`
    const pos = this.pos, A = a * 3, B = b * 3, C = c * 3, list = this.groups[g] || (this.groups[g] = []);
    const ux = pos[B] - pos[A], uy = pos[B + 1] - pos[A + 1], uz = pos[B + 2] - pos[A + 2];
    const vx = pos[C] - pos[A], vy = pos[C + 1] - pos[A + 1], vz = pos[C + 2] - pos[A + 2];
    const cx = uy * vz - uz * vy, cy = uz * vx - ux * vz, cz = ux * vy - uy * vx;
    if (cx * want[0] + cy * want[1] + cz * want[2] < 0) list.push(a, c, b); else list.push(a, b, c);
  }
  geometry() {
    const geo = new THREE.BufferGeometry(), index = [];
    this.groups.forEach((g, m) => { if (g && g.length) { geo.addGroup(index.length, g.length, m); for (const i of g) index.push(i); } });
    geo.setIndex(index);
    geo.setAttribute('position', new THREE.Float32BufferAttribute(this.pos, 3));
    geo.setAttribute('normal', new THREE.Float32BufferAttribute(this.nrm, 3));
    geo.setAttribute('tangent', new THREE.Float32BufferAttribute(this.tan, 4));
    geo.setAttribute('uv', new THREE.Float32BufferAttribute(this.uv0, 2));
    geo.setAttribute('uv1', new THREE.Float32BufferAttribute(this.uv1, 2));
    geo.setAttribute('uv2', new THREE.Float32BufferAttribute(this.uv2, 2));
    geo.setAttribute('color', new THREE.Float32BufferAttribute(this.col, 3));
    geo.userData.owner = Int16Array.from(this.own);
    geo.computeBoundingBox(); geo.computeBoundingSphere();
    return geo;
  }
}

// A plan (points in mm) counter-clockwise, with what each corner needs: its outward normals (na averaged, n0 and n1 of the
// edges before and after it), whether it is sharp, how far it may be inset (about its radius of curvature).
function plan(P) {
  let area = 0;
  for (let i = 0; i < P.length; i++) { const a = P[i], b = P[(i + 1) % P.length]; area += a[0] * b[1] - b[0] * a[1]; }
  if (area < 0) P = P.slice().reverse();
  const n = P.length, info = [];
  for (let i = 0; i < n; i++) {
    const a = P[(i + n - 1) % n], b = P[i], c = P[(i + 1) % n];
    const e0 = [b[0] - a[0], b[1] - a[1]], e1 = [c[0] - b[0], c[1] - b[1]];
    const l0 = Math.hypot(...e0) || 1e-9, l1 = Math.hypot(...e1) || 1e-9;
    const n0 = [e0[1] / l0, -e0[0] / l0], n1 = [e1[1] / l1, -e1[0] / l1];
    let na = [n0[0] + n1[0], n0[1] + n1[1]];
    const la = Math.hypot(...na) || 1e-9; na = [na[0] / la, na[1] / la];
    const turn = Math.acos(clamp(n0[0] * n1[0] + n0[1] * n1[1], -1, 1));
    const R = 0.5 * (l0 + l1) / Math.max(turn, 1e-4);
    const miter = 1 / Math.max(0.5, na[0] * n1[0] + na[1] * n1[1]);
    info.push({ p: b, na, n0, n1, sharp: turn > 35 * DEG, miter, R });
  }
  return info;
}

// Whether a point is inside a polygon (both in the same units).
function inside(p, poly) {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i], b = poly[j];
    if ((a[1] > p[1]) !== (b[1] > p[1]) && p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]) c = !c;
  }
  return c;
}
// The outward normal of a side wall in the geometry's frame (x right, y up), and how a wall opening's span along the side
// (picture px: x for top and bottom, y for left and right) becomes mm along it.
const OUT = { left: [-1, 0], right: [1, 0], top: [0, 1], bottom: [0, -1] };
// A plan (picture px) with points added where the openings' spans begin and end on their side's outermost straight edge, so
// that the wall has a quad edge there.
function splitPlan(pts, openings) {
  let out = pts.slice();
  for (const op of openings) {
    const vertical = op.side === 'left' || op.side === 'right', u = vertical ? 1 : 0, v = 1 - u, span = op.span;
    // the edge of that side: straight across the span, outermost
    let best = -1, bestV = 0;
    for (let i = 0; i < out.length; i++) {
      const a = out[i], b = out[(i + 1) % out.length];
      if (Math.abs(a[v] - b[v]) > 1e-6 || Math.min(a[u], b[u]) > span[0] || Math.max(a[u], b[u]) < span[1]) continue;
      const far = op.side === 'right' || op.side === 'bottom' ? a[v] : -a[v];
      if (best < 0 || far > bestV) { best = i; bestV = far; }
    }
    if (best < 0) continue;
    const a = out[best], b = out[(best + 1) % out.length], dir = Math.sign(b[u] - a[u]);
    const add = span.slice().sort((x, y) => dir * (x - y)).map(s => { const p = a.slice(); p[u] = s; return p; });
    out = [...out.slice(0, best + 1), ...add, ...out.slice(best + 1)];
  }
  return out;
}

// A slab: its front and back caps (with the holes of wells and slots cut out of them), the round edges and the walls (with
// the openings of the side features cut out of them).
function slabGeometry(B, pts, o) {
  const openings = o.openings || [];
  if (openings.length) pts = splitPlan(pts, openings);
  const info = plan(pts.map(([u, v]) => [u / o.upm, -v / o.upm]));
  for (const q of info) { q.inT = Math.min(o.edge, 0.9 * q.R); q.inB = Math.min(o.edgeBack, 0.9 * q.R); }
  const n = info.length;
  // the rings, from the front cap round the edge, down the wall, round the back edge to the back cap (and, where a wall
  // has an opening, a ring at each end of its depth)
  const rings = [];
  const S = BEVEL_STEPS;
  if (o.edge > 0) for (let j = 0; j <= S; j++) { const t = j / S * Math.PI / 2; rings.push({ f: 1 - Math.sin(t), b: false, z: o.z1 - o.edge * (1 - Math.cos(t)), nz: Math.cos(t), nh: Math.sin(t) }); }
  else rings.push({ f: 0, b: false, z: o.z1, nz: 0, nh: 1 });
  const zTop = rings[rings.length - 1].z, zBottom = o.z0 + o.edgeBack;
  const extra = [...new Set(openings.flatMap(op => [op.z0, op.z1]))].filter(z => z < zTop - 1e-6 && z > zBottom + 1e-6).sort((a, b) => b - a);
  for (const z of extra) rings.push({ f: 0, b: false, z, nz: 0, nh: 1 });
  if (o.edgeBack > 0) for (let j = 0; j <= S; j++) { const t = j / S * Math.PI / 2; rings.push({ f: 1 - Math.cos(t), b: true, z: o.z0 + o.edgeBack * (1 - Math.sin(t)), nz: -Math.sin(t), nh: Math.cos(t) }); }
  else rings.push({ f: 0, b: true, z: o.z0, nz: 0, nh: 1 });
  const at = (i, r) => { const q = info[i], d = (r.b ? q.inB : q.inT) * q.miter * r.f; return [q.p[0] - q.na[0] * d, q.p[1] - q.na[1] * d, r.z]; };
  // caps; each has the holes of its face (the wells' openings, the earpiece's slot), and the inlays of its face (flush
  // regions of another material: the glass pane, the slide plate), which are filled with their own slot; a hole inside an
  // inlay is cut out of the inlay
  const V2 = h => h.map(p => new THREE.Vector2(p[0], p[1]));
  for (const back of [false, true]) {
    const r = back ? rings[rings.length - 1] : rings[0], nz = back ? -1 : 1;
    const inlays = (o.inlays || []).filter(x => x.back === back).map(x => Object.assign({ holes: [] }, x)), holes = [];
    for (const h of (o.holes || []).filter(x => !!x.back === back)) {
      const box = inlays.find(x => inside(h.pts[0], x.pts));
      (box ? box.holes : holes).push(h.pts);
    }
    for (const x of inlays) holes.push(x.pts);
    const ring = info.map((q, i) => at(i, r));
    const faces = THREE.ShapeUtils.triangulateShape(V2(ring), holes.map(V2));
    const all = ring.map(p => B.vert(p[0], p[1], p[2], 0, 0, nz, 'front'));
    for (const h of holes) for (const p of h) all.push(B.vert(p[0], p[1], r.z, 0, 0, nz, 'front'));
    for (const f of faces) B.tri(back ? 1 : 0, all[f[0]], all[f[1]], all[f[2]], [0, 0, nz]);
    for (const x of inlays) {
      B.tanFn = x.tangent || null;
      const v = x.pts.map(p => B.vert(p[0], p[1], r.z, 0, 0, nz, 'front'));
      for (const h of x.holes) for (const p of h) v.push(B.vert(p[0], p[1], r.z, 0, 0, nz, 'front'));
      for (const f of THREE.ShapeUtils.triangulateShape(V2(x.pts), x.holes.map(V2))) B.tri(x.slot, v[f[0]], v[f[1]], v[f[2]], [0, 0, nz]);
      B.tanFn = null;
    }
  }
  // the facet on the front edge (and on the back edge, the lid's inner face) is brushed along the edge: its highlight
  // stretches across it
  B.tanFn = (x, y, z, nx, ny) => [nx, ny, 0];
  // edges and walls: each quad has its own four corners, so each can take the side picture of its own side
  const sideOf = (nx, ny) => (!o.sideViews ? 2 : Math.abs(nx) >= Math.abs(ny) ? (nx < 0 ? 2 : 3) : (ny > 0 ? 4 : 5));
  const normalAt = (i, r, other) => {                              // at corner i of the quad whose own normal is `other`
    const q = info[i], h = q.sharp ? other : q.na;
    const x = h[0] * r.nh, y = h[1] * r.nh, l = Math.hypot(x, y, r.nz) || 1;
    return [x / l, y / l, r.nz / l];
  };
  // a quad of the straight wall inside an opening's rectangle is left out (the opening's own face fills round it)
  const open = (i, k, r0, r1, segN) => r0.f === 0 && r1.f === 0 && !r0.b && !r1.b && openings.some(op => {
    const s = OUT[op.side], along = s[0] ? 1 : 0, a = info[i].p[along], b = info[k].p[along], e = 1e-4;
    return segN[0] * s[0] + segN[1] * s[1] > 0.999 && Math.min(a, b) >= op.a0 - e && Math.max(a, b) <= op.a1 + e &&
      Math.min(r0.z, r1.z) >= op.z0 - e && Math.max(r0.z, r1.z) <= op.z1 + e;
  });
  for (let i = 0; i < n; i++) {
    const k = (i + 1) % n, segN = info[i].n1;
    for (let j = 0; j + 1 < rings.length; j++) {
      const r0 = rings[j], r1 = rings[j + 1];
      if (openings.length && open(i, k, r0, r1, segN)) continue;
      const corners = [[i, r0], [k, r0], [k, r1], [i, r1]];
      const N = corners.map(([c, r]) => normalAt(c, r, segN));
      const m = N.reduce((s, v) => [s[0] + v[0], s[1] + v[1], s[2] + v[2]], [0, 0, 0]);
      const mz = m[2] / 4, facet = o.chamfer && !r0.b && !r1.b && mz > 0.2 && mz < 0.92;
      const facetBack = o.backFacet && r0.b && r1.b && mz < -0.2 && mz > -0.92;
      const g = facet ? 6 : facetBack ? o.backFacet : mz > 0.65 ? 0 : mz < -0.65 ? 1 : sideOf(m[0], m[1]);
      const side = g === 0 || g === 6 ? 'front' : g === 1 || facetBack ? 'back' : SIDES[g - 2] || 'left';
      const sideName = !o.sideViews && g >= 2 && g <= 5 ? (Math.abs(m[0]) >= Math.abs(m[1]) ? (m[0] < 0 ? 'left' : 'right') : (m[1] > 0 ? 'top' : 'bottom')) : side;
      const P0 = at(i, r0), P1 = at(k, r0), P2 = at(k, r1);
      if (Math.hypot(P1[0] - P0[0], P1[1] - P0[1], P1[2] - P0[2]) < 1e-7 && Math.hypot(P2[0] - P1[0], P2[1] - P1[1], P2[2] - P1[2]) < 1e-7) continue;
      const idx = corners.map(([c, r], q) => { const p = at(c, r); return B.vert(p[0], p[1], p[2], N[q][0], N[q][1], N[q][2], sideName); });
      B.tri(g, idx[0], idx[1], idx[2], m); B.tri(g, idx[0], idx[2], idx[3], m);
    }
  }
  B.tanFn = null;
}

// Rings round a plan (a, b) at heights w, joined by quads: a key's sides and the round of its top edge, a well's walls. A
// ring: inset (mm, inwards), w, the normal's part along the plan's outward normal (nh) and along w (nw), shade. Corners
// stay smooth except the sharp ones, which get a normal for each of their two edges. F maps a point to the slab's frame:
// F.at(a, b, w) -> [x, y, z], F.dir(na, nb, nw) -> [nx, ny, nz], F.side (the side picture), F.group(j) (the slot of band j).
// Returns the last ring's vertices and points.
function loft(B, info, rings, F, owner) {
  const n = info.length, made = [];
  for (const r of rings) {
    const row = [];
    for (const q of info) {
      const d = Math.min(r.inset, 0.9 * q.R) * q.miter, a = q.p[0] - q.na[0] * d, b = q.p[1] - q.na[1] * d, p = F.at(a, b, r.w);
      const v = h => { const N = F.dir(h[0] * r.nh, h[1] * r.nh, r.nw), l = Math.hypot(...N) || 1; return B.vert(p[0], p[1], p[2], N[0] / l, N[1] / l, N[2] / l, F.side, r.shade, owner); };
      const one = q.sharp ? null : v(q.na);
      row.push({ before: one ?? v(q.n0), after: one ?? v(q.n1), ab: [a, b] });
    }
    made.push(row);
  }
  for (let j = 0; j + 1 < rings.length; j++) {
    const g = F.group(j), mn = 0.5 * (rings[j].nw + rings[j + 1].nw);
    for (let i = 0; i < n; i++) {
      const k = (i + 1) % n, a = made[j][i].after, b = made[j][k].before, c = made[j + 1][k].before, d = made[j + 1][i].after;
      const h = info[i].n1, mh = 0.5 * (rings[j].nh + rings[j + 1].nh), want = F.dir(h[0] * mh, h[1] * mh, mn);
      B.tri(g, a, b, c, want); B.tri(g, a, c, d, want);
    }
  }
  return made[made.length - 1];
}

// A well: walls from the front down to its floor, in shade low down, and the floor, which shows the front picture.
function wellGeometry(B, P, o) {
  const info = plan(P), F = { at: (a, b, w) => [a, b, w], dir: (x, y, z) => [x, y, z], side: 'front', group: () => o.wall };
  const floor = o.top - o.depth;
  const last = loft(B, info, [{ inset: 0, w: o.top, nh: -1, nw: 0, shade: 0.8 }, { inset: 0, w: floor, nh: -1, nw: 0, shade: 0.4 }], F, -1);
  const faces = THREE.ShapeUtils.triangulateShape(last.map(x => new THREE.Vector2(x.ab[0], x.ab[1])), []);
  const base = last.map(x => B.vert(x.ab[0], x.ab[1], floor, 0, 0, 1, 'front'));
  for (const f of faces) B.tri(0, base[f[0]], base[f[1]], base[f[2]], [0, 0, 1]);
}

// The middle of a plan: of its box (the spun parts are symmetric; the mean of their points would follow how finely each
// part of the outline happens to be divided).
function middle(P) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of P) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  return [(x0 + x1) / 2, (y0 + y1) / 2];
}
// The tangents of spun metal round the axis `axis` through C: out from the axis in the plane across it (the highlight is a
// cone through the middle), and along the axis on a wall that faces out from it (the turning runs round the wall). The
// part of a point's offset along the axis is taken out first: on a domed top or a bevel the offset also points up or down,
// and near the middle that part would be most of it (the tangent would fall back to an arbitrary direction there).
function radialTangent(C, axis) {
  const A = Math.hypot(...axis) || 1, ax = axis.map(v => v / A);
  return (x, y, z, nx, ny, nz) => {
    if (Math.abs(nx * ax[0] + ny * ax[1] + nz * ax[2]) < 0.5) return ax;
    const r = [x - C[0], y - C[1], z - C[2]], h = r[0] * ax[0] + r[1] * ax[1] + r[2] * ax[2];
    return [r[0] - h * ax[0], r[1] - h * ax[1], r[2] - h * ax[2]];
  };
}

// A key: its sides up from its foot (a shade at the foot), the round of its top edge and its top, flat or domed (`dome` mm
// higher in the middle: the coin). The top and the round show the picture of the face the key is in (group o.top); the
// sides are the key's material (o.wall). F: the frame (loft()). Returns the range of its vertices.
function capGeometry(B, P, o, F, owner) {
  if (o.radial) {
    // spun metal: the highlight stretches out from the middle; its tangents turn round it, so the outline gets a point
    // every 2.5 degrees round the middle (the highlight's line stays straight, not stepped by the triangles)
    const [cx, cy] = middle(P);
    const Q = [];
    for (let i = 0; i < P.length; i++) {
      const a = P[i], b = P[(i + 1) % P.length];
      const turn = Math.abs(wrap(Math.atan2(b[1] - cy, b[0] - cx) - Math.atan2(a[1] - cy, a[0] - cx)));
      const n = Math.max(1, Math.ceil(turn / (2.5 * DEG)));
      for (let k = 0; k < n; k++) Q.push([a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n]);
    }
    P = Q;
  }
  const info = plan(P), start = B.count, e = Math.max(0, Math.min(o.edge, (o.w1 - o.w0) * 0.8));
  if (o.radial) {                                                  // the tangents: out from the middle
    const [cx, cy] = middle(P);
    B.tanFn = radialTangent(F.at(cx, cy, o.w1), F.dir(0, 0, 1));
  }
  const rings = [{ inset: 0, w: o.w0, nh: 1, nw: 0, shade: 0.45 }, { inset: 0, w: o.w1 - e, nh: 1, nw: 0, shade: 1 }];
  for (let j = 1; j <= KEY_BEVEL && e > 0; j++) { const t = j / KEY_BEVEL * Math.PI / 2; rings.push({ inset: e * (1 - Math.cos(t)), w: o.w1 - e * (1 - Math.sin(t)), nh: Math.cos(t), nw: Math.sin(t), shade: 1 }); }
  const G = Object.assign({}, F, { group: j => (j === 0 ? o.wall : o.top) });
  const last = loft(B, info, rings, G, owner);
  const pts = last.map(x => x.ab), top = o.top;
  if (o.dome > 0) {
    // the dome: rings drawn in towards the middle, each higher by dome * (1 - s^2), and the middle
    const [cx, cy] = middle(pts);
    const K = 7;
    let prev = last.map(x => x.after);
    for (let k = 1; k <= K; k++) {
      const s = 1 - k / K, row = [];
      for (const p of pts) {
        const ra = p[0] - cx, rb = p[1] - cy, r0 = Math.hypot(ra, rb) || 1, slope = 2 * o.dome * s / r0;
        const at = F.at(cx + ra * s, cy + rb * s, o.w1 + o.dome * (1 - s * s)), N = F.dir(ra / r0 * slope, rb / r0 * slope, 1), l = Math.hypot(...N);
        row.push(k === K ? null : B.vert(at[0], at[1], at[2], N[0] / l, N[1] / l, N[2] / l, F.side, 1, owner));
      }
      if (k === K) {
        // the middle: one vertex for each triangle of the fan, its tangent out along that triangle's middle (spun metal has
        // no direction at the very centre; one shared vertex would take some direction and pull the highlight towards it)
        const at = F.at(cx, cy, o.w1 + o.dome), N = F.dir(0, 0, 1), was = B.tanFn;
        for (let i = 0; i < pts.length; i++) {
          const q = pts[(i + 1) % pts.length], ra = (pts[i][0] + q[0]) / 2 - cx, rb = (pts[i][1] + q[1]) / 2 - cy;
          if (o.radial) B.tanFn = () => F.dir(ra, rb, 0);
          const c = B.vert(at[0], at[1], at[2], N[0], N[1], N[2], F.side, 1, owner);
          B.tri(top, prev[i], prev[(i + 1) % pts.length], c, N);
        }
        B.tanFn = was;
      } else {
        for (let i = 0; i < pts.length; i++) {
          const j = (i + 1) % pts.length, N = F.dir(0, 0, 1);
          B.tri(top, prev[i], prev[j], row[j], N); B.tri(top, prev[i], row[j], row[i], N);
        }
        prev = row;
      }
    }
  } else {
    const holes = o.holes || [], N = F.dir(0, 0, 1);
    const faces = THREE.ShapeUtils.triangulateShape(pts.map(p => new THREE.Vector2(p[0], p[1])), holes.map(h => h.map(p => new THREE.Vector2(p[0], p[1]))));
    const all = last.map(x => x.after);
    for (const h of holes) for (const p of h) { const q = F.at(p[0], p[1], o.w1); all.push(B.vert(q[0], q[1], q[2], N[0], N[1], N[2], F.side, 1, owner)); }
    for (const f of faces) B.tri(top, all[f[0]], all[f[1]], all[f[2]], N);
  }
  B.tanFn = null;
  return [start, B.count];
}

// A jewel-cut window (a light window with `cut: "jewel"`), round (cx, cy) of radius r (mm, in the face's frame F): a girdle
// of o.n flat sides from o.w0 up to o.girdle; over it a crown of 2n flat facets (n star facets on the girdle's edges, n
// upper facets between them) rising o.crown mm to a flat table of o.n sides, o.table of the radius across, turned half a
// facet. Each facet has its own normal, so each catches the room's light boxes on its own as the phone turns. Slot o.slot.
function jewelGeometry(B, cx, cy, r, o, F) {
  const n = Math.max(5, Math.round(o.n)), top = o.girdle + o.crown, rt = r * o.table;
  const g = i => { const a = 2 * Math.PI * i / n; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; };
  const t = i => { const a = 2 * Math.PI * (i + 0.5) / n; return [cx + rt * Math.cos(a), cy + rt * Math.sin(a)]; };
  const facet = pts => {
    const P = pts.map(([a, b, w]) => F.at(a, b, w));
    const u = P[1].map((v, k) => v - P[0][k]), v = P[2].map((q, k) => q - P[0][k]);
    let N = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
    const l = Math.hypot(...N) || 1, out = F.dir(0, 0, 1);
    N = N.map(q => q / l);
    // outwards: away from the axis on the girdle, up on the crown
    const mx = pts.reduce((s, q) => s + q[0], 0) / pts.length - cx, my = pts.reduce((s, q) => s + q[1], 0) / pts.length - cy;
    const away = F.dir(mx, my, 0), up = N[0] * out[0] + N[1] * out[1] + N[2] * out[2];
    if (up < -1e-3 || (Math.abs(up) <= 1e-3 && N[0] * away[0] + N[1] * away[1] + N[2] * away[2] < 0)) N = N.map(q => -q);
    const idx = P.map(q => B.vert(q[0], q[1], q[2], N[0], N[1], N[2], F.side));
    for (let k = 1; k + 1 < idx.length; k++) B.tri(o.slot, idx[0], idx[k], idx[k + 1], N);
  };
  for (let i = 0; i < n; i++) {
    const a = g(i), b = g(i + 1), c = t(i), d = t(i - 1);
    facet([[a[0], a[1], o.w0], [b[0], b[1], o.w0], [b[0], b[1], o.girdle], [a[0], a[1], o.girdle]]);   // the girdle
    facet([[a[0], a[1], o.girdle], [b[0], b[1], o.girdle], [c[0], c[1], top]]);                          // a star facet
    facet([[d[0], d[1], top], [a[0], a[1], o.girdle], [c[0], c[1], top]]);                               // an upper facet
  }
  facet(Array.from({ length: n }, (_, i) => { const q = t(i); return [q[0], q[1], top]; }));             // the table
}

// The camera on the back: a ring of spun metal standing proud (outline P, the Myna sign), its top cut by a round hole
// whose bevel goes down to the lens, a disc of coated glass `depth` under the ring's top. F: the back's frame.
function cameraGeometry(B, P, o, F) {
  const [cx, cy] = middle(P);
  const circle = (r, n = 144) => Array.from({ length: n }, (_, i) => [cx + r * Math.cos(2 * Math.PI * i / n), cy + r * Math.sin(2 * Math.PI * i / n)]);
  const hole = circle(o.lens + o.bevel);
  capGeometry(B, P, { w0: -0.05, w1: o.proud, edge: o.edge, dome: 0, top: o.ring, wall: o.ring, radial: true, holes: [hole] }, F, -1);
  // the bevel: from the hole's edge in and down to the lens, polished
  const run = o.bevel, l = Math.hypot(run, o.depth);
  B.tanFn = radialTangent(F.at(cx, cy, o.proud), F.dir(0, 0, 1));
  const last = loft(B, plan(hole), [{ inset: 0, w: o.proud, nh: -o.depth / l, nw: run / l, shade: 1 }, { inset: run, w: o.proud - o.depth, nh: -o.depth / l, nw: run / l, shade: 0.6 }],
    Object.assign({}, F, { group: () => o.bevelSlot }), -1);
  B.tanFn = null;
  // the lens: its glass shows the back picture's lens (the coated element, the aperture)
  const pts = last.map(x => x.ab), N = F.dir(0, 0, 1);
  const v = pts.map(p => { const q = F.at(p[0], p[1], o.proud - o.depth); return B.vert(q[0], q[1], q[2], N[0], N[1], N[2], F.side); });
  for (const f of THREE.ShapeUtils.triangulateShape(pts.map(p => new THREE.Vector2(p[0], p[1])), [])) B.tri(o.lensSlot, v[f[0]], v[f[1]], v[f[2]], N);
}

// A plan grown outwards by d (mm), as loft() insets it (its corners keep their round).
function grown(info, d) { return info.map(q => { const k = Math.min(-d, 0.9 * q.R) * q.miter; return [q.p[0] - q.na[0] * k, q.p[1] - q.na[1] * k]; }); }
// A slot cut into a face (the earpiece): the face's hole is the slot's plan grown by the round of its edge; the round turns
// from the face (slot o.face: the face's own, glass) down into the slot's walls (o.wall), which go down `depth` to its
// floor (o.floor: the grille behind it). F: the face's frame, w out of the face (0 at the face). Returns the face's hole.
function pocketGeometry(B, P, o, F) {
  const info = plan(P), e = Math.max(0, o.edge), rings = [];
  for (let j = 0; j <= 4 && e > 0; j++) { const t = j / 4 * Math.PI / 2; rings.push({ inset: -e + e * Math.sin(t), w: -e + e * Math.cos(t), nh: -Math.sin(t), nw: Math.cos(t), shade: 1 - 0.15 * j / 4 }); }
  if (!rings.length) rings.push({ inset: 0, w: 0, nh: -1, nw: 0, shade: 0.85 });
  rings.push({ inset: 0, w: -o.depth, nh: -1, nw: 0, shade: 0.35 });
  const last = loft(B, info, rings, Object.assign({}, F, { group: j => (j < rings.length - 2 ? o.face : o.wall) }), -1);
  const pts = last.map(x => x.ab), N = F.dir(0, 0, 1);
  const v = pts.map(p => { const q = F.at(p[0], p[1], -o.depth); return B.vert(q[0], q[1], q[2], N[0], N[1], N[2], F.side, 0.8); });
  for (const f of THREE.ShapeUtils.triangulateShape(pts.map(p => new THREE.Vector2(p[0], p[1])), [])) B.tri(o.floor, v[f[0]], v[f[1]], v[f[2]], N);
  return e > 0 ? grown(info, e) : pts;
}

// A stadium (a rectangle with round ends) w by h round (a, b), as a plan.
function stadium(a, b, w, h, n = 14) {
  const r = h / 2, out = [];
  for (let i = 0; i <= n; i++) { const t = -Math.PI / 2 + Math.PI * i / n; out.push([a + w / 2 - r + r * Math.cos(t), b + r * Math.sin(t)]); }
  for (let i = 0; i <= n; i++) { const t = Math.PI / 2 + Math.PI * i / n; out.push([a - w / 2 + r + r * Math.cos(t), b + r * Math.sin(t)]); }
  return out;
}
// A USB-C receptacle in a side wall: the opening (a stadium) in a rectangle of the wall that the wall leaves out (its own
// face fills round the opening, in the wall's slot and side picture), the receptacle's steel shell standing a little back
// in it (its lip, then its inside going in), its dark floor, and the tongue across the middle. F: the wall's frame, a and b
// across the wall, w into the phone (0 at the wall). o: the opening's rectangle (a0 a1 b0 b1), its size (w, h), how deep.
function usbGeometry(B, o, F) {
  const ac = (o.a0 + o.a1) / 2, bc = (o.b0 + o.b1) / 2, V2 = h => h.map(p => new THREE.Vector2(p[0], p[1]));
  const hole = stadium(ac, bc, o.w, o.h), out = F.dir(0, 0, -1);
  const rect = [[o.a0, o.b0], [o.a1, o.b0], [o.a1, o.b1], [o.a0, o.b1]];
  const face = rect.concat(hole).map(p => { const q = F.at(p[0], p[1], 0); return B.vert(q[0], q[1], q[2], out[0], out[1], out[2], F.side); });
  for (const f of THREE.ShapeUtils.triangulateShape(V2(rect), [V2(hole)])) B.tri(o.wallSlot, face[f[0]], face[f[1]], face[f[2]], out);
  const info = plan(hole), lip = o.lip, t = o.shell;
  // the opening's edge down to the shell's lip, the lip (a ring of steel), the shell's inside, its floor
  loft(B, info, [{ inset: 0, w: 0, nh: -1, nw: 0, shade: 0.9 }, { inset: 0, w: lip, nh: -1, nw: 0, shade: 0.8 }], Object.assign({}, F, { group: () => o.inside }), -1);
  const ring = [grown(info, 0), grown(info, -t)].map(r => r.map(p => F.at(p[0], p[1], lip)));
  const iv = [...ring[0], ...ring[1]].map(q => B.vert(q[0], q[1], q[2], out[0], out[1], out[2], F.side));
  for (const f of THREE.ShapeUtils.triangulateShape(V2(grown(info, 0)), [V2(grown(info, -t))])) B.tri(o.steel, iv[f[0]], iv[f[1]], iv[f[2]], out);
  const inner = plan(grown(info, -t));
  // inside, the light of the room hardly reaches: shaded deeper in (o.inside: the steel with vertex shade)
  const last = loft(B, inner, [{ inset: 0, w: lip, nh: -1, nw: 0, shade: 0.45 }, { inset: 0, w: o.depth * 0.25, nh: -1, nw: 0, shade: 0.12 },
    { inset: 0, w: o.depth, nh: -1, nw: 0, shade: 0.04 }], Object.assign({}, F, { group: () => o.inside }), -1);
  const fl = last.map(x => x.ab), fv = fl.map(p => { const q = F.at(p[0], p[1], o.depth); return B.vert(q[0], q[1], q[2], out[0], out[1], out[2], F.side, 0.15); });
  for (const f of THREE.ShapeUtils.triangulateShape(V2(fl), [])) B.tri(o.dark, fv[f[0]], fv[f[1]], fv[f[2]], out);
  // the tongue: from the floor towards the opening, stopping short of the lip
  const G = { at: (a, b, w) => F.at(a, b, o.depth - w), dir: (na, nb, nw) => F.dir(na, nb, -nw), side: F.side };
  const tw = o.tongue[0], th = o.tongue[1], r = th * 0.45;
  const tp = [[ac - tw / 2 + r, bc - th / 2], [ac + tw / 2 - r, bc - th / 2], [ac + tw / 2, bc - th / 2 + r], [ac + tw / 2, bc + th / 2 - r],
    [ac + tw / 2 - r, bc + th / 2], [ac - tw / 2 + r, bc + th / 2], [ac - tw / 2, bc + th / 2 - r], [ac - tw / 2, bc - th / 2 + r]];
  capGeometry(B, tp, { w0: -0.02, w1: o.depth - o.tongueBack, edge: 0.08, dome: 0, top: o.dark, wall: o.dark }, G, -1);
}

// A cylinder on an axis along x (the hinge's barrel and knuckles): from x0 to x1 (mm), radius R round (cy, cz), each end
// rounded by its own radius (ends: [left, right]) into a flat end. Slot o.slot for all of it.
function cylinderGeometry(B, o) {
  const N = 48, S = 4, prof = [];                                   // the profile: [x, radius, normal x, normal radial]
  const [e0, e1] = o.ends.map(e => Math.max(0.01, Math.min(e, o.R * 0.9)));
  prof.push([o.x0, 0, -1, 0]);
  for (let j = 0; j <= S; j++) { const t = j / S * Math.PI / 2; prof.push([o.x0 + e0 - e0 * Math.cos(t), o.R - e0 + e0 * Math.sin(t), -Math.cos(t), Math.sin(t)]); }
  for (let j = 0; j <= S; j++) { const t = j / S * Math.PI / 2; prof.push([o.x1 - e1 + e1 * Math.sin(t), o.R - e1 + e1 * Math.cos(t), Math.sin(t), Math.cos(t)]); }
  prof.push([o.x1, 0, 1, 0]);
  const rows = prof.map(([x, r, nx, nr]) => {
    const row = [];
    for (let i = 0; i <= N; i++) {
      const a = 2 * Math.PI * i / N, c = Math.cos(a), s = Math.sin(a);
      row.push(B.vert(x, o.cy + r * c, o.cz + r * s, nx, nr * c, nr * s, 'front'));
    }
    return row;
  });
  for (let j = 0; j + 1 < rows.length; j++) for (let i = 0; i < N; i++) {
    const a = rows[j][i], b = rows[j][i + 1], c = rows[j + 1][i + 1], d = rows[j + 1][i];
    const ang = 2 * Math.PI * (i + 0.5) / N, nx = prof[j][2] + prof[j + 1][2], nr = prof[j][3] + prof[j + 1][3];
    const want = [nx, nr * Math.cos(ang), nr * Math.sin(ang)];
    B.tri(o.slot, a, b, c, want); B.tri(o.slot, a, c, d, want);
  }
}
// A box (mm) [x0, x1] x [y0, y1] x [z0, z1], all six faces in slot `slot`.
function boxGeometry(B, [x0, x1], [y0, y1], [z0, z1], slot) {
  const faces = [[[-1, 0, 0], [[x0, y0, z0], [x0, y1, z0], [x0, y1, z1], [x0, y0, z1]]], [[1, 0, 0], [[x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [x1, y0, z1]]],
    [[0, -1, 0], [[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]]], [[0, 1, 0], [[x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]]],
    [[0, 0, -1], [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0]]], [[0, 0, 1], [[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]]];
  for (const [n, q] of faces) {
    const v = q.map(p => B.vert(p[0], p[1], p[2], n[0], n[1], n[2], 'front', 0.6));
    B.tri(slot, v[0], v[1], v[2], n); B.tri(slot, v[0], v[2], v[3], n);
  }
}

// A key in a side wall, seen square on: a rounded bar over its span (`along`, mm) and depth (`across`, mm), each end round
// unless `ends` says only one is ("start": the end at the start of its span).
function barPlan(a0, a1, b0, b1, ends) {
  const r = Math.min(Math.abs(a1 - a0), Math.abs(b1 - b0)) / 2, lo = Math.min(a0, a1), hi = Math.max(a0, a1), mid = (b0 + b1) / 2;
  const roundLo = ends !== (a0 < a1 ? 'end' : 'start'), roundHi = ends !== (a0 < a1 ? 'start' : 'end'), out = [], N = 12;
  if (roundHi) for (let i = 0; i <= N; i++) { const t = -Math.PI / 2 + Math.PI * i / N; out.push([hi - r + r * Math.cos(t), mid + r * Math.sin(t)]); }
  else out.push([hi, mid - r], [hi, mid + r]);
  if (roundLo) for (let i = 0; i <= N; i++) { const t = Math.PI / 2 + Math.PI * i / N; out.push([lo + r + r * Math.cos(t), mid + r * Math.sin(t)]); }
  else out.push([lo, mid + r], [lo, mid - r]);
  return out;
}

// ---- pictures: an SVG of the skin drawn into a canvas at a high resolution ----
async function loadPicture(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  const text = await res.text();
  const vb = (/viewBox="([^"]+)"/.exec(text) || [])[1];
  const box = vb ? vb.trim().split(/[\s,]+/).map(Number) : null;
  const img = new Image();
  img.decoding = 'async';
  const ok = new Promise((res2, rej) => { img.onload = res2; img.onerror = () => rej(new Error(url + ': not an image')); });
  img.src = url;
  try { await img.decode(); } catch (e) { await ok; }
  const w = img.naturalWidth || (box && box[2]) || 1, h = img.naturalHeight || (box && box[3]) || 1;
  return { img, url, box: box || [0, 0, w, h], w, h };
}
// The picture's part `crop` (picture units) at `scale` canvas pixels per unit, on `fill` (the colour of the material). A
// list of pictures is drawn one over the other.
function raster(pic, crop, scale, fill) {
  const c = document.createElement('canvas');
  c.width = Math.max(2, Math.round(crop[2] * scale)); c.height = Math.max(2, Math.round(crop[3] * scale));
  const g = c.getContext('2d');
  if (fill) { g.fillStyle = fill; g.fillRect(0, 0, c.width, c.height); }
  const sx = c.width / crop[2], sy = c.height / crop[3];
  for (const p of [].concat(pic)) { const b = p.box; g.drawImage(p.img, (b[0] - crop[0]) * sx, (b[1] - crop[1]) * sy, b[2] * sx, b[3] * sy); }
  return c;
}
// The earpiece's grille: a fine woven mesh, light threads on dark gaps (the material's colour tints it), 4 by 4 cells a
// tile, a cell 0.25 mm (a tile is MESH picture px).
const MESH = 3.5;
let meshCanvas = null;
function meshPicture() {
  if (meshCanvas) return meshCanvas;
  const c = meshCanvas = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  g.fillStyle = '#1c1c1c'; g.fillRect(0, 0, 64, 64);
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
    const x = i * 16, y = j * 16, over = (i + j) % 2 === 0;
    const a = g.createLinearGradient(x, y, over ? x + 16 : x, over ? y : y + 16);
    a.addColorStop(0, '#9a9a9a'); a.addColorStop(0.5, '#ffffff'); a.addColorStop(1, '#9a9a9a');
    g.fillStyle = a;
    if (over) g.fillRect(x + 1, y + 5, 14, 6); else g.fillRect(x + 5, y + 1, 6, 14);
  }
  return c;
}

// ---- the room the phone is in, for its reflections and soft light: a studio made here (nothing is downloaded) ----
// A sphere graded from a light ceiling through a faint bright horizon to a darker, warm floor, and soft rectangular light
// boxes: the key up on the left in front (the light of the drawings), a dimmer fill on the right, a strip above and behind
// (the top edge catches it), and a dim one behind the viewer (the glass, face on, stays dark and the screen readable).
// Their reflections have shapes that slide over glass and metal as the phone turns. Its size (PMREM, px a cube face): 256,
// or 512 for a phone with a face of high-gloss lacquer (a face with a finish map): a sharp clear coat over a whole face
// shows the room nearly as a mirror, and at 256 the horizon in it is jagged.
const ROOM = { size: 256, gloss: 512, key: 9, fill: 2.4, strip: 3.5, behind: 0.3 };
function room() {
  const scene = new THREE.Scene();
  const sky = new THREE.SphereGeometry(20, 64, 48), col = [], P = sky.attributes.position;
  const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
  const top = [0.30, 0.31, 0.33], horizon = [0.17, 0.17, 0.17], low = [0.12, 0.115, 0.11], floor = [0.035, 0.032, 0.03];
  for (let i = 0; i < P.count; i++) {
    const y = P.getY(i) / 20;
    let c = y >= 0 ? mix(horizon, top, Math.pow(y, 0.6)) : mix(low, floor, Math.pow(-y, 0.5));
    const line = 0.16 * Math.exp(-Math.pow(y / 0.018, 2));          // the horizon: a faint bright line
    c = c.map(v => v + line);
    col.push(...c);
  }
  sky.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  scene.add(new THREE.Mesh(sky, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide })));
  // a light box: bright in the middle, its edges soft (a canvas drawn here)
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d'), img = g.createImageData(128, 128);
  for (let y = 0; y < 128; y++) for (let x = 0; x < 128; x++) {
    const e = Math.min(x, 127 - x, y, 127 - y) / 18, v = Math.round(255 * Math.min(1, e) ** 1.5);
    img.data.set([v, v, v, 255], (y * 128 + x) * 4);
  }
  g.putImageData(img, 0, 0);
  const soft = new THREE.CanvasTexture(c);
  const plane = new THREE.PlaneGeometry(1, 1);
  const box = (w, h, at, v, tint = [1, 1, 1]) => {
    const m = new THREE.Mesh(plane, new THREE.MeshBasicMaterial({ map: soft, color: new THREE.Color(tint[0] * v, tint[1] * v, tint[2] * v), side: THREE.DoubleSide }));
    m.scale.set(w, h, 1); m.position.set(...at); m.lookAt(0, 0, 0); scene.add(m);
  };
  box(5, 3.2, [-6.5, 7, 6.5], ROOM.key, [1, 0.97, 0.92]);           // the key: up on the left, in front
  box(3.6, 7, [9.5, 1.2, 3], ROOM.fill, [0.92, 0.96, 1]);           // the fill: on the right, cooler
  box(11, 1.6, [0, 9, -5], ROOM.strip);                            // a strip above and behind
  box(6, 3.5, [0, 1, 12], ROOM.behind);                            // behind the viewer: dim
  scene.userData.dispose = () => soft.dispose();
  return scene;
}

// ---- a face of several finishes: the shader (Viewer.finishFace()) ----
// What three.js's physical material takes from its own uniforms and maps, taken from the finish texture instead: the
// weights of the four layers (black: the base; red, green, blue) mix each layer's roughness, metalness, clear coat and
// its roughness, specular strength and anisotropy; the brushed layer that counts most gives the anisotropy's direction,
// computed here from the picture position (circles or rays round a point, or a fixed direction), in the face's tangent
// frame (fFlip: picture x and y, y down, to it). The relief's slopes come from the texture's alpha by central differences
// one texel apart, faded out where a pixel covers more than about two texels (there the cuts average out and the
// differences would only flicker). The material's own uniforms still scale the clear coat and the specular strength, so
// the page's rest light (light()) works as on any face.
function finishShader(sh, U, relief) {
  Object.assign(sh.uniforms, U);
  const pars = `
uniform sampler2D fMask;
uniform vec4 fHave, fRough, fMetal, fCoat, fCoatRough, fSpec, fAniso, fCrop, fRelief;
uniform vec4 fBrush[ 4 ];
uniform vec3 fCol[ 4 ];
uniform vec2 fFlip, fSize;
vec4 fW;
vec2 fDirOf( vec4 b, vec2 p ) {
  if ( b.x < 0.5 ) return b.yz;
  vec2 d = p - b.yz;
  float l = length( d );
  if ( l < 1e-4 ) return vec2( 1.0, 0.0 );
  d /= l;
  return b.x < 1.5 ? d : vec2( - d.y, d.x );
}
`;
  const weights = `
  {
    vec4 m = texture2D( fMask, vMapUv );
    fW = vec4( 0.0, m.rgb ) * fHave;
    float sum = fW.y + fW.z + fW.w;
    if ( sum > 1.0 ) fW /= sum; else fW.x = 1.0 - sum;
  }
  // the roughness of the reflection: of each layer as much as it reflects (a metal all, a dielectric its F0), so the edge of
  // a metal line on lacquer is the metal's lobe, half as strong, not a rougher one of its own that would catch light the
  // line does not (a bright rim, broken into dashes by the texels)
  vec4 fE = fW * mix( 0.04 * fSpec, vec4( 1.0 ), fMetal );
  float roughnessFactor = roughness * dot( fE, fRough ) / max( dot( fE, vec4( 1.0 ) ), 1e-4 );
  float metalnessFactor = metalness * dot( fW, fMetal );`;
  const bump = !relief ? '' : `
  {
    vec2 ts = 1.0 / fSize, uv = vMapUv;
    float hl = texture2D( fMask, uv - vec2( ts.x, 0.0 ) ).a, hr = texture2D( fMask, uv + vec2( ts.x, 0.0 ) ).a;
    float hu = texture2D( fMask, uv - vec2( 0.0, ts.y ) ).a, hd = texture2D( fMask, uv + vec2( 0.0, ts.y ) ).a;
    vec2 g = vec2( ( hr - hl ) / fRelief.y, ( hd - hu ) / fRelief.z ) * ( 0.5 * fRelief.x );
    float px = max( length( dFdx( uv * fSize ) ), length( dFdy( uv * fSize ) ) );
    // the walls of a cut are the lacquer's (the metal is its floor, flat): the slopes tilt the face where it is not metal
    g *= ( 1.0 - smoothstep( 1.0, 2.5, px ) ) * ( 1.0 - smoothstep( 0.0, 0.6, metalnessFactor ) ) * fFlip;
    normal = normalize( normal - tbn[ 0 ] * g.x - tbn[ 1 ] * g.y );
  }`;
  const after = `
  {
    // the colours: a metal's reflection is its own colour (body3d's), the rest takes the picture's colour, which at the
    // edge of a line is part metal: there the base layer's own colour (else the metal's colour would show as a lit rim)
    vec4 fM = fW * fMetal;
    vec3 metal = ( metalnessFactor > 1e-4 ? ( fCol[ 0 ] * fM.x + fCol[ 1 ] * fM.y + fCol[ 2 ] * fM.z + fCol[ 3 ] * fM.w ) / metalnessFactor : vec3( 1.0 ) ) * diffuse;
    vec3 rest = mix( diffuseColor.rgb, fCol[ 0 ] * diffuse, smoothstep( 0.0, 0.5, metalnessFactor ) );
    material.diffuseColor = metal;
    material.diffuseContribution = rest * ( 1.0 - metalnessFactor );
    float sp = dot( fW, fSpec );
    material.specularColor *= sp;
    material.specularColorBlended = mix( material.specularColor, metal, metalnessFactor );
    material.specularF90 = mix( specularIntensity * sp, 1.0, metalnessFactor );
    #ifdef USE_CLEARCOAT
      material.clearcoat = saturate( clearcoat * dot( fW, fCoat ) );
      material.clearcoatRoughness = min( max( dot( fW * fCoat, fCoatRough ) / max( dot( fW, fCoat ), 1e-4 ), 0.0525 ) + geometryRoughness, 1.0 );
    #endif
    #ifdef USE_ANISOTROPY
      vec4 an = fW * fAniso;
      vec4 b = fBrush[ 0 ];
      float best = an.x;
      if ( an.y > best ) { best = an.y; b = fBrush[ 1 ]; }
      if ( an.z > best ) { best = an.z; b = fBrush[ 2 ]; }
      if ( an.w > best ) { best = an.w; b = fBrush[ 3 ]; }
      vec2 av = fDirOf( b, fCrop.xy + vMapUv * fCrop.zw ) * fFlip;
      // the strength, mixed as the roughness is (by how much each layer reflects): the lobe at the edge of a line is the
      // line's own, half as strong
      material.anisotropy = saturate( anisotropyVector.x * dot( fE, fAniso ) / max( dot( fE, vec4( 1.0 ) ), 1e-4 ) );
      material.alphaT = mix( pow2( material.roughness ), 1.0, pow2( material.anisotropy ) );
      material.anisotropyT = tbn[ 0 ] * av.x + tbn[ 1 ] * av.y;
      material.anisotropyB = tbn[ 1 ] * av.x - tbn[ 0 ] * av.y;
    #endif
  }`;
  sh.fragmentShader = sh.fragmentShader
    .replace('void main() {', pars + 'void main() {')
    .replace('#include <roughnessmap_fragment>', weights)
    .replace('#include <metalnessmap_fragment>', '')
    .replace('#include <normal_fragment_maps>', '#include <normal_fragment_maps>' + bump)
    .replace('#include <lights_physical_fragment>', '#include <lights_physical_fragment>' + after);
}
// A fixed noise in [0, 1) for each index (the dither of an 8-bit map).
function dither(i) { const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x); }

// ---- the viewer ----
class Viewer {
  constructor(container, opts, model) {
    this.container = container; this.opts = opts; this.m = model;
    this.skinUrl = opts.skinUrl.endsWith('/') ? opts.skinUrl : opts.skinUrl + '/';
    this.variant = this.pickVariant(opts.variant);
    this.screenSrc = opts.screenCanvas || null;
    this.flat = [].concat(opts.flat || []).filter(Boolean);
    // main: this view is the phone at rest too (start()); its light is the real light then, a flip's lid stands at restOpen
    this.main = !!opts.main;
    this.restLit = this.main ? clamp(num(opts.restLight, 1), 0, 1) : 0;
    if (this.main && model.joint && model.joint.type === 'hinge') model.joint.flat = num(opts.restOpen, model.joint.open);
    this.ratioCap = num(opts.maxPixelRatio, MAX_RATIO); this.gaps = [];
    this.p = 0; this.view = null;
    this.yaw = 0; this.pitch = 0; this.vYaw = 0; this.vPitch = 0; this.target = null;
    this.active = false; this.shown = false; this.peek = false; this.leaving = false;
    this.onKey = null; this.onMode = null; this.onChange = null; this.onLost = null; this.onRender = null;
    this.raf = 0; this.last = 0; this.dirtyScreen = true;
    this.pointers = new Map(); this.touches = new Map(); this.lastTap = null; this.keyDown = null;
    this.times = []; this.stat = { renders: 0, calls: 0, triangles: 0, cpuMs: 0 };
    this.ready = null;
    this.layer = document.createElement('div');
    this.layer.className = 'p3d' + (this.main ? ' main' : ''); this.layer.hidden = true;
    this.canvas = document.createElement('canvas');
    this.canvas.setAttribute('aria-label', 'The phone in three dimensions. Drag to turn it.');
    this.canvas.setAttribute('role', 'img');
    this.layer.append(this.canvas);
    if (opts.controls !== false) this.layer.append(this.buttons());
    if (opts.before && opts.before.parentNode === container) container.insertBefore(this.layer, opts.before); else container.append(this.layer);
    this.listen();
  }

  pickVariant(id) {
    const ids = this.m.variants.map(v => v.id);
    return ids.includes(id) ? id : this.m.defaultVariant;
  }
  // The address of a picture in the colour: the colour's id goes before the file ending (as the page does).
  url(name, variant = this.variant) {
    if (variant && variant !== this.m.defaultVariant) name = name.replace(/(\.[a-z0-9]+)$/i, '.' + variant + '$1');
    return this.skinUrl + name;
  }
  async picture(name, variant) {
    if (!name) return null;
    try { return await loadPicture(this.url(name, variant)); }
    catch (e) { if (variant && variant !== this.m.defaultVariant) return loadPicture(this.url(name, this.m.defaultVariant)).catch(() => null); return null; }
  }
  // A named material of the colour (body3d.materials: shell, carrier, under, satin, spun, steel, glass), with the colour's
  // swatch as the body when the skin does not name one.
  mat(name, fallback = 'shell') {
    const all = this.m.materials, M = all[this.variant] || all[this.m.defaultVariant] || Object.values(all)[0] || {};
    const sw = (this.m.variants.find(x => x.id === this.variant) || {}).swatch || '#8a8a8a';
    return Object.assign({ colour: sw, roughness: 0.7, metalness: 0 }, M[fallback] || {}, (name && M[name]) || {});
  }

  // ---- building: pictures, geometry, renderer (once; the pictures again for another colour) ----
  prepare() {
    if (!this.ready) this.ready = this.build().catch(e => { this.ready = null; throw e; });
    return this.ready;
  }
  async build() {
    const m = this.m;
    this.sideViews = SIDES.some(s => m.sides[s]);
    await this.loadPictures();
    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, alpha: true, powerPreference: 'default', preserveDrawingBuffer: !!this.opts.keepBuffer });
    const r = this.renderer;
    r.setClearColor(0x000000, 0);
    r.outputColorSpace = THREE.SRGBColorSpace;
    r.toneMapping = THREE.NoToneMapping;
    this.aniso = Math.min(8, r.capabilities.getMaxAnisotropy());
    this.maxTex = Math.min(4096, r.capabilities.maxTextureSize);
    this.canvas.addEventListener('webglcontextlost', e => { e.preventDefault(); this.lost = true; if (this.onLost) this.onLost(true); });
    this.canvas.addEventListener('webglcontextrestored', () => { this.lost = false; this.textures(); this.invalidate(); if (this.onLost) this.onLost(false); });
    const scene = this.scene = new THREE.Scene();
    const pm = new THREE.PMREMGenerator(r);
    const roomScene = room();
    this.roomSize = m.parts.some(p => p.finishes.front || p.finishes.back) ? ROOM.gloss : ROOM.size;
    this.env = pm.fromScene(roomScene, 0, 0.1, 50, { size: this.roomSize }).texture;
    pm.dispose(); roomScene.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); }); roomScene.userData.dispose();
    scene.environment = this.env; scene.environmentIntensity = LIGHT.env;
    const key = new THREE.DirectionalLight(0xfff8f0, LIGHT.key);
    key.position.set(-0.55, 0.85, 1.0); scene.add(key);
    this.camera = new THREE.PerspectiveCamera(FOV_FLAT, 1, 1, 10000);
    this.root = new THREE.Group(); scene.add(this.root);
    this.phone = new THREE.Group(); this.root.add(this.phone);
    this.groups = {}; this.meshes = []; this.materials = {}; this.caps = []; this.capOf = {}; this.rest = [];
    for (const p of m.parts) {
      const g = new THREE.Group(); this.phone.add(g); this.groups[p.id] = g;
      const mats = this.partMaterials(p);
      for (const piece of p.pieces) {
        const B = new Builder({ upm: m.upm, frontUV: (x, y) => this.frontUV(p, x, y), backUV: (x, y) => this.backUV(p, x, y), sideUV: (s, x, y, z) => this.sideUV(s, x, y, z) });
        const made = this.pieceGeometry(B, p, piece);
        const mesh = new THREE.Mesh(B.geometry(), mats);
        mesh.userData.part = p.id; mesh.userData.piece = piece.id; g.add(mesh); this.meshes.push(mesh);
        for (const c of made) { c.mesh = mesh; for (const k of c.keys) this.capOf[k] = c; }
      }
    }
    for (const c of this.caps) this.pressCap(c);
    this.screen();
    this.shadow();
    this.textures();
    this.place();
    // the shaders compiled while the page goes on (where the browser compiles in parallel), not in one long block
    if (r.compileAsync) await r.compileAsync(scene, this.camera); else r.compile(scene, this.camera);
    this.prepared = true;
  }
  // A slab's solid: the slab with its wells cut into its front, the wells, its keys on its front and in its wells, the side
  // keys in its walls, the earpiece's slot, the openings in its walls; for a flip, the hinge's parts. Returns the keys made
  // (this.caps).
  pieceGeometry(B, p, piece) {
    const m = this.m, upm = m.upm, h = (piece.z1 - piece.z0) / 2, made = [];
    const mm = d => pathPoints(d).map(([x, y]) => [x / upm, -y / upm]);
    const wells = piece.wells.map(w => Object.assign({ pts: mm(w.outline) }, w));
    const brush = { x: () => [1, 0, 0], y: () => [0, 1, 0] };
    const inlays = piece.inlays.map(x => ({ pts: mm(x.outline), back: x.back, slot: this.slot(p, `inlay:${x.material}:${x.back ? 'back' : 'front'}`), tangent: brush[x.brush] || null }));
    const outline = pathPoints(piece.outline);
    // the earpiece: a slot in the front (or in the lid's inner face, its back), the round of its edge in the material of
    // the face round it (the glass pane), its floor the grille behind it
    const holes = wells.map(w => ({ pts: w.pts, back: false }));
    for (const f of piece.pockets) {
      const pts = mm(f.outline), face = f.back ? 'back' : 'front', box = inlays.find(x => x.back === f.back && inside(pts[0], x.pts));
      const F = f.back ? { at: (a, b, w) => [a, b, piece.z0 - w], dir: (na, nb, nw) => [na, nb, -nw], side: 'back' } : { at: (a, b, w) => [a, b, piece.z1 + w], dir: (x, y, z) => [x, y, z], side: 'front' };
      holes.push({ back: f.back, pts: pocketGeometry(B, pts, { depth: Math.min(f.depth, h), edge: num(f.edge, 0.2), face: box ? box.slot : f.back ? 1 : 0,
        wall: this.slot(p, 'wall:' + (f.wall || 'mesh')), floor: this.slot(p, `grille:${f.material || 'mesh'}:${face}`) }, F) });
    }
    // the openings in the walls (the USB-C receptacle): where the wall is, across the opening's span
    const openings = [];
    for (const f of piece.openings) {
      const vertical = f.side === 'left' || f.side === 'right', span = vertical ? f.y : f.x;
      if (!Array.isArray(span)) continue;
      const u = vertical ? 1 : 0, v = 1 - u, mid = (span[0] + span[1]) / 2, far = f.side === 'right' || f.side === 'bottom' ? 1 : -1;
      let wall = null;
      for (let i = 0; i < outline.length; i++) {
        const a = outline[i], b = outline[(i + 1) % outline.length];
        if (Math.abs(a[v] - b[v]) > 1e-6 || Math.min(a[u], b[u]) > mid || Math.max(a[u], b[u]) < mid) continue;
        if (wall === null || far * a[v] > far * wall) wall = a[v];
      }
      if (wall === null) continue;
      const [w, hh] = f.size, margin = num(f.margin, 0.5), ac = vertical ? -mid / upm : mid / upm, zc = m.depth - (f.z[0] + f.z[1]) / 2;
      const a0 = ac - w / 2 - margin, a1 = ac + w / 2 + margin, z0 = zc - hh / 2 - margin, z1 = zc + hh / 2 + margin;
      const W0 = vertical ? wall / upm : -wall / upm, inward = { left: 1, right: -1, top: -1, bottom: 1 }[f.side];
      const F = vertical ? { at: (a, b, d) => [W0 + inward * d, a, b], dir: (na, nb, nd) => [inward * nd, na, nb], side: f.side }
        : { at: (a, b, d) => [a, W0 + inward * d, b], dir: (na, nb, nd) => [na, inward * nd, nb], side: f.side };
      openings.push({ side: f.side, span: vertical ? [-a1 * upm, -a0 * upm] : [a0 * upm, a1 * upm], a0, a1, z0, z1, F, f, w, h: hh });
    }
    slabGeometry(B, outline, { upm, z0: piece.z0, z1: piece.z1, edge: Math.min(piece.edge, h), edgeBack: Math.min(piece.edgeBack, h),
      chamfer: !!piece.chamfer, backFacet: piece.chamferBack ? this.slot(p, `facet:${piece.chamferBack}:back`) : 0,
      sideViews: this.sideViews, holes, inlays, openings });
    for (const op of openings)
      usbGeometry(B, { a0: op.a0, a1: op.a1, b0: op.z0, b1: op.z1, w: op.w, h: op.h, lip: 0.12, shell: num(op.f.shell, 0.2), depth: num(op.f.depth, 3.6),
        tongue: op.f.tongue || [6.69, 0.7], tongueBack: num(op.f.tongue_back, 0.9), wallSlot: this.sideViews ? 2 + SIDES.indexOf(op.side) : 2,
        steel: this.slot(p, 'feat:' + (op.f.material || 'steel')), inside: this.slot(p, 'deep:' + (op.f.material || 'steel')),
        dark: this.slot(p, 'deep:' + (op.f.inside || 'tongue')) }, op.F);
    for (const w of wells) wellGeometry(B, w.pts, { top: piece.z1, depth: Math.min(w.depth, piece.z1 - piece.z0 - 0.2), wall: this.slot(p, 'wall:' + w.material) });
    if (m.hinge && piece.id === p.id) this.hingeGeometry(B, p, piece, outline);
    const radial = name => this.mat(name).brush === 'radial';
    const add = (keys, pts, o, F, press) => {
      const c = { keys, press, down: null };
      c.range = capGeometry(B, pts, o, F, this.caps.length);
      // the middle and size of the key in its plan, and where each of its keys is (the coin: tipped towards a direction)
      let cx = 0, cy = 0, r = 0;
      for (const q of pts) { cx += q[0] / pts.length; cy += q[1] / pts.length; }
      for (const q of pts) r = Math.max(r, Math.hypot(q[0] - cx, q[1] - cy));
      c.centre = [cx, cy]; c.radius = r || 1; c.dirs = {};
      for (const k of keys) {
        const rect = (m.keys[p.id] || {})[k];
        if (!rect || keys.length < 2) continue;
        const dx = (rect[0] + rect[2] / 2) / upm - cx, dy = -(rect[1] + rect[3] / 2) / upm - cy, l = Math.hypot(dx, dy);
        if (l > 0.3 * c.radius) c.dirs[k] = [dx / l, dy / l];
      }
      this.caps.push(c); made.push(c);
    };
    const front = { at: (a, b, w) => [a, b, w], dir: (x, y, z) => [x, y, z], side: 'front' };
    for (const c of piece.caps)
      add(c.keys, mm(c.outline), { w0: piece.z1 - c.z[1] - 0.02, w1: piece.z1 - c.z[0], edge: c.edge, dome: c.dome, top: this.slot(p, 'top:' + c.material),
        wall: this.slot(p, 'wall:' + c.material), radial: radial(c.material) }, front, [0, 0, -PRESS]);
    // the side keys: a bar on the wall where the slab's outline crosses the middle of its span
    for (const bar of piece.bars) {
      const vertical = bar.side === 'left' || bar.side === 'right', at = (bar.span[0] + bar.span[1]) / 2;
      let wall = null;
      for (let i = 0; i < outline.length; i++) {
        const a = outline[i], b = outline[(i + 1) % outline.length], u = vertical ? 1 : 0, v = 1 - u;
        if ((a[u] - at) * (b[u] - at) > 0 || a[u] === b[u]) continue;
        const x = a[v] + (b[v] - a[v]) * (at - a[u]) / (b[u] - a[u]);
        if (wall === null || (bar.side === 'right' || bar.side === 'bottom' ? x > wall : x < wall)) wall = x;
      }
      if (wall === null) continue;
      const s = { right: [1, 0], left: [-1, 0], top: [0, -1], bottom: [0, 1] }[bar.side];       // outwards, in picture px
      const W0 = vertical ? wall / upm : -wall / upm, out = vertical ? s[0] : -s[1];
      const F = vertical
        ? { at: (a, b, w) => [W0 + out * w, a, b], dir: (na, nb, nw) => [out * nw, na, nb], side: bar.side }
        : { at: (a, b, w) => [a, W0 + out * w, b], dir: (na, nb, nw) => [na, out * nw, nb], side: bar.side };
      const k = vertical ? -1 / upm : 1 / upm, pts = barPlan(bar.span[0] * k, bar.span[1] * k, m.depth - bar.z[0], m.depth - bar.z[1], bar.ends);
      add(bar.keys, pts, { w0: -0.05, w1: bar.proud, edge: 0.2, dome: 0, top: this.sideViews ? 2 + SIDES.indexOf(bar.side) : 2,
        wall: this.slot(p, 'wall:' + bar.material), radial: radial(bar.material) }, F, F.dir(0, 0, -PRESS));
      made[made.length - 1].outward = F.dir(0, 0, bar.proud);       // facing front it is drawn flush (the 2D picture has no bump)
    }
    // the camera and the flash, standing out of the back (their outlines are in the back's picture, seen from behind)
    const back = { at: (a, b, w) => [a, b, piece.z0 - w], dir: (na, nb, nw) => [na, nb, -nw], side: 'back' };
    for (const f of piece.features) {
      const pts = pathPoints(f.outline).map(([x, y]) => [(m.W - x) / upm, -y / upm]);
      if (f.id === 'camera' && f.lens) cameraGeometry(B, pts, { proud: f.proud, edge: 0.15, lens: f.lens.r / upm, bevel: f.lens.bevel / upm, depth: f.lens.depth,
        ring: this.slot(p, 'feat:spun'), bevelSlot: this.slot(p, 'feat:steel'), lensSlot: this.slot(p, 'feat:lens:back') }, back);
      else capGeometry(B, pts, { w0: -0.05, w1: f.proud, edge: Math.min(0.08, f.proud * 0.6), dome: 0, top: this.slot(p, `feat:${f.material || 'frost'}:back`),
        wall: this.slot(p, 'feat:steel') }, back, -1);
    }
    // the light window on a front (the flip's lid): a disc of spun metal standing `proud`, the window standing on it: a
    // frosted disc, or with `cut: "jewel"` a jewel cut (jewelGeometry(): facets, crown and girdle in mm, table)
    for (const f of piece.lamps) {
      const pts = mm(f.outline), [cx, cy] = middle(pts), r = num(f.window, 0) / upm, top = piece.z1 + f.proud;
      capGeometry(B, pts, { w0: piece.z1 - 0.05, w1: top, edge: Math.min(0.08, f.proud * 0.6), dome: 0, top: this.slot(p, 'top:' + (f.ring || 'spun')),
        wall: this.slot(p, 'wall:' + (f.ring || 'spun')), radial: radial(f.ring || 'spun') }, front, -1);
      if (r > 0 && f.cut === 'jewel') jewelGeometry(B, cx, cy, r, { w0: top - 0.05, girdle: top + num(f.girdle, 0.12), crown: num(f.crown, 0.45),
        table: clamp(num(f.table, 0.5), 0.2, 0.9), n: num(f.facets, 12), slot: this.slot(p, 'top:' + (f.material || 'frost')) }, front);
      else if (r > 0) capGeometry(B, Array.from({ length: 96 }, (_, i) => [cx + r * Math.cos(i * Math.PI / 48), cy + r * Math.sin(i * Math.PI / 48)]),
        { w0: top - 0.05, w1: top + 0.03, edge: 0.03, dome: 0, top: this.slot(p, 'top:' + (f.material || 'frost')), wall: this.slot(p, 'wall:' + (f.material || 'frost')) }, front, -1);
    }
    return made;
  }
  // The hinge of a flip, from body3d.hinge: on the base (the part that stays), its two knuckles (cylinders in the body
  // colour on the axis, the outer ends round, each with the cap of the pin), the webs that join them to the base's hinge
  // end, and the barrel between them. The barrel is the lid's, but a cylinder on its own axis looks the same at every
  // angle, so it is drawn where it is (as the 2D page does) and only its web turns with the lid. Facing front at rest the
  // barrel and the knuckles show the open picture's hinge (the base's layer with the barrel's over it), exactly as the 2D
  // page draws them; turned, their own finishes. On the lid: the web from its hinge end to the barrel.
  hingeGeometry(B, p, piece, outline) {
    const m = this.m, H = m.hinge, upm = m.upm, R = H.R, cy = -H.centre[0] / upm, cz = m.depth - H.centre[1];
    const endY = Math.min(...outline.map(q => q[1]));                // the half's hinge end (picture px)
    const yWeb = e => [-(endY + e) / upm, cy];
    if (p.moving) {
      if (H.barrel) boxGeometry(B, [H.barrel.x[0] / upm + 0.1, H.barrel.x[1] / upm - 0.1], yWeb(0.4), [piece.z0, Math.min(piece.z1, cz + R * 0.8)], this.slot(p, 'wall:shell'));
      return;
    }
    B.uvFn = (u, v) => this.stripUV(u, v);
    for (const k of H.knuckles)
      cylinderGeometry(B, { x0: k.x[0] / upm, x1: k.x[1] / upm, cy, cz, R, ends: k.round, slot: this.slot(p, 'hinge:' + k.material) });
    if (H.barrel) {
      B.tanFn = () => [1, 0, 0];                                     // turned along its length: the highlight runs along it
      cylinderGeometry(B, { x0: H.barrel.x[0] / upm, x1: H.barrel.x[1] / upm, cy, cz, R, ends: H.barrel.round, slot: this.slot(p, 'hinge:' + H.barrel.material) });
      B.tanFn = null;
    }
    B.uvFn = null;
    // the knuckles' webs: only over the straight part of the base's hinge end (not past its round corners)
    const straight = outline.filter(q => Math.abs(q[1] - endY) < 1e-6).map(q => q[0]), s0 = Math.min(...straight), s1 = Math.max(...straight);
    for (const k of H.knuckles) {
      const x0 = Math.max(k.x[0], s0), x1 = Math.min(k.x[1], s1);
      if (x1 > x0) boxGeometry(B, [x0 / upm + 0.05, x1 / upm - 0.05], yWeb(-0.1), [Math.max(piece.z0, cz - R), piece.z1], this.slot(p, 'wall:shell'));
    }
    if (H.pin) {
      const all = H.knuckles.flatMap(k => k.x), lo = Math.min(...all), hi = Math.max(...all), r = H.pin.r;
      const circle = Array.from({ length: 64 }, (_, i) => [cy + r * Math.cos(i * Math.PI / 32), cz + r * Math.sin(i * Math.PI / 32)]);
      for (const [X, out] of [[lo / upm, -1], [hi / upm, 1]]) {
        const F = { at: (a, b, w) => [X + out * w, a, b], dir: (na, nb, nw) => [out * nw, na, nb], side: out < 0 ? 'left' : 'right' };
        capGeometry(B, circle, { w0: -0.05, w1: 0.05, edge: 0.03, dome: 0, top: this.slot(p, 'feat:' + H.pin.material), wall: this.slot(p, 'feat:' + H.pin.material),
          radial: this.mat(H.pin.material).brush === 'radial' }, F, -1);
      }
    }
  }
  // Where the hinge's strip picture (the open picture's hinge, base.svg with hinge.svg over it) has a point of the closed
  // picture (u, v in picture px): the strip is the open picture round its hinge line, T lower.
  stripUV(u, v) { const c = this.stripCrop(); return [(u - c[0]) / c[2], (v + this.m.T - c[1]) / c[3]]; }
  stripCrop() { const m = this.m, a = m.hg.axis_y, R = m.hinge.R * m.upm; return [0, Math.floor(a - R - 3), m.W, Math.ceil(2 * R + 6)]; }
  // The material slot (group) of the keys, wells, inlays and features of a part, after the slab's own seven, made when
  // first asked for. key: 'wall:NAME' (the sides of keys and wells, in shade low down: vertex colours), 'top:NAME' (a key's
  // top: the front picture), 'inlay:NAME:front|back' (a flush region with its face's picture), 'feat:NAME[:back]',
  // 'facet:NAME:back' (the band on a back edge), 'grille:NAME:front|back' (the earpiece's grille: a fine mesh, its face's
  // picture at rest), 'hinge:NAME' (the barrel and knuckles: the hinge's strip picture at rest), 'deep:NAME' (inside an
  // opening: vertex shade, and little of the room's reflection).
  slot(p, key) {
    const M = this.materials[p.id];
    let i = M.slots.findIndex(x => x.key === key);
    if (i < 0) {
      const [kind, name, face] = key.split(':'), pic = kind === 'top' ? 'front' : kind === 'hinge' ? 'strip' : face || null;
      const x = { key, kind, name, pic, mat: new THREE.MeshPhysicalMaterial({ vertexColors: kind === 'wall' || kind === 'grille' || kind === 'deep' }) };
      if (this.atRest(p, pic)) this.rest.push(x.mat);             // facing front at rest: its picture, as the 2D page
      M.slots.push(x); M.list.push(x.mat); i = M.slots.length - 1;
    }
    return 7 + i;
  }
  // Whether a picture of a part faces the viewer when the phone faces front at rest: the fronts; a flip's hinge; and the
  // lid's inner face (its back), which faces front when the lid is open.
  atRest(p, pic) { return pic === 'front' || pic === 'strip' || (pic === 'back' && p.backTurned); }
  /** A key pressed (down) or let go on the page: it sinks in the 3D view. */
  setKey(name, down) {
    if (!this.pressed) this.pressed = new Set();
    this.pressed.delete(name);
    if (down) this.pressed.add(name);
    const c = this.capOf && this.capOf[name];
    if (c) { this.pressCap(c); this.invalidate(); }
  }
  // Where a key's vertices are: at rest, or sunk by PRESS (the coin pressed at a direction tips towards it).
  // A side key also stands out of its wall only as far as the phone is turned (this.out: 0 facing front .. 1).
  pressCap(c, force) {
    if (!c.mesh) return;
    const pos = c.mesh.geometry.attributes.position, [s, e] = c.range, A = pos.array;
    if (!c.rest) c.rest = A.slice(s * 3, e * 3);
    const k = [...(this.pressed || [])].filter(x => c.keys.includes(x)).pop() || null;
    if (k === c.down && !force) return;
    c.down = k;
    const dir = k && c.dirs[k], R = c.rest, o = c.outward, r = o ? 1 - clamp(this.out ?? 1, 0, 1) : 0;
    for (let i = 0; i < e - s; i++) {
      const x = R[i * 3], y = R[i * 3 + 1], z = R[i * 3 + 2];
      const t = !k ? 0 : dir ? clamp(0.5 + 0.5 * ((x - c.centre[0]) * dir[0] + (y - c.centre[1]) * dir[1]) / c.radius, 0, 1) : 1;
      A[(s + i) * 3] = x + c.press[0] * t - (o ? o[0] * r : 0); A[(s + i) * 3 + 1] = y + c.press[1] * t - (o ? o[1] * r : 0);
      A[(s + i) * 3 + 2] = z + c.press[2] * t - (o ? o[2] * r : 0);
    }
    pos.addUpdateRange(s * 3, (e - s) * 3); pos.needsUpdate = true;
  }
  // The slab's own materials: the front, the back, the four walls, the facet on the front edge. The front and the facet,
  // facing front at rest, are their picture exactly (the 2D page's); the light comes in as the phone turns (light()).
  partMaterials(p) {
    const mk = () => new THREE.MeshPhysicalMaterial();
    const front = mk(), edge = mk(), back = mk(), side = SIDES.map(mk);
    const list = this.sideViews ? [front, back, ...side, edge] : [front, back, side[0], side[0], side[0], side[0], edge];
    this.materials[p.id] = { front, back, side, edge, slots: [], list };
    this.rest.push(front, edge);
    if (p.backTurned) this.rest.push(back);
    return list;
  }
  // A finish of body3d.materials on a physically based material: roughness, metalness, and where the skin gives them the
  // soft sheen of soft-touch plastic, a clear coat (glass, the lens), the brushing of metal (anisotropy along the vertex
  // tangents), the coloured coating of the lens (iridescence). pic: the colour comes from a picture (the colour is white).
  finish(x, o, pic) {
    // glass on its picture: the picture's dark pane takes little light itself (it is black behind glass); its reflections
    // are the room's
    const b = { colour: new THREE.Color(pic ? (o.finish === 'glass' ? '#7a7a7a' : '#ffffff') : o.colour), spec: num(o.specular, 0.5), clearcoat: num(o.clearcoat, 0), sheen: num(o.sheen, 0), irid: num(o.iridescence, 0) };
    x.color.copy(b.colour); x.roughness = num(o.roughness, 0.7); x.metalness = num(o.metalness, 0); x.specularIntensity = b.spec;
    x.clearcoat = b.clearcoat; x.clearcoatRoughness = num(o.clearcoat_roughness, 0.04);
    x.sheen = b.sheen; x.sheenRoughness = num(o.sheen_roughness, 0.8); x.sheenColor.set(o.sheen_colour || '#ffffff');
    x.anisotropy = num(o.anisotropy, 0); x.envMapIntensity = num(o.env, 1);
    x.iridescence = b.irid; x.iridescenceIOR = 1.8; x.iridescenceThicknessRange = [220, 420];
    x.emissive.setRGB(0, 0, 0); x.emissiveIntensity = 1;
    x.userData.base = b;
    x.needsUpdate = true;
  }
  async loadPictures() {
    const m = this.m, v = this.variant, jobs = {};
    const want = name => { if (name && !(name in jobs)) jobs[name] = this.picture(name, v); };
    for (const p of m.parts) {
      want(p.front); want(p.back);
      if (!this.main) want(p.front2d);                             // facing front at rest, the 2D page's picture
      for (const f of [p.finishes.front, p.finishes.back]) if (f) { want(f.mask); want(f.relief); }
    }
    for (const s of SIDES) want(m.sides[s]);
    if (m.hinge) { want(m.hinge.strip); want(m.hinge.barrelPicture); }
    const got = {};
    for (const [name, job] of Object.entries(jobs)) got[name] = await job;
    this.pics = got;
  }
  // How far down a picture has the part: the layers of the open view (face.svg, base.svg, rear.svg, under.svg) have the
  // slab that stays lower by the travel, and the moving one where it is when open, which is its closed place.
  dy(p, name) {
    const pic = name && this.pics[name], m = this.m;
    return pic && m.Ho !== m.Hc && Math.abs(pic.box[3] - m.Ho) < 0.5 && !p.moving ? m.T : 0;
  }
  // The part of the pictures a part shows: the box of its pieces' outlines with a margin, closed view px.
  crop(p) {
    if (p.crop) return p.crop;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const piece of p.pieces) for (const [x, y] of pathPoints(piece.outline)) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
    const pad = 2;
    return p.crop = [Math.floor(x0 - pad), Math.floor(y0 - pad), Math.ceil(x1 - x0 + 2 * pad), Math.ceil(y1 - y0 + 2 * pad)];
  }
  frontUV(p, x, y) { const c = this.crop(p); return [(x - c[0]) / c[2], (y - c[1]) / c[3]]; }
  // Seen from behind, left and right change places: the back texture is the crop mirrored (see textures()).
  // A flip's lid: its inner face is seen with the lid turned over the hinge line, so up and down change places instead.
  backUV(p, x, y) { const c = this.crop(p); return p.backTurned ? [(x - c[0]) / c[2], (c[1] + c[3] - y) / c[3]] : [(c[0] + c[2] - x) / c[2], (y - c[1]) / c[3]]; }
  // The side pictures, third-angle (docs/SKINS_3D.md): body length by thickness from the body's edge; left: the front at
  // the right, right: at the left, top: at the bottom, bottom: at the top. Each slab's wall takes its own closed place.
  sideUV(side, x, y, z) {
    const m = this.m, br = m.br, zf = clamp(z / m.depth, 0, 1);
    if (!m.sides[side]) return [0, 0];
    if (side === 'left') return [zf, (y - br[1]) / br[3]];
    if (side === 'right') return [1 - zf, (y - br[1]) / br[3]];
    if (side === 'top') return [(x - br[0]) / br[2], zf];
    return [(x - br[0]) / br[2], 1 - zf];
  }
  // The pictures of the colour into textures. The resolution follows how large the phone is drawn on this display.
  textures() {
    const m = this.m, old = this.texList || [];
    this.texList = [];
    const cache = new Map();
    const ratio = this.ratio();
    const k = this.view ? this.view.k : this.fitView().k;
    const scale = clamp(k * ratio, 2, 5);                       // texels per picture px: as the display shows it facing front
    const fit = crop => Math.min(scale, this.maxTex / crop[2], this.maxTex / crop[3]);
    const tex = (pic, crop, s, fill) => {
      const key = [[].concat(pic).map(x => x.url).join('+'), ...crop, s, fill].join('|');
      if (cache.has(key)) return cache.get(key);
      const t = new THREE.CanvasTexture(raster(pic, crop, s, fill));
      t.colorSpace = THREE.SRGBColorSpace; t.flipY = false; t.anisotropy = this.aniso; t.generateMipmaps = true;
      // one mip level at a time: facing front the picture is drawn at its own size, from level 0, with no blur of level 1
      t.minFilter = THREE.LinearMipmapNearestFilter; t.magFilter = THREE.LinearFilter;
      this.texList.push(t); cache.set(key, t);
      return t;
    };
    // a flip's hinge, as the open picture draws it: the base's layer with the barrel's over it, round the hinge line
    let strip = null;
    if (m.hinge) {
      const pics = [m.hinge.strip, m.hinge.barrelPicture].map(n => n && this.pics[n]).filter(Boolean), sc = this.stripCrop();
      if (pics.length) { strip = tex(pics, sc, fit(sc), null); strip.channel = 0; }
    }
    this.grilles = [];
    for (const p of m.parts) {
      const M = this.materials[p.id], c = this.crop(p);
      const sideMat = this.mat(p.sideMaterial), backMat = this.mat(p.backMaterial || 'shell'), frontMat = this.mat(p.frontMaterial);
      const fp = p.front && this.pics[p.front], bp = p.back && this.pics[p.back], f2 = !this.main && p.front2d && this.pics[p.front2d];
      const fc = [c[0], c[1] + this.dy(p, p.front), c[2], c[3]], fs = fit(c);
      const bc = p.backTurned ? [c[0], m.turnY - c[1] - c[3], c[2], c[3]] : bp ? [bp.box[2] - c[0] - c[2], c[1] + this.dy(p, p.back), c[2], c[3]] : null;
      const bs = p.backTurned ? fit(c) : fit(c) * 0.75;
      M.frontTex = fp ? tex(fp, fc, fs, frontMat.colour) : null;
      if (M.frontTex) M.frontTex.channel = 0;
      // at rest where the 2D page is in charge, a front whose picture is albedo shows the 2D page's (light drawn in)
      M.restTex = f2 ? tex(f2, [c[0], c[1] + this.dy(p, p.front2d), c[2], c[3]], fs, frontMat.colour) : M.frontTex;
      if (f2) M.restTex.channel = 0;
      M.backTex = bp ? tex(bp, bc, bs, backMat.colour) : null;
      if (M.backTex) M.backTex.channel = 1;
      // the front: the slab's own finish (soft-touch shell, the matte deck; front_material) on its picture, and where the
      // skin gives one, its finish map (finishFace())
      this.finish(M.front, frontMat, !!M.frontTex);
      M.front.map = M.frontTex; M.front.emissiveMap = M.restTex;
      this.finishFace(M.front, p, M.frontTex && p.finishes.front, frontMat, fc, fs, 'front');
      // the facet on the front edge: brushed satin metal when turned, the front picture at rest
      const chamfer = p.pieces.find(q => q.chamfer);
      this.finish(M.edge, this.mat(chamfer ? chamfer.chamfer : 'satin', 'shell'), false);
      M.edge.map = null; M.edge.emissiveMap = M.restTex;
      // the back: its picture mirrored (a flip's lid: turned over the hinge line)
      this.finish(M.back, backMat, !!M.backTex);
      M.back.map = M.backTex; M.back.emissiveMap = p.backTurned ? M.backTex : null;
      this.finishFace(M.back, p, M.backTex && p.finishes.back, backMat, bc, bs, p.backTurned ? 'turned' : 'back');
      // the walls
      SIDES.forEach((s, i) => {
        const sp = m.sides[s] && this.pics[m.sides[s]], x = M.side[i];
        const t = sp && this.sideViews ? tex(sp, sp.box.slice(), fit(sp.box), sideMat.colour) : null;
        if (t) t.channel = 2;
        this.finish(x, sideMat, !!t); x.map = t;
      });
      // the keys, wells, inlays and features; the band of a back edge and the hinge's barrel and knuckles are their own
      // finish when turned, their picture only at rest; the grille is its fine mesh when turned
      for (const x of M.slots) {
        const t = x.pic === 'front' ? M.frontTex : x.pic === 'back' ? M.backTex : x.pic === 'strip' ? strip : null, rest = this.atRest(p, x.pic);
        const r = x.pic === 'front' ? M.restTex : t;
        if (x.kind === 'facet' || x.kind === 'hinge' || x.kind === 'grille') {
          this.finish(x.mat, this.mat(x.name), false);
          x.mat.map = x.kind === 'grille' ? this.grille(c) : null; x.mat.emissiveMap = rest ? r : null;
        } else {
          this.finish(x.mat, this.mat(x.name), !!t);
          x.mat.map = t; x.mat.emissiveMap = rest ? r : null;
          // deep inside an opening the room is hardly seen: its reflections (a metal's too, which grazing would make white)
          // are mostly shut out, as the vertex shade darkens the rest
          // (the room is given as the material's own map: with the scene's, three.js takes the scene's intensity)
          if (x.kind === 'deep') { x.mat.envMap = this.env; x.mat.envMapIntensity *= DEEP * LIGHT.env; }
        }
      }
    }
    for (const t of this.grilles || []) this.texList.push(t);
    if (this.screenTex) this.texList.push(this.screenTex);
    if (this.shadowTex) this.texList.push(this.shadowTex);
    for (const t of old) if (!this.texList.includes(t)) t.dispose();
    this.texScale = scale; this.litWas = null;                      // the finishes are new: light() again
    if (this.screenMat) {                                          // the cover glass over the screen
      this.finish(this.screenMat, Object.assign({}, this.mat('glass'), { colour: '#000000' }), false);
      this.screenMat.emissive.setRGB(1, 1, 1); this.screenMat.emissiveMap = this.screenTex;
    }
  }
  // A grille texture for a part (its picture crop c): the mesh repeated at its true size over the part's front uv.
  grille(c) {
    const t = new THREE.CanvasTexture(meshPicture());
    t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = this.aniso;
    t.repeat.set(c[2] / MESH, c[3] / MESH); t.channel = 0;
    this.grilles.push(t);
    return t;
  }
  // ---- a face of several finishes (body3d materials front_finish, back_finish; docs/SKINS_3D.md "Finish maps") ----
  // spec: { base, r, g, b, mask, relief, relief_mm, crown, brush }. The mask is a picture in the face's own frame (as its
  // picture): black is the base material (spec.base, else the face's own, `own`), red, green and blue the materials
  // spec.r, spec.g, spec.b (a polished name, a field of pinstripes), mixed where it is between. Each texel's roughness,
  // metalness, clear coat and its roughness, specular strength and anisotropy are the mix of those materials' (in the
  // shader, finishShader()); a brushed material's direction comes from spec.brush[k].grooves: "circles" round `at`
  // (spun: the highlight radial), "rays" from `at` (a sunburst: the highlight round it), "x", "y" or an angle in degrees
  // (the direction of the grooves; the highlight runs across them). The relief (a height picture, white high) is
  // spec.relief_mm deep: the cut of a pinstripe, a part line; the crown ([across, along] mm: how much higher the middle of
  // the face is than its edges) is a gentle curve over the whole face. The base layer takes both, the clear coat only the
  // crown (it lies over the cuts, flush).
  //
  // On the GPU: one RGBA8 texture at the face picture's resolution (mask in RGB, relief in A, mipmapped, so the lines
  // do not shimmer at a distance), the brushing directions computed in the shader (nothing stored), and the crown as a
  // normal map of a few texels: its slopes are linear across the face, which bilinear filtering reproduces exactly, so
  // a 17 x 23 texture is the whole crown. That one is 32-bit float where the GPU filters float textures
  // (OES_texture_float_linear), else half float, else 8 bits with dithering (finishPrecision()); its slopes fill the
  // texture's range (normalScale gives them back), so even 8 bits step only 0.03 degrees.
  finishFace(x, part, spec, own, crop, s, face) {
    if (x.userData.finish) { x.onBeforeCompile = () => {}; x.customProgramCacheKey = () => ''; delete x.userData.finish; x.normalMap = null; x.clearcoatNormalMap = null; x.needsUpdate = true; }
    if (!spec || !crop) return;
    const mask = spec.mask && this.pics[spec.mask], relief = spec.relief && this.pics[spec.relief];
    const keys = ['base', 'r', 'g', 'b'];
    const L = keys.map(k => (k === 'base' ? (spec.base ? this.mat(spec.base) : own) : spec[k] ? this.mat(spec[k]) : null));
    const prop = (f, d) => new THREE.Vector4(...L.map(o => (o ? num(f(o), d) : d)));
    const flip = face === 'back' ? [-1, 1] : [1, -1];             // picture x, y (down) to the face's tangent frame
    // the brushing: per layer (mode, at x, at y): mode 0 a fixed direction (at = the direction), 1 circles, 2 rays
    const brush = keys.map(k => {
      const q = (spec.brush || {})[k], g = q && q.grooves, at = q && Array.isArray(q.at) ? q.at : [0, 0];
      if (g === 'circles' || g === 'rays') return new THREE.Vector4(g === 'circles' ? 1 : 2, at[0], at[1], 0);
      const a = (g === 'x' ? 0 : g === 'y' ? 90 : num(typeof g === 'string' ? parseFloat(g) : g, 0)) * DEG;
      return new THREE.Vector4(0, -Math.sin(a), Math.cos(a), 0);  // across the grooves
    });
    const aniso = prop(o => o.anisotropy, 0), coat = prop(o => o.clearcoat, 0);
    // the mask and the relief in one texture, mipmapped (the relief's slopes are taken in the shader)
    let W = 2, H = 2, data = new Uint8Array([0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255]);
    if (mask || relief) {
      const cm = mask ? raster(mask, crop, s, '#000') : null, cr = relief ? raster(relief, crop, s, '#fff') : null, any = cm || cr;
      W = any.width; H = any.height;
      const dm = cm && cm.getContext('2d').getImageData(0, 0, W, H).data, dr = cr && cr.getContext('2d').getImageData(0, 0, W, H).data;
      data = new Uint8Array(W * H * 4);
      for (let i = 0; i < W * H * 4; i += 4) {
        data[i] = dm ? dm[i] : 0; data[i + 1] = dm ? dm[i + 1] : 0; data[i + 2] = dm ? dm[i + 2] : 0; data[i + 3] = dr ? dr[i] : 255;
      }
    }
    const mt = new THREE.DataTexture(data, W, H, THREE.RGBAFormat, THREE.UnsignedByteType);
    mt.colorSpace = THREE.NoColorSpace; mt.flipY = false; mt.generateMipmaps = true; mt.anisotropy = this.aniso;
    mt.minFilter = THREE.LinearMipmapLinearFilter; mt.magFilter = THREE.LinearFilter; mt.needsUpdate = true;
    this.texList.push(mt);
    // the crown (and a flat one when there is only the relief: the relief needs the face's tangent frame)
    const crownMap = this.crownMap(part, Array.isArray(spec.crown) ? spec.crown : [0, 0], flip);
    const anyCoat = coat.toArray().some(v => v > 0), anyAniso = aniso.toArray().some(v => v > 0);
    const b = x.userData.base;
    x.roughness = 1; x.metalness = 1; b.spec = 1; x.specularIntensity = 1;
    b.clearcoat = anyCoat ? 1 : 0; x.clearcoat = b.clearcoat; x.anisotropy = anyAniso ? 1 : 0; x.anisotropyRotation = 0;
    x.normalMap = crownMap.texture; x.normalScale.set(crownMap.scale, crownMap.scale);
    x.clearcoatNormalMap = anyCoat ? crownMap.texture : null; x.clearcoatNormalScale.set(crownMap.scale, crownMap.scale);
    const reliefOn = !!relief && num(spec.relief_mm, 0) > 0;
    const U = {
      fMask: { value: mt }, fHave: { value: new THREE.Vector4(1, L[1] ? 1 : 0, L[2] ? 1 : 0, L[3] ? 1 : 0) },
      fRough: { value: prop(o => o.roughness, 0.7) }, fMetal: { value: prop(o => o.metalness, 0) },
      fCoat: { value: coat }, fCoatRough: { value: prop(o => o.clearcoat_roughness, 0.04) },
      fSpec: { value: prop(o => o.specular, 0.5) }, fAniso: { value: aniso }, fBrush: { value: brush },
      fCol: { value: L.map(o => new THREE.Color(o ? o.colour : '#ffffff')) },
      fCrop: { value: new THREE.Vector4(...crop) }, fFlip: { value: new THREE.Vector2(...flip) },
      // the relief: its depth (mm) and a texel's size (mm) across and down, and the texture's size
      fRelief: { value: new THREE.Vector4(num(spec.relief_mm, 0), crop[2] / W / this.m.upm, crop[3] / H / this.m.upm, 0) },
      fSize: { value: new THREE.Vector2(W, H) },
    };
    x.userData.finish = U;
    x.onBeforeCompile = sh => finishShader(sh, U, reliefOn);
    x.customProgramCacheKey = () => 'finish' + (reliefOn ? '+relief' : '');
    x.needsUpdate = true;
  }
  // The crown as a normal map: the face higher in the middle by crown[0] mm across and crown[1] along, a parabola each way
  // over the face's outline (the box of its pieces), so its slope is linear in x and y. The slopes are stored divided by
  // the largest (normalScale gives that back); texel centres fall on the outline's box (repeat and offset), so the bilinear
  // filter reproduces the slopes exactly between them.
  crownMap(p, crown, flip) {
    const N = 17, M = 23, upm = this.m.upm, c = this.crop(p);
    // the box of the part's outline (its crop less the margin), and half its size in mm; the faces' crops are this one,
    // mirrored or turned (the same box, about the same middle), so one mapping serves front and back
    const box = [c[0] + 2, c[1] + 2, c[2] - 4, c[3] - 4], hw = box[2] / 2 / upm, hh = box[3] / 2 / upm;
    const sx = 2 * crown[0] / hw, sy = 2 * crown[1] / hh, S = Math.max(1e-4, sx, sy) * 1.02;
    const prec = this.finishPrecision(), data = prec === 'float' ? new Float32Array(N * M * 4) : prec === 'half' ? new Uint16Array(N * M * 4) : new Uint8Array(N * M * 4);
    const put = prec === 'float' ? v => v : prec === 'half' ? v => THREE.DataUtils.toHalfFloat(v) : (v, i) => clamp(Math.round(v * 255 + (dither(i) - 0.5)), 0, 255);
    for (let j = 0; j < M; j++) for (let i = 0; i < N; i++) {
      const u = i / (N - 1) * 2 - 1, v = j / (M - 1) * 2 - 1;                  // -1 .. 1 over the box, picture x and y
      // the height's slope in mm per mm, picture frame (y down), into the tangent frame; the normal is (-gx, -gy, 1)
      const gx = -sx * u * flip[0], gy = -sy * v * flip[1], o = (j * N + i) * 4;
      data[o] = put((-gx / S) * 0.5 + 0.5, o); data[o + 1] = put((-gy / S) * 0.5 + 0.5, o + 1); data[o + 2] = put(1, o + 2); data[o + 3] = put(1, o + 3);
    }
    const t = new THREE.DataTexture(data, N, M, THREE.RGBAFormat, prec === 'float' ? THREE.FloatType : prec === 'half' ? THREE.HalfFloatType : THREE.UnsignedByteType);
    t.colorSpace = THREE.NoColorSpace; t.flipY = false; t.generateMipmaps = false;
    t.minFilter = THREE.LinearFilter; t.magFilter = THREE.LinearFilter;
    // uv (over the crop) to the box, and the box onto the texel centres
    const ru = c[2] / box[2], rv = c[3] / box[3], ou = (c[0] - box[0]) / box[2], ov = (c[1] - box[1]) / box[3];
    t.repeat.set(ru * (N - 1) / N, rv * (M - 1) / M); t.offset.set(ou * (N - 1) / N + 0.5 / N, ov * (M - 1) / M + 0.5 / M);
    t.needsUpdate = true;
    this.texList.push(t);
    return { texture: t, scale: S };
  }
  // How precisely the crown's normal map is kept: 32-bit float where the GPU filters it, else half float (always filtered
  // in WebGL 2), else 8 bits (dithered). opts.finishPrecision forces one (a test of the fallbacks).
  finishPrecision() {
    const want = this.opts.finishPrecision, ext = this.renderer.extensions;
    if (want === 'half' || want === 'byte') return want;
    return ext.has('OES_texture_float_linear') ? 'float' : 'half';
  }
  // The screen: the emulator's picture (screenCanvas, at the panel's own size) is the texture itself, sent to the GPU as it
  // is (a few hundred kB a picture), and enlarged in the shader "sharp bilinear", as the 2D page draws it: each pixel a
  // square block of the size the display gives it, smoothed only where two meet.
  screen() {
    const m = this.m, g = m.glass.rect;
    this.screenCanvas = this.screenSrc || Object.assign(document.createElement('canvas'), { width: 2, height: 2 });
    this.sharp = { value: new THREE.Vector3(2, 2, 1) };
    this.screenTexture();
    // the screen gives its own light; the cover glass over it reflects the room's light boxes, more at a grazing angle
    const mat = this.screenMat = new THREE.MeshPhysicalMaterial({ color: 0x000000, emissive: 0xffffff, emissiveMap: this.screenTex, roughness: 0.05, metalness: 0,
      polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -4 });
    mat.onBeforeCompile = sh => {
      sh.uniforms.sharp = this.sharp;
      sh.fragmentShader = 'uniform vec3 sharp;\n' + sh.fragmentShader.replace('#include <emissivemap_fragment>', [
        '#ifdef USE_EMISSIVEMAP',
        '  vec2 sp = vEmissiveMapUv * sharp.xy, sc = fract(sp) - 0.5;',
        '  float sn = max(sharp.z, 1.0), sr = 0.5 - 0.5 / sn;',
        '  vec2 sf = (sc - clamp(sc, -sr, sr)) * sn + 0.5;',
        '  totalEmissiveRadiance *= texture2D(emissiveMap, (floor(sp) + sf) / sharp.xy).rgb;',
        '#endif'].join('\n'));
    };
    mat.customProgramCacheKey = () => 'sharp-screen';
    const mesh = this.screenMesh = new THREE.Mesh(new THREE.PlaneGeometry(g[2] / m.upm, g[3] / m.upm), mat);
    if (m.glass.turned) {
      // a flip: the glass is on the lid's inner face (its back), whose picture is turned over the hinge line; the plane is
      // turned over too, so that the picture stands upright when the lid is open
      const lid = m.parts.find(p => p.id === m.glass.part).pieces[0];
      mesh.position.set((g[0] + g[2] / 2) / m.upm, -(m.turnY - g[1] - g[3] / 2) / m.upm, lid.z0 - 0.05);
      mesh.rotation.x = Math.PI;
    } else mesh.position.set((g[0] + g[2] / 2) / m.upm, -(g[1] + g[3] / 2) / m.upm, m.depth + 0.05);
    this.groups[m.glass.part].add(mesh);
  }
  // A texture of the screen's canvas at its size (a new one when the size changes: the GPU's is fixed).
  screenTexture() {
    const c = this.screenCanvas, old = this.screenTex;
    const t = this.screenTex = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace; t.generateMipmaps = false;
    t.minFilter = THREE.LinearFilter; t.magFilter = THREE.LinearFilter;
    this.screenSize = c.width + 'x' + c.height;
    this.sharp.value.x = c.width; this.sharp.value.y = c.height;
    if (old) {
      old.dispose();
      this.texList = (this.texList || []).filter(x => x !== old).concat(t);
      if (this.screenMat) this.screenMat.emissiveMap = t;
    }
  }
  // A new picture on the screen's canvas: it goes to the GPU with the next frame.
  copyScreen() {
    const c = this.screenCanvas;
    if (!c || !c.width || !c.height) return false;
    if (this.screenSize !== c.width + 'x' + c.height) this.screenTexture();
    this.screenTex.needsUpdate = true;
    this.dirtyScreen = false;
    return true;
  }
  // A soft shadow on the page behind the phone, under its outline as it is turned.
  shadow() {
    const c = document.createElement('canvas'), W = 128, H = 256, b = 22;
    c.width = W; c.height = H;
    const g = c.getContext('2d');
    g.shadowColor = '#000'; g.shadowBlur = b; g.shadowOffsetX = 1000;
    g.fillStyle = '#000';
    const r = 18;
    g.beginPath();
    g.roundRect ? g.roundRect(b - 1000, b, W - 2 * b, H - 2 * b, r) : g.rect(b - 1000, b, W - 2 * b, H - 2 * b);
    g.fill();
    const t = this.shadowTex = new THREE.CanvasTexture(c);
    this.shadowBlur = b / (W - 2 * b);                              // the blur, as a part of the width it lies round
    const dark = matchMedia && matchMedia('(prefers-color-scheme: dark)').matches;
    const mat = new THREE.MeshBasicMaterial({ map: t, transparent: true, depthWrite: false, opacity: 0, color: 0xffffff });
    this.shadowOpacity = num(this.opts.shadow, dark ? 0.6 : 0.32);
    const mesh = this.shadowMesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), mat);
    mesh.renderOrder = -1;
    this.scene.add(mesh);
  }

  // ---- where it is ----
  // The 2D page draws the open picture at k CSS pixels per unit with its top left at (x, y) of the container.
  setView(v) {
    const was = this.view;
    this.view = v && isFinite(v.k) && v.k > 0 ? { k: v.k, x: v.x, y: v.y } : null;
    if (was && this.view && was.k === this.view.k && was.x === this.view.x && was.y === this.view.y) return;
    this.invalidate();
    // drawn larger than the pictures were made for (a larger window): new ones, once it has stayed so for a moment
    if (this.prepared && this.view && this.texScale < 5 && this.view.k * this.ratio() > this.texScale * 1.15) {
      clearTimeout(this.sharpen);
      this.sharpen = setTimeout(() => { if (this.prepared) { this.textures(); this.invalidate(); } }, 400);
    }
  }
  fitView() {
    const m = this.m, w = this.container.clientWidth || 300, h = this.container.clientHeight || 500, br = m.br;
    const k = Math.min(w * 0.84 / br[2], h * 0.88 / (br[3] + m.T));
    const u = br[0] + br[2] / 2, v = this.pivotV();
    return { k, x: w / 2 - u * k, y: h / 2 - v * k };
  }
  // The pixel ratio for a canvas of `area` CSS px (by default the part of the container drawn at rest, else all of it).
  ratio(area = (this.band ? this.band.w : this.container.clientWidth || 1) * (this.container.clientHeight || 1)) {
    const d = devicePixelRatio || 1;
    let r = Math.min(d, this.ratioCap);
    while (r > 1 && area * r * r > MAX_PIXELS) r = Math.max(1, r > 2 ? 2 : r - 0.25);
    return r;
  }
  pivotV(p = this.p) { const br = this.m.br; return br[1] + this.m.T + br[3] / 2 - this.m.grow(p) / 2; }
  setSlide(p) { if (p === this.p) return; this.p = p; this.invalidate(); }
  frame() { this.dirtyScreen = true; if (this.shown && this.prepared) { this.copyScreen(); this.invalidate(); } }
  async setVariant(id) {
    const v = this.pickVariant(id);
    if (v === this.variant) return;
    this.variant = v;
    if (!this.prepared) return;
    await this.loadPictures();
    if (this.variant !== v) return;
    this.textures(); this.invalidate();
  }

  // The band of the container the canvas covers (CSS px: x, w): all of it unless the main view is at rest; then the phone's
  // width with room for its shadow and its side keys, kept while it still fits (no new canvas for each frame of a slide).
  bandFor(view, W) {
    if (!this.main || this.active) return (this.band = null) || { x: 0, w: W };
    const m = this.m, pw = m.br[2] * view.k, cx = view.x + (m.br[0] + m.br[2] / 2) * view.k, need = pw * 1.3 + 48;
    const was = this.band;
    const bw = Math.min(W, was && was.w >= Math.min(W, need) && was.w <= need * 1.25 + 64 ? was.w : Math.ceil(need * 1.1 / 32) * 32);
    return (this.band = { x: clamp(Math.round(cx - bw / 2), 0, W - bw), w: bw });
  }
  place() {
    const m = this.m, view = this.view || this.fitView();
    const w = this.container.clientWidth || 1, h = this.container.clientHeight || 1;
    // the canvas: at rest (the main view) only a band of the container's full height round the phone, so that a large
    // window still gets the display's full pixel ratio; turned, all of it. The camera draws that part of the whole view.
    const band = this.bandFor(view, w), ratio = this.ratio(band.w * h);
    if (this.size !== `${band.w}x${h}@${ratio}`) {
      this.size = `${band.w}x${h}@${ratio}`; this.renderer.setPixelRatio(ratio); this.renderer.setSize(band.w, h, false);
      this.canvas.style.width = band.w + 'px';
    }
    if (this.canvas.style.left !== band.x + 'px') this.canvas.style.left = band.x + 'px';
    // how far it is turned from facing front: s, 0 at rest .. 1 turned
    const turned = Math.acos(clamp(Math.cos(this.yaw) * Math.cos(this.pitch), -1, 1));
    const s = smooth(0, 0.5, turned);
    if (m.joint) JOINTS[m.joint.type](this.groups[m.joint.part], m.joint, clamp(this.p, -0.1, 1.1), this.blend === false ? 1 : s);
    const pu = m.br[0] + m.br[2] / 2, pv = this.pivotV(), pz = m.depth / 2;
    this.phone.position.set(-pu / m.upm, (pv - m.T) / m.upm, -pz);      // pv is in the open picture
    this.root.rotation.set(this.pitch, this.yaw, 0, 'XYZ');
    // the camera: the plane of the front at rest (a flip open: the base's front) falls exactly on the 2D picture, k CSS px a
    // unit at (x, y); turned, the phone gets some depth. The main view's eye is at a distance in mm of the phone (the same
    // depth at any size of window); the other's angle of view is almost flat at rest, so that it is the 2D picture.
    const pxmm = view.k * m.upm;
    let D, fov;
    if (this.main) { D = EYE_REST + (EYE_TURNED - EYE_REST) * s; fov = 2 * Math.atan(h / 2 / (D * pxmm)) / DEG; }
    else { fov = FOV_FLAT + (FOV_TURNED - FOV_FLAT) * s; D = h / (2 * Math.tan(fov * DEG / 2)) / pxmm; }
    const zRef = (m.frontAt(this.p) - pz) * (1 - s);
    // the screen's pixels: device pixels for each of them, for the sharp enlargement
    if (this.sharp) this.sharp.value.z = m.glass.rect[2] * view.k * ratio / Math.max(1, this.screenCanvas.width);
    const cam = this.camera;
    cam.fov = fov; cam.aspect = w / h;
    cam.position.set(0, 0, zRef + D);
    cam.near = Math.max(1, D - 160); cam.far = D + 260;
    const Px = view.x + pu * view.k, Py = view.y + pv * view.k;
    cam.setViewOffset(w, h, w / 2 - Px + band.x, h / 2 - Py, band.w, h);
    cam.updateProjectionMatrix();
    const lit = this.blend === false ? 1 : this.restLit + (1 - this.restLit) * s;
    if (lit !== this.litWas) { this.light(lit); this.litWas = lit; }
    // facing front the other view is the 2D picture: no shadow of its own (it comes in as the phone turns), the side keys
    // flush; the main view has its light, its shadow and its side keys standing out at rest too
    this.shadowMesh.material.opacity = this.shadowOpacity * lit;
    if (Math.abs(lit - (this.out ?? -1)) > 0.002 || (lit === 0) !== (this.out === 0)) { this.out = lit; for (const c of this.caps) if (c.outward) this.pressCap(c, true); }
    // the shadow: behind, as large as the phone's outline seen from the front, a little lower (the light is above)
    const box = new THREE.Box3();
    for (const mesh of this.meshes) { mesh.updateWorldMatrix(true, false); box.union(mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld)); }
    const sw = box.max.x - box.min.x, sh = box.max.y - box.min.y, zs = -m.depth * 2.2 - 20, grow = 1 + 2 * this.shadowBlur;
    const far = (zRef + D - zs) / (zRef + D);                      // the plane is further away: as large on the display
    this.shadowMesh.position.set((box.min.x + box.max.x) / 2 * far + 0.4, ((box.min.y + box.max.y) / 2 - 1.6) * far, zs);
    this.shadowMesh.scale.set((sw * grow + 1) * far, (sh + sw * 2 * this.shadowBlur + 1) * far, 1);
    this.posed = this.poseKey();
  }

  // ---- drawing on demand ----
  invalidate() {
    if (!this.shown || !this.prepared || this.raf || this.lost) return;
    this.askedAt = performance.now();
    this.raf = requestAnimationFrame(t => this.tick(t));
  }
  tick(now) {
    this.raf = 0;
    const dt = this.last ? Math.min(0.05, (now - this.last) / 1000) : 1 / 60;
    // a frame asked for as soon as the last was drawn: one of a run (a slide, a turn), whose gap measures the frame rate
    if (this.drawnAt && this.askedAt - this.drawnDone < 10 && now - this.drawnAt < 150) this.adapt(now - this.drawnAt);
    this.last = now;
    const moving = this.step(dt);
    this.render();
    this.drawnAt = now; this.drawnDone = performance.now();
    if (moving) this.invalidate(); else this.last = 0;
  }
  // The pixel ratio follows the GPU: frames drawn one after the other (a slide, a turn) that come much further apart than the
  // display's own frames, while this module's own work on the CPU is a small part of the gap, mean the GPU has too many
  // pixels to fill: the ratio goes down a step (not below RATIO_FLOOR).
  adapt(gap) {
    const g = this.gaps;
    g.push(gap);
    this.vsync = Math.min(this.vsync || 1000, Math.max(6, gap));
    if (g.length < 30) return;
    const sorted = g.slice().sort((a, b) => a - b), median = sorted[15], cpu = this.stat.cpuMs;
    g.length = 0;
    const r = this.ratio();
    if (median > 1.6 * this.vsync && cpu < 0.35 * median && r > RATIO_FLOOR) {
      this.ratioCap = Math.max(RATIO_FLOOR, r - RATIO_STEP);
      this.adapted = (this.adapted || 0) + 1;
    }
  }
  render() {
    if (!this.prepared || this.lost) return;
    if (this.dirtyScreen) this.copyScreen();
    this.place();
    const t0 = performance.now();
    this.renderer.render(this.scene, this.camera);
    const ms = performance.now() - t0, info = this.renderer.info.render;
    this.stat.renders++; this.stat.calls = info.calls; this.stat.triangles = info.triangles; this.stat.cpuMs = ms;
    this.times.push([performance.now(), ms]); if (this.times.length > 240) this.times.shift();
    if (this.onRender) this.onRender();
  }
  // The motion: a held phone follows the finger; let go, it keeps turning and slows down, or a spring takes it to a pose.
  step(dt) {
    if (this.pointers.size) return false;
    let moving = false;
    if (this.target) {
      const w = 11, z = 1, t = this.target;
      for (const [a, va, to] of [['yaw', 'vYaw', t.yaw], ['pitch', 'vPitch', t.pitch]]) {
        const x = this[a] - to;
        this[va] += (-w * w * x - 2 * z * w * this[va]) * dt;
        this[a] += this[va] * dt;
      }
      if (Math.abs(this.yaw - t.yaw) < 0.002 && Math.abs(this.pitch - t.pitch) < 0.002 && Math.abs(this.vYaw) + Math.abs(this.vPitch) < 0.02) {
        this.yaw = t.yaw; this.pitch = t.pitch; this.vYaw = this.vPitch = 0; this.target = null;
        if (t.then) t.then();
      } else moving = true;
    } else if (Math.abs(this.vYaw) + Math.abs(this.vPitch) > 0.01) {
      const k = Math.exp(-3.2 * dt);
      this.yaw += this.vYaw * dt; this.pitch = clamp(this.pitch + this.vPitch * dt, -PITCH_MAX, PITCH_MAX);
      if (Math.abs(this.pitch) >= PITCH_MAX) this.vPitch = 0;
      this.vYaw *= k; this.vPitch *= k;
      moving = true;
      if (Math.abs(this.vYaw) + Math.abs(this.vPitch) <= 0.01) this.settle();
    }
    return moving;
  }
  // Where a turn ends: near the front, the phone goes back to the 2D page; held for a look (peek), to the nearer of front and back.
  settle(predict = false) {
    const ahead = predict ? 1 / 3.2 : 0, yaw = this.yaw + this.vYaw * ahead, pitch = clamp(this.pitch + this.vPitch * ahead, -PITCH_MAX, PITCH_MAX);
    const nearFront = Math.abs(wrap(yaw)) < 28 * DEG && Math.abs(pitch) < 28 * DEG;
    if (nearFront) return this.turnTo(yaw - wrap(yaw), 0, () => this.leave());
    if (this.peek) {
      const back = Math.abs(wrap(yaw)) > Math.PI / 2;
      const to = yaw - wrap(yaw) + (back ? Math.PI * Math.sign(wrap(yaw) || 1) : 0);
      this.peek = !back ? this.peek : false;
      return this.turnTo(to, 0, back ? null : () => this.leave());
    }
    return false;
  }
  turnTo(yaw, pitch, then) { this.target = { yaw, pitch, then }; this.invalidate(); return true; }
  /** Turn it over: to its back, or from its back to the front (and stay in 3D). */
  flip() {
    if (!this.active) return this.enter({ pose: 'back' });
    this.peek = false;
    // on round in the direction it is turned: front to back is half a turn, back to front the rest of the turn
    const w = wrap(this.yaw), dir = w < 0 ? -1 : 1, toBack = Math.abs(w) < Math.PI / 2;
    this.turnTo(this.yaw - w + dir * (toBack ? Math.PI : 2 * Math.PI), 0);
    return Promise.resolve();
  }
  /** Set the pose at once (radians): for tests and for a page that remembers it. */
  pose(yaw, pitch = 0) { this.target = null; this.vYaw = this.vPitch = 0; this.yaw = yaw; this.pitch = clamp(pitch, -PITCH_MAX, PITCH_MAX); this.invalidate(); }

  // ---- into the 3D view and out ----
  // A swap, never a cross-fade: the first frame of the 3D view is drawn facing front, where the 2D page draws the phone,
  // and in the same animation frame the 3D layer shows and the 2D phone hides (so there is never a frame with two phones,
  // nor one half seen through the other). Only then does it turn. Out, the other way: it turns to the front, that frame is
  // drawn, and in the next frame the 2D phone shows and the 3D layer hides.
  async enter(o = {}) {
    if (this.active && !this.leaving) { if (o.pose) this.posePreset(o.pose); return; }
    this.active = true; this.leaving = false; this.peek = !!o.peek;
    if (this.main) {                                               // already drawn: no swap, it only turns
      this.layer.classList.add('active');
      if (this.onMode) this.onMode(true);
      if (o.pose) this.posePreset(o.pose);
      this.invalidate();
      return;
    }
    if (this.onMode) this.onMode(true);
    try { await this.prepare(); } catch (e) { this.active = false; if (this.onMode) this.onMode(false); throw e; }
    if (!this.active) return;
    if (!this.shown) { this.yaw = 0; this.pitch = 0; this.vYaw = this.vPitch = 0; this.target = null; }   // as the 2D phone
    await this.swapIn();
    if (!this.active) return;
    if (o.pose) this.posePreset(o.pose);
    this.invalidate();
  }
  swapIn() {
    if (this.shown) { this.showLayer(true); return Promise.resolve(); }
    this.layer.hidden = false;                                     // laid out, still transparent
    return new Promise(res => {
      cancelAnimationFrame(this.swapRaf);
      this.swapRaf = requestAnimationFrame(() => {
        this.swapRaf = 0;
        if (!this.active) { this.layer.hidden = true; return res(); }
        this.shown = true;
        this.copyScreen(); this.render();                          // the first frame, facing front
        this.showLayer(true);                                      // and the swap, in the same frame
        res();
      });
    });
  }
  // The 3D layer shown and the 2D phone hidden, or the other way round, at once.
  showLayer(on) {
    for (const el of this.flat) el.style.visibility = on ? 'hidden' : '';
    this.layer.classList.toggle('on', on);
  }
  posePreset(name) {
    const P = { front: [0, 0], three: [-0.62, 0.2], back: [Math.PI, 0], left: [Math.PI / 2, 0], right: [-Math.PI / 2, 0], top: [0, 0.95] };
    const p = P[name] || P.three;
    this.peek = false;
    this.turnTo(this.yaw - wrap(this.yaw) + p[0], clamp(p[1], -PITCH_MAX, PITCH_MAX));
  }
  /** Back to the 2D page: the phone turns to the front, then the 2D phone shows again. */
  exit() {
    if (!this.active) return Promise.resolve();
    return new Promise(res => { this.turnTo(this.yaw - wrap(this.yaw), 0, () => { this.leave(); res(); }); });
  }
  leave() {
    if (!this.active || this.leaving) return;
    if (this.main) {                                               // facing front again: it stays, at rest
      this.active = false; this.peek = false;
      this.layer.classList.remove('active');
      if (this.onMode) this.onMode(false);
      this.invalidate();
      return;
    }
    this.leaving = true;
    // the frame facing front is drawn in this animation frame (leave() is called as the turn ends); the swap in the next
    cancelAnimationFrame(this.swapRaf);
    this.swapRaf = requestAnimationFrame(() => {
      this.swapRaf = 0;
      if (!this.leaving) return;
      this.showLayer(false);
      this.layer.hidden = true; this.shown = false; this.active = false; this.leaving = false; this.peek = false;
      if (this.raf) cancelAnimationFrame(this.raf); this.raf = 0; this.last = 0;
      if (this.onMode) this.onMode(false);
    });
  }
  // A leave taken back before its swap (a finger came down in that frame): the 3D view stays.
  resume() { this.leaving = false; cancelAnimationFrame(this.swapRaf); this.swapRaf = 0; }

  // ---- the main view: the phone drawn here all the time ----
  /** Build, draw the first frame facing front, and show it (opts.main). Rejects where there is no WebGL. */
  async start() {
    this.main = true;
    await this.prepare();
    if (!this.prepared) throw new Error('not built');
    this.shown = true; this.layer.hidden = false;
    this.copyScreen(); this.render();
    void this.layer.offsetWidth;                                   // laid out transparent first: .fade comes in from there
    this.layer.classList.add('on');
  }
  // The page's frame of a part at rest: the face the 2D page draws (the front; a flip's lid, its inner face), in the part's
  // own frame (mm, the part where it is closed) and how its picture units become the page's (the open picture). The still
  // part is lower by T in the open picture; a slide's face by T (1 - p); a flip's lid is turned over the hinge line.
  facePlane(which) {
    const m = this.m, part = m.parts.find(p => (which === 'moving') === !!p.moving) || m.parts[0];
    const piece = part.pieces[0], lid = !!m.hinge && part.moving;
    const mesh = this.meshes.find(x => x.userData.part === part.id && x.userData.piece === piece.id);
    const T = m.T, p = clamp(this.p, 0, 1);
    return { mesh, z: lid ? piece.z0 : piece.z1, n: lid ? -1 : 1,
      toPage: y => (lid ? m.turnY - y : part.moving ? y + T * (1 - p) : y + T),
      fromPage: v => (lid ? m.turnY - v : part.moving ? v - T * (1 - p) : v - T) };
  }
  // The part of the view the canvas draws: in client px, or (local) in the container's own px.
  drawn(local = false) {
    const r = local ? { left: 0, top: 0 } : this.container.getBoundingClientRect(), b = this.band;
    return { left: r.left + (b ? b.x : 0), top: r.top, w: b ? b.w : this.container.clientWidth || 1, h: this.container.clientHeight || 1 };
  }
  /** Where a point of the display (client px) is on a part's face, in the page's units (the open picture): [u, v], or null. */
  pick(cx, cy, which = 'still') {
    if (!this.prepared || !this.camera) return null;
    if (this.posed !== this.poseKey()) this.place();
    const f = this.facePlane(which);
    if (!f.mesh) return null;
    const r = this.drawn(), w = r.w, h = r.h;
    const ray = (this.ray || (this.ray = new THREE.Raycaster())).ray;
    this.ray.setFromCamera(new THREE.Vector2((cx - r.left) / w * 2 - 1, -((cy - r.top) / h) * 2 + 1), this.camera);
    f.mesh.updateWorldMatrix(true, false);
    const inv = f.mesh.matrixWorld.clone().invert(), o = ray.origin.clone().applyMatrix4(inv), d = ray.direction.clone().transformDirection(inv);
    if (Math.abs(d.z) < 1e-6) return null;
    const t = (f.z - o.z) / d.z;
    if (t < 0) return null;
    const x = (o.x + d.x * t) * this.m.upm, y = -(o.y + d.y * t) * this.m.upm;
    return [x, f.toPage(y)];
  }
  /** Where a point of a part's face (the page's units) is on the display (client px). */
  project(u, v, which = 'still') {
    if (!this.prepared || !this.camera) return null;
    if (this.posed !== this.poseKey()) this.place();
    const f = this.facePlane(which);
    if (!f.mesh) return null;
    f.mesh.updateWorldMatrix(true, false);
    const q = new THREE.Vector3(u / this.m.upm, -f.fromPage(v) / this.m.upm, f.z).applyMatrix4(f.mesh.matrixWorld).project(this.camera);
    const r = this.drawn(), w = r.w, h = r.h;
    return [r.left + (q.x + 1) / 2 * w, r.top + (1 - q.y) / 2 * h];
  }
  /** The screen's four corners on the container (top left, top right, bottom right, bottom left; CSS px), and whether it
   *  faces the viewer: for the page's words over the screen while the phone starts. */
  screenQuad() {
    if (!this.prepared || !this.screenMesh) return null;
    if (this.posed !== this.poseKey()) this.place();
    const g = this.screenMesh.geometry.parameters, r = this.drawn(true), w = r.w, h = r.h;
    this.screenMesh.updateWorldMatrix(true, false);
    const pts = [[-1, 1], [1, 1], [1, -1], [-1, -1]].map(([a, b]) => {
      const q = new THREE.Vector3(a * g.width / 2, b * g.height / 2, 0).applyMatrix4(this.screenMesh.matrixWorld).project(this.camera);
      return [r.left + (q.x + 1) / 2 * w, r.top + (1 - q.y) / 2 * h];
    });
    let area = 0;
    for (let i = 0; i < 4; i++) { const a = pts[i], b = pts[(i + 1) % 4]; area += a[0] * b[1] - b[0] * a[1]; }
    return { pts, facing: area > 0 };
  }
  // What place() depends on: picking between two frames uses the pose the next frame will have.
  poseKey() { const v = this.view || {}; return `${this.p}|${v.k}|${v.x}|${v.y}|${this.yaw}|${this.pitch}|${this.container.clientWidth}x${this.container.clientHeight}`; }

  // ---- fingers ----
  buttons() {
    const bar = document.createElement('div');
    bar.className = 'p3d-bar';
    const svg = d => { const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true'); const p = document.createElementNS('http://www.w3.org/2000/svg', 'path'); p.setAttribute('d', d); s.append(p); return s; };
    const b = (cls, label, d, fn) => { const x = document.createElement('button'); x.type = 'button'; x.className = 'p3d-btn ' + cls; x.setAttribute('aria-label', label); x.title = label; x.append(svg(d)); x.addEventListener('click', e => { e.stopPropagation(); fn(); }); return x; };
    bar.append(b('p3d-flip', 'Turn it over', 'M12 3v18M8.5 6.5L4 12l4.5 5.5M15.5 6.5L20 12l-4.5 5.5', () => this.flip()),
      b('p3d-use', 'Use the phone', 'M5 12.5l4.5 4.5L19 7.5', () => this.exit()));
    return bar;
  }
  listen() {
    const el = this.opts.gestures || this.container;
    this.el = el;
    const opt = { capture: true, passive: false };
    this.handlers = [['pointerdown', e => this.down(e)], ['pointermove', e => this.move(e)], ['pointerup', e => this.up(e)], ['pointercancel', e => this.up(e)],
      ['lostpointercapture', e => { if (this.pointers.has(e.pointerId)) this.up(e); }]];
    for (const [t, f] of this.handlers) el.addEventListener(t, f, opt);
    this.resize = new ResizeObserver(() => { if (this.shown) this.invalidate(); });
    this.resize.observe(this.container);
  }
  // Whether a point of the display is on a key of the 2D phone (its rectangle in the skin, a little grown), where the page
  // draws it (setView): the keys of the slab that stays are lower by the travel in the open picture, those of the moving
  // slab by the part of it not yet slid.
  onPageKey(cx, cy) {
    const v = this.view, m = this.m;
    if (!v) return false;
    if (m.hinge && this.p < 0.98) return false;                     // a flip not open: the lid covers every key
    const r = this.container.getBoundingClientRect(), pad = 3;
    for (const part of m.parts) {
      const dy = part.moving ? m.T * (1 - clamp(this.p, 0, 1)) : m.T;
      // drawn here (the main view): where the finger is on that part's face; else where the 2D page draws it
      const q = this.main && this.shown ? this.pick(cx, cy, part.moving ? 'moving' : 'still') : null;
      const u = q ? q[0] : (cx - r.left - v.x) / v.k, w = q ? q[1] : (cy - r.top - v.y) / v.k;
      for (const k of Object.values(m.keys[part.id] || {}))
        if (u > k[0] - pad && u < k[0] + k[2] + pad && w > k[1] + dy - pad && w < k[1] + k[3] + dy + pad) return true;
    }
    return false;
  }
  ours(e) { return !(e.target && e.target.closest && e.target.closest('button, input, select, a, summary, label, [data-p3d-ignore]')); }
  down(e) {
    if (!this.ours(e)) return;
    const at = [e.clientX, e.clientY];
    if (!this.active) {
      if (e.pointerType !== 'touch' || this.opts.twoFingers === false) return;
      this.touches.set(e.pointerId, { at, key: this.onPageKey(e.clientX, e.clientY) });
      // two fingers on the phone, neither on a key: pick it up and turn it. A finger on a key is a press of that key (two
      // thumbs typing overlap: the second lands before the first lifts), never the way into 3D.
      if (this.touches.size === 2 && ![...this.touches.values()].some(t => t.key)) {
        e.stopImmediatePropagation(); e.preventDefault();
        for (const [id, t] of this.touches) this.pointers.set(id, { at: t.at, start: t.at, moved: true });
        this.track = [];
        this.enter({ peek: true, keepPose: true });
      }
      return;
    }
    e.stopImmediatePropagation(); e.preventDefault();
    if (this.leaving) this.resume();                                // caught in the frame before its swap out: it stays
    try { this.el.setPointerCapture(e.pointerId); } catch (x) { /* fine */ }
    this.pointers.set(e.pointerId, { at, start: at, moved: false, t: performance.now() });
    this.target = null; this.vYaw = this.vPitch = 0; this.track = [];
    this.layer.classList.add('held');
    if (this.pointers.size === 1 && this.shown) {
      const k = this.keyAt(e.clientX, e.clientY);
      if (k) { this.keyDown = { name: k, id: e.pointerId }; this.setKey(k, true); if (this.onKey) this.onKey(k, true); }
    } else this.release();
  }
  /** A drag the page started (a finger beside the phone, or one moved sideways): it turns the phone from here. */
  grab(e) {
    const at = [e.clientX, e.clientY];
    this.pointers.set(e.pointerId, { at, start: at, moved: true, t: performance.now() });
    this.track = [];
    try { this.el.setPointerCapture(e.pointerId); } catch (x) { /* fine */ }
    this.layer.classList.add('held');
    return this.enter({ peek: !this.active || this.peek, keepPose: true });
  }
  centre() { let x = 0, y = 0; for (const p of this.pointers.values()) { x += p.at[0]; y += p.at[1]; } return [x / this.pointers.size, y / this.pointers.size]; }
  move(e) {
    if (!this.active) { const t = this.touches.get(e.pointerId); if (t) t.at = [e.clientX, e.clientY]; return; }
    const p = this.pointers.get(e.pointerId);
    if (!p) return;
    e.stopImmediatePropagation(); e.preventDefault();
    if (!this.shown) { p.at = [e.clientX, e.clientY]; return; }   // not swapped in yet: the turn starts from here
    const c0 = this.centre();
    p.at = [e.clientX, e.clientY];
    if (!p.moved && Math.hypot(p.at[0] - p.start[0], p.at[1] - p.start[1]) < 7) return;
    if (!p.moved) { p.moved = true; this.release(); }
    const c1 = this.centre();
    const per = Math.PI / Math.max(320, (this.container.clientWidth || 400) * 0.9);
    this.yaw += (c1[0] - c0[0]) * per;
    this.pitch = clamp(this.pitch + (c1[1] - c0[1]) * per, -PITCH_MAX, PITCH_MAX);
    const now = performance.now();
    this.track.push([now, this.yaw, this.pitch]);
    while (this.track.length > 2 && now - this.track[0][0] > 110) this.track.shift();
    this.invalidate();
  }
  up(e) {
    this.touches.delete(e.pointerId);
    const p = this.pointers.get(e.pointerId);
    if (!p) return;
    e.stopImmediatePropagation();
    this.pointers.delete(e.pointerId);
    if (this.keyDown && this.keyDown.id === e.pointerId) this.release();
    if (this.pointers.size) return;
    this.layer.classList.remove('held');
    const now = performance.now();
    if (!p.moved && e.type === 'pointerup') {                      // a tap; two quick taps turn it over
      const l = this.lastTap;
      if (l && now - l.t < 330 && Math.hypot(l.at[0] - p.at[0], l.at[1] - p.at[1]) < 32) { this.lastTap = null; this.flip(); return; }
      this.lastTap = { t: now, at: p.at };
    }
    const t = this.track || [];
    if (t.length > 1 && now - t[t.length - 1][0] < 80) {
      const a = t[0], b = t[t.length - 1], s = Math.max(0.016, (b[0] - a[0]) / 1000);
      this.vYaw = clamp((b[1] - a[1]) / s, -14, 14); this.vPitch = clamp((b[2] - a[2]) / s, -8, 8);
    } else { this.vYaw = this.vPitch = 0; }
    this.track = [];
    if (this.peek || Math.abs(this.vYaw) + Math.abs(this.vPitch) < 0.05) { if (!this.settle(true)) this.invalidate(); }
    else this.invalidate();
  }
  release() { if (this.keyDown) { const k = this.keyDown.name; this.keyDown = null; this.setKey(k, false); if (this.onKey) this.onKey(k, false); } }
  // The key under a point of the display, on a part's front that faces the viewer.
  keyAt(cx, cy) {
    if (!this.prepared) return null;
    const r = this.canvas.getBoundingClientRect(), ray = new THREE.Raycaster(), m = this.m;
    ray.setFromCamera(new THREE.Vector2((cx - r.left) / r.width * 2 - 1, -((cy - r.top) / r.height) * 2 + 1), this.camera);
    const hit = ray.intersectObjects(this.meshes, false)[0];
    if (!hit || !hit.face) return null;
    const local = hit.object.worldToLocal(hit.point.clone()), x = local.x * m.upm, y = -local.y * m.upm, n = hit.face.normal;
    const own = hit.object.geometry.userData.owner, cap = own && own[hit.face.a] >= 0 ? this.caps[own[hit.face.a]] : null;
    if (cap && cap.keys.length === 1) return cap.keys[0];          // a key's solid: that key (the coin: the nearest of its keys)
    let best = null, bd = cap ? Infinity : 3;
    if (cap || n.z >= 0.5) {                                       // the front: the skin's key rectangles
      for (const [name, k] of Object.entries(m.keys[hit.object.userData.part] || {})) {
        if (cap && !cap.keys.includes(name)) continue;
        const d = Math.hypot(Math.max(k[0] - x, 0, x - k[0] - k[2]), Math.max(k[1] - y, 0, y - k[1] - k[3]));
        if (d < bd) { bd = d; best = name; }
      }
      return best;
    }
    // a wall: the side keys of body3d.keys (y in closed px along the side, z in mm from the front)
    const side = Math.abs(n.x) >= Math.abs(n.y) ? (n.x < 0 ? 'left' : 'right') : (n.y > 0 ? 'top' : 'bottom');
    const along = side === 'left' || side === 'right' ? y : x, z = m.depth - local.z;
    for (const k of m.sideKeys) {
      const span = k.y || k.x;
      if (k.side !== side || !span || !k.z) continue;
      const d = Math.hypot(Math.max(span[0] - along, 0, along - span[1]), Math.max(k.z[0] - z, 0, z - k.z[1]) * m.upm);
      if (d < bd * 2) { bd = d / 2; best = k.key; }
    }
    return best;
  }

  // How much the light shows on the fronts and in the glass: none facing front at rest (the 2D picture), all when turned.
  light(s) {
    for (const x of this.rest) {
      const b = x.userData.base;
      if (!b) continue;
      x.color.copy(b.colour).multiplyScalar(s);
      if (x.emissiveMap) x.emissive.setScalar(1); else x.emissive.copy(b.colour);
      x.emissiveIntensity = 1 - s;
      this.lightUp(x, b, s);
    }
    const g = this.screenMat, b = g && g.userData.base;
    if (b) { this.lightUp(g, b, s); g.emissiveIntensity = 1; }
  }
  // Reflections in proportion to s; a clear coat, sheen or coating never quite 0 (crossing 0 would rebuild the shader).
  lightUp(x, b, s) {
    x.specularIntensity = b.spec * s;
    if (b.clearcoat) x.clearcoat = Math.max(1e-3, b.clearcoat * s);
    if (b.sheen) x.sheen = Math.max(1e-3, b.sheen * s);
    if (b.irid) x.iridescence = Math.max(1e-3, b.irid * s);
  }
  /** Numbers for a test: the last frame's draw calls and triangles, the time of render() on the CPU, the textures' memory. */
  stats() {
    const t = this.times, gaps = [];
    for (let i = 1; i < t.length; i++) gaps.push(t[i][0] - t[i - 1][0]);
    let bytes = 0, finish = 0;
    for (const x of this.texList || []) {
      const i = x.image;
      if (!i || !i.width) continue;
      const n = i.width * i.height * 4 * (i.data ? i.data.BYTES_PER_ELEMENT : 1) * (x.generateMipmaps ? 4 / 3 : 1);
      bytes += n; if (i.data) finish += n;
    }
    // the room: a PMREM of half floats (RGBA, 8 bytes a texel), 3 cube faces wide and 4 high with its blurred levels
    const env = this.env && this.env.image ? this.env.image.width * this.env.image.height * 8 : 0;
    return { renders: this.stat.renders, calls: this.stat.calls, triangles: this.stat.triangles, cpuMs: +this.stat.cpuMs.toFixed(3),
      cpuMsMean: t.length ? +(t.reduce((s, x) => s + x[1], 0) / t.length).toFixed(3) : 0,
      frameGapMs: gaps.length ? +(gaps.reduce((s, x) => s + x, 0) / gaps.length).toFixed(2) : 0,
      textureMB: +(bytes / 1048576).toFixed(1), finishMB: +(finish / 1048576).toFixed(2), envMB: +(env / 1048576).toFixed(1),
      finishPrecision: finish ? this.finishPrecision() : null, textureScale: this.texScale, pixelRatio: this.renderer ? this.renderer.getPixelRatio() : 0,
      ratioSteps: this.adapted || 0, environment: (this.roomSize || ROOM.size) + ' px PMREM (half float)', three: THREE.REVISION };
  }
  dispose() {
    if (this.raf) cancelAnimationFrame(this.raf);
    clearTimeout(this.sharpen);
    cancelAnimationFrame(this.swapRaf);
    for (const [t, f] of this.handlers || []) this.el.removeEventListener(t, f, { capture: true });
    if (this.resize) this.resize.disconnect();
    for (const el of this.flat) el.style.visibility = '';
    if (this.scene) this.scene.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) [].concat(o.material).forEach(x => x.dispose()); });
    for (const t of this.texList || []) t.dispose();
    if (this.env) this.env.dispose();
    if (this.renderer) { this.renderer.dispose(); this.renderer.forceContextLoss(); }
    this.layer.remove();
    this.active = this.shown = this.prepared = false;
  }
}

/** Make a viewer for the phone of a skin in `container` (positioned; the 3D layer covers it). Nothing is drawn until enter(). */
export async function create(container, opts = {}) {
  const skin = opts.skinJson || await (await fetch((opts.skinUrl.endsWith('/') ? opts.skinUrl : opts.skinUrl + '/') + 'skin.json')).json();
  if (!supports(skin) && !opts.force) throw new Error('this skin has no body3d block: no 3D view');
  if (opts.css !== false && !document.querySelector('link[data-p3d]')) {
    const l = document.createElement('link');
    l.rel = 'stylesheet'; l.href = new URL('phone3d.css', import.meta.url).href; l.dataset.p3d = '1';
    document.head.append(l);
  }
  return new Viewer(container, opts, describe(skin));
}

/** The flip's lid turns on its hinge (body3d.hinge): the pages offer the 3D view for a flip when this is true. */
export const hinges = true;
export const Phone3D = { create, supports, hinges, THREE_VERSION };
export default Phone3D;
