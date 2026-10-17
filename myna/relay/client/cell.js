// cell.js: the page's side of the public relay for text messages (PROTOCOL.md). Served to Myna's phone page
// (myna/web) as /cell.js: the worker posts what the phone sends ({t:'cell', n, sc, tpdu}); this file sends it through the relay and
// tells the worker the answer ({t:'cell_result', n, ok, cause}); what arrives is handed in ({t:'cell_in', sc, tpdu, k})
// and the phone's answer ({t:'cell_in_result', k, ok, cause}) travels back to the sender.
//
// What it reports (the page's `report`) never names another phone's number: the page may send its log to a server.
// Use:  const link = cellLink(worker, () => emulatedSeconds, report, { url: 'wss://relay.example', onState, turnstile });
//       link.onMessage(m) for every worker message.
//   link.number            '' until the keys are loaded (link.ready resolves then), after that the 12-digit number
//   onState(s)             s = { state, number, reason, text, services }; state is one of
//                            'starting'    the keys are being loaded or made
//                            'idle'        the phone is not running: not connected
//                            'connecting'
//                            'online'      joined: texts go and come
//                            'offline'     no connection; it tries again by itself (reason: an error code or 'lost')
//                            'stopped'     it will not try again (reason: update, replaced, banned, bad_join, origin, no_relay,
//                                          later: the page put the person check off; link.reconnect() goes on)
//   turnstile(sitekey)     -> Promise of a Turnstile token; called only when the relay asks for the person check. An error
//                          with `later: true` puts the check off: the link stops ('stopped', 'later') until reconnect()
//   link.ticket()          after link.ready: null, or { valid, exp } of the ticket kept from the last join (12 hours): while
//                          it is valid the relay asks for no person check
//   link.reconnect()       try now: after 'later', or after a failed check once the page has a new token (else the link
//                          waits 30 s or more)
//   welcome(number)        -> the text of a welcome (plain GSM letters, one part), or none (the default): after the first join
//                          of this browser's number the phone gets it once, from welcomeFrom ('3246', the relay's echo
//                          service), made here (the relay sends nothing); kept as given in the store ('welcomed:NUMBER')
//   other options          encrypt (true), requireEncryption (true), workerAcks (true), signal (true), store, WebSocket (for tests)
// The phone's signal: the worker gets {t:'cell_state', up: true|false}: up while the link is 'online', down when it has
// not been online for 4 s (and at once when the phone starts without a link).
//
// The number is made from this browser's identity key (ECDSA P-256, kept in IndexedDB, not extractable): it lasts as long
// as the browser's storage for this site. Clearing the storage gives a new number.
// SPDX-License-Identifier: MIT
'use strict';

globalThis.cellRelay = (() => {
  const VERSION = 1, EPOCH = 1224504000, DEFAULT_SC = '81550501f0';
  const FATAL = new Set(['update', 'replaced', 'banned', 'bad_join', 'bad_number', 'origin', 'later']);
  const SLOW = new Set(['off', 'paused', 'full', 'flood', 'turnstile', 'slow_join']);      // try again, but not soon
  const utf8 = s => new TextEncoder().encode(s);
  const hex = u => Array.from(u, b => b.toString(16).padStart(2, '0')).join('');
  const unhex = s => { if (!/^([0-9a-f]{2})*$/i.test(s)) throw new Error('not hex'); const u = new Uint8Array(s.length / 2); for (let i = 0; i < u.length; i++) u[i] = parseInt(s.substr(2 * i, 2), 16); return u; };
  const b64 = u => { u = u instanceof Uint8Array ? u : new Uint8Array(u); let s = ''; for (let i = 0; i < u.length; i++) s += String.fromCharCode(u[i]); return btoa(s); };
  const unb64 = s => { const t = atob(s), u = new Uint8Array(t.length); for (let i = 0; i < t.length; i++) u[i] = t.charCodeAt(i); return u; };
  const cat = (...parts) => { const u = new Uint8Array(parts.reduce((n, p) => n + p.length, 0)); let at = 0; for (const p of parts) { u.set(p, at); at += p.length; } return u; };

  // ---- numbers and keys ----
  async function numberOf(rawPublicKey) {
    const h = new Uint8Array(await crypto.subtle.digest('SHA-256', rawPublicKey));
    let v = 0n;
    for (let i = 0; i < 8; i++) v = (v << 8n) | BigInt(h[i]);
    return (100000000000n + v % 900000000000n).toString();        // 12 digits, the first never 0
  }
  const joinText = (host, number, nonce) => utf8(`myna-relay/join/1\n${host}\n${number}\n${nonce}`);
  const encText = (number, ek) => utf8(`myna-relay/enc/1\n${number}\n${ek}`);
  const e2eText = (from, to) => utf8(`myna-relay/e2e/1\n${from}\n${to}`);
  const ECDSA = { name: 'ECDSA', namedCurve: 'P-256' }, ECDH = { name: 'ECDH', namedCurve: 'P-256' }, SIGN = { name: 'ECDSA', hash: 'SHA-256' };

  async function makeKeys() {
    const id = await crypto.subtle.generateKey(ECDSA, false, ['sign', 'verify']);
    const en = await crypto.subtle.generateKey(ECDH, false, ['deriveBits']);
    const idPub = new Uint8Array(await crypto.subtle.exportKey('raw', id.publicKey));
    const encPub = new Uint8Array(await crypto.subtle.exportKey('raw', en.publicKey));
    const number = await numberOf(idPub);
    const encSig = new Uint8Array(await crypto.subtle.sign(SIGN, id.privateKey, encText(number, b64(encPub))));
    return { v: 1, number, idPriv: id.privateKey, idPub, encPriv: en.privateKey, encPub, encSig };
  }

  async function verify(rawPublicKey, sig, data) {
    try {
      const key = await crypto.subtle.importKey('raw', rawPublicKey, ECDSA, false, ['verify']);
      return await crypto.subtle.verify(SIGN, key, sig, data);
    } catch (e) { return false; }
  }

  // ---- storage: IndexedDB; a store of this visit only when there is none ----
  function memoryStore() {
    const m = new Map();
    return { kind: 'memory', get: async k => m.get(k), put: async (k, v) => void m.set(k, v), putIfAbsent: async (k, v) => { if (!m.has(k)) m.set(k, v); return m.get(k); } };
  }
  function idbStore() {
    let dbp = null;
    const open = () => dbp || (dbp = new Promise((res, rej) => {
      const r = indexedDB.open('cell-relay', 1);
      r.onupgradeneeded = () => r.result.createObjectStore('kv');
      r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); r.onblocked = () => rej(new Error('blocked'));
    }));
    const tx = (mode, f) => open().then(db => new Promise((res, rej) => {
      const t = db.transaction('kv', mode); let out;
      f(t.objectStore('kv'), v => { out = v; });
      t.oncomplete = () => res(out); t.onerror = t.onabort = () => rej(t.error || new Error('aborted'));
    }));
    return {
      kind: 'indexedDB',
      get: k => tx('readonly', (s, out) => { const q = s.get(k); q.onsuccess = () => out(q.result); }),
      put: (k, v) => tx('readwrite', s => { s.put(v, k); }),
      // two tabs that start together must end up with the same keys: the first to write wins
      putIfAbsent: (k, v) => tx('readwrite', (s, out) => { const q = s.get(k); q.onsuccess = () => { if (q.result === undefined) { s.put(v, k); out(v); } else out(q.result); }; }),
    };
  }

  async function loadKeys(store, report) {
    try {
      const have = await store.get('keys');
      if (have && have.v === 1 && have.idPriv) return { keys: have, store };
      return { keys: await store.putIfAbsent('keys', await makeKeys()), store };
    } catch (e) {
      report(`text messages: this browser does not keep the phone's keys (${e && e.message || e}): the number lasts for this visit only`);
      return { keys: await makeKeys(), store: memoryStore() };
    }
  }

  // ---- 3GPP TS 23.040 units, as far as the page needs them (the same as native/emu_cell/cell.py) ----
  function addressField(number) {
    const d = number.replace(/^\+/, '');
    if (!/^\d{1,20}$/.test(d)) throw new Error('not a number');
    const p = d + (d.length % 2 ? 'f' : ''), out = [d.length, number.startsWith('+') ? 0x91 : 0x81];
    for (let i = 0; i < p.length; i += 2) out.push(parseInt(p[i + 1] + p[i], 16));
    return Uint8Array.from(out);
  }
  /** The digits of the destination of an SMS-SUBMIT (no '+'). */
  function destination(t) {
    if (t.length < 7 || (t[0] & 3) !== 1) throw new Error('not an SMS-SUBMIT');
    const n = t[2], raw = t.subarray(4, 4 + ((n + 1) >> 1));
    if (n < 1 || n > 20 || raw.length < (n + 1) >> 1) throw new Error('SMS-SUBMIT cut short');
    const d = Array.from(raw, b => (b & 15).toString(16) + (b >> 4).toString(16)).join('').slice(0, n);
    if (!/^\d+$/.test(d)) throw new Error('not a number');
    return d;
  }
  function timeStamp(seconds) {
    const t = new Date(seconds * 1000);
    return Uint8Array.from([t.getUTCFullYear() % 100, t.getUTCMonth() + 1, t.getUTCDate(), t.getUTCHours(), t.getUTCMinutes(), t.getUTCSeconds(), 0], v => (v % 10) << 4 | Math.floor(v / 10));
  }
  /** An SMS-DELIVER of one part from the number `from` at `seconds`: a text in the GSM 7-bit alphabet, of the letters, digits,
   *  space and plain signs it shares with ASCII. */
  function textDeliver(from, text, seconds) {
    if (!/^[A-Za-z0-9 !"#%&'()*+,\-./:;<=>?]{1,160}$/.test(text)) throw new Error('not a text of one part in plain GSM letters');
    const ud = new Uint8Array(Math.ceil(text.length * 7 / 8));
    for (let i = 0; i < text.length; i++) for (let b = 0; b < 7; b++) if (text.charCodeAt(i) >> b & 1) { const bit = i * 7 + b; ud[bit >> 3] |= 1 << (bit & 7); }
    return cat([0x04], addressField(from), [0x00, 0x00], timeStamp(seconds), [text.length], ud);
  }
  /** The SMS-DELIVER that the receiver of the SMS-SUBMIT `t` gets from `origin` (an address field) at `seconds`. */
  function submitToDeliver(t, seconds, origin) {
    if (t.length < 7 || (t[0] & 3) !== 1) throw new Error('not an SMS-SUBMIT');
    let at = 2;
    const address = t.subarray(at, at + 2 + ((t[at] + 1) >> 1));
    at += address.length;
    const validity = [0, 7, 1, 7][(t[0] >> 3) & 3];                // TP-VPF: none, enhanced, relative, absolute
    if (t.length < at + 2 + validity + 1) throw new Error('SMS-SUBMIT cut short');
    return cat([(t[0] & 0xc0) | 0x04], origin || address, t.subarray(at, at + 2), timeStamp(seconds), t.subarray(at + 2 + validity));
  }

  // ---- end-to-end encryption (PROTOCOL.md, "The envelope") ----
  async function aesKey(encPriv, peerPubRaw, salt, info, use) {
    const pub = await crypto.subtle.importKey('raw', peerPubRaw, ECDH, false, []);
    const bits = await crypto.subtle.deriveBits({ name: 'ECDH', public: pub }, encPriv, 256);
    const hk = await crypto.subtle.importKey('raw', bits, 'HKDF', false, ['deriveKey']);
    return crypto.subtle.deriveKey({ name: 'HKDF', hash: 'SHA-256', salt, info }, hk, { name: 'AES-GCM', length: 256 }, false, [use]);
  }
  async function seal(encPriv, peerPubRaw, from, to, payload) {
    const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12)), info = e2eText(from, to);
    const key = await aesKey(encPriv, peerPubRaw, salt, info, 'encrypt');
    return cat([1], salt, iv, new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: info }, key, payload)));
  }
  async function unseal(encPriv, peerPubRaw, from, to, body) {
    if (body.length < 1 + 16 + 12 + 16 || body[0] !== 1) throw new Error('not an envelope of version 1');
    const info = e2eText(from, to), key = await aesKey(encPriv, peerPubRaw, body.subarray(1, 17), info, 'decrypt');
    return new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: body.subarray(17, 29), additionalData: info }, key, body.subarray(29)));
  }

  // ---- the link ----
  function link(worker, emuSeconds, report, options) {
    const o = Object.assign({ url: globalThis.CELL_RELAY_URL || '', encrypt: true, requireEncryption: true, workerAcks: true, signal: true, onState: null, turnstile: null,
      welcome: null, welcomeFrom: '3246', store: null, WebSocket: globalThis.WebSocket }, options || {});
    const say = s => { try { report('text messages: ' + s); } catch (e) { /* the page's matter */ } };
    const clock = () => EPOCH + Math.floor(emuSeconds());
    let keys = null, store = o.store, ws = null, state = 'starting', reason = '', text = '', wanted = false, tries = 0, retry = null, pinger = null, pongWait = null;
    let services = new Map(), limits = { pendSec: 45 }, ticket = null, lastSc = DEFAULT_SC, nextId = 1, nextK = 1, nextR = 1, joinedAt = 0;
    const sends = new Map();          // message id -> { done, timer, to }
    const asks = new Map();           // key request -> resolve
    const waits = new Map();          // hand-in number -> { sock, d, timer }
    const peers = new Map();          // number -> { ek, id } checked against the number
    const self = {
      number: '', state,
      get services() { return [...services.values()]; },
      onMessage, close() { wanted = false; stop('idle', ''); },
      format: n => n.replace(/^(\d{4})(\d{4})(\d{4})$/, '$1 $2 $3'),
      ticket: () => ticket ? { valid: ticket.exp > Math.floor(Date.now() / 1000) + 60, exp: ticket.exp } : null,
      reconnect() {
        if (state === 'stopped' && reason !== 'later') return;
        if (state === 'stopped') { state = self.state = 'offline'; reason = ''; }
        tries = 0; connect();
      },
    };

    // The phone's signal follows the link: {t:'cell_state', up} goes to the worker when the link comes up (at once) and when
    // it has been down for DOWN_MS (so that a quick reconnect does not move the bars). A new phone start is told afresh.
    const DOWN_MS = 4000;
    let told = null, downTimer = null;
    function signal(up) {
      if (!o.signal) return;
      if (up) { clearTimeout(downTimer); downTimer = null; if (told !== true) { told = true; worker.postMessage({ t: 'cell_state', up: true }); } }
      else if (told !== false && !downTimer) downTimer = setTimeout(() => { downTimer = null; if (wanted && state !== 'online') { told = false; worker.postMessage({ t: 'cell_state', up: false }); } }, told === null ? 0 : DOWN_MS);
    }

    function set(s, why, words) {
      state = self.state = s; reason = why || ''; text = words || '';
      if (s === 'idle') { clearTimeout(downTimer); downTimer = null; told = null; } else signal(s === 'online');
      if (o.onState) try { o.onState({ state: s, number: self.number, reason, text, services: self.services }); } catch (e) { /* the page's matter */ }
    }

    self.ready = (async () => {
      if (!store) { try { store = typeof indexedDB !== 'undefined' ? idbStore() : memoryStore(); } catch (e) { store = memoryStore(); } }
      const got = await loadKeys(store, report);
      keys = got.keys; store = got.store;
      self.number = keys.number;
      try { const t = await store.get('ticket'); if (t && t.n === keys.number) ticket = t; } catch (e) { /* none */ }
      set(wanted ? 'offline' : 'idle', '');
      if (wanted) connect();
      return keys.number;
    })();
    self.ready.catch(e => { say('no keys: ' + (e && e.message || e)); set('stopped', 'no_keys', 'This browser cannot make the keys for a number.'); });

    function connect() {
      clearTimeout(retry); retry = null;
      if (!wanted || ws || !keys || state === 'stopped') return;
      if (!o.url) { say('no relay address given'); return set('stopped', 'no_relay', 'No network is set up for this page.'); }
      const u = new URL(o.url, globalThis.location ? globalThis.location.href : undefined);
      u.protocol = u.protocol === 'https:' ? 'wss:' : u.protocol === 'http:' ? 'ws:' : u.protocol;
      u.pathname = u.pathname.replace(/\/$/, '') + '/ws'; u.search = `?n=${keys.number}&v=${VERSION}`;
      set('connecting', '');
      let sock;
      try { sock = ws = new o.WebSocket(u.href); } catch (e) { say('no socket: ' + e.message); return again('lost'); }
      sock.relayHost = u.host; sock.why = '';
      sock.onmessage = e => { if (sock === ws) incoming(sock, e.data).catch(x => say('error: ' + (x && x.message || x))); };
      sock.onclose = () => { if (sock === ws) { ws = null; lost(sock.why || 'lost', sock.words || ''); } };
      sock.onerror = () => { /* onclose follows */ };
    }

    function lost(why, words) {
      clearInterval(pinger); clearTimeout(pongWait); pinger = pongWait = null;
      for (const [id, s] of sends) { clearTimeout(s.timer); s.done(false, 38); }
      sends.clear();
      for (const [, f] of asks) f({ ok: false, cause: 38 });
      asks.clear();
      for (const [, w] of waits) clearTimeout(w.timer);                 // the sender's wait runs out: its relay cannot be told
      waits.clear();
      if (!wanted) return set('idle', '');
      if (FATAL.has(why)) { signal(false); say(`stopped: ${why}${words ? ' (' + words + ')' : ''}`); return set('stopped', why, words); }
      again(why, words);
    }

    function again(why, words) {
      ws = null;
      if (joinedAt && Date.now() - joinedAt > 30000) tries = 0;
      joinedAt = 0;
      const base = Math.min(60, 2 ** tries++) * 1000;
      // the network is switched off: ask again every 3 to 5 minutes; other refusals: not before 30 s; else 1, 2, 4 ... 60 s
      const wait = why === 'off' ? 180000 + 120000 * Math.random() : Math.max(SLOW.has(why) ? 30000 : 0, base) * (0.6 + 0.4 * Math.random());
      set('offline', why, words);
      say(`no service (${why}); next try in ${(wait / 1000).toFixed(0)} s`);
      retry = setTimeout(connect, wait);
    }

    function stop(s, why) {
      clearTimeout(retry); retry = null;
      const sock = ws;
      if (sock) { try { sock.close(1000, 'bye'); } catch (e) { /* closed */ } ws = null; lost('lost'); }
      if (state !== 'stopped' && state !== s && keys) set(s, why);
    }

    const sendJson = (sock, m) => { try { sock.send(JSON.stringify(m)); return true; } catch (e) { return false; } };

    async function incoming(sock, data) {
      if (data === 'pong') { clearTimeout(pongWait); pongWait = null; return; }
      let m;
      try { m = JSON.parse(data); } catch (e) { return; }
      if (m.t === 'challenge') return join(sock, m);
      if (m.t === 'joined') return joined(sock, m);
      if (m.t === 'sent') {
        const s = sends.get(m.id);
        if (!s) return;
        sends.delete(m.id); clearTimeout(s.timer);
        if (!m.ok) { peers.delete(s.to); say(`a text was not sent: ${m.code} (cause ${m.cause})`); } else say('a text was sent: the far phone took it');
        return s.done(!!m.ok, m.ok ? 0 : (m.cause || 38));
      }
      if (m.t === 'deliver') return deliver(sock, m);
      if (m.t === 'key') { const f = asks.get(m.r); if (f) { asks.delete(m.r); f(m); } return; }
      if (m.t === 'error') {
        if (m.fatal) {
          // The relay closes after a fatal error. The page does not wait for the close to complete: it may take long.
          if (m.code === 'turnstile' || m.code === 'bad_join') ticket = null;
          ws = null; sock.onclose = null;
          try { sock.close(); } catch (e) { /* closed */ }
          lost(m.code, m.text || '');
        }
        else say(`the relay refused a frame: ${m.code}${m.re ? ' (' + m.re + ')' : ''}`);
      }
    }

    async function join(sock, m) {
      if (m.relay !== sock.relayHost) { say(`the relay names itself ${m.relay}, not ${sock.relayHost}: not joining`); sock.why = 'bad_join'; return sock.close(); }
      const now = Math.floor(Date.now() / 1000), out = { t: 'join', v: VERSION, id: b64(keys.idPub), ek: b64(keys.encPub), es: b64(keys.encSig) };
      out.sig = b64(await crypto.subtle.sign(SIGN, keys.idPriv, joinText(m.relay, keys.number, m.nonce)));
      if (ticket && ticket.exp > now + 60) out.ticket = ticket.ticket;
      else if (m.sitekey) {
        if (!o.turnstile) { say('the relay asks for the person check and the page has none'); sock.why = 'turnstile'; return sock.close(); }
        try { out.ts = await o.turnstile(m.sitekey); }
        catch (e) { say(e && e.later ? 'the person check is put off' : 'the person check failed: ' + (e && e.message || e)); sock.why = e && e.later ? 'later' : 'turnstile'; return sock.close(); }
      }
      sendJson(sock, out);
    }

    function joined(sock, m) {
      services = new Map((m.services || []).map(s => [s.n, s]));
      limits = Object.assign(limits, m.limits || {});
      joinedAt = Date.now();
      if (m.ticket) { ticket = { n: keys.number, ticket: m.ticket, exp: m.ticketExp }; store.put('ticket', ticket).catch(() => {}); }
      clearInterval(pinger);
      pinger = setInterval(() => {
        if (sock !== ws || pongWait) return;
        try { sock.send('ping'); } catch (e) { return; }
        pongWait = setTimeout(() => { pongWait = null; say('the relay does not answer'); try { sock.close(); } catch (e) { /* closed */ } if (sock === ws) { ws = null; sock.onclose = null; lost('lost'); } }, 10000);
      }, (m.ping || 45) * 1000);
      set('online', '');
      say(`on the network as ${keys.number}`);
      welcome();
    }

    // ---- the welcome: once for this browser's number, after its first join ----
    // The phone takes a text only once it is registered and has asked for them (the modem stand-in refuses it before): it is
    // offered again every 5 s for a minute, and kept as given only when the phone took it; else at the next join.
    let welcoming = false;
    async function welcome() {
      if (!o.welcome || welcoming) return;
      welcoming = true;
      const flag = 'welcomed:' + keys.number;
      try {
        if (await store.get(flag)) return;
        const text = o.welcome(keys.number);
        if (!text) return;
        for (let i = 0; i < 12 && wanted; i++) {
          await new Promise(r => setTimeout(r, i ? 5000 : 1500));
          if (!wanted) break;
          const tpdu = textDeliver(o.welcomeFrom, text, clock());
          const took = await Promise.race([new Promise(r => handIn(tpdu, ok => r(ok))), new Promise(r => setTimeout(() => r(false), 45000))]);
          if (took) { await store.put(flag, Date.now()); say('the welcome text: the phone took it'); return; }
        }
        say('the welcome text: the phone did not take it, again at the next join');
      } catch (e) { say('no welcome text: ' + (e && e.message || e)); }
      finally { welcoming = false; }
    }

    // ---- the phone sends ----
    function ask(sock, number) {
      return new Promise(res => {
        const r = nextR++;
        const t = setTimeout(() => { asks.delete(r); res({ ok: false, cause: 41 }); }, 10000);
        asks.set(r, m => { clearTimeout(t); res(m); });
        if (!sendJson(sock, { t: 'key', r, n: number })) { asks.delete(r); clearTimeout(t); res({ ok: false, cause: 38 }); }
      });
    }

    /** The checked keys of a number: the identity key must give the number, and must have signed the encryption key.
     *  A number has one identity key for ever, so a second one is refused (kept in this browser's storage). */
    async function checkPeer(number, id, ek, es) {
      const have = peers.get(number);
      if (have && have.id === id && have.ek === ek) return have;
      let idRaw, ekRaw, esRaw;
      try { idRaw = unb64(id); ekRaw = unb64(ek); esRaw = unb64(es); } catch (e) { return null; }
      if (await numberOf(idRaw) !== number || !await verify(idRaw, esRaw, encText(number, ek))) { say('the keys given for a number do not belong to it: refused'); return null; }
      try {
        const pin = await store.putIfAbsent('pin:' + number, id);
        if (pin !== id) { say('a number came with another identity key than before: refused'); return null; }
      } catch (e) { /* no storage: checked against the number only */ }
      const p = { id, ek, ekRaw };
      peers.set(number, p);
      return p;
    }

    async function send(m) {
      const done = (ok, cause) => worker.postMessage({ t: 'cell_result', n: m.n, ok, cause });
      const sock = ws;
      if (state !== 'online' || !sock) return done(false, 38);
      let tpdu, to;
      try { tpdu = unhex(m.tpdu); to = destination(tpdu); } catch (e) { say('the phone sent something that is not a text: ' + e.message); return done(false, 95); }
      if (m.sc) lastSc = m.sc;
      let body = cat([1], tpdu), enc = 0;
      if (o.encrypt && !services.has(to)) {
        let p = peers.get(to);
        if (!p) {
          const k = await ask(sock, to);
          if (!k.ok) return done(false, k.cause || 27);
          if (!k.service) { p = await checkPeer(to, k.id, k.ek, k.es); if (!p) return done(false, 21); }
        }
        if (p) { body = await seal(keys.encPriv, p.ekRaw, keys.number, to, body); enc = 1; }
      }
      if (sock !== ws || state !== 'online') return done(false, 38);
      const id = nextId++;
      sends.set(id, { done, to, timer: setTimeout(() => { sends.delete(id); say('a text was not acknowledged in time'); done(false, 41); }, (limits.pendSec + 5) * 1000) });
      if (!sendJson(sock, { t: 'msg', id, to, enc, body: b64(body) })) { clearTimeout(sends.get(id).timer); sends.delete(id); done(false, 38); }
    }

    // ---- a text arrives ----
    async function deliver(sock, m) {
      const fromService = services.has(m.from);
      const answer = (ok, cause) => { if (!fromService && sock === ws) sendJson(sock, ok ? { t: 'ack', d: m.d, ok: true } : { t: 'ack', d: m.d, ok: false, cause }); };
      if (typeof m.from !== 'string' || !(fromService || /^[1-9]\d{11}$/.test(m.from)) || typeof m.body !== 'string') return answer(false, 111);
      let payload;
      try { payload = unb64(m.body); } catch (e) { return answer(false, 111); }
      if (m.enc) {
        const p = fromService ? null : await checkPeer(m.from, m.id, m.ek, m.es);
        if (!p) return answer(false, 21);
        try { payload = await unseal(keys.encPriv, p.ekRaw, m.from, keys.number, payload); }
        catch (e) { say('a text could not be opened: refused'); return answer(false, 21); }
      } else if (o.encrypt && o.requireEncryption && !fromService) {
        say('a text came without encryption: refused');
        return answer(false, 21);
      }
      let tpdu;
      try {
        if (payload[0] !== 1) throw new Error('unknown kind ' + payload[0]);
        tpdu = submitToDeliver(payload.subarray(1), clock(), addressField(m.from));
      } catch (e) { say(`a text was not understood (${e.message}): refused`); return answer(false, 95); }
      if (!wanted) return answer(false, 27);
      handIn(tpdu, (ok, cause, late) => {
        if (o.workerAcks) say(late ? 'a text arrived: the phone did not answer in time' : ok ? 'a text arrived: the phone took it' : `a text arrived: the phone refused it (cause ${cause})`);
        answer(ok, cause);
      });
    }

    /** An SMS-DELIVER to the phone; done(ok, cause, late) with its answer (late: none came in time, cause 41). */
    function handIn(tpdu, done) {
      const k = nextK++;
      if (!o.workerAcks) { worker.postMessage({ t: 'cell_in', sc: lastSc, tpdu: hex(tpdu), k }); return done(true, 0); }
      waits.set(k, { answer: done, timer: setTimeout(() => { waits.delete(k); done(false, 41, true); }, 40000) });
      worker.postMessage({ t: 'cell_in', sc: lastSc, tpdu: hex(tpdu), k });      // after the wait is set: the answer may come at once
    }

    function onMessage(m) {
      if (m.t === 'cell') send(m).catch(e => { say('send failed: ' + (e && e.message || e)); worker.postMessage({ t: 'cell_result', n: m.n, ok: false, cause: 38 }); });
      else if (m.t === 'cell_in_result') { const w = waits.get(m.k); if (w) { waits.delete(m.k); clearTimeout(w.timer); w.answer(!!m.ok, m.cause || 21); } }
      else if (m.t === 'running') { if (!wanted) { wanted = true; tries = 0; told = null; if (keys && state !== 'stopped') connect(); else signal(false); } }
      else if (m.t === 'end' || (m.t === 'error' && !m.soft)) { wanted = false; stop('idle', ''); }
    }

    // a tab that comes back, or a network that comes back: try now
    if (typeof addEventListener === 'function') {
      const nudge = () => { if (wanted && !ws && state === 'offline' && !SLOW.has(reason)) { tries = 0; connect(); } };
      addEventListener('online', nudge);
      if (typeof document !== 'undefined') document.addEventListener('visibilitychange', () => { if (!document.hidden) nudge(); });
    }
    return self;
  }

  return { VERSION, link, numberOf, joinText, encText, makeKeys, verify, addressField, destination, submitToDeliver, textDeliver, timeStamp, seal, unseal, memoryStore, hex, unhex, b64, unb64, cat };
})();

function cellLink(worker, emuSeconds, report, options) { return cellRelay.link(worker, emuSeconds, report, options); }
