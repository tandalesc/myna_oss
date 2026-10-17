# relay: the text-message network of Myna's phone page

A Cloudflare Worker with Durable Objects that carries text messages between phones running in browsers. Each browser
gets a 12-digit number made from its own identity key (ECDSA P-256, kept in the browser); a phone's SMS-SUBMIT goes
through the relay, end-to-end encrypted, to the phone with that number, and the receiving phone's acknowledgement
travels back to the sender. The relay keeps no text once it is delivered and no address. The page's side is
`client/cell.js`; the page is `myna/web` (its worker hands the texts to the modem stand-in's "host" cell network,
`native/emu_cell/cell.py`). Licence: MIT.

Nothing has been deployed: the relay has been run with `wrangler dev` only.

| file | what |
|---|---|
| `PROTOCOL.md` | every message, the join, error codes and RP causes, the encryption envelope, what is kept |
| `DEPLOY.md` | the steps to put it on Cloudflare, cost arithmetic, switching it off, what the page must do |
| `TWIN.md`, `vectors.json` | note on a Python twin of the routing rule; shared test vectors (TEST KEYS, published on purpose) |
| `src/index.ts` | the Worker: routes `/ws` to a shard, `/info`, `/admin` (Cloudflare Access or a shared secret) |
| `src/shard.ts` | one of 900 objects holding connections (WebSocket Hibernation API) |
| `src/control.ts` | the one control object: kill switch, pause, limits, bans, live counts |
| `src/proto.ts` | constants, numbers, signatures, tickets, the environment |
| `src/services.ts` | service numbers: echo `3246`; a disabled stub for an AI contact (`enabled: false`, calls nothing) |
| `src/admin.html` | the admin page |
| `client/cell.js` | the page's side: `cellLink(worker, emuSeconds, report, options)` |
| `test/run.mjs`, `test/lib.mjs` | the tests; they start `wrangler dev` themselves |
| `test/vectors.mjs` | writes `vectors.json`, or checks it with `--check` |
| `wrangler.jsonc` | the Worker's configuration; the production settings are empty here |
| `.dev.vars.example` | the secrets of a local run, as placeholders |

## Local run

Node 20 or later. Nothing leaves the machine.

```
cd myna/relay
npm install
cp .dev.vars.example .dev.vars        # then change the placeholders; .dev.vars is not in the repository
npm run dev                           # http://127.0.0.1:8787 ; admin page at /admin with ADMIN_SECRET as the bearer token
```

The page uses it when its server names it: `python3 myna/web/serve.py --relay ws://127.0.0.1:8787 --pyodide DIR`
(`myna/web/README.md`; the server also puts the relay into the page's content security policy).

## Tests

```
node test/run.mjs                     # about 90 s; --no-hibernation skips the 35 s hibernation test; --only TEXT
node test/vectors.mjs --check         # the vectors against client/cell.js
npx tsc --noEmit                      # type check
```

`test/run.mjs` starts two relays of its own on 127.0.0.1 (ports 8791 and 8793, inspector ports 9791 and 9793, stand-ins
for Turnstile and Access on 8795), each with its own state folder under `.wrangler/` and its own test secrets; it needs
no `.dev.vars` and no account. It writes its output to `test/last_run.txt`.

`node test/vectors.mjs` without `--check` makes a new `vectors.json` with new random test keys. The SMS-DELIVER of the
vectors is the same in `client/cell.js` and `native/emu_cell/cell.py` (`submit_to_deliver`).

## Must set for production

`wrangler.jsonc` and the secrets are empty or local in the repository. Before a public deploy (`DEPLOY.md`):

- **Turnstile**: `TURNSTILE_SITEKEY` in `wrangler.jsonc` and the widget's secret with `wrangler secret put
  TURNSTILE_SECRET` (step 3). Without them anyone can join without the person check. The page must also render the
  widget (`DEPLOY.md`, section 8, point 3): it does not yet.
- **Allowed origins**: `ALLOWED_ORIGINS`, the phone page's origin. Empty means any page may open a socket.
- **Access for /admin**: `ACCESS_TEAM_DOMAIN` and `ACCESS_AUD` (step 6), and no `ADMIN_SECRET` in production. Until
  then the admin page answers 403 to everyone.
- **Tickets**: `TICKET_SECRET` with `wrangler secret put` (step 4), a random value (`openssl rand -base64 32`).
- **Host name**: `workers_dev: false` and a route for the relay's host name (step 2).

## Open decisions (the owner's)

- The domain: the relay's host name and the phone page's host name (they go into `routes`, `ALLOWED_ORIGINS`, the
  page's content security policy and its relay address).
- The Cloudflare account (Workers Paid plan) that runs it, and its budget alert (step 7).
- The Turnstile widget and its site key.
