// run.mjs: the relay's tests. Starts `wrangler dev` itself (no account, nothing leaves this machine), twice:
//   relay 1  no person check, admin by shared secret                         port 8791
//   relay 2  person check against a stand-in for Turnstile's siteverify, admin behind a stand-in for Cloudflare Access,
//            an origin list, 5 joins per address and minute                  port 8793 (stand-ins on 8795)
// Use:  node test/run.mjs [--only TEXT] [--no-hibernation]
// SPDX-License-Identifier: MIT
import http from 'node:http';
import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { R, HERE, Phone, identity, submit, fakeWorker, relay, test, eq, ok, sleep, results } from './lib.mjs';

const only = process.argv.includes('--only') ? process.argv[process.argv.indexOf('--only') + 1] : '';
const T = (name, f) => (!only || name.includes(only)) ? test(name, f) : null;
const out = [];
const log = console.log; console.log = (...a) => { out.push(a.join(' ')); log(...a); };

/** Two joined phones on different shards (or the same one). */
async function pair(base, same = false) {
  const a = await identity(), b = same ? await identity(a.number.slice(0, 3)) : await identity('', a.number.slice(0, 3));
  const A = new Phone(base, a), B = new Phone(base, b);
  eq((await A.join()).t, 'joined', 'A joins'); eq((await B.join()).t, 'joined', 'B joins');
  return [A, B];
}
async function joined(base, who) { const p = new Phone(base, who || await identity()); const m = await p.join(); eq(m.t, 'joined', 'join'); return p; }

// =====================================================================================================================
const r1 = await relay('one', 8791);
console.log('relay 1 up at ' + r1.base);
try {
  await T('info: version and services, no account needed', async () => {
    const i = await (await fetch(r1.base + '/info')).json();
    eq([i.v, i.min, i.digits], [1, 1, 12]); eq(i.services.map(s => s.n), ['3246'], 'only the echo number is on');
  });

  await T('stale protocol version: a clear "update the page" error', async () => {
    const p = new Phone(r1.base, await identity()).open({ v: 0 });
    const e = await p.next('error');
    eq([e.code, e.fatal, e.min], ['update', true, 1]); ok(/Reload the page/.test(e.text), e.text);
    eq((await p.untilClosed()).code, 4000);
    const q = new Phone(r1.base, await identity());                    // the right URL, an old version in the join frame
    eq((await q.join({ over: { v: 0 } })).code, 'update');
    eq((await q.untilClosed()).code, 4000);
  });

  await T('join: the number is the hash of the key; joined carries limits, services, a ticket', async () => {
    const who = await identity(), p = new Phone(r1.base, who);
    const j = await p.join();
    eq([j.t, j.v, j.n], ['joined', 1, who.number]); ok(/^\d{12}$/.test(who.number));
    eq(p.challenge.relay, '127.0.0.1:8791'); ok(j.limits.perMin > 0 && j.ticket && j.ticketExp > Date.now() / 1000);
    p.close();
  });

  await T('numbers: 12 digits, the first never 0 (10^11 + hash modulo 9 * 10^11); a number starting with 0 is no number', async () => {
    const first = new Set();
    for (let i = 0; i < 300; i++) { const n = (await identity()).number; ok(/^[1-9]\d{11}$/.test(n), n); first.add(n[0]); }
    eq([...first].sort().join(''), '123456789', 'every first digit from 1 to 9 turns up in 300 numbers');
    const p = new Phone(r1.base, await identity()).open({ n: '012345678901' });
    eq((await p.next('error')).code, 'bad_number');
    const A = await joined(r1.base); const id = A.text('012345678901');
    eq(await A.next('sent'), { t: 'sent', id, ok: false, code: 'unknown', cause: 1 }); A.close();
  });

  await T('a URL that is no number: refused', async () => {
    const p = new Phone(r1.base, await identity()).open({ n: '12345' });
    eq((await p.next('error')).code, 'bad_number'); eq((await p.untilClosed()).code, 4010);
  });

  await T('spoof: wrong key for a number, a signature by another key, a replayed signature, a signature for another relay', async () => {
    const victim = await identity(), thief = await identity();
    // 1. the thief's key under the victim's number
    let p = new Phone(r1.base, { ...thief, number: victim.number });
    eq((await p.join()).code, 'bad_join'); eq((await p.untilClosed()).code, 4001);
    // 2. the victim's public key (it is public), signed by the thief
    p = new Phone(r1.base, victim);
    eq((await p.join({ signer: thief })).code, 'bad_join');
    // 3. a signature the victim once made for another challenge
    p = new Phone(r1.base, victim);
    eq((await p.join({ nonce: 'AAAAAAAAAAAAAAAAAAAAAA==' })).code, 'bad_join');
    // 4. a signature the victim made for another relay (a page in the middle passing the challenge on)
    p = new Phone(r1.base, victim);
    eq((await p.join({ signHost: 'relay.example' })).code, 'bad_join');
    // 5. an encryption key the identity did not sign
    p = new Phone(r1.base, victim);
    eq((await p.join({ over: { ek: R.b64(thief.encPub) } })).code, 'bad_join');
    // 6. a text before joining
    p = new Phone(r1.base, victim).open(); await p.next('challenge'); p.text(thief.number);
    eq((await p.next('error')).code, 'bad_join');
    // and the honest join still works
    p = new Phone(r1.base, victim); eq((await p.join()).t, 'joined'); p.close();
  });

  await T('rate limit (defaults: 2 texts right after joining, then 12 a minute): the third text is refused with cause 42', async () => {
    const [A, B] = await pair(r1.base);
    for (let i = 0; i < 3; i++) A.text(B.who.number);
    await B.next('deliver'); await B.next('deliver');
    const s = await A.next('sent');
    eq([s.id, s.ok, s.code, s.cause], [3, false, 'rate', 42]);
    ok(await B.none('deliver'), 'the third never reached B');
    A.close(); B.close();
  });

  await T('admin: wrong secret refused; limits are changed at run time and reach the shards at once', async () => {
    eq((await r1.admin('state', null, { authorization: 'Bearer nope' })).status, 403);
    eq((await r1.admin('state', null, {})).status, 403);
    eq((await r1.admin('set', { kill: true }, { authorization: 'Bearer nope' })).status, 403);
    const before = (await r1.admin('state')).body;
    eq([before.cfg.kill, before.cfg.pause, before.cfg.limits.perMin], [false, false, 12]);
    const s = (await r1.admin('set', { limits: { perMin: 6000, burst: 200, joinTokens: 200, framesPerMin: 6000, reportSec: 5 } })).body;
    eq([s.cfg.limits.perMin, s.cfg.limits.joinTokens, s.cfg.limits.maxBody], [6000, 200, 1024]);
    const [A, B] = await pair(r1.base);
    for (let i = 0; i < 5; i++) A.text(B.who.number);
    for (let i = 0; i < 5; i++) await B.next('deliver');
    A.close(); B.close();
  });

  await T('a text across two shards: "sent" comes only when the far phone has acknowledged', async () => {
    const [A, B] = await pair(r1.base);
    ok(A.who.number.slice(0, 3) !== B.who.number.slice(0, 3), 'two shards');
    const tpdu = submit(B.who.number, 'Hello over the air'), id = A.text(B.who.number, tpdu);
    const d = await B.next('deliver');
    eq([d.from, d.enc, d.d], [A.who.number, 0, `${A.who.number}.${id}`]);
    eq(R.hex(R.unb64(d.body)), '01' + R.hex(tpdu), 'the payload arrives byte for byte');
    ok(await A.none('sent', 500), 'no "sent" before the acknowledgement');
    B.send({ t: 'ack', d: d.d, ok: true });
    eq(await A.next('sent'), { t: 'sent', id, ok: true });
    // the far phone refuses (its message store is full): the cause comes back
    const id2 = A.text(B.who.number); const d2 = await B.next('deliver');
    B.send({ t: 'ack', d: d2.d, ok: false, cause: 22 });
    eq(await A.next('sent'), { t: 'sent', id: id2, ok: false, code: 'refused', cause: 22 });
    A.close(); B.close();
  });

  await T('a text within one shard, and a text to oneself', async () => {
    const [A, B] = await pair(r1.base, true);
    eq(A.who.number.slice(0, 3), B.who.number.slice(0, 3));
    const id = A.text(B.who.number); const d = await B.next('deliver');
    B.send({ t: 'ack', d: d.d, ok: true }); eq((await A.next('sent')).ok, true);
    const id2 = A.text(A.who.number); const d2 = await A.next('deliver');
    eq(d2.from, A.who.number); A.send({ t: 'ack', d: d2.d, ok: true }); eq(await A.next('sent'), { t: 'sent', id: id2, ok: true });
    A.close(); B.close();
  });

  await T('recipient not connected: fails at once (cause 27); not a number: cause 1; nothing is kept for later', async () => {
    const A = await joined(r1.base), b = await identity('', A.who.number.slice(0, 3));
    const id = A.text(b.number);
    eq(await A.next('sent'), { t: 'sent', id, ok: false, code: 'offline', cause: 27 });
    const id2 = A.text('5551234');
    eq(await A.next('sent'), { t: 'sent', id: id2, ok: false, code: 'unknown', cause: 1 });
    const id3 = A.text('252833');                                       // the Claude number is a disabled stub
    eq(await A.next('sent'), { t: 'sent', id: id3, ok: false, code: 'unknown', cause: 1 });
    const B = await joined(r1.base, b);                                 // B comes later: the earlier text is not delivered
    ok(await B.none('deliver', 700), 'nothing was stored');
    const C = await joined(r1.base); const id4 = A.text(C.who.number); await C.next('deliver'); C.close(); await sleep(200);
    const id5 = A.text(C.who.number);                                   // C left
    eq((await A.next(m => m.t === 'sent' && m.id === id5)).code, 'offline');
    A.close(); B.close();
  });

  await T('forged sender: the relay stamps the number itself; a forged acknowledgement is ignored', async () => {
    const [A, B] = await pair(r1.base), C = await joined(r1.base), V = await identity();
    const id = A.text(B.who.number, undefined, { from: V.number, n: V.number, sender: V.number });
    const d = await B.next('deliver');
    eq(d.from, A.who.number, 'the sender is the connection, whatever the frame says');
    C.send({ t: 'ack', d: d.d, ok: true });                             // C saw nothing but guesses the id
    C.send({ t: 'ack', d: `${A.who.number}.${id}`, ok: false, cause: 22 });
    ok(await A.none('sent', 600), 'an acknowledgement from a phone that is not the destination does nothing');
    B.send({ t: 'ack', d: d.d, ok: true });
    eq(await A.next('sent'), { t: 'sent', id, ok: true });
    B.send({ t: 'ack', d: d.d, ok: true });                             // twice: nothing more
    ok(await A.none('sent', 300));
    A.close(); B.close(); C.close();
  });

  await T('size cap: a payload over the limit is refused; a huge frame closes the connection', async () => {
    const [A, B] = await pair(r1.base);
    const id = A.text(B.who.number, new Uint8Array(1100));
    eq(await A.next('sent'), { t: 'sent', id, ok: false, code: 'too_big', cause: 111 });
    ok(await B.none('deliver', 300));
    const id2 = A.text(B.who.number, new Uint8Array(1000)); await B.next('deliver');       // under the cap: passes
    A.send({ t: 'msg', id: 9, to: B.who.number, enc: 0, body: 'A'.repeat(8000) });
    eq((await A.next('error')).code, 'too_big'); eq((await A.untilClosed()).code, 4006);
    B.close();
  });

  await T('service number: 3246 echoes the text back; frames for calls and rooms are reserved', async () => {
    const A = await joined(r1.base), tpdu = submit('3246', 'echo me');
    const id = A.text('3246', tpdu);
    eq(await A.next('sent'), { t: 'sent', id, ok: true });
    const d = await A.next('deliver');
    eq([d.from, d.enc, R.hex(R.unb64(d.body))], ['3246', 0, '01' + R.hex(tpdu)]);
    A.send({ t: 'key', r: 7, n: '3246' }); eq(await A.next('key'), { t: 'key', r: 7, n: '3246', ok: true, service: true });
    A.send({ t: 'call.offer', to: '123' }); eq(await A.next('error'), { t: 'error', code: 'unsupported', re: 'call.offer', fatal: false });
    A.send({ t: 'room.join', room: 'x' }); eq((await A.next('error')).code, 'unsupported');
    A.send({ t: 'whatever' }); eq((await A.next('error')).code, 'bad_frame');
    A.send('ping'); eq((await A.next('pong')).t, 'pong');               // the keep-alive, answered without waking the object
    A.close();
  });

  await T('the same number twice: the newer connection replaces the older', async () => {
    const who = await identity(), one = await joined(r1.base, who), two = await joined(r1.base, who);
    eq((await one.next('error')).code, 'replaced'); eq((await one.untilClosed()).code, 4002);
    const A = await joined(r1.base); A.text(who.number); await two.next('deliver');
    A.close(); two.close();
  });

  await T('ban: the number is disconnected and cannot join; by number and by key; lifted again', async () => {
    const [A, B] = await pair(r1.base);
    const r = await r1.admin('ban', { number: B.who.number });
    eq([r.status, r.body.banned, r.body.cfg.bans], [200, B.who.number, [B.who.number]]);
    eq((await B.next('error')).code, 'banned'); eq((await B.untilClosed()).code, 4004);
    const again = new Phone(r1.base, B.who).open();
    eq((await again.next('error')).code, 'banned');
    const id = A.text(B.who.number); eq((await A.next('sent')).code, 'offline');
    eq((await r1.admin('number?n=' + B.who.number)).body.banned, true);
    eq((await r1.admin('ban', { number: B.who.number, on: false })).body.cfg.bans, []);
    const B2 = await joined(r1.base, B.who);
    const k = await r1.admin('ban', { key: R.b64(A.who.idPub) });       // by identity key: the number follows from it
    eq(k.body.banned, A.who.number);
    eq((await A.next('error')).code, 'banned');
    await r1.admin('ban', { key: R.b64(A.who.idPub), on: false });
    eq((await r1.admin('ban', { number: 'abc' })).status, 400);
    B2.close();
  });

  await T('pause joins: new phones are turned away, connected phones keep texting and may reconnect', async () => {
    const [A, B] = await pair(r1.base);
    eq((await r1.admin('set', { pause: true })).body.cfg.pause, true);
    const N = new Phone(r1.base, await identity());
    eq((await N.join()).code, 'paused'); eq((await N.untilClosed()).code, 4005);
    const F = new Phone(r1.base, await identity('', '')); F.ticket = A.ticket;       // another number's ticket is worth nothing
    eq((await F.join()).code, 'paused');
    const id = A.text(B.who.number); const d = await B.next('deliver'); B.send({ t: 'ack', d: d.d, ok: true });
    eq((await A.next('sent')).ok, true);
    B.close(); await sleep(100);
    const B2 = new Phone(r1.base, B.who); B2.ticket = B.ticket;
    eq((await B2.join()).t, 'joined', 'a phone that was on the network reconnects with its ticket');
    eq((await r1.admin('set', { pause: false })).body.cfg.pause, false);
    eq((await new Phone(r1.base, await identity()).join()).t, 'joined');
    A.close(); B2.close();
  });

  await T('kill switch: everyone drops to no service, nobody joins, texts stop; on again and it works', async () => {
    const [A, B] = await pair(r1.base);
    eq((await r1.admin('set', { kill: true })).body.cfg.kill, true);
    eq((await A.next('error')).code, 'off'); eq((await A.untilClosed()).code, 4003); eq((await B.untilClosed()).code, 4003);
    const N = new Phone(r1.base, A.who).open();
    eq((await N.next('error')).code, 'off');
    const fresh = new Phone(r1.base, await identity()).open();          // a shard that never had a phone learns it at once
    eq((await fresh.next('error')).code, 'off');
    eq((await r1.admin('state')).body.phones, 0, 'the admin page counts no phones');
    eq((await r1.admin('set', { kill: false })).body.cfg.kill, false);
    const A2 = await joined(r1.base, A.who), B2 = await joined(r1.base, B.who);
    A2.text(B2.who.number); await B2.next('deliver');
    A2.close(); B2.close();
  });

  await T('a socket that never joins is closed after the join time', async () => {
    await r1.admin('set', { limits: { joinSec: 5 } });
    const p = new Phone(r1.base, await identity()).open(); await p.next('challenge');
    eq((await p.next('error', 12000)).code, 'slow_join');
    // Seen with wrangler 4.150 and Node's WebSocket: a socket that never sent a frame stays in CLOSING after the relay's
    // close (the close frame arrives, the connection is not torn down). Either state counts here.
    await sleep(500); ok(p.ws.readyState >= 2, 'closing or closed');
    await r1.admin('set', { limits: { joinSec: 120 } });
  });

  await T('live counts on the admin page: phones, texts and failures per minute, one number\'s counters', async () => {
    const before = (await r1.admin('state')).body;
    const sum = s => s.minutes.reduce((a, m) => [a[0] + m.sent, a[1] + m.failed, a[2] + (m.fail.offline || 0)], [0, 0, 0]);
    const [A, B] = await pair(r1.base);
    for (let i = 0; i < 3; i++) { A.text(B.who.number); const d = await B.next('deliver'); B.send({ t: 'ack', d: d.d, ok: true }); await A.next('sent'); }
    A.text((await identity('', A.who.number.slice(0, 3))).number); await A.next('sent');
    const n = (await r1.admin('number?n=' + A.who.number)).body;
    eq([n.connected, n.sent, n.failed, n.limited, n.waiting], [true, 3, 1, 0, 0]); ok(n.since > Date.now() - 60000);
    ok(!('ip' in n) && !('to' in n), 'no address, no recipients');
    let s;
    for (let i = 0; i < 40; i++) { await sleep(500); s = (await r1.admin('state')).body; if (sum(s)[0] >= sum(before)[0] + 3 && s.phones >= 2) break; }
    eq([sum(s)[0] - sum(before)[0], sum(s)[2] - sum(before)[2]], [3, 1], 'texts and offline failures counted (reports come every 5 s here)');
    ok(s.phones >= 2, 'phones ' + s.phones);
    A.close(); B.close();
    for (let i = 0; i < 40; i++) { await sleep(500); s = (await r1.admin('state')).body; if (s.phones === 0) break; }
    eq(s.phones, 0, 'the count goes down when phones leave');
  });

  // ---- the page's own client (client/cell.js) -----------------------------------------------------------------------
  const page = (base, extra = {}) => {
    const worker = fakeWorker(), said = [], states = [];
    const link = cellLink(worker, () => 100, s => said.push(s), { url: base, store: R.memoryStore(), onState: s => states.push(s.state + (s.reason ? ':' + s.reason : '')), ...extra });
    const until = async (state, ms = 8000) => { for (let t = 0; t < ms; t += 25) { if (link.state === state) return; await sleep(25); } throw new Error(`state ${link.state}, wanted ${state}; said ${said.join(' | ')}`); };
    return { link, worker, said, states, until };
  };

  await T('cell.js: two pages text each other; the receiver gets an SMS-DELIVER from the sender\'s number, "sent" follows the phone\'s acknowledgement', async () => {
    const a = page(r1.base), b = page(r1.base);
    eq(a.link.number, ''); await a.link.ready; await b.link.ready;
    ok(/^\d{12}$/.test(a.link.number)); eq(a.link.state, 'idle');
    a.link.onMessage({ t: 'running' }); b.link.onMessage({ t: 'running' });
    await a.until('online'); await b.until('online');
    const tpdu = submit(b.link.number, 'Hello phone');
    a.link.onMessage({ t: 'cell', n: 1, sc: '81550501f0', tpdu: R.hex(tpdu) });
    const inn = await b.worker.next('cell_in');
    const want = R.hex(R.cat([0x04], R.addressField(a.link.number), [0, 0], R.timeStamp(1224504000 + 100), tpdu.subarray(tpdu.length - 1 - 10)));
    eq(inn.tpdu, want, 'SMS-DELIVER: origin = the stamped sender, time = the receiver\'s emulated clock');
    eq(inn.sc, '81550501f0');
    await sleep(400); eq(a.worker.posted.filter(m => m.t === 'cell_result').length, 0, 'no result before the phone acknowledged');
    b.link.onMessage({ t: 'cell_in_result', k: inn.k, ok: true, cause: 0 });
    eq(await a.worker.next('cell_result'), { t: 'cell_result', n: 1, ok: true, cause: 0 });
    // the receiving phone's store is full
    a.link.onMessage({ t: 'cell', n: 2, sc: '81550501f0', tpdu: R.hex(tpdu) });
    b.link.onMessage({ t: 'cell_in_result', k: (await b.worker.next('cell_in')).k, ok: false, cause: 22 });
    eq(await a.worker.next('cell_result'), { t: 'cell_result', n: 2, ok: false, cause: 22 });
    // the far phone is switched off
    b.link.onMessage({ t: 'end' }); await b.until('idle'); await sleep(200);
    a.link.onMessage({ t: 'cell', n: 3, sc: '81550501f0', tpdu: R.hex(tpdu) });
    eq(await a.worker.next('cell_result'), { t: 'cell_result', n: 3, ok: false, cause: 27 });
    // this phone is not on the network: no connection, cause 38
    a.link.onMessage({ t: 'end' }); await a.until('idle');
    a.link.onMessage({ t: 'cell', n: 4, sc: '81550501f0', tpdu: R.hex(tpdu) });
    eq(await a.worker.next('cell_result'), { t: 'cell_result', n: 4, ok: false, cause: 38 });
    eq(a.states.join(' '), 'idle connecting online idle');
  });

  await T('cell.js: end-to-end encryption round trip; the relay carries only the envelope', async () => {
    const a = page(r1.base), spy = await identity();
    await a.link.ready; a.link.onMessage({ t: 'running' }); await a.until('online');
    const S = await joined(r1.base, spy);                               // a phone driven by hand shows what the relay delivers
    const tpdu = submit(spy.number, 'a secret');
    a.link.onMessage({ t: 'cell', n: 1, sc: '81550501f0', tpdu: R.hex(tpdu) });
    const d = await S.next('deliver');
    eq([d.from, d.enc], [a.link.number, 1]);
    const body = R.unb64(d.body);
    ok(!R.hex(body).includes(R.hex(tpdu).slice(8)), 'the text is not readable in what the relay carried');
    eq(body.length, 1 + 16 + 12 + (1 + tpdu.length) + 16, 'version, salt, nonce, ciphertext, tag');
    eq(await R.numberOf(R.unb64(d.id)), a.link.number, 'the sender\'s identity key hashes to the stamped number');
    ok(await R.verify(R.unb64(d.id), R.unb64(d.es), R.encText(d.from, d.ek)), 'and signed its encryption key');
    eq(R.hex(await R.unseal(spy.encPriv, R.unb64(d.ek), d.from, spy.number, body)), '01' + R.hex(tpdu), 'the receiver opens it');
    let failed = false; try { await R.unseal(spy.encPriv, R.unb64(d.ek), d.from, '000000000000', body); } catch (e) { failed = true; }
    ok(failed, 'an envelope moved to another number does not open');
    S.send({ t: 'ack', d: d.d, ok: true }); eq((await a.worker.next('cell_result')).ok, true);
    // the other direction: the hand-driven phone seals for the page
    const back = submit(a.link.number, 'and back'), sealed = await R.seal(spy.encPriv, R.unb64(d.ek), spy.number, a.link.number, R.cat([1], back));
    S.send({ t: 'msg', id: 50, to: a.link.number, enc: 1, body: R.b64(sealed) });
    const inn = await a.worker.next('cell_in');
    ok(inn.tpdu.endsWith(R.hex(back.subarray(back.length - 8))), 'the page opened it and handed the phone an SMS-DELIVER');
    a.link.onMessage({ t: 'cell_in_result', k: inn.k, ok: true }); eq((await S.next('sent')).ok, true);
    // a damaged envelope, and a text without encryption from a phone: both refused (cause 21), nothing reaches the phone
    sealed[40] ^= 1;
    S.send({ t: 'msg', id: 51, to: a.link.number, enc: 1, body: R.b64(sealed) });
    eq(await S.next('sent'), { t: 'sent', id: 51, ok: false, code: 'refused', cause: 21 });
    S.send({ t: 'msg', id: 52, to: a.link.number, enc: 0, body: R.b64(R.cat([1], back)) });
    eq(await S.next('sent'), { t: 'sent', id: 52, ok: false, code: 'refused', cause: 21 });
    eq(a.worker.posted.filter(m => m.t === 'cell_in').length, 0);
    // the echo number is the relay itself: sent plain, comes back as a text from 3246
    a.link.onMessage({ t: 'cell', n: 2, sc: '81550501f0', tpdu: R.hex(submit('3246', 'echo')) });
    eq((await a.worker.next('cell_result')).ok, true);
    ok((await a.worker.next('cell_in')).tpdu.startsWith('0404812364'), 'an SMS-DELIVER from 3246');
    a.link.onMessage({ t: 'end' }); S.close();
  });

  await T('cell.js: two pages, encrypted both ways (the default)', async () => {
    const a = page(r1.base), b = page(r1.base);
    await a.link.ready; await b.link.ready;
    a.link.onMessage({ t: 'running' }); b.link.onMessage({ t: 'running' }); await a.until('online'); await b.until('online');
    for (const [x, y, n] of [[a, b, 1], [b, a, 1], [a, b, 2]]) {
      x.link.onMessage({ t: 'cell', n, sc: '81550501f0', tpdu: R.hex(submit(y.link.number, 'ping pong')) });
      const inn = await y.worker.next('cell_in');
      ok(inn.tpdu.startsWith('040c81'), 'an SMS-DELIVER from a 12-digit number');
      y.link.onMessage({ t: 'cell_in_result', k: inn.k, ok: true });
      eq(await x.worker.next('cell_result'), { t: 'cell_result', n, ok: true, cause: 0 });
    }
    a.link.onMessage({ t: 'end' }); b.link.onMessage({ t: 'end' });
  });

  await T('cell.js against a lying relay: wrong relay name, keys that do not belong to the number, a changed identity key', async () => {
    const me = await R.makeKeys(), store = R.memoryStore(); await store.put('keys', me);
    const honest = await identity(), liar = await identity();
    let sock = null;
    class Fake { constructor(url) { sock = this; this.url = url; this.sent = []; setTimeout(() => this.onopen && this.onopen(), 0); } send(s) { this.sent.push(s === 'ping' ? s : JSON.parse(s)); } close() { setTimeout(() => this.onclose && this.onclose({ code: 1000 }), 0); } give(m) { this.onmessage({ data: JSON.stringify(m) }); } }
    const p = page('ws://relay.test', { store, WebSocket: Fake });
    await p.link.ready; p.link.onMessage({ t: 'running' }); await sleep(20);
    sock.give({ t: 'challenge', v: 1, relay: 'other.test', nonce: 'x', sitekey: '' }); await sleep(50);
    eq(sock.sent.length, 0, 'no join for a relay that names itself differently'); await p.until('stopped');
    const q = page('ws://relay.test', { store, WebSocket: Fake });
    await q.link.ready; q.link.onMessage({ t: 'running' }); await sleep(20);
    sock.give({ t: 'challenge', v: 1, relay: 'relay.test', nonce: 'abc', sitekey: '' }); await sleep(50);
    eq(sock.sent[0].t, 'join'); ok(await R.verify(me.idPub, R.unb64(sock.sent[0].sig), R.joinText('relay.test', me.number, 'abc')));
    sock.give({ t: 'joined', v: 1, n: me.number, services: [], limits: {}, ticket: '' }); await q.until('online');
    const seal = async (from, keys) => R.b64(await R.seal(keys.encPriv, me.encPub, from, me.number, R.cat([1], submit(me.number, 'x'))));
    const bundle = k => ({ id: R.b64(k.idPub), ek: R.b64(k.encPub), es: R.b64(k.encSig) });
    // 1. the relay says "from honest" but gives the liar's keys
    sock.give({ t: 'deliver', d: `${honest.number}.1`, from: honest.number, enc: 1, body: await seal(honest.number, liar), ...bundle(liar) }); await sleep(80);
    eq(sock.sent.pop(), { t: 'ack', d: `${honest.number}.1`, ok: false, cause: 21 });
    // 2. honest keys: taken, and remembered
    sock.give({ t: 'deliver', d: `${honest.number}.2`, from: honest.number, enc: 1, body: await seal(honest.number, honest), ...bundle(honest) });
    const inn = await q.worker.next('cell_in'); q.link.onMessage({ t: 'cell_in_result', k: inn.k, ok: true }); await sleep(30);
    eq(sock.sent.pop(), { t: 'ack', d: `${honest.number}.2`, ok: true });
    // 3. a second identity key whose hash gives the same number cannot be made here; the pin is checked directly
    eq(await store.get('pin:' + honest.number), R.b64(honest.idPub), 'the first identity key of a number is kept');
    await store.put('pin:' + liar.number, R.b64(honest.idPub));        // as if the liar's number had been seen with another key
    sock.give({ t: 'deliver', d: `${liar.number}.3`, from: liar.number, enc: 1, body: await seal(liar.number, liar), ...bundle(liar) }); await sleep(80);
    eq(sock.sent.pop(), { t: 'ack', d: `${liar.number}.3`, ok: false, cause: 21 });
    ok(q.said.some(s => /another identity key/.test(s)), q.said.join('|'));
    eq(q.worker.posted.filter(m => m.t === 'cell_in').length, 0);
    q.link.onMessage({ t: 'end' });
  });

  await T('cell.js: reconnects by itself after the connection is cut; stops for good when barred', async () => {
    const a = page(r1.base);
    await a.link.ready; a.link.onMessage({ t: 'running' }); await a.until('online');
    eq(a.worker.posted.filter(m => m.t === 'cell_state').map(m => m.up), [false, true], 'the phone\'s signal: down at the start, up when joined');
    await r1.admin('set', { kill: true }); await a.until('offline');
    ok(a.states.includes('offline:off'), a.states.join(' ')); await r1.admin('set', { kill: false });
    const wait = Number((a.said.find(x => /no service \(off\)/.test(x)) || '').match(/next try in (\d+) s/)?.[1]);
    ok(wait >= 180 && wait <= 300, 'while the network is off the page asks again every 3 to 5 minutes: ' + wait);
    eq(a.worker.posted.filter(m => m.t === 'cell_state').length, 2, 'no signal change yet: a short break does not move the bars');
    await sleep(4500);
    eq(a.worker.posted.filter(m => m.t === 'cell_state').map(m => m.up), [false, true, false], 'after 4 s without the link: no service');
    // a quick reconnect inside the 4 s: the worker is told nothing
    const c = page(r1.base); await c.link.ready; c.link.onMessage({ t: 'running' }); await c.until('online');
    const twin = new Phone(r1.base, { ...(await c.link.ready, {}), number: c.link.number }); twin.open(); await sleep(300); twin.close();   // a second socket for the number that never joins: nothing happens
    await r1.admin('set', { limits: { framesPerMin: 6000 } });
    eq(c.worker.posted.filter(m => m.t === 'cell_state').map(m => m.up), [false, true]);
    c.link.onMessage({ t: 'end' });
    const b = page(r1.base); await b.link.ready; b.link.onMessage({ t: 'running' }); await b.until('online');
    await r1.admin('ban', { number: b.link.number }); await b.until('stopped');
    eq(b.states[b.states.length - 1], 'stopped:banned'); await r1.admin('ban', { number: b.link.number, on: false });
    a.link.onMessage({ t: 'end' });
  });

  // ---- the ceilings of the whole network ----------------------------------------------------------------------------
  // n texts from A to B, each acknowledged; returns the refusal when one is refused, else null
  const chat = async (A, B, n) => {
    for (let i = 0; i < n; i++) {
      const id = A.text(B.who.number), sent = A.next(x => x.t === 'sent' && x.id === id, 8000);
      const d = await Promise.race([B.next('deliver', 1500).catch(() => null), sent.then(m => m.ok ? new Promise(() => {}) : null)]);
      if (!d) { const m = await sent; await sleep(1600); return m; }
      B.send({ t: 'ack', d: d.d, ok: true }); await sent;
    }
    return null;
  };
  const gauges = async () => (await r1.admin('state')).body.gauges;
  const until = async (f, ms, what) => { for (let t = 0; t < ms; t += 250) { if (await f()) return; await sleep(250); } throw new Error('never: ' + what); };

  await T('defaults of the ceilings: 3,000 texts a minute, 3,000 phones, 500,000 texts a day; shown as three gauges', async () => {
    const g = await gauges();
    eq([g.netPerMin, g.maxPhones, g.dayMax, g.hold], [3000, 3000, 500000, { texts: false, joins: false, day: false }]);
    ok(g.rate >= 0 && g.phones >= 0 && g.day > 0, JSON.stringify(g));
  });

  await T('ceiling on connected phones: at it new phones are turned away, connected ones keep texting; below it joins resume', async () => {
    await until(async () => (await gauges()).phones === 0, 20000, 'no phones left from earlier tests');
    await r1.admin('set', { limits: { maxPhones: 3 } });
    const [A, B] = await pair(r1.base), C = await joined(r1.base);
    await until(async () => (await gauges()).hold.joins, 15000, 'the hold on joins');
    eq((await gauges()).phones, 3);
    eq((await r1.admin('state')).body.cfg.pause, false, 'the admin\'s own pause switch is untouched');
    const N = new Phone(r1.base, await identity()); eq((await N.join()).code, 'paused'); eq((await N.untilClosed()).code, 4005);
    eq(await chat(A, B, 2), null, 'connected phones still text');
    C.close(); await sleep(100);
    const C2 = new Phone(r1.base, C.who); C2.ticket = C.ticket; eq((await C2.join()).t, 'joined', 'a phone that was on the network comes back');
    C2.close(); B.close();
    await until(async () => !(await gauges()).hold.joins, 15000, 'the hold on joins ends');
    eq((await new Phone(r1.base, await identity()).join()).t, 'joined');
    await r1.admin('set', { limits: { maxPhones: 3000 } }); A.close();
  });

  await T('ceiling on texts per minute: above it texts are refused with cause 42, nobody is disconnected, and it ends by itself when the rate falls', async () => {
    await r1.admin('set', { limits: { netPerMin: 20 } });
    const [A, B] = await pair(r1.base);
    let refused = null, sent = 0;
    for (let i = 0; i < 20 && !refused; i++) { refused = await chat(A, B, 5); if (!refused) sent += 5; }
    ok(refused, 'texts were refused after ' + sent);
    eq([refused.ok, refused.code, refused.cause], [false, 'net_rate', 42]);
    ok(sent <= 60, 'the hold came soon after the ceiling (a busy shard reports every 25 texts; texts of the minute before count too): ' + sent);
    const g = await gauges(); eq(g.hold.texts, true); ok(g.rate > 20, 'rate ' + g.rate);
    ok(!A.closed && !B.closed, 'both are still connected');
    A.send({ t: 'key', r: 1, n: B.who.number }); eq((await A.next('key')).ok, true, 'everything but texts still works');
    console.log('      waiting for the rate to fall (up to 80 s) ...');
    await until(async () => !(await gauges()).hold.texts, 85000, 'the hold on texts ends by itself');
    eq(await chat(A, B, 2), null, 'texts go again');
    await r1.admin('set', { limits: { netPerMin: 3000 } }); A.close(); B.close();
  });

  await T('ceiling on texts per day: when used up, texts are refused until the ceiling is raised (or the UTC day ends)', async () => {
    const day = (await gauges()).day;
    await r1.admin('set', { limits: { dayMax: day + 30, netPerMin: 0 } });
    const [A, B] = await pair(r1.base);
    let refused = null, sent = 0;
    for (let i = 0; i < 30 && !refused; i++) { refused = await chat(A, B, 5); if (!refused) sent += 5; }
    ok(refused, 'refused after ' + sent); eq([refused.code, refused.cause], ['net_day', 42]);
    ok(sent >= 30 && sent <= 60, 'the bound is overshot by at most one report step: ' + sent);
    const g = await gauges(); eq(g.hold.day, true); ok(g.day >= g.dayMax);
    ok(!A.closed && !B.closed); const id = A.text('3246'); eq((await A.next(x => x.t === 'sent' && x.id === id)).code, 'net_day', 'service numbers too');
    await r1.admin('set', { limits: { dayMax: 500000, netPerMin: 3000 } });
    eq((await gauges()).hold.day, false); eq(await chat(A, B, 2), null);
    A.close(); B.close();
  });

  if (!process.argv.includes('--no-hibernation')) await T('hibernation: the objects are evicted and built again; number, keys and a waiting acknowledgement survive', async () => {
    await r1.admin('set', { limits: { pendSec: 120 } });
    const [A, B] = await pair(r1.base);
    const boot = async n => (await (await fetch(`${r1.base}/dev/boot?n=${n}`)).json()).boot;
    const id = A.text(B.who.number); const d = await B.next('deliver');          // B does not acknowledge yet
    await sleep(8000);                                                           // the report alarms (5 s) pass
    const a1 = await boot(A.who.number), b1 = await boot(B.who.number);
    ok(a1 && b1, 'boot ids');
    console.log('      waiting 25 s with both connections idle ...');
    await sleep(25000);
    B.send({ t: 'ack', d: d.d, ok: true });                                      // wakes B's shard, which wakes A's
    eq(await A.next('sent'), { t: 'sent', id, ok: true }, 'the acknowledgement found the waiting text after the sleep');
    const a2 = await boot(A.who.number), b2 = await boot(B.who.number);
    console.log(`      shard of A: ${a1.slice(0, 8)} -> ${a2.slice(0, 8)}; shard of B: ${b1.slice(0, 8)} -> ${b2.slice(0, 8)}`);
    ok(a1 !== a2 && b1 !== b2, 'both objects were built again (if not: this wrangler did not hibernate, the test proves nothing)');
    A.send({ t: 'key', r: 1, n: B.who.number });
    const k = await A.next('key'); eq([k.ok, k.id, k.ek], [true, R.b64(B.who.idPub), R.b64(B.who.encPub)], 'the keys given at the join are still there');
    const n = (await r1.admin('number?n=' + A.who.number)).body; eq([n.connected, n.sent], [true, 1], 'and the counters');
    eq((await r1.admin('state')).body.cfg.limits.pendSec, 120, 'the shard kept the configuration');
    const id2 = B.text(A.who.number); const d2 = await A.next('deliver'); eq(d2.from, B.who.number);
    A.close(); B.close();
  });
} finally { await r1.stop(); }

// =====================================================================================================================
// Relay 2: stand-ins for Turnstile's siteverify and for Cloudflare Access's keys, on this machine.
const rsa = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
const jwk = { ...(await crypto.subtle.exportKey('jwk', rsa.publicKey)), kid: 'test-key', alg: 'RS256', use: 'sig' };
const seen = [];
const stand = http.createServer((req, res) => {
  let body = ''; req.on('data', d => body += d); req.on('end', () => {
    res.setHeader('content-type', 'application/json');
    if (req.url === '/siteverify') { const b = JSON.parse(body); seen.push(b); res.end(JSON.stringify(b.secret === 'test-turnstile-secret' && b.response === 'XXXX.DUMMY.TOKEN.XXXX' ? { success: true } : { success: false, 'error-codes': ['invalid-input-response'] })); }
    else if (req.url === '/certs') res.end(JSON.stringify({ keys: [jwk] }));
    else { res.statusCode = 404; res.end('{}'); }
  });
}).listen(8795, '127.0.0.1');
const b64u = x => Buffer.from(x).toString('base64url');
async function jwt(claims, key = rsa.privateKey, head = { alg: 'RS256', kid: 'test-key' }) {
  const text = b64u(JSON.stringify(head)) + '.' + b64u(JSON.stringify(claims));
  return text + '.' + b64u(new Uint8Array(await crypto.subtle.sign('RSASSA-PKCS1-v1_5', key, new TextEncoder().encode(text))));
}

const r2 = await relay('two', 8793, { joinLimit: 12, vars: { TURNSTILE_SECRET: 'test-turnstile-secret', TURNSTILE_SITEKEY: '1x00000000000000000000AA', TURNSTILE_VERIFY_URL: 'http://127.0.0.1:8795/siteverify',
  ACCESS_TEAM_DOMAIN: 'https://team.test', ACCESS_AUD: 'aud-of-the-admin-app', ACCESS_CERTS_URL: 'http://127.0.0.1:8795/certs', ALLOWED_ORIGINS: 'https://page.test,http://localhost:8923' } });
console.log('relay 2 up at ' + r2.base);
const O = { headers: { origin: 'https://page.test' } };
try {
  await T('origin list: a page of another site may not open the socket', async () => {
    const p = new Phone(r2.base, await identity()).open({ headers: { origin: 'https://evil.test' } });
    eq((await p.next('error')).code, 'origin'); eq((await p.untilClosed()).code, 4011);
    const q = new Phone(r2.base, await identity()).open();             // no origin at all
    eq((await q.next('error')).code, 'origin');
  });

  await T('person check at the join: no token and a bad token are refused, a good one joins; the ticket then joins without one', async () => {
    const who = await identity();
    let p = new Phone(r2.base, who); p.open(O);
    eq((await p.join()).code, 'turnstile'); eq(p.challenge.sitekey, '1x00000000000000000000AA'); eq((await p.untilClosed()).code, 4009);
    p = new Phone(r2.base, who); p.open(O); eq((await p.join({ over: { ts: 'forged' } })).code, 'turnstile');
    p = new Phone(r2.base, who); p.open(O);
    const j = await p.join({ over: { ts: 'XXXX.DUMMY.TOKEN.XXXX' } }); eq(j.t, 'joined'); ok(j.ticket);
    eq(seen[seen.length - 1], { secret: 'test-turnstile-secret', response: 'XXXX.DUMMY.TOKEN.XXXX' }, 'what the check was sent: the secret and the token, nothing else');
    const calls = seen.length;
    const again = new Phone(r2.base, who); again.ticket = p.ticket; again.open(O);
    eq((await again.join()).t, 'joined'); eq(seen.length, calls, 'no second check with a ticket');
    const thief = new Phone(r2.base, await identity()); thief.ticket = p.ticket; thief.open(O);
    eq((await thief.join()).code, 'turnstile', 'a ticket is for one number');
    const old = new Phone(r2.base, who); old.ticket = '1000.' + p.ticket.split('.')[1]; old.open(O);
    eq((await old.join()).code, 'turnstile', 'an expired or altered ticket is nothing');
    again.close();
  });

  await T('cell.js asks the page for the person check when the relay wants one', async () => {
    const worker = fakeWorker(), asked = [];
    class WS extends WebSocket { constructor(u) { super(u, O); } }
    const link = cellLink(worker, () => 0, () => {}, { url: r2.base, store: R.memoryStore(), WebSocket: WS, turnstile: async key => { asked.push(key); return 'XXXX.DUMMY.TOKEN.XXXX'; } });
    await link.ready; link.onMessage({ t: 'running' });
    for (let i = 0; i < 200 && link.state !== 'online'; i++) await sleep(25);
    eq([link.state, asked], ['online', ['1x00000000000000000000AA']]);
    link.onMessage({ t: 'end' });
  });

  await T('admin behind Access: only a token signed by the team\'s key, for this application, not expired', async () => {
    const now = Math.floor(Date.now() / 1000), good = { iss: 'https://team.test', aud: ['aud-of-the-admin-app'], exp: now + 300, email: 'owner@example.com' };
    const get = async (h) => (await r2.admin('state', null, h)).status;
    eq(await get({}), 403, 'no token');
    eq(await get({ authorization: 'Bearer test-admin' }), 403, 'the shared secret does not open it when Access is set');
    eq(await get({ 'cf-access-jwt-assertion': await jwt(good) }), 200);
    eq(await get({ 'cf-access-jwt-assertion': await jwt({ ...good, aud: ['another-app'] }) }), 403, 'another application');
    eq(await get({ 'cf-access-jwt-assertion': await jwt({ ...good, iss: 'https://other.test' }) }), 403, 'another team');
    eq(await get({ 'cf-access-jwt-assertion': await jwt({ ...good, exp: now - 10 }) }), 403, 'expired');
    const other = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
    eq(await get({ 'cf-access-jwt-assertion': await jwt(good, other.privateKey) }), 403, 'signed by someone else');
    eq(await get({ 'cf-access-jwt-assertion': b64u('{"alg":"none"}') + '.' + b64u(JSON.stringify(good)) + '.' }), 403, 'unsigned');
    eq((await fetch(r2.base + '/admin')).status, 403, 'the page itself is behind it too');
    const page = await fetch(r2.base + '/admin', { headers: { 'cf-access-jwt-assertion': await jwt(good) } });
    eq(page.status, 200); ok((await page.text()).includes('data-mode="access"'));
    const set = await r2.admin('set', { pause: true }, { 'cf-access-jwt-assertion': await jwt(good) }); eq(set.body.cfg.pause, true);
    await r2.admin('set', { pause: false }, { 'cf-access-jwt-assertion': await jwt(good) });
  });

  await T('join attempts per address: over the limit (12 a minute here) the socket is refused', async () => {
    const codes = [];
    for (let i = 0; i < 30; i++) { const p = new Phone(r2.base, await identity()).open(O); const m = await p.next(x => x.t === 'challenge' || x.t === 'error'); codes.push(m.t === 'challenge' ? 'ok' : m.code); p.close(); }
    console.log('      ' + codes.join(' '));
    ok(codes.includes('flood'), 'some were refused'); ok(codes.indexOf('flood') <= 12, 'the first refusal came by the 13th try');
  });
} finally { await r2.stop(); stand.close(); }

const bad = results.filter(r => !r[0]).length;
console.log(`\n${results.length - bad} passed, ${bad} failed`);
writeFileSync(resolve(HERE, 'last_run.txt'), `${new Date().toISOString()}  node ${process.version}\n` + out.join('\n') + '\n');
process.exit(bad ? 1 : 0);
