# A Python twin of the routing rule (note only; not built)

For recorded two-phone runs that must repeat exactly, the relay cannot be used: when its answers arrive depends on the
host. A twin in Python would sit between two `Host` networks (`native/emu_cell/cell.py`) inside one test program and
apply the same rule on emulated time.

What the twin must do, and nothing more:

1. **Number**: `str(10**11 + int.from_bytes(sha256(raw_public_key).digest()[:8], 'big') % (9 * 10**11))` (12 digits, the
   first never 0). A test may also just
   give each phone a fixed 12-digit number; then no key is needed.
2. **Route** a text from `a` to `to`, in this order:
   - `to` is `3246`: accept (`result(n, True)`), then deliver the same SMS-SUBMIT back to `a` from `3246`.
   - `to` is not 12 digits starting with 1 to 9: refuse, cause 1.
   - `to` is not attached: refuse, cause 27.
   - else hand `submit_to_deliver(tpdu, EPOCH + receiver_emulated_seconds, address_field(a))` to the receiver with a
     `report` callback. `report(True, 0)`: `result(n, True)`. `report(False, cause)`: `result(n, False, cause or 21)`.
     The sender's answer comes only after the receiver's report: this is the relay's end-to-end acknowledgement.
3. **Limits**, if a test wants them: token bucket per sender (2 tokens at the start, 12 a minute, at most 6), refuse
   with cause 42. Size cap 1,024 bytes of payload, cause 111. Kill switch: cause 38.
4. Encryption, joins, tickets, bans and the admin side are not part of the twin: they do not change what a phone sees.

`vectors.json` holds the shared vectors: four test identities with their numbers and shards, the routing cases with
their results, the cause table, an SMS-SUBMIT with the SMS-DELIVER it becomes (checked here against both
`client/cell.js` and `native/emu_cell/cell.py`), the echo case, a join signature and one encryption envelope with fixed
salt and nonce. `node test/vectors.mjs --check` checks the JavaScript side. A twin should load the same file.

One difference to keep in mind: the relay's delays are real time and the twin's must be emulated time
(`port.later`), chosen once and written down, as the loopback network does with `ACCEPT_NS` and `DELIVER_NS`.
