// control.ts: the one object that holds what the admin page sets and shows.
//   kept: the configuration (kill switch, pause, limits, barred numbers) and the live picture (per shard: connections and
//   cumulative counters; per minute: texts sent and failed; the numbers that ran into the rate limit).
// Shards get the configuration pushed when it changes, and again with the answer to each of their reports.
// SPDX-License-Identifier: MIT
import { DurableObject } from 'cloudflare:workers';
import { Config, DEFAULT_CONFIG, DEFAULT_LIMITS, Env, Hold, Limits, isNumber, shardOf } from './proto';

interface Totals { joins: number; sent: number; fail: Record<string, number>; }
interface ShardRow { conns: number; tot: Totals; at: number; }
interface Minute { m: number; sent: number; failed: number; joins: number; fail: Record<string, number>; }
interface Live { shards: Record<string, ShardRow>; minutes: Minute[]; hot: Record<string, [number, number, number]>;
  recent?: [number, number][];           // [second, texts sent] of the last WINDOW_S seconds: the network's rate
  day?: { d: number; sent: number }; }   // texts sent in the UTC day d (days since 1970)

const MINUTES = 60, HOT = 300, PUSH_AT_ONCE = 25, PUSH_PER_RUN = 500, WINDOW_S = 60, WATCH_S = 15;

export class Control extends DurableObject<Env> {
  cfg: Config;
  live: Live;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    const kv = ctx.storage.kv;
    this.cfg = (kv.get('cfg') as Config | undefined) ?? { ...DEFAULT_CONFIG, version: 1 };
    this.cfg.limits = { ...DEFAULT_LIMITS, ...this.cfg.limits };       // a limit added by a later version gets its default
    this.live = (kv.get('live') as Live | undefined) ?? { shards: {}, minutes: [], hot: {} };
  }

  forShard(idx: string): Config { return { ...this.cfg, idx, bans: this.cfg.bans.filter(n => shardOf(n) === idx) }; }

  minute(now: number): Minute {
    const m = Math.floor(now / 60000), list = this.live.minutes;
    if (!list.length || list[list.length - 1].m !== m) { list.push({ m, sent: 0, failed: 0, joins: 0, fail: {} }); while (list.length > MINUTES) list.shift(); }
    return list[list.length - 1];
  }

  take(idx: string, data: { conns: number; tot: Totals; hot: [string, number, number][] }, now: number) {
    const prev = this.live.shards[idx]?.tot ?? { joins: 0, sent: 0, fail: {} }, b = this.minute(now);
    const sent = Math.max(0, data.tot.sent - prev.sent);
    b.sent += sent;
    if (sent) { this.window(now).push([Math.floor(now / 1000), sent]); this.today(now).sent += sent; }
    b.joins += Math.max(0, data.tot.joins - prev.joins);
    for (const [k, v] of Object.entries(data.tot.fail)) {
      const d = Math.max(0, v - (prev.fail[k] || 0));
      if (d) { b.failed += d; b.fail[k] = (b.fail[k] || 0) + d; }
    }
    this.live.shards[idx] = { conns: data.conns, tot: data.tot, at: now };
    for (const [n, sent, limited] of data.hot) this.live.hot[n] = [sent, limited, now];
    const keys = Object.keys(this.live.hot);
    if (keys.length > HOT) for (const n of keys.sort((a, c) => this.live.hot[a][2] - this.live.hot[c][2]).slice(0, keys.length - HOT)) delete this.live.hot[n];
    this.ctx.storage.kv.put('live', this.live);
  }

  /** A shard's report: its cumulative counters. The answer carries the configuration when the shard's is old. */
  report(idx: string, data: { conns: number; tot: Totals; hot: [string, number, number][] }, have: number): { cfg: Config | null } {
    if (!/^[1-9]\d\d$/.test(idx)) return { cfg: null };
    this.take(idx, data, Date.now());
    this.ctx.waitUntil(this.watch());
    return { cfg: have === this.cfg.version ? null : this.forShard(idx) };
  }

  // ---- the ceilings of the whole network --------------------------------------------------------------------------
  window(now: number) { const from = Math.floor(now / 1000) - WINDOW_S; return this.live.recent = (this.live.recent ?? []).filter(e => e[0] > from); }
  today(now: number) { const d = Math.floor(now / 86400000); if (this.live.day?.d !== d) this.live.day = { d, sent: 0 }; return this.live.day!; }
  phones() { let n = 0; for (const r of Object.values(this.live.shards)) n += r.conns; return n; }

  gauges(now: number) {
    const L = this.cfg.limits;
    return { rate: this.window(now).reduce((n, e) => n + e[1], 0), netPerMin: L.netPerMin, phones: this.phones(), maxPhones: L.maxPhones, day: this.today(now).sent, dayMax: L.dayMax,
      hold: this.cfg.hold ?? { texts: false, joins: false, day: false } };
  }

  /** Compare the counts with the ceilings; when a hold starts or ends, tell every shard. While a hold is on, or texts
   *  were counted in the last minute, the alarm looks again every WATCH_S seconds (the rate falls without any report). */
  async watch() {
    const now = Date.now(), g = this.gauges(now);
    const want: Hold = { texts: g.netPerMin > 0 && g.rate > g.netPerMin, joins: g.maxPhones > 0 && g.phones >= g.maxPhones, day: g.dayMax > 0 && g.day >= g.dayMax };
    const have = g.hold;
    const again = want.texts || want.day || g.rate > 0;
    if (again && !(await this.ctx.storage.getAlarm())) await this.ctx.storage.setAlarm(now + WATCH_S * 1000);
    if (want.texts === have.texts && want.joins === have.joins && want.day === have.day) return;
    this.cfg.hold = want;
    await this.changed(Object.keys(this.live.shards));
  }

  // ---- the admin page ---------------------------------------------------------------------------------------------
  state() {
    const now = Date.now(), cur = Math.floor(now / 60000);
    let phones = 0, shards = 0;
    for (const r of Object.values(this.live.shards)) { phones += r.conns; if (r.conns) shards++; }
    const last = this.live.minutes.find(x => x.m === cur - 1), current = this.live.minutes.find(x => x.m === cur);
    return {
      now, cfg: this.cfg, phones, shards, gauges: this.gauges(now),
      lastMinute: last ?? { m: cur - 1, sent: 0, failed: 0, joins: 0, fail: {} },
      thisMinute: current ?? { m: cur, sent: 0, failed: 0, joins: 0, fail: {} },
      minutes: this.live.minutes,
      hot: Object.entries(this.live.hot).map(([n, v]) => ({ n, sent: v[0], limited: v[1], at: v[2] })).sort((a, b) => b.limited - a.limited || b.sent - a.sent).slice(0, 50),
      busiest: Object.entries(this.live.shards).filter(([, r]) => r.conns).sort((a, b) => b[1].conns - a[1].conns).slice(0, 10).map(([idx, r]) => ({ idx, conns: r.conns, at: r.at })),
      pushing: ((this.ctx.storage.kv.get('pushq') as string[] | undefined) ?? []).length,
    };
  }

  async set(patch: { kill?: boolean; pause?: boolean; limits?: Partial<Limits> }) {
    if (typeof patch.kill === 'boolean') this.cfg.kill = patch.kill;
    if (typeof patch.pause === 'boolean') this.cfg.pause = patch.pause;
    if (patch.limits && typeof patch.limits === 'object') {
      for (const k of Object.keys(DEFAULT_LIMITS) as (keyof Limits)[]) {
        const v = (patch.limits as any)[k];
        if (typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1e6) this.cfg.limits[k] = v;
      }
      const L = this.cfg.limits;
      L.maxBody = Math.min(Math.max(L.maxBody, 64), 8192); L.maxConns = Math.min(Math.max(L.maxConns, 1), 30000);
      L.netPerMin = Math.floor(L.netPerMin); L.maxPhones = Math.floor(L.maxPhones); L.dayMax = Math.floor(L.dayMax);
      L.reportSec = Math.max(L.reportSec, 5); L.joinSec = Math.max(L.joinSec, 5); L.pendSec = Math.max(L.pendSec, 5); L.maxPending = Math.min(L.maxPending, 64);
    }
    await this.changed(Object.keys(this.live.shards));      // every shard that ever reported; one that never did asks at its first connection
    await this.watch();                                     // a changed ceiling may start or end a hold
    return this.state();
  }

  async ban(number: string, on: boolean) {
    if (!isNumber(number)) return this.state();
    const had = this.cfg.bans.includes(number);
    if (on && !had) this.cfg.bans.push(number);
    if (!on && had) this.cfg.bans = this.cfg.bans.filter(n => n !== number);
    await this.changed([shardOf(number)]);
    return this.state();
  }

  async changed(shards: string[]) {
    this.cfg.version++;
    const kv = this.ctx.storage.kv;
    kv.put('cfg', this.cfg);
    const q = new Set([...((kv.get('pushq') as string[] | undefined) ?? []), ...shards]);
    kv.put('pushq', [...q]);
    await this.drain();
  }

  /** Push the configuration to the shards in the queue. What is left over goes on with the alarm. */
  async drain() {
    const kv = this.ctx.storage.kv;
    let q = (kv.get('pushq') as string[] | undefined) ?? [], done = 0;
    while (q.length && done < PUSH_PER_RUN) {
      const batch = q.slice(0, PUSH_AT_ONCE), failed: string[] = [], now = Date.now();
      await Promise.all(batch.map(async idx => {
        try { this.take(idx, await this.env.SHARD.get(this.env.SHARD.idFromName('s' + idx)).apply(this.forShard(idx)) as any, now); }
        catch { failed.push(idx); }
      }));
      done += batch.length;
      q = [...q.slice(batch.length), ...failed];
      kv.put('pushq', q);
      if (failed.length) break;
    }
    if (q.length) await this.ctx.storage.setAlarm(Date.now() + (done < PUSH_PER_RUN ? 2000 : 0));
  }

  async alarm() { await this.drain(); await this.watch(); }
}
