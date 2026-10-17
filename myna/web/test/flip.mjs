// flip.mjs: the Myna flip on the phone page in headless Chrome, with no relay (the loopback network).
//
//   MYNA_PYODIDE=DIR node myna/web/test/flip.mjs         (after make -C myna/firmware and sh native/core/build.sh)
//
// Steps: the shelf shows the flip beside the slider; it starts with its lid open (the page tells the phone before it starts)
// and the firmware knows it is in a flip; it registers; the lid is closed (the phone sleeps, the page shows the lid's outside
// and no key answers a finger), opened (the phone wakes); a finger on a key of the open keypad presses it; a text written with
// the keys comes back on loopback; closed and opened again, the phone is awake where it was; the flip keeps its own flash
// state, apart from the slider's. Exit status 0 when every step passed. Environment: lib.mjs.
// SPDX-License-Identifier: MIT
import { start, tab, check, summary, sleep } from './lib.mjs';

const env = await start();
try {
  const t = await tab(env.cdp);
  await t.go(env.base);
  check(await t.waitFor(`!!document.querySelector('.pick[data-name="myna_flip"]') && !!document.querySelector('.pick[data-name="myna"]')`, 20000),
    'the shelf shows the flip beside the slider');
  await t.evaluate(`document.querySelector('.pick[data-name="myna_flip"]').click()`);
  const t0 = Date.now();
  const up = await t.waitFor(`app.frames > 0 || app.error`, 240000) && !(await t.evaluate('app.error'));
  check(up, `first picture (${((Date.now() - t0) / 1000).toFixed(1)} s): ${await t.evaluate('app.error') || 'no error'}`);
  check(await t.waitLine(/board: id 1, P2 flip/, 5000) && await t.waitLine(/\blid: open/, 5000) && await t.waitLine(/display: first frame at .*panel on/, 10000),
    'the phone starts in a flip with its lid open, the panel on');
  check(await t.waitLine(/network: registration 1/, 20000), 'the phone registers');
  await t.shot('flip-01-open');

  // a finger on the 5 of the open keypad
  const press = async (x, y) => {
    await t.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 }); await sleep(120);
    await t.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 }); await sleep(300);
  };
  const [x5, y5] = await t.evaluate(`app.where('5')`);
  await press(x5, y5);
  check(await t.waitLine(/ui: key 5 down/, 3000), 'open: a finger on the 5 presses it');
  await t.key('clear'); await t.key('end');

  // closed: asleep, the lid's outside, no key under a finger
  await t.evaluate(`app.slide(false)`);
  check(await t.waitLine(/ui: lid closed: asleep/, 5000), 'the lid closed: the phone sleeps');
  // the 3D phone (the page's default where there is WebGL): the lid shut on its hinge; the 2D drawing: the lid turned over
  check(await t.waitFor(`app.three() ? app.v3().p === 0 && (q => 2 * Math.acos(Math.min(1, Math.abs(q.w))) < 0.01)(app.v3().groups[app.v3().m.joint.part].quaternion)
    : !document.getElementById('lidBack').hidden && document.getElementById('rig').classList.contains('flip')`, 3000),
  `the page shows the lid shut (${await t.evaluate('app.three() ? "in 3D" : "the 2D drawing"')})`);
  await t.shot('flip-02-closed');
  const n = await t.evaluate(`app.lines.filter(s => /ui: key 2 down/.test(s)).length`);
  const [x2, y2] = await t.evaluate(`app.where('2')`);
  await press(x2, y2);
  check(await t.evaluate(`app.lines.filter(s => /ui: key 2 down/.test(s)).length`) === n, 'closed: a finger where the keypad was presses nothing');
  await t.evaluate(`app.slide(true)`);
  check(await t.waitLine(/ui: lid open: awake \(home\)/, 5000), 'the lid opened: the phone wakes on standby');

  // a text on loopback
  await t.text('5551234', 'hi from the flip');
  const back = await t.waitLine(/message \d+ from \S+ received: "hi from the flip"/i, 30000);
  check(!!back, 'a text sent on loopback comes back: ' + (back || 'nothing').replace(/^.*\| /, ''));
  await sleep(1500);
  await t.shot('flip-03-conversation');

  // closed and opened in the conversation
  await t.evaluate(`app.slide(false)`);
  check(await t.waitLine(/ui: lid closed: asleep \(conversation\)/, 5000), 'closed in the conversation');
  await sleep(800);
  await t.evaluate(`app.slide(true)`);
  check(await t.waitLine(/ui: lid open: awake \(conversation\)/, 5000), 'opened again: back in the conversation');
  await sleep(800);
  await t.shot('flip-04-reopened');

  await t.evaluate(`document.getElementById('off').click()`);
  check(await t.waitFor(`!app.running && location.search === ''`, 30000), 'switched off and put down');
  const keys = await t.waitFor(`new Promise(r => { const q = indexedDB.open('myna-phone', 1); q.onsuccess = () => { const g = q.result.transaction('kv').objectStore('kv').getAllKeys(); g.onsuccess = () => r(g.result.map(String)); }; q.onerror = () => r([]); })`, 10000);
  check(keys && keys.some(k => k.startsWith('state:myna_flip:')) && !keys.some(k => k.startsWith('state:myna:')),
    'its flash state is kept under the flip, not the slider: ' + (keys || []).join(', '));
  if (t.logs.length) console.log('--- page ---\n' + t.logs.join('\n'));
  t.close();
} catch (e) {
  check(false, 'the test ran: ' + (e.message || e));
} finally {
  await env.stop();
}
process.exit(summary());
