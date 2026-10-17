# web: Myna's phone page

Myna in a browser tab. The page draws the phone from its skin (`native/devices/myna/skin/`) at its true size: the
simulator's screen lies in the skin's glass, every key area takes a finger or the mouse, a swipe on the face slides the
phone open and closed, and the computer's keyboard works too (arrows, Enter, 0-9, `*`, `#`, F1 / F2 soft keys; Space is
`#`, the space key of text, and opens the phone when the slide is closed; O slides it either way). The whole phone runs
in the tab: the WebAssembly build of the compiled core (`native/core`), and under Pyodide the simulator's device
models, the AT modem stand-in and the launcher, with Myna's ELF file loaded as the firmware.
Nothing runs on the server.

Texts go through the relay (`myna/relay`) to other phones on other pages, each with its own 12-digit number. Without a
relay the page uses the modem stand-in's loopback network: a text comes back to the phone that sent it, from the number
it was sent to. What the phone writes to its flash (messages, contacts, settings) is kept in the browser (IndexedDB)
and given back at the next start; "Start over" in the settings forgets it.

The first screen (the shelf) offers the phones, drawn closed at one scale (true size where it fits), each a button that
switches it on, with its colours under it; the slider shows Myna's standby in its glass (`icons/screen.png`). Its words and
the number use the phones' own font, Nunito (OFL, `myna/assets/fonts`, served as `fonts/`); the rest is the system's.

Getting a number: where the relay asks for its person check (Turnstile) and the page knows the site key (`config.json`,
`--turnstile`), picking a phone with a modem brings a sheet over the stage while the phone loads behind it, unless this
browser holds a valid ticket of an earlier join (12 hours; `link.ticket()` of `cell.js`). First the check (Cloudflare's
widget, loaded then; "Not now" leaves the phone without service, with "Get a number" in the settings), then the number,
in groups of four, with the state of its connection; "Go to your phone". The token is held until the relay asks for it;
one older than 250 s, used, or for another site key is not given, and the check comes again. A check the relay refuses
says so and offers another; a widget that cannot load says so. A ticket that has run out asks for the check again, naming
the number.

The welcome: after the first join of this browser's number the phone gets one text from the echo service (3246) that
names its number and says how to use it. `cell.js` makes it (option `welcome`; the relay sends nothing), offers it to the
phone until the phone takes it (once registered), and keeps a mark in its store (`welcomed:NUMBER`): no reconnection,
reload or new ticket brings another. Clearing the site's data gives a new number, and a new welcome.

A phone whose skin has a `body3d` block (both Myna phones) is drawn in 3D (`native/core/web/phone3d.js`, three.js), at
rest too: facing front at its true size, in the place the 2D layout gives it, with a long lens and the studio's light. The
slide and the flip's lid move as solids with the page's spring; a pressed key sinks; a finger finds its key on the face it
touches in 3D. A sideways drag across the face, a drag beside the phone or two fingers off the keys turn it round; let
go, it springs back to the front. The 2D drawing stays laid out under it (its geometry is the page's) and is the phone
where there is no WebGL, where the 3D module does not load, and with the setting "Flat drawing (2D)" (off by default,
kept in this browser). While the 3D phone is made the 2D one is not shown, unless that takes longer than 0.7 s.

The page is generic: it offers every device with a firmware of its own (a profile with `BOOT_ELF`) whose ELF file is
built. It fetches no stock firmware and no flash image. A skin with a `hinge` block in place of `slide` is a flip (Myna flip,
`native/devices/myna_flip`): the lid turns about the hinge (in 3D on its solid hinge, standing at its open angle when
open; in the flat drawing in CSS 3D), with a spring; swipe the closed lid up, tap the corner button or press O (Space
when closed) to open it. Its keys answer only with the lid open, and it starts open (the screen is on the lid).

    "hinge": {"closed": VIEW, "open": VIEW, "lid": SVG, "base": SVG, "barrel": SVG, "lid_back": SVG, "axis_y": Y, "open_deg": DEG}

`lid` (the lid's inner face, with the screen), `base` (the keypad half) and `barrel` (drawn last, static) are pictures in
the open view's frame; `lid_back`, the lid's outside in the closed view's frame, defaults to the closed view's picture;
`axis_y` is the hinge's line in the open picture (the closed picture is the bottom of the open one: closed y = open y -
(open height - closed height)). Without `lid` and `base` the open picture is cut at the line. `open_deg` is for 3D.

| file | what |
|---|---|
| `index.html`, `app.js`, `app.css` | the page: the shelf, the phone on its stage, the sheet that gives a number, the settings sheet. No inline script or style (strict content security policy) |
| `phone_worker.js` | the worker that holds the phone: Pyodide, the core, the launcher's `build()` and `run()`, paced against the host clock, resting while the phone sleeps; each key goes to the phone at the emulated time of the moment the page saw it, so a press lasts on the phone what it lasted on the page; it carries the texts of the "host" cell network |
| `manifest.webmanifest`, `icons/` | the home-screen web app; `icons/make.sh` draws the icons from `icons/icon.html` (the skin and a frame of Myna's standby) |
| `platform.txt` | the simulator's Python files a phone imports: the page's archive and the release take exactly these |
| `serve.py` | the development server (standard library only) |
| `test/` | the page in headless Chrome: `smoke.mjs` (loopback), `typing.mjs` (predictive text tapped on the keys), `flip.mjs` (the flip), `flip3d.mjs` (the flip in 3D: at rest, the lid, keys, turning), `phone3d.mjs` (the slider in 3D as on an iPhone: the slide, two thumbs, turning, the flat drawing, no WebGL), `relay.mjs` (two phones through a local relay) and `onboarding.mjs` (getting a number through a relay with the person check); `lib.mjs` |

The relay's client is not here: the server serves `myna/relay/client/cell.js` as `/cell.js`.

## Run it

Needs: Myna built, the compiled core built with its WebAssembly module, an unpacked Pyodide release (not in the
repository; the page was tested with Pyodide 314.0.7: `pyodide.js`, `pyodide.asm.mjs`, `pyodide.asm.wasm`,
`python_stdlib.zip`, `pyodide-lock.json`), Python 3.10 or later for the server.

```
make -C myna/firmware
sh native/core/build.sh                    # dbcore.wasm needs the wasm32-unknown-unknown standard library (DBCORE_WASM_SYSROOT)
python3 myna/web/serve.py --pyodide DIR    # http://127.0.0.1:8940/
python3 myna/web/serve.py --pyodide DIR --relay ws://127.0.0.1:8787     # with a local relay (myna/relay/README.md)
python3 myna/web/serve.py --pyodide DIR --relay ws://127.0.0.1:8787 --turnstile 1x00000000000000000000AA   # and its person check (test key)
```

`serve.py` listens on 127.0.0.1 by default. Options: `--port` (8940), `--host` (another address: a development server
only, never one on the internet), `--relay URL` (the relay the page uses; also put into the page's content security
policy; repeat it to allow more), `--turnstile SITEKEY` (the site key of the relay's person check, into `config.json`:
the page asks for the check before the first join; the policy allows Cloudflare's script and frame whenever there is a
relay), `--log` (print the lines a page sends when opened with `?log=1`: they contain the
phone's number), `--cert PEM` (https; a page on another host than this one needs it, because the relay's keys need a
secure context). `MYNA_PYODIDE` may name the Pyodide folder; `DBCORE_OUT` another build folder of the core.

Page addresses: `?p=myna` starts the phone at once; `?relay=URL` uses another relay (the server must allow it with
`--relay`); `?net=loopback` keeps a page with a relay on the loopback network (also a switch in the settings);
`?log=1` sends diagnostic lines to the server. For tests: `?keylog=1` puts each key's emulated time into the phone's
console lines; `?slow=N` makes the worker take N times as long for each step (a slow phone; DevTools slows a page's CPU
but not a worker's).

## Hosting it

The page is static: any server can give these files and the routes of `serve.py` (`devices.json`, `phone_src.json`,
`config.json`, `firmware/NAME.elf`, `skin/NAME/FILE`, `pycore.js`, `dbcore.wasm`, `pyodide/*`, `cell.js`, `fonts/*`,
`icons/*`). For a public
host:

- `python3 myna/web/serve.py --write DIR --pyodide PYODIDE --relay wss://relay.example.com --turnstile SITEKEY` writes
  the whole site into the empty folder DIR: every route as a file, `config.json` naming the relay and the site key, and
  `_headers` (the format of Cloudflare Pages and Netlify) with the content security policy, its `connect-src` naming the
  relay, Cloudflare's Turnstile in `script-src` and `frame-src`. Serve DIR over https; on another host, set the same
  header.
- The relay must allow the page's origin (`ALLOWED_ORIGINS`, `myna/relay/DEPLOY.md`).
- The relay's person check (Turnstile, `myna/relay/DEPLOY.md` section 3): `--turnstile` with the same site key as the
  relay's `TURNSTILE_SITEKEY`, and the page's host name added to the widget. Without `--turnstile` the page still answers
  a relay that asks (the sheet comes up when the relay sends its challenge), but only once the phone has started.
- Do not use `?log=1` or `--log` on a public host.

## Tests

```
MYNA_PYODIDE=DIR node myna/web/test/smoke.mjs     # about 1 minute
MYNA_PYODIDE=DIR node myna/web/test/typing.mjs    # about 3 minutes
MYNA_PYODIDE=DIR node myna/web/test/flip.mjs      # the flip: lid open, closed, a key, a text, its own flash state
MYNA_PYODIDE=DIR node myna/web/test/relay.mjs     # needs (cd myna/relay && npm install); about 2 minutes
MYNA_PYODIDE=DIR node myna/web/test/onboarding.mjs   # the same, and the internet (Turnstile's test keys); about 4 minutes
```

Both start `serve.py` and a headless Chrome on free ports, each with a temporary profile, and stop them. `smoke.mjs`: the
shelf shows Myna; it starts; no relay, so the loopback network; the phone registers; a text written with the keys
(Messages, New message, a number, multi-tap) comes back; switched off, the flash state is in IndexedDB; after a reload
the text is in the phone's store. `typing.mjs`: "what is up" and "where are you now" in predictive text, tapped on the
skin's key areas (60 to 150 ms a tap, 100 to 300 ms between), with the mouse and with an iPhone's touch screen five times
slower, after the phone has rested and with pauses before the spaces: every press is as long on the phone as on the page,
no key is held (# held would change the input method), and the text comes back as typed. `relay.mjs`: a local relay (`wrangler dev`, nothing leaves the computer); two phones,
the page at 127.0.0.1 and at localhost (two origins: two numbers), both on the relay and registered; A writes to B's
number, B receives it from A's number, A's text is marked sent. `onboarding.mjs`: as on an iPhone, through local relays
that ask for the person check with Cloudflare's test keys (one accepts every token, one refuses every token): the sheet
asks for the check, the number is shown and the phone gets online with it; one welcome text from 3246 names the number;
a reload with the ticket skips the sheet and brings no second welcome; a ticket run out asks again and keeps the number; a refused check is said, with no number, and "Not now" leaves the phone
without service and "Get a number" in the settings. `CHROME` names another Chrome, `SHOTS` a folder for
screenshots. Result (2026-10-14, Chrome on a Mac): 8 of 8 and 7 of 7.
