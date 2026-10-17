// smoke.mjs: Myna's phone page end to end in headless Chrome, with no relay (the loopback network).
//
//   MYNA_PYODIDE=DIR node myna/web/test/smoke.mjs        (after make -C myna/firmware and sh native/core/build.sh)
//
// Steps: the shelf shows Myna; it starts and draws its first picture; the network is the loopback one and the phone
// registers; a text written with the keys (Messages, New message, a number, multi-tap) is sent and comes back; the phone
// is switched off, its flash state is kept in IndexedDB, and after a reload the text is still in its store.
// Exit status 0 when every step passed. Environment: lib.mjs.
// SPDX-License-Identifier: MIT
import { start, tab, check, summary, sleep } from './lib.mjs';

const env = await start();
try {
  const t = await tab(env.cdp);
  await t.go(env.base);
  check(await t.waitFor(`!!document.querySelector('.pick[data-name="myna"]')`, 20000), 'the shelf shows Myna');
  await t.shot('smoke-01-shelf');
  await t.evaluate(`document.querySelector('.pick[data-name="myna"]').click()`);
  const t0 = Date.now();
  const up = await t.waitFor(`app.frames > 0 || app.error`, 240000) && !(await t.evaluate('app.error'));
  check(up, `first picture (${((Date.now() - t0) / 1000).toFixed(1)} s, drawn ${await t.evaluate('app.three() ? "in 3D" : "in 2D"')}): ${await t.evaluate('app.error') || 'no error'}`);
  check(await t.evaluate(`app.cell`) === 'loopback', 'no relay given: the loopback network');
  check(await t.waitLine(/network: registration 1/, 20000), 'the phone registers');
  await t.evaluate(`app.slide(true)`); await sleep(1500);
  await t.shot('smoke-02-standby');
  await t.text('5551234', 'hi from the page');
  const back = await t.waitLine(/message \d+ from \S+ received: "hi from the page"/i, 30000);
  check(!!back, 'a text sent on loopback comes back: ' + (back || 'nothing').replace(/^.*\| /, ''));
  await sleep(1500);
  await t.shot('smoke-03-conversation');
  await t.evaluate(`document.getElementById('off').click()`);
  check(await t.waitFor(`!app.running && location.search === ''`, 30000), 'switched off and put down');
  const kept = await t.waitFor(`new Promise(r => { const q = indexedDB.open('myna-phone', 1); q.onsuccess = () => { const g = q.result.transaction('kv').objectStore('kv').getAllKeys(); g.onsuccess = () => r(g.result.filter(k => String(k).startsWith('state:myna:')).length); }; q.onerror = () => r(0); })`, 10000);
  check(kept > 0, 'its flash state is kept in this browser');
  await t.go(env.base + '?p=myna');
  const again = await t.waitFor(`app.frames > 0 || app.error`, 240000) && await t.waitLine(/sms store: [1-9]\d* messages/, 30000);
  check(!!again, 'after a reload the stored text is there: ' + (await t.line(/sms store: /) || 'no store line').replace(/^.*\| /, ''));
  if (t.logs.length) console.log('--- page ---\n' + t.logs.join('\n'));
  t.close();
} catch (e) {
  check(false, 'the test ran: ' + (e.message || e));
} finally {
  await env.stop();
}
process.exit(summary());
