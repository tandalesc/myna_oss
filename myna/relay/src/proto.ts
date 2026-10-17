// proto.ts: what the relay and its clients agree on (PROTOCOL.md is the written form). No state here.
// SPDX-License-Identifier: MIT

export const VERSION = 1;                 // the protocol version of this relay
export const MIN_VERSION = 1;             // the oldest client version it still serves
export const NUMBER_DIGITS = 12;
export const SHARDS = 900;                // the first three digits of a number (100 to 999) choose the object

// Error codes and the RP cause (3GPP TS 24.011 table 8.4) the client gives the phone for each.
export const CAUSE: Record<string, number> = {
  unknown: 1,        // unassigned number: not a number of this network
  banned: 8,         // operator determined barring
  refused: 21,       // short message transfer rejected (the receiving phone refused, no cause given)
  offline: 27,       // destination out of order: the number is not connected
  off: 38,           // network out of order: the kill switch, or no connection to the relay
  error: 38,         // the relay failed inside
  timeout: 41,       // temporary failure: no acknowledgement in time
  rate: 42,          // congestion: rate limited
  busy: 42,          // congestion: too many unacknowledged messages
  net_rate: 42,      // congestion: the whole network is over its texts-per-minute ceiling
  net_day: 42,       // congestion: the whole network has used up its texts for this UTC day
  too_big: 111,      // protocol error, unspecified
  bad_frame: 111,
  unsupported: 69,   // requested facility not implemented
};

export const CLOSE = { update: 4000, bad_join: 4001, replaced: 4002, off: 4003, banned: 4004, paused: 4005, flood: 4006, full: 4007, slow_join: 4008, turnstile: 4009, bad_number: 4010, origin: 4011 } as const;

export const TEXT: Record<string, string> = {
  update: 'This page is too old for the network. Reload the page to update it.',
  bad_number: 'Not a number of this network.',
  bad_join: 'The key does not belong to this number.',
  replaced: 'This number was connected from another tab or device.',
  off: 'The network is switched off.',
  banned: 'This number is barred.',
  paused: 'The network takes no new phones at the moment.',
  flood: 'Too many messages. Disconnected.',
  full: 'This part of the network is full.',
  slow_join: 'The phone did not join in time.',
  turnstile: 'The check that you are a person failed.',
  origin: 'This page may not use the network.',
};

export interface Limits {
  perMin: number;        // texts per minute of one connection (the refill rate of its bucket)
  burst: number;         // the size of the bucket
  joinTokens: number;    // what a new connection starts with (small: reconnecting must not refill the bucket)
  maxBody: number;       // bytes of one payload
  maxPending: number;    // texts of one connection that wait for the far phone's acknowledgement
  pendSec: number;       // how long one may wait
  framesPerMin: number;  // frames of any kind per connection; more closes it
  maxConns: number;      // connections of one shard
  joinSec: number;       // time to answer the challenge
  reportSec: number;     // a shard with news tells the control object after this time
  // Ceilings for the WHOLE network, kept by the control object (0: none). They bound the bill.
  netPerMin: number;     // texts per minute; above it texts are refused (cause 42) until the rate falls; nobody is disconnected
  maxPhones: number;     // connected phones; above it new joins are turned away (as with "pause") until the count falls
  dayMax: number;        // texts per UTC day; when reached, texts are refused until the next UTC day
}

/** What the control object has switched on by itself because a ceiling is reached. */
export interface Hold { texts: boolean; joins: boolean; day: boolean; }

export const DEFAULT_LIMITS: Limits = { perMin: 12, burst: 6, joinTokens: 2, maxBody: 1024, maxPending: 8, pendSec: 45, framesPerMin: 60, maxConns: 5000, joinSec: 120, reportSec: 60, netPerMin: 3000, maxPhones: 3000, dayMax: 500000 };

export interface Config { version: number; kill: boolean; pause: boolean; limits: Limits; bans: string[]; idx?: string; hold?: Hold; }
export const DEFAULT_CONFIG: Config = { version: 0, kill: false, pause: false, limits: DEFAULT_LIMITS, bans: [] };

export const enc = new TextEncoder();

export function b64(bytes: ArrayBuffer | Uint8Array): string {
  const u = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let s = '';
  for (let i = 0; i < u.length; i++) s += String.fromCharCode(u[i]);
  return btoa(s);
}

export function unb64(text: unknown, max = 4096): Uint8Array | null {
  if (typeof text !== 'string' || text.length > max || !/^[A-Za-z0-9+/]*={0,2}$/.test(text)) return null;
  try {
    const s = atob(text), u = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
    return u;
  } catch { return null; }
}

/** The number of an identity key: SHA-256 of the raw public key (65 bytes, uncompressed P-256 point), the first 8 bytes
 *  as a big-endian integer v; the number is 10^11 + (v modulo 9 * 10^11): 12 digits, the first never 0. */
export async function numberOf(rawPublicKey: Uint8Array): Promise<string> {
  const h = new Uint8Array(await crypto.subtle.digest('SHA-256', rawPublicKey));
  let v = 0n;
  for (let i = 0; i < 8; i++) v = (v << 8n) | BigInt(h[i]);
  return (100000000000n + v % 900000000000n).toString();
}

export const isNumber = (n: unknown): n is string => typeof n === 'string' && /^[1-9]\d{11}$/.test(n);
export const shardOf = (n: string) => n.slice(0, 3);          // "100".."999"

export const joinText = (host: string, number: string, nonce: string) => enc.encode(`myna-relay/join/1\n${host}\n${number}\n${nonce}`);
export const encText = (number: string, ek: string) => enc.encode(`myna-relay/enc/1\n${number}\n${ek}`);

/** True when `sig` (raw r||s, 64 bytes) is the ECDSA P-256 / SHA-256 signature of `data` by the raw public key. */
export async function verify(rawPublicKey: Uint8Array, sig: Uint8Array, data: Uint8Array): Promise<boolean> {
  if (rawPublicKey.length !== 65 || rawPublicKey[0] !== 4 || sig.length !== 64) return false;
  try {
    const key = await crypto.subtle.importKey('raw', rawPublicKey, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
    return await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, sig, data);
  } catch { return false; }
}

async function hmac(secret: string, text: string): Promise<string> {
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return b64(await crypto.subtle.sign('HMAC', key, enc.encode(text)));
}

/** A ticket lets a phone that passed the person check join again without a new one, until `exp` (seconds). */
export async function makeTicket(secret: string, number: string, exp: number): Promise<string> {
  return `${exp}.${await hmac(secret, `ticket/1/${number}/${exp}`)}`;
}

export async function checkTicket(secret: string, number: string, ticket: unknown, now: number): Promise<boolean> {
  if (!secret || typeof ticket !== 'string' || ticket.length > 80) return false;
  const dot = ticket.indexOf('.'), exp = Number(ticket.slice(0, dot));
  if (dot < 1 || !Number.isInteger(exp) || exp < now) return false;
  const want = await makeTicket(secret, number, exp);
  let diff = want.length ^ ticket.length;
  for (let i = 0; i < want.length; i++) diff |= want.charCodeAt(i) ^ ticket.charCodeAt(i % ticket.length);
  return diff === 0;
}

export interface Env {
  SHARD: DurableObjectNamespace<import('./shard').Shard>;
  CONTROL: DurableObjectNamespace<import('./control').Control>;
  JOIN_LIMIT?: { limit(o: { key: string }): Promise<{ success: boolean }> };
  DEV?: string;
  TURNSTILE_SECRET?: string;
  TURNSTILE_SITEKEY?: string;
  TURNSTILE_VERIFY_URL?: string;
  TICKET_SECRET?: string;
  ADMIN_SECRET?: string;
  ALLOWED_ORIGINS?: string;
  ACCESS_TEAM_DOMAIN?: string;
  ACCESS_AUD?: string;
  ACCESS_CERTS_URL?: string;
  ANTHROPIC_API_KEY?: string;
}
