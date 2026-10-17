// vectors.mjs: writes ../vectors.json, the shared test vectors of the routing rule and the payload formats (TWIN.md).
//   node test/vectors.mjs            make the file (new random keys: the file is then different)
//   node test/vectors.mjs --check    check the file that is there against client/cell.js
// The keys in the file are TEST KEYS, published on purpose. Never use them for a phone.
// SPDX-License-Identifier: MIT
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { R, ROOT, submit } from './lib.mjs';

const FILE = resolve(ROOT, 'vectors.json'), SIGN = { name: 'ECDSA', hash: 'SHA-256' }, hex = R.hex, unhex = R.unhex;
const CAUSES = { unknown: 1, banned: 8, refused: 21, offline: 27, off: 38, error: 38, timeout: 41, rate: 42, busy: 42, too_big: 111, bad_frame: 111, unsupported: 69 };

async function sealWith(encPrivJwk, peerPub, from, to, payload, salt, iv) {       // seal() of cell.js with a given salt and nonce
  const priv = await crypto.subtle.importKey('jwk', encPrivJwk, { name: 'ECDH', namedCurve: 'P-256' }, false, ['deriveBits']);
  const pub = await crypto.subtle.importKey('raw', peerPub, { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  const info = new TextEncoder().encode(`myna-relay/e2e/1\n${from}\n${to}`);
  const hk = await crypto.subtle.importKey('raw', await crypto.subtle.deriveBits({ name: 'ECDH', public: pub }, priv, 256), 'HKDF', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey({ name: 'HKDF', hash: 'SHA-256', salt, info }, hk, { name: 'AES-GCM', length: 256 }, false, ['encrypt']);
  return R.cat([1], salt, iv, new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: info }, key, payload)));
}

async function make() {
  const who = [];
  for (let i = 0; i < 4; i++) {
    const id = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
    const en = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
    const idPub = new Uint8Array(await crypto.subtle.exportKey('raw', id.publicKey)), encPub = new Uint8Array(await crypto.subtle.exportKey('raw', en.publicKey));
    const number = await R.numberOf(idPub);
    who.push({ number, shard: number.slice(0, 3), identity_public: hex(idPub), identity_sha256: hex(new Uint8Array(await crypto.subtle.digest('SHA-256', idPub))),
      identity_private_jwk: await crypto.subtle.exportKey('jwk', id.privateKey), encryption_public: hex(encPub), encryption_private_jwk: await crypto.subtle.exportKey('jwk', en.privateKey),
      encryption_signature: hex(new Uint8Array(await crypto.subtle.sign(SIGN, id.privateKey, R.encText(number, R.b64(encPub))))), encryption_signed_text: new TextDecoder().decode(R.encText(number, R.b64(encPub))) });
  }
  const [a, b] = who, nonce = 'AAECAwQFBgcICQoLDA0ODw==', host = 'relay.example';
  const idA = await crypto.subtle.importKey('jwk', a.identity_private_jwk, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']);
  const tpdu = submit(b.number, 'Hello'), payload = R.cat([1], tpdu), salt = Uint8Array.from({ length: 16 }, (_, i) => i), iv = Uint8Array.from({ length: 12 }, (_, i) => 0xa0 + i);
  const out = {
    about: 'Shared test vectors of the relay (PROTOCOL.md, TWIN.md). TEST KEYS, published on purpose: never use them for a phone. ECDSA signatures are random: check them, do not compare them.',
    version: 1, number_rule: 'SHA-256(raw public key, 65 bytes) -> first 8 bytes as a big-endian integer = v; number = 10^11 + (v modulo 9 * 10^11): 12 digits, the first never 0; shard = the first 3 digits (100 to 999)',
    identities: who,
    routing: [
      { from: a.number, to: b.number, to_connected: true, same_shard: a.shard === b.shard, forward_to_shard: b.shard, result: 'deliver, then the receiver\'s acknowledgement' },
      { from: a.number, to: who[2].number, to_connected: false, result: { ok: false, code: 'offline', cause: 27 } },
      { from: a.number, to: '5551234', result: { ok: false, code: 'unknown', cause: 1 } },
      { from: a.number, to: '3246', result: 'service echo: sent ok, then the same payload delivered from 3246' },
      { from: a.number, to: '252833', result: { ok: false, code: 'unknown', cause: 1 }, note: 'the Claude number is a disabled stub' },
    ],
    causes: CAUSES,
    join: { relay: host, number: a.number, nonce, signed_text: new TextDecoder().decode(R.joinText(host, a.number, nonce)), signature: hex(new Uint8Array(await crypto.subtle.sign(SIGN, idA, R.joinText(host, a.number, nonce)))) },
    payload: { sms_submit: hex(tpdu), plain_payload: hex(payload), note: 'payload = 01 (kind: SMS-SUBMIT) + the unit as the phone built it' },
    deliver: { from: a.number, receiver_clock: 1224504100, origin_address_field: hex(R.addressField(a.number)), time_stamp: hex(R.timeStamp(1224504100)), sms_deliver: hex(R.submitToDeliver(tpdu, 1224504100, R.addressField(a.number))) },
    echo_deliver: { from: '3246', receiver_clock: 1224504100, sms_deliver: hex(R.submitToDeliver(submit('3246', 'Hello'), 1224504100, R.addressField('3246'))) },
    envelope: { from: a.number, to: b.number, info_text: `myna-relay/e2e/1\n${a.number}\n${b.number}`, salt: hex(salt), nonce: hex(iv), plain_payload: hex(payload),
      body: hex(await sealWith(a.encryption_private_jwk, unhex(b.encryption_public), a.number, b.number, payload, salt, iv)),
      layout: '01 | salt 16 | nonce 12 | AES-256-GCM ciphertext and tag; key = HKDF-SHA256(ECDH P-256 shared x, salt, info_text); additional data = info_text' },
  };
  writeFileSync(FILE, JSON.stringify(out, null, 1) + '\n');
  console.log('written ' + FILE);
}

async function check() {
  const v = JSON.parse(readFileSync(FILE, 'utf8'));
  let n = 0; const ok = (c, what) => { n++; if (!c) throw new Error('vector does not hold: ' + what); };
  for (const w of v.identities) {
    ok(await R.numberOf(unhex(w.identity_public)) === w.number && w.shard === w.number.slice(0, 3), 'number of ' + w.number);
    ok(await R.verify(unhex(w.identity_public), unhex(w.encryption_signature), new TextEncoder().encode(w.encryption_signed_text)), 'encryption key signature');
  }
  const [a, b] = v.identities;
  ok(await R.verify(unhex(a.identity_public), unhex(v.join.signature), R.joinText(v.join.relay, v.join.number, v.join.nonce)), 'join signature');
  ok(hex(R.submitToDeliver(unhex(v.payload.sms_submit), v.deliver.receiver_clock, R.addressField(v.deliver.from))) === v.deliver.sms_deliver, 'deliver');
  ok(R.destination(unhex(v.payload.sms_submit)) === b.number, 'destination');
  const privB = await crypto.subtle.importKey('jwk', b.encryption_private_jwk, { name: 'ECDH', namedCurve: 'P-256' }, false, ['deriveBits']);
  ok(hex(await R.unseal(privB, unhex(a.encryption_public), a.number, b.number, unhex(v.envelope.body))) === v.envelope.plain_payload, 'envelope opens');
  ok(hex(await sealWith(a.encryption_private_jwk, unhex(b.encryption_public), a.number, b.number, unhex(v.envelope.plain_payload), unhex(v.envelope.salt), unhex(v.envelope.nonce))) === v.envelope.body, 'envelope is reproduced byte for byte');
  console.log(`vectors.json: ${n} checks hold`);
}

await (process.argv.includes('--check') ? check() : make());
