# The relay's protocol, version 1

The relay is a "virtual cell network" for the phone page. A page connects with one WebSocket, proves which number it
has, and may then send texts to other connected numbers. The relay passes a text on at once or refuses it. It stores
no text and logs none.

Source of truth: `src/proto.ts` (constants), `src/shard.ts` (the server), `client/cell.js` (the page). Test vectors:
`vectors.json`.

## 1. Numbers

- A phone has an **identity key**: ECDSA on P-256, made in the browser, private part not extractable, kept in IndexedDB.
- Its **number** is 12 decimal digits and never starts with 0: SHA-256 of the raw public key (65 bytes, uncompressed
  point), the first 8 bytes read as a big-endian integer v; the number is 10^11 + (v modulo 9 * 10^11).
- The first 3 digits name the **shard** (`100` to `999`, 900 of them): the Durable Object that holds the connection.
- There is no account. The number lasts as long as the browser keeps the key. Cleared storage means a new number.
- Service numbers are short and answered by the relay itself: `3246` (echo). `252833` is reserved for a disabled stub.

## 2. Transport

- `GET /ws?n=NUMBER&v=1` with a WebSocket upgrade. `n` is the number the page will prove; it chooses the shard.
- Every frame is JSON text with a field `t` (the type), except the keep-alive: the page sends the text `ping` every
  45 s and gets `pong`. (Answered by the platform; the object is not woken and nothing is billed.) No `pong` within
  10 s: the page closes and reconnects.
- A refusal is always sent in band before the close: `{t:"error", code, text, fatal:true}`, then a close with a code
  from the table in section 7. `text` is a sentence for the user.
- `GET /info` (plain HTTP, any origin): `{v, min, digits, services}`.

## 3. Versions

- The page says its version twice: `v` in the URL and `v` in the `join` frame. The relay says `v` (its version) and
  `min` (the oldest it serves) in `challenge` and in an `update` error.
- A page older than `min` gets `{t:"error", code:"update", text:"This page is too old for the network. Reload the page
  to update it.", v, min, fatal:true}` and close code 4000. The page stops and does not reconnect.
- A change that old pages cannot ignore raises the version. New optional fields do not.
- Unknown frame types get `{t:"error", code:"bad_frame", re:TYPE, fatal:false}`; the connection stays.

## 4. Joining

```
page                                         relay (shard of the number)
 |  GET /ws?n=N&v=1  ----------------------->  |
 |  <------  {t:"challenge", v, min, relay, nonce, sitekey}
 |  {t:"join", v, id, sig, ek, es, ts?, ticket?}  ->
 |  <------  {t:"joined", v, n, ping, limits, services, ticket, ticketExp}
```

- `relay`: the host name the relay was reached under. The page checks that it is the host it connected to, and signs it.
  A page in the middle that passes the challenge of another relay on gets a signature that the real relay refuses.
- `nonce`: 16 random bytes, base64. Used once.
- `sitekey`: the Turnstile site key when the person check is on, else `""`.
- `id`: the identity public key (raw, base64). The relay checks that its number is `N`.
- `sig`: ECDSA P-256 / SHA-256 signature (raw r||s, 64 bytes, base64) over the UTF-8 text
  `myna-relay/join/1\n` + relay + `\n` + number + `\n` + nonce.
- `ek`: the **encryption key** (ECDH P-256 public key, raw, base64). `es`: the identity key's signature over
  `myna-relay/enc/1\n` + number + `\n` + ek.
- `ts`: a Turnstile token. Needed when `sitekey` is set and the page has no valid ticket.
- `ticket`: given in `joined`; valid 12 hours for this number only (`EXP.HMAC-SHA256(secret, "ticket/1/N/EXP")`). A page
  with a valid ticket joins again without a new person check, and may join while new joins are paused.
- `limits`: `{perMin, burst, maxBody, pendSec}` for the page's information. `services`: `[{n, name, notice}]`.
- A second connection for the same number replaces the first (`replaced`, 4002; the first page stops).
- A socket that does not join within `joinSec` (120 s) is closed (`slow_join`).

Failures: `bad_number`, `update`, `origin`, `flood` (join attempts per address), `off`, `banned`, `full`, `bad_join`
(any failed proof), `paused`, `turnstile`.

## 5. Texts

```
A's page          A's shard                 B's shard            B's page
 | msg ----------> |                          |                    |
 |                 | deliver(...)  ---------> | deliver ---------> |   (the phone's modem takes it)
 |                 | <---------  acked(...)   | <---------- ack    |
 | <---------- sent|                          |                    |
```

- `{t:"msg", id, to, enc, body}`: `id` an integer chosen by the page (unique among its waiting texts), `to` the
  destination digits, `enc` 0 or 1, `body` base64 of the payload (at most `maxBody` bytes, 1,024).
  **There is no sender field.** The relay takes the sender from the connection. Extra fields are ignored.
- `{t:"deliver", d, from, enc, body}` to the receiver; with `enc: 1` also `id`, `ek`, `es`: the sender's keys as it
  gave them at its join. `d` names the delivery (`FROM.ID`). `from` is the number the relay proved.
- `{t:"ack", d, ok:true}` or `{t:"ack", d, ok:false, cause}` from the receiver when its phone has taken or refused the
  text. `cause` is the RP cause of the phone (22 = its store is full).
- `{t:"sent", id, ok:true}` or `{t:"sent", id, ok:false, code, cause}` to the sender.
  **`ok:true` means the receiving phone's modem took the text.** It is sent only after the receiver's `ack`.
- An acknowledgement counts only when it comes from the number the text went to. The sender's shard remembers, per
  waiting text, the id, the destination and a deadline (`pendSec`, 45 s), in the connection's own state; this goes with
  the acknowledgement or the deadline. A page waits `pendSec + 5` s, then tells its phone cause 41.
- The destination is not connected: `sent` with `offline` at once. Nothing is kept for later.
- The payload is opaque to the relay. Plain payload: one byte kind, then data. Kind `01`: an SMS-SUBMIT of 3GPP TS
  23.040 exactly as the phone built it. The **receiver** turns it into an SMS-DELIVER: origin = the address field of
  `from` (type `81`), time stamp = the receiver's own emulated clock, validity period dropped
  (`submitToDeliver` in `cell.js`, `submit_to_deliver` in `native/emu_cell/cell.py`; both agree on `vectors.json`).

### Error codes and RP causes

`cause` is what the page gives the phone's modem (3GPP TS 24.011, table 8.4).

| code | cause | meaning |
|---|---|---|
| `unknown` | 1 unassigned number | not a 12-digit number and not a service |
| `banned` | 8 operator determined barring | the sender is barred |
| `refused` | 21 transfer rejected, or the receiver's own cause (22 store full) | the receiving phone or page refused it |
| `offline` | 27 destination out of order | the number is not connected |
| `off` | 38 network out of order | kill switch; also used by the page when it has no connection |
| `error` | 38 | the relay failed inside |
| `timeout` | 41 temporary failure | no acknowledgement in time (decided by the page) |
| `rate` | 42 congestion | rate limited |
| `busy` | 42 congestion | too many texts waiting for acknowledgement |
| `net_rate` | 42 congestion | the whole network is over its texts-per-minute ceiling; ends by itself |
| `net_day` | 42 congestion | the whole network has used up its texts for this UTC day |
| `unsupported` | 69 not implemented | for example an encrypted text to a service number |
| `too_big`, `bad_frame` | 111 protocol error | payload over the size cap, or not understood |

The relay cannot tell "never existed" from "not connected now": it has no list of numbers. Both are `offline`.

## 6. End-to-end encryption

`{t:"key", r, n}` asks for a number's keys; the answer is `{t:"key", r, n, ok:true, id, ek, es}`,
`{..., ok:true, service:true}` for a service number (send plain), or `{..., ok:false, code, cause}`.

The page checks, before it uses keys (asked for, or arriving with a `deliver`):
1. the number of `id` is the number in question,
2. `es` is `id`'s signature over the encryption key and the number,
3. `id` is the same identity key this browser saw for that number before (kept in IndexedDB as `pin:NUMBER`).
   A number has one identity key for ever, so a second one is always refused.

### The envelope (`enc: 1`)

```
01 | salt (16) | nonce (12) | AES-256-GCM ciphertext and tag
key  = HKDF-SHA256(ECDH(sender's encryption key, receiver's encryption key), salt, info)
info = "myna-relay/e2e/1\n" + FROM + "\n" + TO            (also the additional data of AES-GCM)
```

The plaintext is the plain payload of section 5. The page refuses (`ack` with cause 21) an envelope that does not
open, and a plain text from anything but a service number.

### What this protects, honestly

- The relay, Cloudflare and anyone on the wire cannot read a text between two phones, and cannot change it.
- A text that opens was made by someone holding the encryption key that the stamped number's identity key signed.
- **The relay sees who texts whom, when, and how long each text is.** It does not write this down, but it could.
- **12 digits are about 40 bits** (9 * 10^11 numbers). Someone with a few hundred dollars of computing can make an identity key whose
  number equals a victim's. With it they could join as that number while the victim is away, or (if they also run the
  relay) put themselves in the middle of a first contact. The pin of point 3 stops this for contacts a browser has
  already seen; it does not help at first contact. Do not use this network for anything that matters.
- No forward secrecy: the keys are long-lived. A stolen browser profile opens recorded traffic.
- No replay protection: the relay could deliver the same envelope twice.
- Texts to service numbers are not encrypted: the relay is the other end.
- The keys are not extractable through the Web Crypto API, but any script running on the page's origin can use them.

## 7. Close codes

4000 `update` · 4001 `bad_join` · 4002 `replaced` · 4003 `off` · 4004 `banned` · 4005 `paused` · 4006 `flood` (also
`too_big`, `bad_frame` as the reason) · 4007 `full` · 4008 `slow_join` · 4009 `turnstile` · 4010 `bad_number` ·
4011 `origin`.

The page does not reconnect after `update`, `replaced`, `banned`, `bad_join`, `bad_number`, `origin`. After `off`
(the kill switch) it asks again every 3 to 5 minutes (random). After `paused`, `full`, `flood`, `turnstile`,
`slow_join` it waits at least 30 s. Otherwise it backs off 1, 2, 4 ... 60 s with jitter, and tries at once when the
browser comes back on line or the tab becomes visible.

### The phone's signal

"Signal means connectivity to the relay." `cell.js` posts `{t:'cell_state', up: true|false}` to the phone's worker:
`up: true` at once when the link is `online`; `up: false` when the link has not been online for 4 s (a quick
reconnect does not move the bars), and at once when a phone starts without a link. Option `signal: false` turns it off.

## 8. Limits (all changed at run time on the admin page, except the last)

| name | default | what |
|---|---|---|
| `perMin` / `burst` | 12 / 6 | token bucket per connection: texts per minute, bucket size |
| `joinTokens` | 2 | tokens of a new connection (small, so that reconnecting does not refill the bucket) |
| `maxBody` | 1,024 | bytes of one payload |
| `maxPending` / `pendSec` | 8 / 45 | texts waiting for acknowledgement; how long |
| `framesPerMin` | 60 | frames of any kind per connection; more closes it (`flood`) |
| `maxConns` | 5,000 | connections per shard (`full`) |
| `joinSec` | 120 | time to answer the challenge |
| `reportSec` | 60 | delay of the counts on the admin page |
| `netPerMin` | 3,000 | WHOLE NETWORK: texts per minute (counted over the last 60 s). Above it every text is refused with `net_rate` until the rate falls. Nobody is disconnected. 0 = no ceiling |
| `maxPhones` | 3,000 | WHOLE NETWORK: connected phones. At it new joins get `paused` (a phone with a ticket may still reconnect); joins resume below it |
| `dayMax` | 500,000 | WHOLE NETWORK: texts per UTC day. When reached every text is refused with `net_day` until the next UTC day |
| join attempts per address | 30 a minute | `wrangler.jsonc`, counted by Cloudflare per location; fixed at deploy time |

The three ceilings are kept by the control object from the shards' reports. A shard reports after 25 texts or joins,
or after `reportSec`, whichever is first, so a ceiling acts within about 25 texts per busy shard; the phone count can
lag by up to `reportSec`. The control object looks again every 15 s while a hold is on.

## 9. Reserved, not built

- Frame types starting with `call.` (call set-up signalling: `call.offer`, `call.answer`, `call.ice`, `call.end`) and
  `room.` (private rooms). The relay answers `{t:"error", code:"unsupported", re:TYPE, fatal:false}`.
- Payload kinds other than `01`. A page refuses an unknown kind with cause 95.
- Envelope versions other than `01`.

## 10. What the relay keeps

| where | what | how long |
|---|---|---|
| a connection's state (socket attachment) | number, public keys, join time, rate buckets, counters (sent, failed by code, rate-limited), and per waiting text: id, destination, deadline | while connected; the destination until the acknowledgement or the deadline |
| a shard's storage | the configuration; summed counters of closed connections; its own index | for ever (a few hundred bytes) |
| the control object | configuration, barred numbers; per shard: connection count, cumulative counters; per minute for an hour: texts sent, failed (by code), joins; texts of the last 60 s and of the UTC day; up to 300 numbers that hit the rate limit or sent 30 or more texts in one connection, with their counts | for ever / one hour / until pushed out |

Never kept or logged by the relay's code: a text, a payload, a recipient (beyond the waiting entry above), an IP
address, a Turnstile token. The Worker contains no `console.log`. (Cloudflare itself sees addresses, as any host
does, and the join limiter counts by address inside Cloudflare.)
