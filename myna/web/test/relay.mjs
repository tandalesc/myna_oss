// relay.mjs: two phones on the page text each other through a local relay (myna/relay, `wrangler dev`, nothing leaves
// this computer). Phone A is the page at 127.0.0.1, phone B the same page at localhost: two origins, so two numbers.
//
//   (cd myna/relay && npm install)
//   MYNA_PYODIDE=DIR node myna/web/test/relay.mjs        (after make -C myna/firmware and sh native/core/build.sh)
//
// Steps: the relay starts; both phones start, get a number from the relay and register; A writes a text to B's number
// with the keys; B receives it from A's number and A's text is marked sent (the relay's end-to-end acknowledgement).
// Exit status 0 when every step passed. Environment: lib.mjs; RELAY_PORT (default: a free port).
// SPDX-License-Identifier: MIT
import { start, tab, check, summary, freePort, sleep } from './lib.mjs';
import { relay } from '../../relay/test/lib.mjs';

const port = Number(process.env.RELAY_PORT) || await freePort();
const r = await relay('page', port);
console.log('relay up at ' + r.base);
const env = await start({ relay: r.base.replace(/^http/, 'ws') });
try {
  const a = await tab(env.cdp), b = await tab(env.cdp, true);
  await a.go(env.base + '?p=myna'); await b.go(env.other + '?p=myna');
  const phone = async (t, name) => {
    await t.front();
    const up = await t.waitFor(`app.frames > 0 || app.error`, 240000) && !(await t.evaluate('app.error'));
    const online = up && await t.waitFor(`app.cell === 'online' && app.number`, 60000);
    check(!!online, `${name} is on the relay as ${online || '?'}: ${await t.evaluate('app.error') || 'no error'}`);
    check(await t.waitLine(/network: registration 1/, 30000), `${name} registers`);
    await t.evaluate(`app.slide(true)`); await sleep(1200);
    return online;
  };
  const na = await phone(a, 'A'), nb = await phone(b, 'B');
  check(na && nb && na !== nb, 'two numbers');
  await a.front();
  await a.text(nb, 'hello b');
  const got = await b.waitLine(new RegExp(`message \\d+ from \\+?${na} received: "hello b"`, 'i'), 60000);
  check(!!got, 'B receives the text from A\'s number: ' + (got || 'nothing').replace(/^.*\| /, ''));
  const sent = await a.waitLine(/message \d+ to \S+ sent/, 30000);
  check(!!sent, 'A\'s text is sent: ' + (sent || 'nothing').replace(/^.*\| /, ''));
  await sleep(1500);
  await a.shot('relay-a'); await b.shot('relay-b');
  for (const [t, n] of [[a, 'A'], [b, 'B']]) if (t.logs.length) console.log(`--- page ${n} ---\n` + t.logs.join('\n'));
  a.close(); b.close();
} catch (e) {
  check(false, 'the test ran: ' + (e.message || e));
} finally {
  await env.stop();
  await r.stop();
}
process.exit(summary());
