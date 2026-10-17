// shard.ts: one of the 900 objects that hold the phones' connections. A number's first three digits choose its shard.
//
// Nothing about a text is kept: a text is passed on in the same event that brought it, or refused. What is kept:
//   per connection (in the socket's attachment, which lives exactly as long as the connection and survives hibernation):
//     the number, its public keys, the time it joined, its rate bucket, its counters, and for each text that waits for
//     the far phone's acknowledgement: the sender's message id, the destination and a deadline (so that only the
//     real receiver can acknowledge it). The destination is dropped with the acknowledgement or at the deadline.
//   per shard (in its storage): the configuration from the control object, and the summed counters of closed connections.
// SPDX-License-Identifier: MIT
import { DurableObject } from 'cloudflare:workers';
import { CAUSE, CLOSE, TEXT, VERSION, MIN_VERSION, DEFAULT_CONFIG, Config, Env, b64, unb64, numberOf, isNumber, shardOf, joinText, encText, verify, makeTicket, checkTicket } from './proto';
import { SERVICES, service, answer } from './services';

const TICKET_S = 12 * 3600, REPORT_EVERY = 25;

interface Att {
  n: string;                     // the number asked for in the URL; proven when st = 1
  st: 0 | 1;                     // 0: challenged, 1: joined
  at: number;                    // ms: when the socket opened (st 0) or joined (st 1)
  host: string;                  // the relay's host name as the client reached it (signed by the join)
  nonce?: string;
  id?: string; ek?: string; es?: string;      // identity key, encryption key, its signature (base64)
  tk: number; tl: number;        // rate bucket: tokens, time of the last refill (ms)
  fk: number; fl: number;        // frame bucket
  s: number; f: number; l: number;            // texts sent, failed, refused by the rate limit
  fc: Record<string, number>;    // failures by code
  p: [number, string, number][]; // waiting for an acknowledgement: message id, destination, deadline (ms)
  gone?: boolean;                // its counters are already in the shard's totals
}

interface Totals { joins: number; sent: number; fail: Record<string, number>; }

export class Shard extends DurableObject<Env> {
  cfg: Config;
  boot = crypto.randomUUID();    // changes whenever the object is built again (the hibernation test reads it)
  alarmAt = 0;                   // what this instance knows of its alarm (0: not known)
  since = 0;                     // texts and joins since the last report: a busy shard reports early, so that the network's ceilings act quickly

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.cfg = (ctx.storage.kv.get('cfg') as Config | undefined) ?? DEFAULT_CONFIG;
    // The page's keep-alive ("ping" every 45 s) is answered by the platform without waking this object.
    ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('ping', 'pong'));
  }

  // ---- the socket opens -------------------------------------------------------------------------------------------
  async fetch(req: Request): Promise<Response> {
    const url = new URL(req.url), n = url.searchParams.get('n') || '';
    const pair = new WebSocketPair(), client = pair[0], server = pair[1];
    const refuse = (code: keyof typeof CLOSE) => {
      server.accept();
      server.send(JSON.stringify({ t: 'error', code, text: TEXT[code], fatal: true }));
      server.close(CLOSE[code], code);
      return new Response(null, { status: 101, webSocket: client });
    };
    if (!isNumber(n)) return refuse('bad_number');
    if (!this.ctx.storage.kv.get('idx')) this.ctx.storage.kv.put('idx', shardOf(n));
    if (this.cfg.version === 0) await this.sync();       // a shard's first connection ever: fetch the configuration first
    if (this.cfg.kill) return refuse('off');
    if (this.cfg.bans.includes(n)) return refuse('banned');
    if (this.ctx.getWebSockets().length >= this.cfg.limits.maxConns) return refuse('full');
    const now = Date.now(), nonce = b64(crypto.getRandomValues(new Uint8Array(16)));
    this.ctx.acceptWebSocket(server, ['n:' + n]);
    const L = this.cfg.limits;
    const att: Att = { n, st: 0, at: now, host: url.host, nonce, tk: L.joinTokens, tl: now, fk: L.framesPerMin, fl: now, s: 0, f: 0, l: 0, fc: {}, p: [] };
    server.serializeAttachment(att);
    const sitekey = this.turnstile() ? (this.env.TURNSTILE_SITEKEY || '') : '';
    server.send(JSON.stringify({ t: 'challenge', v: VERSION, min: MIN_VERSION, relay: url.host, nonce, sitekey }));
    await this.ensureAlarm(L.joinSec + 1);
    return new Response(null, { status: 101, webSocket: client });
  }

  turnstile() { const s = this.env.TURNSTILE_SECRET; return !!s && s !== 'off'; }

  // ---- a frame arrives --------------------------------------------------------------------------------------------
  async webSocketMessage(ws: WebSocket, raw: string | ArrayBuffer) {
    const L = this.cfg.limits, now = Date.now();
    const att = ws.deserializeAttachment() as Att;
    if (typeof raw !== 'string' || raw.length > 2 * L.maxBody + 1024) return this.drop(ws, 'flood', 'too_big');
    att.fk = Math.min(L.framesPerMin, att.fk + (now - att.fl) * L.framesPerMin / 60000) - 1; att.fl = now;
    if (att.fk < 0) return this.drop(ws, 'flood');
    let m: any;
    try { m = JSON.parse(raw); } catch { m = null; }
    if (!m || typeof m !== 'object' || typeof m.t !== 'string') return this.drop(ws, 'flood', 'bad_frame');
    if (att.st === 0) {
      if (m.t !== 'join') return this.drop(ws, 'bad_join');
      return this.join(ws, att, m, now);
    }
    ws.serializeAttachment(att);
    if (m.t === 'msg') return this.msg(ws, m, now);
    if (m.t === 'ack') return this.ack(att, m);
    if (m.t === 'key') return this.key(ws, m);
    // Reserved for later (PROTOCOL.md): call set-up signalling and private rooms. Not built.
    if (m.t.startsWith('call.') || m.t.startsWith('room.')) return ws.send(JSON.stringify({ t: 'error', code: 'unsupported', re: m.t, fatal: false }));
    ws.send(JSON.stringify({ t: 'error', code: 'bad_frame', re: String(m.t).slice(0, 20), fatal: false }));
  }

  async join(ws: WebSocket, att: Att, m: any, now: number) {
    if (m.v !== VERSION && !(Number.isInteger(m.v) && m.v >= MIN_VERSION && m.v <= VERSION)) return this.drop(ws, 'update');
    const id = unb64(m.id, 100), sig = unb64(m.sig, 100), ek = unb64(m.ek, 100), es = unb64(m.es, 100);
    if (!id || !sig || !ek || !es || ek.length !== 65 || ek[0] !== 4) return this.drop(ws, 'bad_join');
    if (await numberOf(id) !== att.n) return this.drop(ws, 'bad_join');
    if (!await verify(id, sig, joinText(att.host, att.n, att.nonce!))) return this.drop(ws, 'bad_join');
    if (!await verify(id, es, encText(att.n, m.ek))) return this.drop(ws, 'bad_join');
    if (this.cfg.kill) return this.drop(ws, 'off');
    if (this.cfg.bans.includes(att.n)) return this.drop(ws, 'banned');
    const nowS = Math.floor(now / 1000), secret = this.env.TICKET_SECRET || '';
    const known = await checkTicket(secret, att.n, m.ticket, nowS);     // it joined before, within the ticket's life
    if ((this.cfg.pause || this.cfg.hold?.joins) && !known) return this.drop(ws, 'paused');
    if (this.turnstile() && !known && !await this.person(m.ts)) return this.drop(ws, 'turnstile');
    for (const other of this.ctx.getWebSockets('n:' + att.n)) if (other !== ws) this.drop(other, 'replaced');
    const L = this.cfg.limits;
    const joined: Att = { n: att.n, st: 1, at: now, host: att.host, id: m.id, ek: m.ek, es: m.es, tk: L.joinTokens, tl: now, fk: att.fk, fl: att.fl, s: 0, f: 0, l: 0, fc: {}, p: [] };
    ws.serializeAttachment(joined);
    const exp = nowS + TICKET_S;
    ws.send(JSON.stringify({
      t: 'joined', v: VERSION, n: att.n, ping: 45,
      limits: { perMin: L.perMin, burst: L.burst, maxBody: L.maxBody, pendSec: L.pendSec },
      services: SERVICES.filter(s => s.enabled).map(s => ({ n: s.number, name: s.name, notice: s.notice })),
      ticket: secret ? await makeTicket(secret, att.n, exp) : '', ticketExp: secret ? exp : 0,
    }));
    this.bump({ joins: 1 });
    this.tick();
    await this.ensureAlarm(L.reportSec);
  }

  /** The Turnstile check of a token. One request to Cloudflare; the token is not kept. */
  async person(token: unknown): Promise<boolean> {
    if (typeof token !== 'string' || !token || token.length > 2048) return false;
    try {
      const res = await fetch(this.env.TURNSTILE_VERIFY_URL || 'https://challenges.cloudflare.com/turnstile/v0/siteverify', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ secret: this.env.TURNSTILE_SECRET, response: token }),
      });
      return (await res.json() as any).success === true;
    } catch { return false; }
  }

  // ---- a text from this shard's phone -----------------------------------------------------------------------------
  async msg(ws: WebSocket, m: any, now: number) {
    const L = this.cfg.limits;
    let att = ws.deserializeAttachment() as Att;
    const id = m.id;
    if (!Number.isInteger(id) || id < 0 || id > 0x7fffffff) return ws.send(JSON.stringify({ t: 'error', code: 'bad_frame', re: 'msg', fatal: false }));
    const fail = (code: string) => {
      att.f++; att.fc[code] = (att.fc[code] || 0) + 1;
      ws.serializeAttachment(att);
      ws.send(JSON.stringify({ t: 'sent', id, ok: false, code, cause: CAUSE[code] ?? 38 }));
    };
    if (this.cfg.kill) return fail('off');
    if (this.cfg.hold?.day) return fail('net_day');
    if (this.cfg.hold?.texts) return fail('net_rate');
    att.tk = Math.min(L.burst, att.tk + (now - att.tl) * L.perMin / 60000); att.tl = now;
    if (att.tk < 1) { att.l++; fail('rate'); return this.ensureAlarm(L.reportSec); }
    att.tk -= 1;
    const to = m.to, enc = m.enc ? 1 : 0;
    if (typeof m.body !== 'string' || m.body.length > Math.ceil(L.maxBody / 3) * 4 || !unb64(m.body, 1 << 20)) return fail('too_big');
    if (typeof to !== 'string' || !/^\d{1,20}$/.test(to)) return fail('unknown');
    const late = att.p.filter(p => p[2] <= now);                        // never acknowledged: they count as failures
    if (late.length) { att.p = att.p.filter(p => p[2] > now); att.f += late.length; att.fc.timeout = (att.fc.timeout || 0) + late.length; }
    const svc = service(to);
    if (svc) {
      if (enc) return fail('unsupported');
      att.s++;
      ws.serializeAttachment(att);
      ws.send(JSON.stringify({ t: 'sent', id, ok: true }));
      this.tick();
      let k = 0;
      for (const body of await answer(svc, m.body)) ws.send(JSON.stringify({ t: 'deliver', d: `${svc.number}.${id}.${k++}`, from: svc.number, enc: 0, body }));
      return this.ensureAlarm(L.reportSec);
    }
    if (!isNumber(to)) return fail('unknown');
    if (att.p.length >= L.maxPending || att.p.some(p => p[0] === id)) return fail('busy');
    att.p.push([id, to, now + L.pendSec * 1000]);
    ws.serializeAttachment(att);                                        // before the await: the acknowledgement may overtake it
    const item = { from: att.n, mid: id, to, enc, body: m.body, keys: enc ? { id: att.id!, ek: att.ek!, es: att.es! } : null };
    let res: { ok: boolean; code?: string };
    try {
      res = shardOf(to) === shardOf(att.n) ? this.deliver(item) : await this.shard(to).deliver(item);
    } catch { res = { ok: false, code: 'error' }; }
    if (!res.ok) {
      att = ws.deserializeAttachment() as Att;
      att.p = att.p.filter(p => p[0] !== id);
      fail(res.code || 'error');
    }
    await this.ensureAlarm(L.reportSec);
  }

  shard(number: string) { return this.env.SHARD.get(this.env.SHARD.idFromName('s' + shardOf(number))); }

  phone(number: string): WebSocket | null {
    for (const ws of this.ctx.getWebSockets('n:' + number)) {
      const a = ws.deserializeAttachment() as Att;
      if (a.st === 1 && !a.gone) return ws;
    }
    return null;
  }

  /** Called by the sender's shard: hand a text to this shard's phone. Nothing is kept here. */
  deliver(item: { from: string; mid: number; to: string; enc: number; body: string; keys: { id: string; ek: string; es: string } | null }): { ok: boolean; code?: string } {
    if (this.cfg.kill) return { ok: false, code: 'off' };
    const ws = this.phone(item.to);
    if (!ws) return { ok: false, code: 'offline' };
    try {
      ws.send(JSON.stringify({ t: 'deliver', d: `${item.from}.${item.mid}`, from: item.from, enc: item.enc, body: item.body, ...(item.keys || {}) }));
    } catch { return { ok: false, code: 'offline' }; }
    return { ok: true };
  }

  // ---- the receiving phone's answer travels back ------------------------------------------------------------------
  async ack(att: Att, m: any) {
    const parts = typeof m.d === 'string' ? m.d.split('.') : [];
    const from = parts[0], mid = Number(parts[1]);
    if (parts.length !== 2 || !isNumber(from) || !Number.isInteger(mid)) return;       // a service's delivery, or nonsense
    const ok = m.ok === true, cause = Number.isInteger(m.cause) ? m.cause & 0x7f : 0;
    try {
      if (shardOf(from) === shardOf(att.n)) this.acked(from, mid, att.n, ok, cause);
      else await this.shard(from).acked(from, mid, att.n, ok, cause);
    } catch { /* the sender's wait runs out */ }
  }

  /** Called by the receiver's shard. `by` is the number that shard proved; only the destination of the waiting text counts. */
  acked(from: string, mid: number, by: string, ok: boolean, cause: number) {
    const ws = this.phone(from);
    if (!ws) return;
    const att = ws.deserializeAttachment() as Att;
    const i = att.p.findIndex(p => p[0] === mid && p[1] === by);
    if (i < 0) return;
    att.p.splice(i, 1);
    if (ok) { att.s++; this.tick(); } else { att.f++; att.fc.refused = (att.fc.refused || 0) + 1; }
    ws.serializeAttachment(att);
    ws.send(JSON.stringify(ok ? { t: 'sent', id: mid, ok: true } : { t: 'sent', id: mid, ok: false, code: 'refused', cause: cause || CAUSE.refused }));
  }

  // ---- the public keys of a number, for end-to-end encryption -----------------------------------------------------
  async key(ws: WebSocket, m: any) {
    const r = Number.isInteger(m.r) ? m.r : 0, n = m.n;
    const reply = (o: object) => ws.send(JSON.stringify({ t: 'key', r, n: String(n).slice(0, 20), ...o }));
    if (typeof n === 'string' && service(n)) return reply({ ok: true, service: true });
    if (!isNumber(n)) return reply({ ok: false, code: 'unknown', cause: CAUSE.unknown });
    let k: { id: string; ek: string; es: string } | null = null;
    try { k = shardOf(n) === shardOf((ws.deserializeAttachment() as Att).n) ? this.getKey(n) : await this.shard(n).getKey(n); } catch { /* as offline */ }
    reply(k ? { ok: true, ...k } : { ok: false, code: 'offline', cause: CAUSE.offline });
  }

  getKey(number: string): { id: string; ek: string; es: string } | null {
    const ws = this.phone(number);
    if (!ws) return null;
    const a = ws.deserializeAttachment() as Att;
    return { id: a.id!, ek: a.ek!, es: a.es! };
  }

  // ---- connections end --------------------------------------------------------------------------------------------
  /** Tell the phone why, close, and move its counters to the shard's totals. */
  drop(ws: WebSocket, code: keyof typeof CLOSE, said?: string) {
    try { ws.send(JSON.stringify({ t: 'error', code: said || code, text: TEXT[said || code] || TEXT[code], fatal: true })); } catch { /* gone */ }
    this.fold(ws);
    try { ws.close(CLOSE[code], said || code); } catch { /* gone */ }
  }

  fold(ws: WebSocket) {
    let att: Att;
    try { att = ws.deserializeAttachment() as Att; } catch { return; }
    if (!att || att.gone) return;
    att.gone = true;
    try { ws.serializeAttachment(att); } catch { /* closed */ }
    if (att.st !== 1) return;
    const late = att.p.length;                       // texts still waiting when their sender left
    const fail = { ...att.fc }; if (late) fail.timeout = (fail.timeout || 0) + late;
    this.bump({ sent: att.s, fail });
  }

  bump(d: { joins?: number; sent?: number; fail?: Record<string, number> }) {
    const t = this.totals();
    t.joins += d.joins || 0; t.sent += d.sent || 0;
    for (const [k, v] of Object.entries(d.fail || {})) t.fail[k] = (t.fail[k] || 0) + v;
    this.ctx.storage.kv.put('tot', t);
  }

  totals(): Totals { return (this.ctx.storage.kv.get('tot') as Totals | undefined) ?? { joins: 0, sent: 0, fail: {} }; }

  async webSocketClose(ws: WebSocket, code: number, reason: string) {
    this.fold(ws);
    try { ws.close(code === 1005 || code === 1006 ? 1000 : code, reason); } catch { /* already closed */ }
    await this.ensureAlarm(this.cfg.limits.reportSec);
  }

  async webSocketError(ws: WebSocket) {
    this.fold(ws);
    await this.ensureAlarm(this.cfg.limits.reportSec);
  }

  // ---- the alarm: sweep sockets that never joined, tell the control object the counts ------------------------------
  async ensureAlarm(seconds: number) {
    const want = Date.now() + seconds * 1000;
    if (!this.alarmAt) this.alarmAt = (await this.ctx.storage.getAlarm()) ?? -1;
    if (this.alarmAt > 0 && this.alarmAt <= want) return;
    this.alarmAt = want;
    await this.ctx.storage.setAlarm(want);
  }

  async alarm() {
    this.alarmAt = -1;
    const now = Date.now(), L = this.cfg.limits;
    let waiting = 0;
    for (const ws of this.ctx.getWebSockets()) {
      const a = ws.deserializeAttachment() as Att;
      if (a.st !== 0 || a.gone) continue;
      if (now - a.at >= L.joinSec * 1000) this.drop(ws, 'slow_join'); else waiting++;
    }
    await this.sync();
    if (waiting) await this.ensureAlarm(L.joinSec + 1);
  }

  /** The cumulative counts of this shard: closed connections (storage) plus the open ones (their attachments). */
  counts() {
    const t = this.totals(), tot: Totals = { joins: t.joins, sent: t.sent, fail: { ...t.fail } };
    let conns = 0;
    const hot: [string, number, number][] = [];                         // number, texts sent, texts refused by the rate limit
    for (const ws of this.ctx.getWebSockets()) {
      const a = ws.deserializeAttachment() as Att;
      if (a.st !== 1 || a.gone) continue;
      conns++;
      tot.sent += a.s;
      for (const [k, v] of Object.entries(a.fc)) tot.fail[k] = (tot.fail[k] || 0) + v;
      if (a.l > 0 || a.s >= 30) hot.push([a.n, a.s, a.l]);
    }
    hot.sort((x, y) => y[2] - x[2] || y[1] - x[1]);
    return { conns, tot, hot: hot.slice(0, 20) };
  }

  /** One more text or join. Every REPORT_EVERY of them the control object is told at once. */
  tick() { if (++this.since >= REPORT_EVERY) { this.since = 0; this.ctx.waitUntil(this.sync()); } }

  async sync() {
    this.since = 0;
    const idx = await this.index();
    if (idx === null) return;
    try {
      const res = await this.env.CONTROL.get(this.env.CONTROL.idFromName('control')).report(idx, this.counts(), this.cfg.version);
      if (res.cfg) this.apply(res.cfg);
    } catch { /* the next alarm tells it */ }
  }

  /** "100".."999": written at the first connection, since an object does not know its own name. */
  async index(): Promise<string | null> { return (this.ctx.storage.kv.get('idx') as string | undefined) ?? null; }

  // ---- called by the control object -------------------------------------------------------------------------------
  /** A new configuration. Takes effect at once: the kill switch and bans close connections. */
  apply(cfg: Config) {
    if (!this.ctx.storage.kv.get('idx') && cfg.idx) this.ctx.storage.kv.put('idx', cfg.idx);
    this.cfg = cfg;
    this.ctx.storage.kv.put('cfg', cfg);
    for (const ws of this.ctx.getWebSockets()) {
      const a = ws.deserializeAttachment() as Att;
      if (a.gone) continue;
      if (cfg.kill) this.drop(ws, 'off');
      else if (cfg.bans.includes(a.n)) this.drop(ws, 'banned');
    }
    return this.counts();
  }

  /** What the admin page shows of one number: counters and connection time. No texts, no addresses, no recipients. */
  info(number: string) {
    const ws = this.phone(number);
    if (!ws) return { connected: false, banned: this.cfg.bans.includes(number) };
    const a = ws.deserializeAttachment() as Att;
    return { connected: true, banned: false, since: a.at, sent: a.s, failed: a.f, limited: a.l, waiting: a.p.length, key: a.id };
  }

  /** Local runs only (DEV): the identity of this instance in memory, to see that the object was built again. */
  bootId() { return this.env.DEV ? this.boot : ''; }
}
