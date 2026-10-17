# Deploying the relay (for the owner)

Nothing here has been run yet: the relay has only been started with `wrangler dev`. Read the steps once before
starting; steps 2 to 6 can be done in one sitting of about 20 minutes.

You need: the Cloudflare account on the Workers Paid plan, a domain on that account (for example `example.com`; the
relay becomes `relay.example.com`), Node 20 or later, this folder.

## 1. Install and log in

```
cd myna/relay
npm install
npx wrangler login          # opens the browser
npx wrangler whoami
```

## 2. Edit `wrangler.jsonc`

Add the host name and switch the `workers.dev` address off (Access in step 6 protects the host name you name there):

```jsonc
  "workers_dev": false,
  "routes": [{ "pattern": "relay.example.com", "custom_domain": true }],
```

Set in `"vars"`:

```jsonc
    "TURNSTILE_SITEKEY": "<site key from step 3>",
    "ALLOWED_ORIGINS": "https://<the host of the phone page>",
    "ACCESS_TEAM_DOMAIN": "https://<team>.cloudflareaccess.com",
    "ACCESS_AUD": "<AUD tag from step 6>"
```

Leave `ADMIN_SECRET` unset in production. Then the admin page answers 403 to everyone until Access is set up: the
relay is safe to deploy before step 6.

Do not add an `"observability"` block and do not leave `wrangler tail` running: Cloudflare's request logs would hold
the address and the URL of every join, and the URL contains the number. The Worker itself logs nothing.

## 3. Turnstile (the person check at the join)

Dashboard: **Turnstile > Add widget**. Name it, add the host name of the phone page, mode "Managed". Copy the site
key (into `wrangler.jsonc`, and the page uses it automatically: the relay sends it in the challenge) and the secret
key (next step).

Test keys from Cloudflare's documentation, for trying things without a widget: site key `1x00000000000000000000AA`
(always passes) with secret `1x0000000000000000000000000000000AA`; `2x00000000000000000000AB` with
`2x0000000000000000000000000000000AA` always fails; secret `3x0000000000000000000000000000000AA` answers "token
already spent". The test site keys produce the token `XXXX.DUMMY.TOKEN.XXXX`. `TURNSTILE_SECRET=off` (the local
default in `.dev.vars.example`) switches the check off.

## 4. Secrets

```
npx wrangler secret put TURNSTILE_SECRET        # paste the widget's secret key
openssl rand -base64 32                         # copy the output
npx wrangler secret put TICKET_SECRET           # paste it
```

`TICKET_SECRET` signs the 12-hour tickets that let a phone reconnect without a new person check. Changing it only
means every phone does the check once more. (`wrangler secret put` before the first deploy creates the Worker; say yes.)

## 5. Deploy

```
npx wrangler deploy
curl https://relay.example.com/info             # {"v":1,"min":1,"digits":12,"services":[{"n":"3246",...}]}
curl -i https://relay.example.com/admin         # 403 until step 6 is done
```

The first deploy creates the two Durable Object classes (`Shard`, `Control`, both SQLite-backed, migration `v1`).

## 6. The admin page behind Cloudflare Access

Dashboard: **Zero Trust > Access controls > Applications > Add an application > Self-hosted**.
- Application domain: `relay.example.com`, path `admin` (this covers `/admin` and `/admin/api/...`).
- Policy: Allow, Include > Emails > your address. Session duration as you like.
- After saving: **Configure > Additional settings > Application Audience (AUD) Tag**: copy it into `ACCESS_AUD`. Your
  team domain (Zero Trust > Settings) goes into `ACCESS_TEAM_DOMAIN`, with `https://` in front.
- `npx wrangler deploy` again.

Open `https://relay.example.com/admin`: Access asks you to log in, then the page shows. The Worker checks Access's
signed header on every admin request by itself, so the page stays closed even if the Access application is deleted
by mistake. Check from a private window that `/admin` and `/admin/api/state` do not open without the login.

## 7. Billing alert

Dashboard: **Manage Account > Billing > Billable Usage > Create budget alert**. Name, a threshold in USD (for example
10), your e-mail. Cloudflare says these alerts are "informational only": they **do not stop anything**. The stop is
the kill switch on the admin page (texts and connections end), and step 10 (everything ends).

## 8. What the phone page must do

The phone page is `myna/web` of this repository; it does all of this already except the Turnstile widget (point 3).

0. The phone's signal: `client/cell.js` posts `{t:'cell_state', up}` to the worker (PROTOCOL.md section 7); the
   page's worker passes it to the phone.
1. The page uses `client/cell.js` of this folder (`myna/web/serve.py` serves it as `/cell.js`), and its worker reports
   the phone's answer to an incoming text (`cell_in_result`); without that no text is ever "sent".
2. It calls `cellLink(worker, () => A.emu, report, { url: 'wss://relay.example.com', onState, turnstile })`.
   `link.number` is `''` at first: the number comes with `onState` (`link.format(n)` writes it as `1234 5678 9012`).
   `state`: `online` = service; `offline`, `connecting` = no service; `stopped` = say why (`text`).
3. `turnstile(sitekey)` must return a promise of a token: load `https://challenges.cloudflare.com/turnstile/v0/api.js`,
   render the widget with the site key it is given, resolve with the token. The page passes `turnstile: null` now: with
   a site key set here, its join is refused until this is written.
4. Content security policy: `connect-src 'self' wss://relay.example.com`; for Turnstile
   `script-src ... https://challenges.cloudflare.com` and `frame-src https://challenges.cloudflare.com`.
5. Do not send the page's `report` lines to a server in production (they hold the phone's own number).
6. Serve the page over https (the keys need a secure context).

## 9. What it costs

Prices read on 2026-10-13 (developers.cloudflare.com/durable-objects/platform/pricing): Workers Paid 5 USD a month,
which includes 1 million Durable Object requests and 400,000 GB-s of duration; then 0.15 USD per million requests and
12.50 USD per million GB-s. An incoming WebSocket message counts as 1/20 request; outgoing messages, protocol pings
and the automatic `ping`/`pong` answer are free; a call from one object to another is one request; an alarm is one
request; a connection that sits idle costs nothing (hibernation).

One text between two phones on different shards:

| what | requests |
|---|---|
| sender's `msg` frame (1/20) | 0.05 |
| sender's shard calls the receiver's shard | 1 |
| receiver's `ack` frame (1/20) | 0.05 |
| receiver's shard calls the sender's shard | 1 |
| **sum** | **2.1** |

- **One million texts = 2.1 million requests = about 0.32 USD.**
- First text to a new contact in a session: one key look-up more (1.05 requests).
- Counting for the admin page: a shard with news sets one alarm and makes one report per `reportSec` (60 s), 2
  requests. On a busy network this disappears in the texts. In the worst case (every text on its own shard in its own
  minute; 900 shards) it doubles the bill: **4.1 million requests = about 0.62 USD per million texts**.
- Duration: an object is awake for some tens of milliseconds per event. At 128 MB and an assumed 20 ms, two objects per
  text: 0.005 GB-s per text, 5,000 GB-s per million texts = about 0.06 USD, and the first 400,000 GB-s are included.
  The 20 ms is an estimate, not a measurement.
- Storage: a few rows per shard. Each alarm set and each report is one row written (50 million a month included, then
  1 USD per million): nothing until tens of millions of texts a month.
- A join: 1 Worker request (10 million a month included, then 0.30 USD per million), 1 request to the shard, the join
  frame, one Turnstile check (free), and the report: about 3 Durable Object requests.

So: **about 0.40 to 0.70 USD per million texts**, and the plan's included million requests carry the first 250,000
to 475,000 texts of each month. An attacker who gets past the limits pays you nothing but costs you this rate: a
flood of 100 million texts would be about 30 to 70 USD. The limits (12 texts a minute per connection, 30 joins a
minute per address) and the kill switch are what bound it; the budget alert tells you.

### Are the limits per phone or in total?

Both exist. **The rate limit is per connection, and one phone is one connection**: 2 texts right after joining, then
12 a minute (a bucket of 6). **Three ceilings are for the whole network**, kept by the control object and changed on
the admin page (the three gauges there show them):

| ceiling | default | when reached |
|---|---|---|
| texts per minute | 3,000 | texts are refused (cause 42) until the rate falls; nobody is disconnected |
| phones connected | 3,000 | new phones are turned away; connected ones stay and may reconnect; joins resume below it |
| texts per UTC day | 500,000 | texts are refused until the next UTC day |

Sized for "thousands of people in the first week": 3,000 phones at the same moment is far more than a few thousand
visitors produce (a visit is minutes long); 3,000 texts a minute is one text per connected phone per minute, which
keypad typing does not reach; 500,000 a day is 100 texts a day from each of 5,000 people.

What a week costs, above the 5 USD plan (which includes 1 million requests):

| case | texts | requests | cost |
|---|---|---|---|
| 5,000 people, each sends 20 texts and joins 10 times | 100,000 | 0.36 to 0.56 million | nothing |
| 5,000 people, each sends 500 texts | 2.5 million | 5.3 to 10.3 million | 0.65 to 1.40 USD |
| **the worst the ceilings allow** | 3.5 million (7 x 500,000) | see below | **about 20 USD** |

The worst week, item by item:
- Texts at the daily ceiling all week: 3.5 million x 2.1 to 4.1 requests = 7.4 to 14.4 million = 1.10 to 2.15 USD.
  (A ceiling is overshot by at most about 25 texts per busy shard, and each busy shard makes one extra report per 25
  texts: both under 5 per cent.)
- Refused texts and other junk frames. A connection may send 60 frames a minute before it is closed, and there are at
  most 3,000 connections: 180,000 frames a minute = 9,000 requests a minute (20 frames are one request) = 90.7 million
  requests a week = 13.60 USD. This is the largest item; lowering "Frames per minute, one phone" lowers it in proportion.
- Duration for those frames, at an assumed 2 ms each: 1.8 billion x 0.002 s x 0.125 GB = 454,000 GB-s; 400,000 are
  included: under 1 USD. With the texts' duration: under 2 USD.
- Sum: about 17 to 18 USD; call it **20 USD for the worst week, 80 to 90 USD for the worst month**.

**Not bounded by any ceiling: join attempts.** Each costs about one Worker request and one or two object requests,
0.60 to 0.80 USD per million. One address is limited to 30 a minute (43,200 a day, about 3 cents); someone with a
thousand addresses could cost about 30 USD a day. Against that: the kill switch does not help (attempts still arrive);
a WAF rate limiting rule or "Under Attack" mode on the relay's host name in the Cloudflare dashboard does, and
`npx wrangler delete` ends it. The budget alert of step 7 is what tells you.

## 10. Switching it off

- For now: the kill switch on the admin page. Phones show no service. Each open page asks again every 3 to 5
  minutes, and each try is one Worker request and one request to its shard, which refuses it.
- For good: `npx wrangler delete` removes the Worker, both object classes and their storage. Then delete the Access
  application (step 6), the Turnstile widget (step 3) and the DNS record of `relay.example.com` if one is left.
- To come back: steps 5 and 6 again. Numbers are not lost: they live in the browsers.

## 11. Not covered by the platform

- **Connections per address** are not limited, only join attempts per address and minute (30, in `wrangler.jsonc`,
  counted per Cloudflare location, not exact). A limit on simultaneous connections would need the relay to remember
  addresses, which it does not do. A WAF rate limiting rule on `/ws` can be added in the dashboard as a second brake.
- A barred number comes back with a new key. A bar is a speed bump: Turnstile and the join limit are the real brakes.
