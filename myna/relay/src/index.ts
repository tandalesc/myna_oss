// index.ts: the Worker in front of the objects. It sends a phone's socket to its shard and serves the admin page.
// SPDX-License-Identifier: MIT
import { CLOSE, TEXT, VERSION, MIN_VERSION, Env, isNumber, shardOf, numberOf, unb64 } from './proto';
import { SERVICES } from './services';
import ADMIN from './admin.html';

export { Shard } from './shard';
export { Control } from './control';

const json = (o: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(o), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store', ...headers } });

/** A socket that only says why not, for refusals that need no object. */
function refuse(code: keyof typeof CLOSE): Response {
  const pair = new WebSocketPair();
  pair[1].accept();
  pair[1].send(JSON.stringify({ t: 'error', code, text: TEXT[code], v: VERSION, min: MIN_VERSION, fatal: true }));
  pair[1].close(CLOSE[code], code);
  return new Response(null, { status: 101, webSocket: pair[0] });
}

function originAllowed(req: Request, env: Env): boolean {
  const list = (env.ALLOWED_ORIGINS || '').split(',').map(s => s.trim()).filter(Boolean);
  return !list.length || list.includes(req.headers.get('origin') || '');
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (url.pathname === '/ws') {
      if (req.headers.get('upgrade')?.toLowerCase() !== 'websocket') return new Response('a WebSocket is expected here', { status: 426 });
      if (!originAllowed(req, env)) return refuse('origin');
      const v = Number(url.searchParams.get('v')), n = url.searchParams.get('n');
      if (!Number.isInteger(v) || v < MIN_VERSION || v > VERSION) return refuse('update');
      if (!isNumber(n)) return refuse('bad_number');
      if (env.JOIN_LIMIT) {
        // Counted by the platform per address and minute; the relay itself keeps no address.
        const { success } = await env.JOIN_LIMIT.limit({ key: req.headers.get('cf-connecting-ip') || 'none' });
        if (!success) return refuse('flood');
      }
      return env.SHARD.get(env.SHARD.idFromName('s' + shardOf(n))).fetch(req);
    }
    if (url.pathname === '/info') {
      return json({ v: VERSION, min: MIN_VERSION, digits: 12, services: SERVICES.filter(s => s.enabled).map(s => ({ n: s.number, name: s.name, notice: s.notice })) },
        200, { 'access-control-allow-origin': '*' });
    }
    if (url.pathname === '/admin' || url.pathname.startsWith('/admin/')) return admin(req, env, url);
    if (env.DEV && url.pathname === '/dev/boot') {
      const n = url.searchParams.get('n') || '';
      return json({ boot: isNumber(n) ? await env.SHARD.get(env.SHARD.idFromName('s' + shardOf(n))).bootId() : '' });
    }
    if (url.pathname === '/') {
      // Also the page to open once in a browser that must first accept a self-signed certificate (a local network trial).
      return new Response('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Relay</title>' +
        '<body style="font: 17px/1.5 system-ui, sans-serif; margin: 12vh auto; max-width: 30em; padding: 0 20px">' +
        '<h1 style="font-size: 22px">The text message network is reachable</h1><p>This browser accepts the relay\'s certificate. You can close this page and open the phone again.</p>',
        { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });
    }
    return new Response('not found\n', { status: 404 });
  },
};

// ---- the admin page and its interface ------------------------------------------------------------------------------
// Production: Cloudflare Access in front of /admin*; the Worker checks Access's signed header itself, so a request that
// did not come through Access is refused even if the Access application is removed by mistake.
// Local runs: the shared secret ADMIN_SECRET as a bearer token.
async function admin(req: Request, env: Env, url: URL): Promise<Response> {
  const access = !!(env.ACCESS_TEAM_DOMAIN && env.ACCESS_AUD);
  if (!access && !env.ADMIN_SECRET) return new Response('the admin page is not configured\n', { status: 403 });
  if (access) {
    if (!await accessOk(req, env)) return new Response('forbidden\n', { status: 403 });
  } else if (url.pathname !== '/admin' && url.pathname !== '/admin/') {
    if (!same(req.headers.get('authorization') || '', 'Bearer ' + env.ADMIN_SECRET)) return new Response('forbidden\n', { status: 403 });
  }
  if (url.pathname === '/admin' || url.pathname === '/admin/') {
    return new Response(ADMIN.replace('__MODE__', access ? 'access' : 'secret'), { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store', 'x-frame-options': 'DENY', 'referrer-policy': 'no-referrer' } });
  }
  const control = env.CONTROL.get(env.CONTROL.idFromName('control'));
  const what = url.pathname.slice('/admin/api/'.length);
  if (req.method === 'GET' && what === 'state') return json(await control.state());
  if (req.method === 'GET' && what === 'number') {
    const n = url.searchParams.get('n') || '';
    if (!isNumber(n)) return json({ error: 'not a number of this network' }, 400);
    return json({ n, ...(await env.SHARD.get(env.SHARD.idFromName('s' + shardOf(n))).info(n)) });
  }
  if (req.method === 'POST') {
    // A page of another site cannot make this request: it needs the bearer token, or (with Access) a JSON content type
    // that a cross-site form cannot send without a preflight this Worker never answers.
    if (!(req.headers.get('content-type') || '').startsWith('application/json')) return json({ error: 'JSON expected' }, 415);
    let body: any;
    try { body = await req.json(); } catch { return json({ error: 'JSON expected' }, 400); }
    if (what === 'set') return json(await control.set(body));
    if (what === 'ban') {
      // A number, or an identity key (base64): a key's number follows from the key, so barring the number bars the key.
      let n = String(body.number || '').replace(/\s/g, '');
      const key = unb64(body.key, 100);
      if (key && key.length === 65) n = await numberOf(key);
      if (!isNumber(n)) return json({ error: 'not a number of this network' }, 400);
      return json({ banned: n, ...(await control.ban(n, body.on !== false)) });
    }
  }
  return new Response('not found\n', { status: 404 });
}

function same(a: string, b: string): boolean {
  let d = a.length ^ b.length;
  for (let i = 0; i < b.length; i++) d |= b.charCodeAt(i) ^ a.charCodeAt(i % (a.length || 1));
  return d === 0;
}

let certs: { at: number; keys: any[] } | null = null;

/** The Access token of the request (header Cf-Access-Jwt-Assertion): RS256 by one of the team's keys, right audience,
 *  right issuer, not expired. */
async function accessOk(req: Request, env: Env): Promise<boolean> {
  try {
    const token = req.headers.get('cf-access-jwt-assertion') || '';
    const [h, p, s] = token.split('.');
    if (!h || !p || !s) return false;
    const dec = (t: string) => unb64(t.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((t.length + 3) % 4), 8192)!;
    const head = JSON.parse(new TextDecoder().decode(dec(h))), claims = JSON.parse(new TextDecoder().decode(dec(p)));
    if (head.alg !== 'RS256') return false;
    const team = env.ACCESS_TEAM_DOMAIN!.replace(/\/$/, '');
    const aud = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
    if (claims.iss !== team || !aud.includes(env.ACCESS_AUD) || !(claims.exp > Date.now() / 1000)) return false;
    if (!certs || Date.now() - certs.at > 3600_000 || !certs.keys.some(k => k.kid === head.kid)) {
      const res = await fetch(env.ACCESS_CERTS_URL || team + '/cdn-cgi/access/certs');
      certs = { at: Date.now(), keys: (await res.json() as any).keys || [] };
    }
    const jwk = certs.keys.find(k => k.kid === head.kid);
    if (!jwk) return false;
    const key = await crypto.subtle.importKey('jwk', jwk, { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
    return await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, dec(s), new TextEncoder().encode(h + '.' + p));
  } catch { return false; }
}
