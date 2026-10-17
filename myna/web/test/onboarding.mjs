// onboarding.mjs: getting a number on the phone page, as on an iPhone (390 x 844, touch), through a local relay
// (myna/relay, `wrangler dev`) that asks for the person check (Turnstile) with Cloudflare's published test keys: the
// site key 1x00000000000000000000AA always passes, the secret 1x...AA always accepts its token, 2x...AA always refuses it.
// The widget comes from challenges.cloudflare.com and the relay asks Cloudflare about the token: this test needs the
// internet.
//
//   (cd myna/relay && npm install)
//   MYNA_PYODIDE=DIR node myna/web/test/onboarding.mjs      (after make -C myna/firmware and sh native/core/build.sh)
//
// Steps, with a relay that accepts the check: the shelf; a phone picked, the sheet comes over the stage with the check;
// the check passes and the number is shown (12 digits in groups of four) while the phone loads; the phone gets online with
// that number and the sheet says so; "Go to your phone" takes it away and the phone registers. A reload with the ticket of
// that join: no sheet, online. The first join brings one welcome text from 3246 naming the number; no later join brings
// another (the reload, the check again). The ticket run out (its time set back in this browser's store): the sheet asks to check
// again and names the number; after the check the phone is online with the same number. With a relay that refuses the
// check: the sheet says the check did not go through and shows no number, the phone is not online; "Not now" takes it
// away and the phone has no service, with "Get a number" in the settings; that tries again and is refused again.
// Exit status 0 when every step passed. Environment: lib.mjs; SHOTS=DIR.
// SPDX-License-Identifier: MIT
import { start, tab, check, summary, freePort, sleep } from './lib.mjs';
import { relay } from '../../relay/test/lib.mjs';

const SITE = '1x00000000000000000000AA', PASS = '1x0000000000000000000000000000000AA', FAIL = '2x0000000000000000000000000000000AA';
const step = `(window.app && app.onboard)`;
const shown = id => `!document.getElementById(${JSON.stringify(id)}).closest('[hidden]')`;
const text = id => `document.getElementById(${JSON.stringify(id)}).textContent`;
const click = id => `document.getElementById(${JSON.stringify(id)}).click()`;
const grouped = `app.number.replace(/(\\d{4})(?=\\d)/g, '$1 ')`;

async function iphone(env) {
  const t = await tab(env.cdp, true);
  await t.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 3, mobile: true });
  await t.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
  return t;
}
async function withRelay(name, secret, f) {
  const r = await relay(name, await freePort(), { vars: { TURNSTILE_SITEKEY: SITE, TURNSTILE_SECRET: secret } });
  const env = await start({ relay: r.base.replace(/^http/, 'ws'), turnstile: SITE });
  try { await f(env); }
  catch (e) { check(false, `the ${name} run ran: ${e.message || e}`); }
  finally { await env.stop(); await r.stop(); }
}

// ---- a relay that accepts the check ----
await withRelay('onboard-pass', PASS, async env => {
  const t = await iphone(env);
  await t.go(env.base);
  check(await t.waitFor(`!!document.querySelector('.pick[data-name="myna"]')`, 20000), 'the shelf shows the phones');
  await sleep(1200); await t.shot('onboarding-01-shelf');
  await t.evaluate(`document.querySelector('.pick[data-name="myna"]').click()`);
  check(await t.waitFor(`${step} === 'check' && ${shown('onCheck')}`, 20000), 'a phone picked: the sheet asks for the check');
  check(await t.evaluate(`${text('onTitle')} === 'Get your number' && document.getElementById('stage').inert`), 'its title is "Get your number"; the stage under it takes nothing');
  await sleep(1500); await t.shot('onboarding-02-check');
  const digits = await t.waitFor(`${step} === 'number' && ${shown('onDigits')} && ${text('onDigits')}`, 60000);
  check(/^\d{4} \d{4} \d{4}$/.test(digits || ''), `the check passes: the number is shown, ${digits} (the phone ${await t.evaluate('app.running') ? 'running' : 'still loading'})`);
  await sleep(800); await t.shot('onboarding-03-number');
  const up = await t.waitFor(`app.frames > 0 || app.error`, 240000) && !(await t.evaluate('app.error'));
  const online = up && await t.waitFor(`app.cell === 'online' && ${grouped} === ${JSON.stringify(digits)}`, 60000);
  check(!!online, `the phone is on the network with that number: ${await t.evaluate('app.error') || await t.evaluate('app.cell')}`);
  check(await t.waitFor(`${text('onState')} === 'On the network' && document.getElementById('onState').dataset.state === 'on'`, 5000), 'the sheet says so');
  await sleep(600); await t.shot('onboarding-04-online');
  await t.evaluate(click('onGo'));
  check(await t.waitFor(`${step} === '' && !document.getElementById('stage').inert`, 5000), '"Go to your phone" takes the sheet away');
  check(await t.waitLine(/network: registration 1/, 30000), 'the phone registers');
  const welcome = new RegExp(`message \\d+ from 3246 received: "Hi from Myna! Your number is ${digits}\\. Give it to a friend`);
  const welcomes = () => t.evaluate(`app.lines.filter(s => ${welcome}.test(s)).length`);
  check(await t.waitLine(welcome, 90000), 'the first join: a welcome text from 3246 with the number');
  await sleep(8000);
  check(await welcomes() === 1, 'exactly one');

  // the ticket of that join: no check
  await t.go(env.base + '?p=myna');
  const again = await t.waitFor(`(window.seen = window.seen || !!${step}, window.app && app.cell === 'online')`, 240000);
  check(again && !(await t.evaluate('window.seen')), 'a reload with the ticket: no sheet, and the phone is online');
  await t.waitLine(/network: registration 1/, 30000); await sleep(12000);
  check(await welcomes() === 0, 'no second welcome after the reload');

  // the ticket run out: check again, the same number
  const number = await t.evaluate('app.number');
  await t.evaluate(`new Promise((res, rej) => { const q = indexedDB.open('cell-relay', 1); q.onerror = rej; q.onsuccess = () => {
    const s = q.result.transaction('kv', 'readwrite').objectStore('kv'), g = s.get('ticket');
    g.onsuccess = () => { const v = g.result; v.exp = Math.floor(Date.now() / 1000) - 10; s.put(v, 'ticket').onsuccess = () => res(1); }; }; })`);
  await t.go(env.base + '?p=myna');
  check(await t.waitFor(`${step} === 'check' && ${text('onTitle')} === 'Check again to reconnect' && ${text('onWhy')}.includes(${JSON.stringify(number.replace(/(\d{4})(?=\d)/g, '$1 '))})`, 20000),
    'the ticket run out: the sheet asks to check again and names the number');
  await sleep(1500); await t.shot('onboarding-05-again');
  check(await t.waitFor(`app.cell === 'online' && app.number === ${JSON.stringify(number)}`, 240000), 'after the check the phone is online with the same number');
  await t.waitLine(/network: registration 1/, 30000); await sleep(12000);
  check(await welcomes() === 0, 'and no second welcome');
  if (t.logs.length) console.log('--- page ---\n' + t.logs.join('\n'));
  t.close();
});

// ---- a relay that refuses it ----
await withRelay('onboard-fail', FAIL, async env => {
  const t = await iphone(env);
  await t.go(env.base + '?p=myna');
  check(await t.waitFor(`${step} === 'check'`, 20000), 'the sheet asks for the check');
  const failed = await t.waitFor(`${step} === 'fail'`, 300000);
  check(!!failed && await t.evaluate(`${text('onFailTitle')} === 'The check did not go through' && !${shown('onDigits')} && app.cell !== 'online'`),
    `the relay refuses it: the sheet says so and shows no number; the phone is ${await t.evaluate('app.cell')}`);
  await sleep(800); await t.shot('onboarding-06-refused');
  await t.evaluate(click('onSkip'));
  check(await t.waitFor(`${step} === '' && app.cell === 'stopped' && document.getElementById('net').dataset.state === 'off' && !document.getElementById('getNumber').hidden`, 120000),
    '"Not now": no sheet, no service, "Get a number" in the settings');
  await t.evaluate(click('getNumber'));
  check(await t.waitFor(`${step} === 'fail'`, 120000), '"Get a number" checks again: refused again');
  if (t.logs.length) console.log('--- page ---\n' + t.logs.join('\n'));
  t.close();
});
process.exit(summary());
