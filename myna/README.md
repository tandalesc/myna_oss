# Myna

Myna (working name) is an open-source firmware for phones on the ST-Ericsson DB3210 platform (the hardware that
`spec/` describes). It runs on this repository's simulator in place of the stock firmware. It uses no stock
firmware: no code, no data, no graphics, no sounds, no fonts, no text. Licence: MIT (third-party parts: see
"Third-party parts" below).

Version 0.1.0-dev, milestone 3: the phone boots to its standby screen in 121 ms of emulated time. The UI is the
design's "Pebble" theme (design round 2) and its dark variant "Pebble night": a standby screen with a dune wallpaper,
the big clock, the date and the status bar; a 3 x 4 main menu in keypad order with full-colour icons and a tile that
grows under the selected item; a numbered settings list (key sounds, theme, time, time format, brightness, memory); a
time and number field; Notes, typed with multi-tap into message blocks; dialogs and toasts; a "coming soon" screen for
the menu items not built yet. Icons, wallpapers, the selection tile and the status signs are rendered at build time
from the design's own drawings by a stdlib Python rasteriser (no browser). Settings are kept in a littlefs file system
on the NAND flash and survive power off; a blank chip is formatted at the first start. The slide's opening and closing
show a note, and the keys under a closed slide are ignored. The same firmware runs in the P2 flip
(native/devices/myna_flip): it reads the board-ID strap at start (drivers/board.c), and there the switch is the lid:
closed, the screen goes black and the panel dark, only the side keys reach the UI; open, it is where it was. Holding END for 3 s writes what is pending and switches the
phone off. Between minutes the CPU sleeps: one wake-up a minute, about 21,000 instructions each. The modem CPU is not
started.

Telephony (milestones 3a and 3b): the link to the modem (channel 0, interrupt receive, DMA transmit), a 3GPP TS 27.010
multiplexer client, an AT command engine, a network service (registration, operator, signal bars, own number, network
time), text messages in PDU mode (a codec for SMS-SUBMIT, SMS-DELIVER and SMS-STATUS-REPORT, GSM 7-bit with the
extension table and UCS-2, concatenation up to 6 parts), a message store on the user file system (acknowledgement only
after storing, a refusal with "memory capacity exceeded" when it is full), a send queue with retry rules, and contacts
kept as vCard 3.0 files with lookup by number. Their screens, in the Pebble design: Messages (conversations as message
blocks, a text box that counts the parts, the state of each sent text with the reason of a failure and Retry, a
recipient picker), Contacts (an alphabetical list searched by the keys typed, a contact's numbers and note, new / edit /
delete) and a dialer that says plainly that calls are not available yet and offers a text message instead. A text that
arrives elsewhere shows a toast with the sender and its first words, the envelope and "1 new message" on standby. The
network's operator and signal reach the status bar through its setters. The modem adds nothing to the idle cost.

The phone's own UI, round 2: **predictive text** in every text box (one press per letter from a ranked list of 32,000
English words, 12dicts, public domain; candidates on *, punctuation on 1, an apostrophe inside a word, a capital at a
sentence's start, a completion offered after the cursor and taken with right, Spell for a word no list has, which then
stays in My words; a word chosen over the first one is learnt), the keys laid out as on the slider phones of the era (#
the space, * the case Abc / abc / ABC, # held the input method: predictive, letters, 123; * held the symbols), digits
on a held key; UTF-8 text throughout, with Cyrillic in the sizes that show what people write; drafts kept per
conversation and a Retry that sends only the parts that failed; a deeper Settings tree (Sounds & alerts with the
profiles Normal, Silent and Meeting, Display, Time & date, Text input with My words, Phone status, Reset and master
reset); the keypad lock (* then Lock); shortcuts on the navigation key at standby; the dunes of the standby drift
slowly (the animated wallpaper, still after 20 s); screens push in and out sideways in 100 ms; lists longer than the
screen have a scroll bar; Options in Notes and conversations; the Clock (alarm in the status bar, timer, stopwatch)
and a Calendar. **Smart dialling**: while a number is typed, the dialer shows under it the contacts whose name the
keys spell at the start of a word (5-6-4-6 finds John; accents folded, Cyrillic on the Russian layout, 0 or 1 for the
break between words), then the contacts and recent conversations whose number holds the digits, the most recently
messaged first, the matched letters in the accent; down chooses one, Message writes to it (the setting Calls, Smart
dialling, turns it off). Contacts is searched by the same keys, in a field over the list.

The hardware interface Myna is written against is `myna/spec/` (questions on it: `myna/spec/QUESTIONS.md`).

## Folder

    myna/
      README.md                 this file
      spec/                     the hardware interface specification, and QUESTIONS.md
      assets/fonts/             Nunito Light, SemiBold, Bold and ExtraBold (OFL) and their licence
      assets/words/             the English words of predictive text (12dicts, public domain with the AGID notice),
                                ranked by frequency, their licence, and extra.txt (contractions, the project's own)
      assets/design/            the design's drawings as code (MIT): icons.py, wallpapers.py, lettering.py (from the
                                design round 2), tiles.py and status.py (the selection tile, the status signs)
      third_party/stb/          stb_truetype.h (used by the build-host font tool only) and its licence
      third_party/littlefs/     littlefs 2.11.3 (the file system, BSD-3-Clause), unchanged, and its licence
      tools/mkfont.c            build-host tool: TrueType -> glyph atlases (C source)
      tools/mkassets.py         build-host tool: the design's drawings -> firmware images (C source); stdlib only
      tools/svgraster.py        the SVG subset rasteriser mkassets.py uses (anti-aliased, gradients, strokes)
      tools/png.py              PNG reading and writing (stdlib), for previews and checks
      tools/cmpassets.py        a check: the rendered images against the design's PNG mock-ups
      tools/importwords.py      one-time tool: the 12dicts archive -> assets/words/en.txt
      tools/mkdict.py           build-host tool: assets/words/en.txt -> the dictionary's index by key sequence (C source)
      web/                      the phone page: Myna in a browser tab, its development server, platform.txt (the
                                simulator's files a phone imports) and the page's tests (web/README.md)
      relay/                    the text-message relay between pages: a Cloudflare Worker, its protocol, tests and the
                                page's client (relay/README.md)
      LICENSE                   MIT
      firmware/
        Makefile                the build (firmware and font pipeline)
        link.ld                 the memory layout
        src/crt0.S              first instructions, exception vectors, IRQ entry, fault frame, the call of main()
        src/main.c              start-up order: kernel, drivers, storage and settings, tasks, then the event loop
        src/cpu.h, hw.h         CP15, CPSR and IRQ masking; register access and the device base addresses
        src/kernel/             interrupts, OS timer, software timers, tasks and the event loop, fault report, start-up memory
        src/drivers/            UART, display + panel, keypad, slide switch (the flip's lid), board ID, I2C, power chip,
                                wall clock, backlight,
                                NAND flash (with its self-test), DMA controller
        src/fs/                 storage: partitions and littlefs on the NAND driver; littlefs's system header
        src/modem/              link channel 0, the 27.010 multiplexer, the AT engine, the modem task and its bring-up
        src/services/           settings, network (registration, operator, signal, own number, time), contacts,
                                words (the candidates of predictive text and My words)
        src/sms/                text messages: the service (send queue, receive, acknowledgement) and the store
        src/gfx/                fills (plain, dithered by row, translucent), copies, rounded rectangles, images,
                                text; the glyph atlas and image formats
        src/ui/                 the UI task and screen stack (with the push between screens), themes, layout, widgets
                                (list, text box with predictive text, the symbols and Spell, field, message blocks,
                                choice, editor), status bar, the screens (standby with the keypad lock, menu, the
                                settings tree and My words, notes, field, placeholder), the animated standby, benchmarks
        src/apps/               the telephony's screens: Messages, Contacts, the dialer and Calls, smart search (what
                                matches keys typed, for the dialer and Contacts), the glue that brings the services'
                                news to the UI task, text helpers (UTF-8, dates); the Clock (alarm, timer, stopwatch)
                                and its task; the Calendar
        src/lib/                kprintf, memory and string routines, the compiler's run-time helpers; codecs: GSM 7-bit
                                alphabet, text message PDUs, vCard, phone numbers, UTF-8; key sequences (letters to the
                                keypad's keys, for predictive text and smart search)
        test/test_codecs.c      host tests of the codecs and the key sequences (make host-test)
        test/test_dict.c        host tests of the dictionary of predictive text (make host-test)
        test/sim_telephony.py   the telephony through the simulator, driven by keys on Myna's screens, with this script
                                as the cell network (or the stand-in's loopback network); frames of every screen
        test/stock_free.py      the same run under an import guard: nothing of the stock firmware's stand-ins,
                                profiles or key tables, every file imported listed in web/platform.txt
        test/sim_organiser.py   the Clock through the simulator: the alarm (rings asleep, snooze, stop, after a power
                                cycle and a clock change), the timer, the stopwatch with laps; frames of every screen
        test/sim_wallpaper.py   the animated standby through the simulator: motion, rest, sleep, both engines' frames
        test/sim_flip.py        the P2 flip: the board-ID strap, the lid (dark when closed, the face's keys ignored, back
                                where it was when opened, a text while closed), both engines' frames
        test/sim_ui.py          text input (predictive text, Spell, modes, symbols) and the phone's own screens (keypad
                                lock, profiles, shortcuts, settings tree, My words, Calendar, master reset)
        test/sim_dial.py        smart dialling and the search in Contacts: matches by name and number, the ranking, a
                                match chosen and written to, the setting; with --bench the cost of a key at 500 contacts
        build/                  the output (not in git): myna.elf, myna.bin, myna.map, gen/fonts_*.c, gen/assets.c
                                and gen/preview/*.png (the images as the phone shows them)

The simulator's side is the device folder `native/devices/myna/` (profile: `BOOT_ELF`, the add-on chips) and the
`BOOT_ELF` path in `native/sim/db3210.py`.

## Build

Needs only what a Mac with Xcode's command-line tools and Rust (rustup) already has: `clang` (target
`armv5te-none-eabi`, `-mcpu=arm926ej-s`, ARM state, soft float), `rust-lld -flavor gnu`, `rust-objcopy`, the host
`cc` for the font tool and `python3` (standard library only, 3.9 or later) for the image tool. Nothing to install. The Makefile finds the Rust tools on the PATH, in the sysroot of `rustc`, or
under `~/.rustup/toolchains`. Other tools: `make LLD=... OBJCOPY=... CC=... HOSTCC=...`.

    make -C myna/firmware                     # -> myna/firmware/build/myna.elf
    make -C myna/firmware clean all BENCH=1   # the same with benchmarks on the console (see "Measurements")
    make -C myna/firmware clean all DEFS=-DMYNA_UI_DEMO=1   # the status bar as in the mock-ups (3 bars, "Loopback",
                                                             # one unread message), whatever the network says
    make -C myna/firmware clean all DEFS=-DMYNA_TEST_HOOKS=1   # test codes in the dialer (sms/store.h): a full store;
                                                               # *#2668*5#: 500 made-up contacts in RAM (smart search)
    make -C myna/firmware host-test           # the codecs on the host

## Run

From the repository root. The display controller is attached only with `--display` (or `--frames-dir`, which implies
it); without it Myna runs headless (console only). N is the limit of emulated seconds:

    make -C myna/firmware && native/.venv/bin/python -I native/sim/db3210.py --device myna --standard --display --emu-seconds N
    make -C myna/firmware && native/.venv/bin/python -I native/sim/db3210.py --device myna --standard --display --emu-seconds N --core own

`--core own` is the compiled core (`native/core/`; build it first with `native/core/build.sh`, or name a build with
`DBCORE_OUT`). Logs go to `SIM_LOG_DIR` (default `run/`), the console also into `myna/app-uart.log` there. The
simulator may run past N while Myna sleeps on a long timer (`spec/QUESTIONS.md` Q7).

In the viewer: `SIM_DEVICE=myna tools/viewer.sh`, or "+" on the desktop of a running viewer. The viewer gives
`--idle wait`, so an idle Myna waits for a key instead of the run ending.

What it prints at the first start on a blank chip (Unicorn; the compiled core differs only in the entry CPSR and a few
microseconds):

    APP uart| Myna 0.1.0-dev booting (cpu 41069265, entry cpsr 400001d3)
    APP uart| display: controller 00004101, framebuffer 0x4802c000, panel waking
    APP uart| pmic: chip c8, power-on events 01 00 00 (power key)
    APP uart| clock: 2008-10-20 12:00:00 UTC
    APP uart| battery: 3951 mV
    APP uart| backlight: illumination driver answers; its commands are not known yet, nothing sent
    APP uart| nand: id ec aa 10 15 44, page 2048, block 131072
    APP uart| storage: system: blank, formatting 32 blocks
    APP uart| storage: system: 32 blocks from block 32, 2 in use; format 668 us, mount 191 us
    APP uart| storage: user: blank, formatting 1976 blocks
    APP uart| storage: user: 1976 blocks from block 64, 2 in use; format 597 us, mount 191 us
    APP uart| settings: 0 of 3 groups read in 451 us; 24h 1, theme 0, offset 0 s, brightness 4, key sounds 1
    APP uart| slide: closed
    APP uart| kernel: started at 3461 us
    [sim] display frame 1 240x320 at 120.8 ms, non-zero bytes 230400
    APP uart| display: first frame at 120.825 ms, panel on (power mode 9c)
    [sim] display frame 2 240x320 at 60004.0 ms, ...          (the next minute)

At a later start the file systems are mounted, not formatted, and the settings come from their files:

    APP uart| storage: system: 32 blocks from block 32, 2 in use; mount 418 us
    APP uart| storage: user: 1976 blocks from block 64, 2 in use; mount 191 us
    APP uart| settings: 2 of 3 groups read in 816 us; 24h 0, theme 1, offset 0 s, brightness 4, key sounds 1

The date is the power chip's clock: a fixed date in the simulator [MOCK], or another one with
`EMU_PMIC_RTC=host` (the host's time) or `EMU_PMIC_RTC=<Unix seconds>`.

### Frames and keys

`--frames-dir DIR` writes every panel update as `DIR/frame_NNNN.png` (the whole 240 x 320 picture). Keys come from a
key script: `EMU_KEYPAD_CTL=FILE`, one JSON object per line (`docs/USING.md`, section 2), with the viewer's input names
(`spec/06-keypad.md` 4.1), for example:

    {"tap":"select","ms":120,"at_ms":2000}
    {"press":"up","at_ms":5000}
    {"press":"right","at_ms":5100}
    {"release":"up","at_ms":5300}
    {"release":"right","at_ms":5400}
    {"tap":"end","ms":3500,"at_ms":70000}

    EMU_KEYPAD_CTL=run/keys.jsonl native/.venv/bin/python -I native/sim/db3210.py --device myna --standard \
        --frames-dir run/frames --emu-seconds 100

Each press prints `ui: key <name> down`. The last line above holds END 3.5 s and the phone switches itself off
("powered off by the phone").

Commands with `at_ms` arrive on time also while Myna sleeps on a long timer (since the simulator stops a sleeping
phone at the end of each run slice, 2481e97): a script with presses at 5, 20, 61, 95, 130.5 and 131 s, between
minute wake-ups, gave every press at its time on both engines, without `--realtime` (2026-10-14). The slide is a
switch of the key script: `{"switch":"slide","state":"open","at_ms":500}`.

### Flash state: settings across power off

Without a flash state every run starts from a blank chip. To keep the chip between runs as the viewer does, attach the
flash state and name its file:

    SIM_FLASH_STATE=run/myna_flash.bin native/.venv/bin/python -I native/sim/db3210.py --device myna --standard \
        --display --attach flash_state:attach --emu-seconds 30 [--core own]

The first run formats the chip's two file systems; change a setting (left soft key, then select), hold END 3 s
(`{"tap":"end","ms":3500,"at_ms":...}`), and the next run with the same file starts with the setting. The viewer keeps
the file itself (`flash_state_blank.bin` in its run directory); "Factory reset" in its device manager deletes it.
The simulator keeps the chip only from a moment at which it has been quiet for 1.5 s (`spec/10-storage-nand.md` 4):
Myna's power off waits for that.

### Screens and keys

| Screen | Keys |
|---|---|
| standby | select: menu; left soft key: Messages; right soft key: Contacts; a number key or #: the dialer (with that key); * then a number key: the dialer with both; * then Lock (right soft key, within 3 s): keypad lock; # held: Silent on or off; up: Clock; down: Notes; left: new message; right: Settings; END held 3 s: power off |
| standby, keys locked | right soft key (Unlock) then * (within 3 s): unlock; any other key: a note that says how; END held 3 s: power off; an alarm still rings and takes its keys |
| menu | arrows: move (round the grid); select: open; 1-9, *, 0, #: open that item directly; left soft key: options (none yet); right soft key or C: back |
| settings (the top, a page) | up / down or 1-9: choose a row (a number key also acts on it); select: open the page, or act on the row (a value with two states changes, a field or a choice opens); right soft key or C: back a level |
| My words | up / down or 1-9: choose; select (Forget): forget the word (a question); right soft key or C: back |
| calendar | left / right: a day; up / down: a week (into the next or the last month); left soft key: today; select: the day in full; right soft key or C: back |
| a field (time, brightness) | number keys: type the digit under the cursor; left / right: move; up / down: step; select: save; right soft key: back |
| a text box (notes, a conversation, an editor) | the era's slider-phone layout: # is the space, * the case, # held the input method, * held the symbols. Predictive text: a number key once per letter; * or down: the next word, up: the one before (the candidates show as a list); #: the word and a space; right: the word as it is (or with the completion shown after the cursor); 1: an apostrophe inside a word, else "." (1 again or *: , ? ! ' " - ...); 0: 0 (again within 1 s: +); left soft key (Spell, when no word fits or after all the candidates): type the word with multi-tap, it is added to My words. Letters (multi-tap): 2 abc ... 9 wxyz, 1 signs, 0 then +, # ends the letter and types a space. 123: digits, * and #. In every mode: * (no word being chosen) the case Abc / abc / ABC; # held the next input method (predictive text, letters, 123, named in a toast for a second; the setting follows, so the next box starts the same way); * held the symbols; a number key held its digit; C delete (held: everything); left / right move the cursor |
| symbols | arrows: choose a sign (the last one, ¶, is a new line); select: insert it; right soft key or *: back |
| notes | the text box; select: save the note; up / down: scroll the notes; left soft key: Options (Add symbol, Delete all notes with a question); right soft key: back |
| placeholder | select, right soft key or C: back |
| clock | up / down or 1-3: choose Alarm, Timer, Stopwatch; select: open; right soft key or C: back |
| alarm | select: turn on / off; left soft key: options (set time, turn on / off); right soft key: back |
| timer | select: start / pause / resume; left soft key: set the length (stopped) or reset (running, paused); right soft key: back |
| stopwatch | select: start / stop; left soft key: lap (running) or reset (stopped); up / down: scroll the laps; right soft key: back |
| alarm ringing | select (Snooze): again in 9 minutes; right soft key or END: stop; other keys wait; a minute unanswered: snooze |
| timer alert | select, right soft key, C or END: close; a minute unanswered: it closes |
| messages | up / down: choose ("New message" first, then the conversations, newest first); select: open; left soft key: options (new message, delete conversation, mark all as read); right soft key or C: back |
| a conversation | the text box (as in notes; a draft is kept when you leave); select (Send): send the text; up / down: scroll the messages (a screenful at a time through a long one; the lowest one in view is the one options act on); left soft key: options (retry a failed text, delete message, delete conversation, call (not available), add to contacts / view contact, add symbol); right soft key: back; the call key: "calls are not available yet" |
| new message | up / down: choose; select: "Enter number" (an editor for a phone number) or a contact (one of its numbers, if it has more); 2-9: jump to names with the key's letters; right soft key: back |
| contacts | up / down: choose ("New contact" first); 0-9: search (the keys show in a field over the list, which keeps the contacts with a word of the name that starts with the keys' letters, 5-6-4 for John, then those whose number holds the digits); C: the last key back; C held or right soft key: the whole book again; select: open; left soft key: options (new contact, send message, edit, delete); right soft key (no search): back |
| a contact | up / down or 1-4: choose a number; select (Message): write to it; left soft key: options (send message, call (not available), edit, delete with a question); right soft key: back |
| new / edit contact | up / down or 1-9: choose a field; select: edit it (a number: the left soft key changes its label; an emptied number is removed); left soft key: save; right soft key or C: back (a question when something changed) |
| an editor | the text box (a name starts in Abc; a phone number: digits, * gives +, # gives #); select: save; right soft key or C on an empty box: back |
| dialer and Calls | number keys, *, #: type (0 held: +); C: delete (held: the whole number); select (Message): a text to the number; left soft key: save as a new contact; the call key: "calls are not available yet"; right soft key: back. Smart dialling (on by default): the matches under the number; down: into them, up: back to the number; a match chosen: select (Call) and the call key say calls are not available yet, right soft key (Message): a text to its number, left soft key: options (send message, call (not available), view contact or add to contacts) |
| everywhere | C goes back and END goes to standby when the screen does not use them; a key takes a toast away; END held 3 s: power off |

The settings tree (`ui/settings_screen.c`): 1 Sounds & alerts (profile: Normal, Silent, Meeting, with their sign in the
status bar; key sounds, kept, no sound output yet), 2 Display (theme Pebble / Pebble night; wallpaper Animated /
Still; brightness 1-5, kept but not yet sent to the backlight: `spec/QUESTIONS.md` Q4), 3 Time & date (time and date,
fields that move the clock offset; time format 24-hour / 12-hour; network time), 4 Text input (predictive text on /
off: how a box starts, also set by # held in a box; My words), 5 Calls (Smart dialling on / off: the dialer shows the
contacts and conversations that match the keys, or the number only), 6 Phone status (version, memory, battery,
network, own number), 7 Reset (Reset settings: every setting back to its default except the time, after a question;
Master reset: both file systems erased after a question, then the phone switches off and starts as new). Each top row shows a value of its page. A
change shows at once and is written to flash a second later.

## Architecture

### Boot (`crt0.S`, `main.c`)

crt0 sets a stack for each CPU mode, copies the exception vectors to address 0 (low vectors, `spec/00-machine.md` 6.4;
gap G5), copies `.data` if needed, clears `.bss` and calls `main()`. `main()` starts, in order: the interrupt
controllers (all lines off), the OS timer, the display (first, because its panel needs 120 ms to wake and everything
else fits in that time), the power chip, the wall clock, the backlight check, then storage (the NAND chip, both file
systems mounted, a blank chip formatted) and the settings, which set the clock offset, the theme and the brightness;
then the modem's link and engines (`modem_init()`: the link is enabled, nothing is sent yet); then it registers the
tasks (keypad, display, modem, settings, sms, UI, in priority order), starts the slide and keypad drivers, posts the
UI, the modem and the message service their start messages and enters the event loop. The kernel is running 2.9-3.8 ms
after reset (0.6-0.8 ms of it before storage); the modem's bring-up and the message store's start run in the event
loop while the panel wakes; the first frame reaches the panel at 121 ms.

### Kernel (`src/kernel/`)

- **Interrupts** (`irq.c`): the two PL190 controllers in their simplest mode (no vectored slots, so no hardware
  priority logic). The IRQ entry in crt0 saves r0-r3, r12, lr and calls `irq_dispatch()`, which reads both status words
  and calls each pending line's handler, lowest line first, until both are quiet. Every handler clears its source
  before it returns (`spec/00-machine.md` 5.4, gap G6) and only posts messages. A pending line without a handler is
  switched off and reported.
- **Faults** (`fault.c`): every other exception builds a frame on the exception mode's stack (r0-r12, the interrupted
  mode's sp and lr, the exception's lr, SPSR) and prints it on the console with the faulting pc, the instruction (for
  an undefined one) and FSR/FAR (for a data abort), then stops. `make clean all DEFS=-DMYNA_FAULT_TEST=1` builds a
  firmware that shows it.
- **Time** (`ostimer.c`): kernel time is the OS timer's count since reset, in its own unit (4.094 MHz: 1 ms = 4094,
  4 ms = one hardware step), 64 bits. The timer is used **tickless**: never the periodic 4 ms tick, only one one-shot
  event armed for the earliest deadline (rounded up to whole 4 ms steps, so never early, up to 4 ms late).
- **Software timers** (`timer.c`): a list sorted by expiry; the OS timer is armed for its head. An expired timer posts
  `MSG_TIMER` (with its id) to its task; periodic timers keep their cadence. With no timer armed the OS timer still
  gets its longest one-shot (262 s): an idle CPU always has a wake-up to come (`spec/00-machine.md` 5.2, gap G7).
- **Tasks** (`task.c`): a task is an event handler with a 32-message queue. The event loop delivers one message at a
  time to the most urgent task that has one; handlers run to completion (no preemption yet; a per-task stack can be
  added behind the same interface). With no message anywhere the loop masks IRQ, checks again and sleeps with
  wait-for-interrupt (the core wakes on a pending line even when masked, so no wake-up is lost), and counts the CPU's
  awake time.
- **Start-up memory** (`heap.c`): a pointer moving up through the heap of `link.ld`, for the framebuffer.

### Drivers (`src/drivers/`)

- **Display** (`display.c`, `panel.c`): a 240 x 320 RGB565 framebuffer in SDRAM, reached by the display controller
  through GRAM banks 1 and 2 (the 1 MB blocks that hold it). The UI marks changed rectangles; `display_flush()` merges
  them (one update for all when the union is at most twice their area, else one per rectangle) and starts the first
  update; the rest are chained on the update-done interrupt (line 18), so nothing waits. Panel: DCS commands through
  the panel bus engine: sleep out at start, after 120 ms colour order, pixel format and window, then the first full
  frame while the panel is still dark, and display on when it has arrived (the power mode read back is 0x9C).
- **Keypad** (`keypad.c`): interrupt-driven. Idle: all rows driven, only the key-down line (30) enabled. A key-down
  interrupt switches to the all-up line (31) and wakes the keypad task, which scans the matrix and the direct keys and
  posts `MSG_KEY_DOWN` / `MSG_KEY_UP` (key index) for every change to its subscriber; while a key is down it scans
  again every 25 ms (for further keys and releases); the all-up interrupt switches back. Key names are the viewer's
  input names (`key_name()`). The keys on the slide's hidden part (0-9, *, #) are reported by the matrix whatever the
  slide does (`spec/06-keypad.md` 4.1), so while the slide is closed their presses are not passed on (a key reported
  down is still reported up).
- **Slide switch** (`slide.c`): GPIO bank 0 pin 4 (variant A: 1 = closed), on its interrupt (line 32). A pin interrupts on
  one edge, set by its polarity bit, so the driver always waits for the level the pin does not have: after each
  interrupt it reads the level, sets the polarity to the other one, and posts `MSG_SLIDE` (open or closed) when the
  state changed.
- **NAND flash** (`nand.c`, `nand_arm.S`): the 2 Gbit chip behind the NAND controller (`spec/10-storage-nand.md`),
  in sectors of 512 bytes (four to a 2 KB page), pages and erase blocks of 64 pages (128 KB). Commands and addresses go
  to the controller's latches; data moves with LDM/STM of eight words at the data port (the DMA controller has no port
  for it, `spec/13-dma.md`; Q12). Every sector is written with the 24-bit Hamming code of the controller's ECC engine,
  which the driver starts before each sector and reads after its 512th byte; the codes go to the page's spare area in
  the same program operation. A read computes the code again and compares: one wrong bit in the sector (or in its
  stored code) is corrected and counted, more are reported (`NAND_ERR_ECC`). The chip has no completion interrupt
  (line 45 is never raised), so after a busy command the driver polls the ready bit (in the simulator: three polls;
  Q9). Bad blocks: a block whose page 0 or page 1 has a spare byte 0 other than 0xFF is bad (the factory's mark; Q11);
  the driver checks a block once per start before its first erase or program, refuses bad ones, and marks a block bad
  when a program or erase fails. `make clean all DEFS=-DMYNA_NAND_TEST=1` builds a firmware that tests all this on the
  chip's last block at start (the engine's code against the specification's formula, a corrected bit, an uncorrectable
  sector, partial programs, the bad mark).

  Spare area of a page (64 bytes): byte 0 bad-block mark (0xFF = good; Myna writes it only to mark a block bad),
  byte 1 reserved, bytes 40-51 the codes of sectors 0-3 (three bytes each, least significant first), the rest free.
  An erased sector reads as valid: 512 bytes of 0xFF have the code 0xFFFFFF.
- **I2C** (`i2c.c`): the two ST-style masters, polled (used at start only; an interrupt-driven bus task comes when the
  UI needs I2C while running).
- **Power chip** (`pmic.c`): identity, power-on cause (read, which also clears it), the battery-backed clock, battery
  voltage, and power off (system supply off).
- **Wall clock** (`clock.c`): the power chip's clock is read once at start (to 1/65536 s); after that the time is that
  reading plus the kernel time elapsed, so the time needs no bus traffic and the next minute boundary is exact to the
  OS timer. The SoC's real-time clock is loaded with the same seconds for later alarms. UTC; Unix time to the civil
  calendar by counting years and months.
- **Backlight** (`backlight.c`): the commands of the illumination driver chip are not known (`QUESTIONS.md` Q4), so it
  only checks that the chip answers, and keeps the brightness setting for when they are. The simulator always shows the
  screen lit.
- **Wall clock offset**: the time the user sets is kept as an offset (seconds) to the power chip's clock, the setting
  `offset`; the chip's own clock is never written. `clock_seconds()` is the chip's time plus the offset.

### Storage (`src/fs/`)

The chip is divided into partitions (`fs/storage.h`); two of them hold a littlefs file system:

| Partition | Erase blocks | Size | Content |
|---|---|---|---|
| boot | 0-31 | 4 MB | reserved for a boot loader and the firmware image (not used yet: the simulator loads the ELF file) |
| system | 32-63 | 4 MB | littlefs "system": the settings files, later other state of the phone |
| user | 64-2039 | 247 MB | littlefs "user": the user's files (mounted, nothing uses it yet) |
| reserve | 2040-2047 | 1 MB | outside the file systems: the NAND self-test's block (2047); later a crash log or a factory area |

littlefs 2.11.3 (`third_party/littlefs/`, unchanged) runs on the NAND driver (`fs/storage.c`): a littlefs block is one
erase block (128 KB); reads and programs are whole 512-byte sectors (the unit of the codes, and the chip allows a page
to be programmed a sector at a time); the read and program caches hold one page (2 KB), so a cache fill is one page
read. Metadata logs are limited to 8 KB of their block (`metadata_max`), so a mount or a file lookup reads at most 16
sectors per log; small files (up to 1 KB, every settings file) live inside their directory's metadata; metadata moves
to fresh blocks after 500 erases (`block_cycles`). An uncorrectable sector reaches littlefs as `LFS_ERR_CORRUPT`; a
failed program or erase, or a block marked bad, also gives `LFS_ERR_CORRUPT`, and littlefs moves the data to another
block. littlefs's first two blocks (the superblock) cannot move, so a partition starts at its first pair of good blocks.

At start a partition whose first two blocks are both erased is formatted; one that holds something littlefs cannot
mount is reported and left alone (never formatted over). littlefs's system header is Myna's (`fs/lfs_port.h`, through
littlefs's `LFS_CONFIG`): Myna's memory and string routines, errors and warnings on the console, a stop with a report
for a failed assertion, and a table-driven CRC-32 (`fs/lfs_port.c`). littlefs never allocates: every buffer is given.
RAM: about 8.5 KB for both file systems (2 caches of 2 KB each, the lookahead bitmaps, the littlefs state), 2 KB for
the settings' file cache, 1 KB for the CRC table, 1 KB for the NAND driver's block bitmaps and its bounce buffer.

Writes finish when the call returns (the chip is polled), so there is no write-back state to flush; but the simulator
keeps the chip only from a moment at which it has been quiet for 1.5 s (`spec/10-storage-nand.md` 4), so power off
waits until 1.6 s after the last write (Q14).

### Settings (`src/services/settings.c`)

Typed settings with defaults compiled in (`services/settings.h`): each has a name, a group, a kind (bool, enum,
number), a default and a range.

| Setting | Name in the file | Group | Values | Default |
|---|---|---|---|---|
| time format | `time_24h` | clock | 1 = 24-hour, 0 = 12-hour | 1 |
| clock offset | `offset` | clock | seconds added to the power chip's clock | 0 |
| theme | `theme` | display | 0 dark, 1 light | 0 |
| brightness | `brightness` | display | 1-5 | 4 |
| key sounds | `key_sounds` | sound | 0 / 1 | 1 |
| network time | `net_time` | clock | 1 = the clock follows the network's time at each registration | 1 |
| wallpaper | `wallpaper` | display | 1 = the standby's dunes drift (animated), 0 = the still picture | 1 |
| profile | `profile` | sound | 0 Normal, 1 Silent, 2 Meeting (the status bar's sign; no sound output yet) | 0 |
| predictive text | `predictive` | input | 1 = a text box starts in predictive text | 1 |
| smart dialling | `smart_dial` | input | 1 = the dialer shows the contacts and conversations that match the keys | 1 |

Each group is one small file in the root of the system file system (`settings.clock`, `settings.display`,
`settings.sound`, `settings.input`) with a line `name=value` per setting, read at start; a missing file or line, an unknown name or a
value out of range gives the default. Reading a setting (`settings_get()`) is from RAM. `settings_set()` checks the
range, changes the value at once, sends `MSG_SETTING_CHANGED` (setting, new value) to the subscribed tasks (the UI),
and starts a one-second timer of the settings task, which then rewrites the changed groups: a burst of changes is one
write per group. A file is replaced whole (opened with truncate, written, closed), which littlefs commits atomically:
after a power cut it holds the old or the new values. `settings_sync()` writes at once (power off). `settings_reset()`
puts every setting but the clock offset back to its default (each change announced); `settings_forget()` drops what
is not written yet (master reset, after `storage_erase_all()` formatted both file systems).

### Graphics (`src/gfx/`)

- `blit_arm.S`: the row loops everything else uses. A fill stores 16 pixels per STM (eight registers holding the
  colour twice, or two alternating pixels for a dithered fill); a copy moves 16 pixels per LDM/STM pair; a leading odd
  pixel aligns to a word; the 0-15 pixel tail is done by testing bits of the remaining count. Rows with different
  halfword alignment fall back to two halfwords per step.
- `gfx.c`: rectangle clipping and union, `gfx_fill()`, `gfx_copy()` (clipped rectangle copy between surfaces).
- `shape.c`: colours as 0xRRGGBB (what themes keep) to RGB565; `gfx_fill_rows()`, a fill whose colour changes by row
  (a vertical gradient computed once per theme, each row a pair of pixels from a 2 x 2 ordered dither, so a slow dark
  gradient shows no bands); `gfx_blend_fill()` (a translucent fill); `gfx_round_rect()`, a rectangle with
  anti-aliased round corners and an optional 1 px edge (corner coverage from 4 x 4 samples, made once per radius).
- `image.c`: the build-time images of `image.h`: opaque RGB565, opaque 8-bit palette, RGB565 with alpha in runs
  (transparent runs skipped, opaque runs copied with the copy loop, edge pixels blended), and 4-bit coverage masks
  drawn in a colour given at run time. Every draw is clipped to a rectangle, so a part of a picture can be redrawn.
- `text.c`: anti-aliased text from 4-bit glyph bitmaps. Blending is done in the RGB565 "spread" form (pixel copied into
  both halves of a word and masked so each colour field has spare bits): one multiply per pixel. With a known
  background colour (`gfx_text()`) the 16 possible pixel values are computed once per call and each pixel is a table
  load and a store; `gfx_text_over()` blends with whatever the surface holds (text on a gradient or the wallpaper).
  A glyph wholly inside the clip takes a loop without per-pixel tests. Pen positions are kept in 1/16 pixel and each
  glyph is drawn from the bitmap made for the nearest third of a pixel (below). Text is UTF-8: each character is
  decoded on the way (`gfx_utf8_next()`, one compare for ASCII) and found in the atlas by a table for U+0000-00FF or
  a short list of ranges above it; a malformed byte shows as U+FFFD, which the atlas draws as '?'.

### Font pipeline (`myna/tools/mkfont.c`, `src/gfx/font.h`)

At build time the Makefile compiles `mkfont` with the host `cc` and `stb_truetype.h`, and runs it on the static
Nunito fonts in `myna/assets/fonts/`, in the weights the design names (Pebble: "Nunito: body 13/600, titles 15/800",
the clock 60/300): Light for the standby clock, SemiBold for text and list rows, Bold for the status bar, soft keys,
the date and message headers, ExtraBold for titles, the centre soft key and the selected row. For each size it writes
a `struct font` into `build/gen/fonts_<weight>.c`: the glyphs of "text" (printable ASCII, Latin-1 and the typographic
signs Windows-1252 adds: the list's chevron U+203A, the ellipsis, the bullet, dashes, quotes, the euro sign),
"text+cyrillic" (the same with Cyrillic U+0400-045F and U+0490-0491: in the sizes that show what people write, body
13, rows 14, their values 12, titles 15 and the headers' and status bar's 11; 98 glyphs, about 106 KB in all), or a given character set
(the 60 px clock has only digits, ':' and space), as 4-bit coverage bitmaps, each glyph's box, offset and advance (in
1/16 pixel), a 256-entry index for U+0000-00FF and the ranges above it (Nunito has no Greek: Greek shows as '?'),
and the font's ascent, descent, line height and digit height (what layouts centre on). Text sizes are rendered in
three phases (shifted by 0, 1/3 and 2/3 pixel; `phases=3`), so a word keeps the spacing of its font instead of each
letter snapping to whole pixels, and with a coverage gamma of 0.75 (`gamma=`, `FONT_GAMMA` in the Makefile), which
brings the weight close to the browser's rendering of the design (chosen by comparing frames with the mock-ups:
the error on text falls from 7.6 to 6.6 per channel with the phases and the gamma). The phone never sees the TrueType
files. Sizes: `FONT_SIZES_<weight>` in the Makefile, about 300 KB of bitmaps and 95 KB of glyph tables in all.

### Image pipeline (`myna/tools/mkassets.py`, `svgraster.py`, `src/gfx/image.h`)

The design's pictures are code: `myna/assets/design/icons.py` (the twelve menu icons on a 48 x 48 grid),
`wallpapers.py` (the Pebble dunes and, for Pebble night, the dunes at night), `lettering.py` (the calendar icon's
figures), `tiles.py` (the selected item's tile of each theme, with its drop shadow and inner top light) and `status.py`
(signal bars, battery, envelope, alarm). Each writes SVG. At build time `mkassets.py` renders them with
`svgraster.py`, a rasteriser in standard-library Python (paths with curves and arcs, strokes with joins and caps,
linear and radial gradients, group opacity; 16 sub-scanlines per pixel with exact horizontal coverage; source-over in
premultiplied sRGB, as a browser paints), blurs the tile's shadow, and converts:

| Images | Sizes | Format | Bytes |
|---|---|---|---|
| 12 menu icons | 24 (lists), 42 (menu), 46 (the grow step), 50 (selected), 64 (placeholder) px | RGB565 + alpha in runs | 146,462 |
| 2 wallpapers | 240 x 320 | 4 x 4 ordered dither to RGB565, then an 8-bit palette (165 and 163 colours) | 154,256 |
| 2 animated standbys: the sky alone and 4 dune bands each | sky 240 x 26 (rows 173-198); bands 240 x 56, 58, 55, 25 | sky: 8-bit palette; bands: dithered RGB565 + alpha in runs | 169,498 |
| 2 selection tiles | 60 x 58 with the shadow round it (80 x 78, 82 x 80) | RGB565 + alpha in runs | 20,110 |
| 13 status signs | 16 x 10, 21 x 10, 13 x 10, 11 x 10 | 4-bit coverage, coloured at run time | 1,190 |

It takes about 2 s; nothing generated is in git. `build/gen/preview/*.png` shows every image decoded from the
firmware format, as the phone blends it. `cmpassets.py DESIGN_R2 OUTDIR` compares the renders with the design's PNGs
(made by a browser from the same drawings): the 42 px icons and the selected Photos on its tile against the menu
mock-up differ by 1.66 per channel on average (PSNR 35.8 dB; 2.34 and 34.2 dB as the phone shows them, after RGB565
and the 5-bit alpha), the 96 px icons of `icons.png` by 0.50 (42.4 dB), the wallpaper by 0.29 (52.2 dB; 2.0 and 39.5 dB
after the dither). Positions match to the pixel; the browser draws thin strokes a touch darker (Alarms, Calls).

### User interface (`src/ui/`)

**Task and screen stack** (`ui.c`, `ui.h`). One task, `ui`, owns the framebuffer and what every screen shares: the
status bar, the title bar, the soft-key bar (three labels: left, centre in the accent, right), toasts and dialogs,
the power-off hold of END, a timer at the start of each minute, and the reactions to settings (the theme switches and
everything is drawn again; the clock offset moves the clock and the minute timer; brightness goes to the backlight
driver). Screens are a stack: standby at the bottom, `ui_push()` opens one over the current, `ui_pop()` goes back,
`ui_home()` to standby, `ui_open()` replaces a passing screen (a choice, an editor, a picker: flag
`SCREEN_PASSING`) or pushes. A screen (`struct screen`) has flags (title bar; wallpaper behind; standby status bar),
`enter(fresh)` (build widgets from the theme and mark them for drawing; fresh = 0 when it shows again with its state:
the screen over it closed, the theme changed, a toast went away), `leave`, `paint`, `key`, `key_up`, `timer` and
`setting`. Keys a screen does not use: C goes back, END goes to standby. Widgets remember whether they changed; the
UI task changes them in reaction to messages and paints once per batch (a `MSG_PAINT` it posts to itself); only
changed widgets draw, and only their rectangles go to the panel. `ui_backdrop()` paints what is behind any rectangle
(the background gradient, or the wallpaper on standby), so a widget can be redrawn alone over it.

**Themes are data** (`theme.c`, `theme.h`, `layout.h`). A theme is a palette (0xRRGGBB, the design's values), its
type scale (pointers to atlases), its wallpaper and tile (images) and a few radii. `theme_select()` turns it into
`ink`: RGB565 colours and every gradient as one dithered pair of pixels per row (background, status bar, title bar,
soft-key bar, the selected row), so drawing a gradient costs what a plain fill costs. The structure is the same in
every theme (STYLE.md section 2: status bar 20 px, title bar 26, content, soft-key bar 26) and lives in `layout.h`,
whose baselines were measured on the mock-ups. Two themes now: Pebble (the design's) and Pebble night (its dark
variant, drawn for this firmware: warm dark brown, the same terracotta, the dunes at night). Instrument and Lantern
need a palette, their atlases (IBM Plex renamed for its Reserved Font Name; Atkinson Hyperlegible Next) and their
wallpaper and tile in the image pipeline; no screen code changes.

**Widgets.**
- `statusbar.c`: signal bars, then the network's name (standby) or the time, and on the right the battery and, left
  of it, the unread-message envelope (in the accent) and the alarm bell. Over the wallpaper it is a veil (each row
  blended), elsewhere opaque. Setters for any task: `ui_status_signal()`, `ui_status_operator()`,
  `ui_status_unread()`, `ui_status_alarm()`, `ui_status_battery()`.
- `list.c` (`struct list`): the numbered list of the settings: rows of 27 px from callbacks (label, value or the
  chevron), numbers 1-9 that choose a row directly, the selected row a bar of the accent gradient with a top light.
  Moving the selection redraws two rows; scrolling past an end copies the picture by one row and draws one new row.
  A list longer than its area has a scroll bar in a 6 px column of its own at the right (a 1 px track, a 3 px thumb as
  long as the share of rows in view), redrawn after the rows.
- `list.c` also draws two-line rows of 41 px (`LIST_TALL_H`, the conversations: the row's content from a
  callback, on the same background and selection bar) and muted rows (an action not possible yet); a list can show
  no selection bar (`unfocused`: the dialer's matches while the number has the focus).
- `textentry.c` (`struct text_entry`): a rounded text box with the keys of the slider phones of the era: # is
  the space, * the case, # held the input method, * held the symbols. Three input methods, stepped by # held:
  predictive text (the default when the setting is on; moving into or out of it sets the setting), letters
  (multi-tap), 123; and three cases, stepped by *: Abc (a capital at a sentence's start), abc, ABC. The mode shows with the count at the
  right of the last line ("Abc 12/160"; predictive text has the book sign in front, "Abc" or "abc" as the next word
  will be, and while a word is chosen which candidate of how many: "2/4", or "?" when none fits); the count can be the
  caller's (a text message counts its parts: "Abc 2 parts 40/153"). Predictive text: each number key adds a key to
  the word being chosen, which is replaced in the text by its first candidate from `services/words.c` (underlined; a
  sequence no word has shows the best beginning and the keys' first letters, underlined in dashes); * or down the next
  candidate, up the one before, and from the first such step the candidates show as a small list over the box (up to
  four round the one shown, that one on an accent bar; drawn after the box at every paint while it shows; when a key
  does anything else the screen is drawn again without it); # takes it with a space, right as it is; 1 is an apostrophe when a word has one there
  and otherwise ends the word with a sign (".", then 1 or * for , ? ! ' " - : ; ( ) @ / &). The first letter of a
  word that starts a sentence is a capital. A completion (the likeliest longer word, `words_complete()`) is drawn after
  the caret in the muted colour when it fits on the line, and right takes it. The left soft key offers Spell (through
  `ui_soft_override()`) when no word fits or after going round all the candidates: a screen with a box of its own
  (multi-tap, abc) whose word replaces the one being chosen and goes to My words. A word chosen over the first one is
  learnt (`words_learn()`). Multi-tap: 2 abc ... 9 wxyz, 1 punctuation, 0 then +, a few accented letters after each
  digit, 1 s to take a letter, the letter being chosen underlined; # takes it and types a space. 0 in predictive text
  is 0, then + within 1 s. A number key held (`KEY_HELD`, below) gives its
  digit in place of what its press gave; C deletes (held: the whole text); left / right move the cursor; * held
  opens the symbols (a 6 x 6 grid in the title font, the chosen one on an accent tile; the last
  is a new line). Up to 612 bytes of UTF-8 (four parts of a text); cursor moves and deletions go by whole characters.
  A phone-number mode: digits, * for + and *, # for #. A key that leaves the lines where they were redraws only the
  cursor's line and the count (typing at the end of a long text: 10,000-50,000 instructions instead of 140,000 for
  four lines).
- Held keys (`ui.c`): a key still down after 700 ms comes to the screen a second time as `KEY_HELD | key`; a screen
  that does not use it returns 0 and nothing happens (END keeps its own 3 s hold).
- `field.c` (`struct field`): an editable number in one to three groups ("09:45": hours 0-23, minutes 0-59), the
  digit being edited in the accent and underlined; number keys type, up / down step, left / right move.
  `field_screen_open()` shows a field on a screen with Save and Back.
- `convo.c` (`struct convo`): message blocks as in the conversation mock-up: full-width rounded blocks with a header
  (sender, time) and the wrapped text, the newest at the bottom, outgoing ones in the outgoing colour with an accent
  header; a state at the right of the header ("Sending...", "Failed") and a note under the text (the reason of a
  failure). Up / down scroll: each step brings the next block's edge to the area's edge, never more than the area less
  two lines, so a message longer than the screen is read a screenful at a time; the lowest block in view is the
  focused one (an accent edge once scrolled). The caller keeps the messages; the text is drawn on the block's colour.
- `choice.c`: two passing screens every application uses: a choice (a numbered list of actions or values on a screen
  of its own: Options, a label, one of a contact's numbers; a muted row shows why it cannot be chosen) and an editor
  (one text box under the title bar, with a help line, Save, and a left soft key of the caller's).
- `ui_note()` (a toast for 1.5 s; `ui_note_ms()` for another time, up to four lines) and `ui_dialog()` (a box with
  its own soft keys that takes the keys until answered).
- `widget.c`: a text label (on a colour, on a bar's gradient or over the backdrop), digits in fixed cells (the clock:
  a new minute redraws one cell), word wrap, the time in the user's format.

**Screens.** `home.c` (standby: wallpaper, the clock in Light 60 with AM / PM in 12-hour form, the date, "1 new
message" in the accent under it while there are unread texts, soft keys Messages, Menu, Contacts; the keypad lock: *
then Lock locks, the soft keys show only Unlock, "Keys locked" under the date and the padlock in the status bar, the
dunes stand still, Unlock then * unlocks, every other key gets a note that says how; the navigation key's shortcuts),
`menu.c` (the 3 x 4 grid, below), `settings_screen.c` (the settings tree: a top list of six pages, each the same
screen with a table of rows, every row with its value; My words, a list in which a word can be forgotten), `notes.c`
(Notes: the message blocks over a text box that grows to four lines; Save adds a note; Options: Add symbol, Delete all
notes; kept in RAM for now), `field.c` (time, date and brightness), and the placeholder in `apps.c` ("Coming soon"
with the item's 64 px icon). The status bar shows, left of the battery, the unread envelope, the alarm bell, the
profile's sign (Silent: a bell crossed out; Meeting: a phone that vibrates) and the padlock.

**Animated standby** (`livewall.c`, STYLE.md section 4). The Pebble dunes drift: `wallpapers.live()` draws the
still picture's sky alone and each of its four dune bands alone, with an edge that repeats every 240 px (the still
picture's first sine, with a half and a third of its period for the others), and `mkassets.py` makes the sky a strip
of its rows that move (173-198) and each band a strip 240 px wide from its highest point down to where the next band
covers every column (the last one down to the soft-key bar). A frame is copies into the expanded wallpaper (what
`ui_backdrop()` copies from, so anything redrawn over the standby shows the current frame): the sky strip, then each
band at its own offset, twice (the part that leaves at the left comes in at the right); then only the rows from the
highest band that reached a new pixel go to the framebuffer. Offsets advance in 1/65536 px at 1.5, 2.5, 4 and 6.5 px a
second at full speed, on a 100 ms timer of the standby screen, which starts when the standby shows (opened, or another
screen over it closed) or a key is pressed on it, gains speed over 1.6 s, and after 20 s without a key loses it over
2.6 s and stops. It stops when another screen covers the standby and while a toast or a dialog is over it (it goes on
when it goes), and `livewall_hold()` keeps it still (for the keypad lock). The setting `wallpaper` (Still) puts the still
picture back in those rows. At rest nothing is armed: the next wake-up is the minute.

**Main menu and motion** (STYLE.md section 4). The grid is in keypad order (1 Messages, 2 Contacts, 3 Calls, 4 Camera,
5 Photos, 6 Music, 7 Radio, 8 Clock, 9 Calendar, * Notes, 0 Web, # Settings); the item's key opens it directly. A move
draws, in one frame, the old item plain and the tile under the new one with its icon at 42 px; two timer ticks 40 ms
apart step the icon to 46 and 50 px (pre-rendered sizes, no scaling). A key ends the step at once. Each frame redraws
only the cells that changed, each with the strip of its neighbours a tile's shadow can reach. The list moves its bar
by redrawing two rows. Opening a screen (`ui_push`) or going back (`ui_pop`) pushes the content area sideways in four
frames 25 ms apart (the new picture from the right going in, from the left going back; the status and soft-key bars
stay): the old picture and the new one are kept in two buffers of the heap and each frame is two row copies per row
(32,000-38,000 instructions). Paints wait while it runs; a key ends it at once. A passing step (a choice, an editor),
END to standby, a toast and a redraw stay cuts.

**Extension points** (`apps.h`). The menu refers weakly to `messages_screen`, `contacts_screen`, `calls_screen` and
the other items' screens, and standby to `dialer_screen`: until something defines one, its item opens the placeholder;
a definition anywhere in the firmware replaces it without a change in `src/ui/` (`src/apps/` defines the four of the
telephony). A number key on standby opens `dialer_screen` and passes it that key. The applications' share of the UI
task's messages goes to `app_event()` (weak as well): MSG_START, MSG_NETWORK_CHANGED, MSG_SMS_EVENT.
`make DEFS=-DMYNA_UI_DEMO=1` sets the status bar as the mock-ups show it.

### Applications (`src/apps/`)

The telephony's screens are screens of the UI task like any other. They call the services directly (the calls run in
the UI task: storing a text, reading a record) and hear from them by messages: the network service and the message
service post `MSG_NETWORK_CHANGED` and `MSG_SMS_EVENT` to the UI task, which hands them to `app_event()`
(`apps/phone.c`). The status bar is set only through its setters: the operator's name, the signal (the service's bars
0-5 as the design's sign of four: 5 shows as 4), the unread count (the envelope). Text is UTF-8
everywhere: everything shown from a service passes `text_from_utf8()`, which makes a malformed byte safe (`apps/text.c`);
Cyrillic shows in the sizes that have it, a character the fonts do not have (Greek, CJK, emoji) as '?'.

- **Messages** (`messages.c`). The list: "New message" with the envelope icon, then one two-line row per number,
  newest first: the contact's name or the number, the time of the last message ("14:05", "Yesterday", "Mon",
  "12 Oct"), a line of it ("Sending:", "Not sent:" or "Me:" in front when it is an outgoing one in that state) and the
  count of unread ones on an accent mark. A conversation with an unsent draft shows the draft's line instead ("Draft:"
  in the accent) and takes the draft's time when that is newer; a draft to a number with no messages yet is a row of
  its own; the newest conversation with unread texts is selected when the list opens. Built from the store's records
  in RAM; the lines of the last messages are read once and kept (eight). A conversation: its newest messages (up to 32, as many as 8 KB of text hold) as message
  blocks over the text box, Send on the centre soft key. Each sent text shows its state at the right of its header:
  "Sending...", "Waiting for network" (not registered), "Trying again" (a passing refusal, before the next attempt),
  "Sent", "Delivered", or "Failed" in the accent with the reason under the text ("Not sent: Message rejected"; "Part 2
  of 3 not sent: ..." when the network took the first parts). Options act on the lowest block in view: Retry (a failed
  text goes again from the first part the network did not take, under the same concatenation reference, so the
  recipient can still join the parts: "Sending part 2 of 3"; a one-part text simply goes again; `sms_retry()`),
  Delete message, Delete conversation (each after a question), Call (muted: "Calls are not available yet"), Add to
  contacts or View contact. Opening a conversation marks its texts read; a text that arrives in the open conversation
  is read where it arrives. New message: "Enter number", then the contacts with a number (a contact with several asks
  which). A text that arrives anywhere else shows a toast for 3 s with the sender (the contact's name) and its first
  words; a failure elsewhere a toast "Not sent to ...". Drafts: text left in the box when a conversation closes (Back,
  END, a screen opened over it, power off) is kept as that number's draft on flash, and is in the box again, the
  cursor at its end, whenever the conversation opens (from the list, New message to the same number, a contact);
  sending it or emptying the box deletes it, and so does deleting the conversation. A box that did not change
  writes nothing.
- **Contacts** (`people.c`). The list is alphabetical (letters without regard to case; the order is the contacts
  service's, kept at every change). The number keys search it (smart search, below): the keys show in a field over
  the list with a glass and "4 matches" at the right, and the list under it (seven rows) has only the matches: the
  names whose letters match first, alphabetical, their matched letters in the accent, then those found by a number,
  the number at the right with its matched digits marked; "No contact matches" when none does. C takes the last key
  back, C held or Back clears the search (the whole book again, with the contact that was chosen still chosen). The
  jump to a letter by pressing a key again (the old behaviour; the era study names no alphabetical jump of its
  own) is gone from Contacts; the recipient picker of New message keeps it. A contact: its
  numbers as a numbered list with their labels, its note in a block under them. New / Edit: the fields as a numbered
  list (first name, last name, up to four numbers with labels, "Add number", note), each edited in the editor; a
  number's label changes with the editor's left soft key; Save needs a name or a number; Back asks before dropping
  changes; Delete asks first. A contact just made is selected when the list shows again.
- **Dialer and Calls** (`dialer.c`). Calls are not part of this milestone, and the screen says so: the number in
  Nunito Light 30 (digits, + * #), and a card "Calls are not available yet. Myna cannot make calls yet. Press Message to
  send this number a text instead." Message opens the conversation with the number, Save makes it a new contact, the
  call key shows the same explanation. The Calls item of the menu opens the same screen, titled Calls. With smart
  dialling (the setting, on by default), the matches of the keys typed take the card's place under the number: up to
  24 two-line rows, four in view (a scroll bar when there are more), each the name (a conversation's number) with the
  time of its latest message, under it the number (the one that matched, or the contact's first; "Not in contacts"
  for a conversation's), the matched letters and digits in the accent. Nothing is chosen until down; up from the
  first row gives the number the focus again. A match chosen: the soft keys are Options, Call and Message; Call
  (select) and the call key say that calls are not available yet and point at Message, which opens the conversation
  with the row's number; Options: Send message, Call (muted), View contact (or Add to contacts for a conversation).
  Any key that changes the number gives it the focus again. Contacts without a number are not offered.
- **Smart search** (`search.c`). What matches keys typed, for the dialer and Contacts. A contact matches when a word
  of its name starts with the keys' letters (`lib/keyseq.h`: 2 abc ... 9 wxyz, accents folded: é on 3, ł on 5, ș
  on 7; Cyrillic on the Russian layout, 2 абвг ... 9 ьэюя; a hyphen or space between words is a break that 0 or 1
  also match, an apostrophe joins: 5-6-4-6-1-7 is "John S...", 2-6-6-3-1-6-6 "Anne Mo..."), or when one of its numbers
  holds the keys (a query with + * # finds only numbers); the dialer adds the newest 32 conversations with a number
  no contact has. The order: the name's first word, then a later word, then a number; among equals the most recently
  messaged first (the dialer: each contact gets the place of its latest conversation among the 32, made when the
  screen opens), then alphabetical. The dialer keeps the best 24, each put in its place as it is found; Contacts keeps
  them all, in a pass over the alphabet per kind (no sorting). The contacts service does the matching on what it
  keeps in RAM for each contact (below), so a key costs only comparisons, and a key that continues the query looks
  only at the contacts that matched the shorter one. Each search prints its hits on the console (`search: "266": 2:
  Anne Moss, Bonn Hart`), which `test/sim_dial.py` reads.
- **Clock** (`clock.c`, `stopwatch.c`; menu item 8). A numbered list: Alarm (its time, "Off" or "Snoozed"), Timer (its
  length, "Running" or "Paused"), Stopwatch. The alarm's screen shows its time in Light 60 (muted while off) and "Rings
  in 7 h 12 min"; Set time is the time field, and saving it turns the alarm on (a toast says when it rings). While it is
  on or snoozed the status bar shows the bell. The alarm and the timer must go off while the phone sleeps and over any
  screen, so their timers belong to a task of their own, `clock` (registered after the UI): the alarm's timer is aimed
  at the kernel time of its minute's start (`clock_next_minute()` plus whole minutes), aimed again when the clock offset
  changes (the task subscribes to the settings) and checked when it fires (a clock moved under it aims again). An
  armed alarm adds no wake-up: the UI's minute timer always comes first. When one goes off, an alert screen opens over
  whatever is shown: the alarm clock's icon nudging 2 px from side to side four times a second (there is no sound
  output yet: only its box is redrawn), the time in Light 60 and the date, or "Time is up" for the timer; Snooze (9
  minutes) or Stop; unanswered for a minute it snoozes (the timer's alert closes). The timer counts minutes and seconds
  (up to 99:59) on the kernel clock and runs on when its screen is left; its screen redraws only at each change of the
  shown second. The stopwatch is arithmetic on the kernel clock too (the time it started and what it had counted): its
  screen shows minutes and seconds in Light 60 with the tenths beside them in ExtraBold 15 ("H:MM:SS" from an hour on)
  and the laps as a list, newest first, each with its own time; it redraws ten times a second only while shown and
  running, and only the cells that changed. Kept in `organiser.clock` on the system file system (the alarm's time and
  state, the timer's length; replaced whole, as the settings files); a snooze, a running timer and the stopwatch are in
  RAM and do not survive a power cycle.
- **Calendar** (`calendar.c`; menu item 9). The month as a grid of weeks, Monday first, the weekend's numbers muted:
  today on a round accent mark, the chosen day in a ring; left / right a day, up / down a week (into the next month),
  the left soft key back to today, select the day in full. A line under the grid gives the day and its ISO week. No
  appointments yet. Moving a day redraws two cells.
- **Waking**: there is no screen-off yet (the backlight's commands are not known, Q4, and the panel stays on), so an
  arriving text only draws its toast; when the display sleeps, `app_event()` is where it will be woken.

Power off: END held 3 s shows "Switching off", writes pending settings, and cuts the system supply 0.5 s later, or
1.6 s after the last flash write if that is later.

**Against the mock-ups.** Frames of the simulator (Pebble, 14:32 on Wednesday 14 October, the demo status bar)
against the design's PNGs (`design/r2/ui/png/pebble-*.png`, made by a browser), mean absolute difference per channel
(0-255) and PSNR:

| Screen | Whole screen | Pictures | Text bands |
|---|---|---|---|
| standby | 3.82, 26.4 dB | wallpaper 2.11, 39.3 dB | clock 6.30; date 8.06; soft keys 7.00 |
| menu | 3.10, 30.8 dB | icon grid 2.67, 35.7 dB | title 3.07; soft keys 5.75 |
| settings | 8.73, 19.0 dB (other row labels: the real settings) | - | two rows with the same text 6.62; title 3.95 |
| conversation | 7.40 (the same three messages, Juno Park, 14:32) | - | blocks 8.65 (a state "Sent" the mock-up has not); text box 10.31 (the mode "Abc", the caret); title 5.16; soft keys 5.78 |

Every text lands within one pixel of the mock-up; what differs is the glyph rasterisation (stb_truetype at 4 bits
against the browser's renderer), the RGB565 panel (about 2 per channel), the envelope the demo shows on every screen,
and the settings' own row labels. Frames from `--frames-dir`, keys from a key file. The conversation was staged on
the phone with keys (a contact, the clock set to 14:02, two texts sent and one received at 14:03, 14:05, 14:06, the
frame at 14:32): blocks, headers and the box are within one pixel of the mock-up.

**Costs** (`make BENCH=1`, `--slice 100`, instructions from the message to the end of its paint; the panel update
runs on after, on its interrupt; Unicorn):

| What | Instructions | Pixels to the panel |
|---|---|---|
| Menu: move the selection (old cell plain, tile under the new one, icon at 42 px) | 91,000-97,000 | about 19,000 |
| Menu: each of the two grow steps (46, then 50 px; the tile's box only) | 38,000-44,000 | 3,480 |
| List: move the selection by one row | 25,000-49,000 | 12,960 |
| List: scroll by one row (8 rows copied, 2 drawn) | 58,000-71,000 | 58,320 |
| Text box: a multi-tap key (one line: the whole box; typing at the end of a longer text: its line and the count) | 10,000-50,000 | 6,102 or less |
| Field: a digit | 61,000-64,000 | 20,160 |
| Open a screen: menu / settings / standby / notes / placeholder | 310,000-381,000 / 217,000 / 242,000 / 167,000 / 137,000 | 76,800 |
| Switch the theme (the new wallpaper expanded: 545,000) | 795,000 | 76,800 |
| Icon 42 px / 50 px / the tile with its shadow (drawing alone) | 11,000 / 14,300 / 38,600 | - |
| Text, 13 px, 18 characters, on a known colour / over the picture | 12,200 / 20,800 | - |
| Messages list: move by one row (two two-line rows) | 98,000-112,000 | 19,680 |
| Conversation: a multi-tap key (median of 1,468 keys; up to 266,000 when the box grows and the blocks move) | 49,000 | - |
| Conversation: scroll by a step (the blocks redrawn) | 299,000-319,000 | 49,000 |
| Conversation: Send (the text stored, its block drawn) | 458,000-929,000 | - |
| Open: Messages (with the lines of the last messages read) / a conversation / Contacts / a contact | 146,000-590,000 / 399,000-538,000 / 123,000-133,000 / 303,000 | 76,800 |
| A text arriving on standby: from `+CMT` to the toast on the panel (the service's store included) | 692,000-1,459,000 | - |
| A minute on standby (one wake-up: a digit over its piece of wallpaper; registered, one unread text) | about 21,000 | about 2,300 |
| A minute on standby with the alarm set (minutes 2-6; loopback network, nothing unread) | 20,780 | about 2,300 |
| The alarm goes off on standby: the clock task's timer to the alert screen on the panel | 189,000 | 76,800 |
| The alert's icon nudge (one step, its 70 x 64 box) | 28,400-28,500 | 4,480 |
| Stopwatch: a tenth (the tenths' label) / a new second (and its digit cell) | 4,100-4,900 / 17,900-21,000 | 418 / 3,840 |
| Stopwatch: start or stop / open it from the Clock list | 45,000-61,000 / 175,000 | - |
| Animated standby: a frame (the bands that moved composed into the wallpaper, those rows to the panel; median of 206 / the frames in which the farthest band moves too) | 109,000 / 236,000 | 13,900 / 28,600 |
| Animated standby at rest: a minute on standby (BENCH, minutes 2-6, the animation stopped at 24 s) | 20,800 | about 2,300 |
| Text box, predictive text: a key (82 keys of an English sentence in a conversation: the word looked up, shown, a completion sought; `test/sim_ui.py --bench`) | median 47,800, 90 % under 108,300, at most 256,600 (the list of candidates closing: the screen drawn again) | the line and the count |
| Text box, multi-tap in the same conversation (41 keys) | median 44,600, at most 156,400 | the line and the count |
| The push between screens: one of its four frames (the content area, 240 x 274, from two buffers) | 31,900-37,900 | 65,760 |
| Open a screen with the push: the menu / Settings / a settings page / the calendar / notes (the first frame included; then four frames) | 418,000 / 277,000 / 230,000 / 452,000 / 258,000 | 65,760 a frame |
| Back to standby with END (a cut: the whole standby) | 465,000-467,000 | 76,800 |
| Settings page: move by one row | 42,800 | 12,960 |
| Keypad lock: * (the hint) / a key while locked (its note) / Unlock then * | 43,000 / 61,000 / 28,000 + 153,000 | - |
| Calendar: a day / a week into the next month (the grid again) | 94,000-109,000 / 280,000 | 2 cells / the grid |
| A minute on standby after all this (the dunes at rest, BENCH, minutes 3-6) | about 21,800 | about 2,300 |
| Smart dialling with 500 contacts (`sim_dial.py --bench`: made-up contacts in the RAM index; 5-6-7-7, 7-6-7-2, 2-7-8-2): the first key, which opens the dialer (the push's first frame, a search of all 500, four rows; with smart dialling off: 334,000) / each next key (the search, the number and four two-line rows) / down (two rows) | 393,000-413,000 / 61,000-208,000 / 66,000-81,000 | 76,800 / 50,880 / 19,680 |
| The search alone in that (`bench: search`): all 500 contacts (317-500 hits) / only the hits of the shorter query (2-500 contacts) | 72,000-87,000 / 600-42,000 | - |
| Contacts with 500 contacts: open (the order is the service's; before smart search, an insertion sort of the names: 4,493,000) / a key of the search (the field and seven rows) / C (a search of all 500 again) | 300,000 / 190,000-275,000 / 214,000 | 76,800 / 53,520 / 53,520 |
| The contacts' keys and order at start, 500 contacts (each name's keys and the masks; the merge sort) | 424,000 + 190,000 | - |

At 100 instructions per microsecond a menu move is under 1 ms of CPU and a list scroll 0.7 ms; idle stays one
wake-up a minute (340 instructions per emulated second on average). Start-up spends 5.5 ms more than before (the
wallpaper expanded into RAM, the theme's tables made) and still fits in the panel's 120 ms wake-up. With 500 contacts
smart search costs at most about 87,000 instructions a key (0.9 ms), and with its drawing every key stays under
300,000 (3 ms) but the one that opens the dialer, which costs what opening a screen costs (393,000-413,000).

### Modem (`src/modem/`)

Myna talks to the modem with standard protocols only (`spec/14-modem-at.md`).

- **Link** (`link.c`): channel 0 of the link block in both directions. Receive is interrupt-driven (line 5): the handler
  empties the 64-byte FIFO with word reads into a 4 KB ring and posts `MSG_LINK_RX` to the modem task once per batch.
  When the ring has no room for the FIFO's bytes, the handler switches the receive interrupt off and leaves them in
  the FIFO, which holds the modem back (the link's only flow control) until the task has read. Transmit goes through a
  4 KB ring and DMA channel 2 (`drivers/dma.c`): one transfer per contiguous stretch, the next one started from the
  completion interrupt; the DMA waits for FIFO space by itself, so a 360-character PDU line costs one set-up and one
  interrupt instead of six FIFO refills. Nothing polls.
- **Multiplexer** (`cmux.c`): 3GPP TS 27.010 basic option as the initiator: frames (flag, address with C/R, control,
  one- or two-octet length, CRC-8 FCS) and a receive state machine that hunts for flags, checks the FCS and drops bad
  frames. Start: SABM on DLC 0, then on DLC 1 (each retried 3 times, 300 ms apart), then MSC on DLC 1 (RTC, RTR, DV,
  no flow stop). N1 is 256 octets (`AT+CMUX=0,0,5,256`), so a 360-character PDU line takes two frames. A DM, or no
  answer, fails the start: a close-down (CLD) goes out in case the modem did switch, and the AT commands stay on the
  raw channel. A modem that does not answer the first `AT` twice gets a blind CLD as well (it may have been left in
  multiplexer mode by an earlier start).
- **AT engine** (`at.c`): a queue of 24 commands, one running at a time with its own timeout (5 s; 90 s for `+CMGS`,
  whose network answer the modem gives up on after 60 s). The answer is cut into lines; final result codes (`OK`,
  `ERROR`, `+CME ERROR: n`, `+CMS ERROR: n`, the V.250 call codes) end the command; lines with the command's prefix go
  to its line handler; unsolicited codes are recognised by prefix wherever they come, also inside an answer, and a
  two-line code (`+CMT`, `+CDS`) gets its second line. A command with a payload waits for the `> ` prompt (no line end
  follows it), then sends the PDU and Ctrl-Z; a timeout while waiting for the prompt sends ESC. Echoed command lines
  are ignored. Three timeouts in a row restart the bring-up. `make DEFS=-DMYNA_AT_TRACE=1` writes the whole dialogue on
  the console (`at>` / `at<`).
- **Modem task** (`modem.c`): routes link bytes to the multiplexer or the AT engine, runs the bring-up and tells the
  services when the modem is ready.

The bring-up as Myna runs it (`MYNA_AT_TRACE`, loopback network, Unicorn; each command is answered within one 200 us
slice, ready 6 ms after the first byte; the `OK` after an information line is left out here):

    at> AT                       at< OK                    raw channel; echo still on, so "AT" comes back first
    at> ATE0                     at< OK
    at> AT+CMUX=0,0,5,256        at< OK                    then SABM DLC 0 / UA, SABM DLC 1 / UA, MSC on DLC 1
    at> ATE0                     at< OK                    on DLC 1 from here
    at> AT+CMEE=1                at< OK
    at> AT+CPIN?                 at< +CPIN: READY          network: card ready
    at> AT+CFUN=1                at< OK
    at> AT+CREG=2                at< OK
    at> AT+CIND=?                at< +CIND: ("signal",(0-5)),("service",(0,1)),("roam",(0,1))
    at> AT+CMER=3,0,0,1          at< OK
    at> AT+CIND?                 at< +CIND: 5,1,0
    at> AT+CMGF=0                at< OK
    at> AT+CSMS=1                at< +CSMS: 1,1,0          Myna acknowledges each message (+CNMA)
    at> AT+CSCA?                 at< +CSCA: "5550100",129
    at> AT+CNMI=2,2,0,0,0        at< OK                    messages come as +CMT
    at> AT+CNUM                  at< +CNUM: ,"+15550123",145
    at> AT+COPS=3,0              at< OK
    at> AT+COPS?                 at< +COPS: 0,0,"Simulator",0
    at> AT+CREG?                 at< +CREG: 2,1,"0001","00000001",0      network: registration 1 (home)
    at> AT                       at< OK                    modem: ready (27.010 multiplexer, DLC 1), 20 commands
    at> AT+CCLK?                 at< +CCLK: "08/10/20,12:00:00+00"       network: time ..., clock agrees

If `AT+CMUX` is refused, the same commands run on the raw channel. `make DEFS=-DMYNA_CMUX_REFUSE_TEST=1` builds a
firmware that asks for the advanced option, which the stand-in refuses, to test that path.

### Network service (`src/services/network.c`)

Keeps the card state, the registration (`+CREG` stat, location area and cell), the operator name (`+COPS?`, long
alphanumeric), the signal in bars 0-5 (the `"signal"` indicator of `+CIND`, its position read from `+CIND=?`; `+CSQ`
when the modem has no such indicator) and the own number (`+CNUM`). Changes come as unsolicited codes (`+CREG`,
`+CIEV`); the service asks only when something changed (the operator at a new registration). Subscribed tasks (the UI,
the message service) get `MSG_NETWORK_CHANGED`; the UI task sets the status bar from it with its setters: the
operator and the bars while registered (5 shows as the design's 4), "Searching" (stat 2), "No network" (0, 3, 4) or
"No SIM", the bars dimmed. At each new registration it reads `+CCLK?`; with the new
setting `net_time` (on by default) the clock offset is set to the network's local time when it differs by more than
2 s. PIN entry is not handled (closed area): a card that is not READY is only reported.

### Text messages (`src/sms/`)

- **Sending** (`sms.c`): `sms_send(number, text)` checks the number (`lib/phonenum`), plans the parts (`lib/sms_pdu`),
  stores the message as "queued" and returns its id. The service sends queued messages one at a time, oldest first,
  part by part (`AT+CMGS=<length>`, prompt, `00` + SMS-SUBMIT in hex, Ctrl-Z), whenever the modem is ready and the
  phone is registered; the network's reference of each part is kept. After every part the record is written, so a
  restart does not send a part again. Outcomes:

  | Answer | What happens |
  |---|---|
  | `+CMGS: <mr>` for the last part | "sent" |
  | `+CMS ERROR: 331` (no service), 310-318 (card), the channel restarting | not an attempt: the message waits and goes when the network is back |
  | RP causes 27, 38, 41, 42, 47 (TS 24.011 table 8.4: destination out of order, network out of order, temporary failure, congestion, resources unavailable); `+CMS ERROR: 332`, 500; no answer | tried again after 10 s, then 60 s, then "failed" with the cause |
  | any other RP cause (unassigned number, barred, rejected, invalid message ...), `+CMS ERROR: 304`, 330 ... | "failed" at once with the cause, never repeated |

- **Receiving**: `+CSMS=1` and `+CNMI=2,2`: each message comes as a `+CMT` URC, which the modem task hands to the
  message task. The PDU is decoded; a whole message is stored, a part of a concatenated one is stored as a part. Only
  then does Myna answer `AT+CNMA`. If the store is full, the answer is `AT+CNMA=2,3` with an SMS-DELIVER-REPORT whose
  TP-FCS is 0xD3 ("memory capacity exceeded": the network hears RP cause 22 and keeps the message); any other storage
  failure answers 0xFF (unspecified). When there is room again, `AT+CNMI=2,2,0,0,0` is sent once more, which tells the
  network (RP-SMMA, spec 14 7.2). Type-0 messages (TP-PID 0x40) and "discard" message-waiting indications are
  acknowledged and not kept. A status report (`+CDS`) is matched to the sent message by its reference.
- **Concatenation**: parts are kept on flash until all are there (in any order, 8-bit or 16-bit reference, up to 6
  parts), then the text is put together in order, stored as one message, and the parts are deleted.
- **Store** (`store.c`), on the user file system:

  | File | Content |
  |---|---|
  | `/sms/index` | every message's record (56 bytes: number, direction, state, phone and network times, parts sent, cause, reference, message references), oldest first; read whole at start, rewritten whole at every change (atomic in littlefs) |
  | `/sms/m/<id>` | the text (UTF-8), written once; its record at creation rides along as a littlefs attribute, so a message whose index entry was not written yet (a power cut between the two commits) is found again at the next start, and a lost index is rebuilt from the files |
  | `/sms/p/<key>-<ref>-<total>-<seq>` | one part waiting for the others (the sender's match key, the reference, the count and the part's number in the name) |
  | `/sms/d/<key>` | the unsent draft of a conversation (the number's match key in the name): its text (UTF-8), with the number and the time it was left as an attribute, in one commit; up to 16 (one more replaces the oldest); read at start, the first 48 bytes of each kept in RAM for the list. A store from before drafts gets the folder at its next start |

  The records are in RAM too, so lists, counts and states cost no flash reads; reading a text costs one file lookup.
  At most 500 messages are kept; storing one more deletes the oldest that is not waiting to be sent. States: queued,
  sent, failed (with cause), received (unread), read, delivered. A first version kept each record as an attribute of
  its file and read them all at start: 1.3 ms per message, because a littlefs path lookup costs about 1.1 ms of CPU
  here (the metadata logs of every directory on the path are read and checked). One index file makes the start
  constant.

Subscribed tasks get `MSG_SMS_EVENT` (queued, sent, failed, received, changed; b = the message id).
`sms_display_name()` gives a number's contact name.

### Contacts (`src/services/contacts.c`)

A contact is a name (given and family), up to four numbers with labels (mobile, home, work, other) and a note. Each is
kept as a vCard 3.0 file, `/contacts/<id>.vcf`, so sharing one is giving its file (`contacts_export()`), and one from
another phone is taken in with `contacts_import()`. An index file (`/contacts/index`: id, display name, the numbers'
normal forms and their match keys; 128 bytes a contact, 64 KB for 500) is read at start; a lookup by number compares
32-bit keys in RAM. Numbers match when their last 9 digits are the same (`lib/phonenum`: "+15550100123" and
"05550100123" are one person; shorter numbers match only themselves). An index of the earlier form (`CNX1`, without
the numbers) is made again from the contacts' files once.

For smart search the service keeps, in RAM only, what it made from each entry when the index was read or the entry
changed: the name's key sequence (`lib/keyseq.h`: "Anne Moss" is "2663 6677"), a mask of the keys its words start
with, masks of the digits of its numbers and of the pairs of digits next to each other, and the first 8 bytes of the
name as two numbers for the alphabet; and the alphabetical order of all of them (a merge sort, made again at each
change). `contacts_search()` compares a query with each contact (or only with those a shorter query found): the
masks dismiss most contacts with a few bit tests, the rest are compared key by key. `contacts_sorted()` copies the
order (Contacts and New message open without sorting).

### Codecs (`src/lib/`)

All written from the standards, freestanding, no allocation, tested on the host (`make host-test`: 186 checks with
vectors worked out by hand from TS 23.038 / 23.040, the examples of `spec/14-modem-at.md`, RFC 2426 / 6350, and the
keypad's letter groups of ITU-T E.161):

- `gsm7.c`: the default alphabet and extension table (TS 23.038 6.2.1), septet packing with fill bits.
- `sms_pdu.c`: SMS-SUBMIT encoding (relative validity 7 days, concatenation header with an 8-bit reference), text
  planning (the default alphabet when every character has a septet, else UCS-2; 160 / 153 septets, 70 / 67 units; an
  escape pair or a surrogate pair is never cut; at most 6 parts), SMS-DELIVER and SMS-STATUS-REPORT decoding
  (addresses including alphanumeric senders, every DCS group, time stamps with time zone to Unix time, concatenation
  with 8-bit and 16-bit references), the SMS-DELIVER-REPORT of a refusal. Characters outside the BMP go as UTF-16
  surrogate pairs.
- `vcard.c`: vCard 3.0 out (folded at 75 octets, never inside a UTF-8 character, escaped) and in: 2.1, 3.0 and 4.0
  forms (bare type parameters, groups, quoted-printable with soft breaks, `tel:` URIs, type lists).
- `phonenum.c`: normal form and the 9-digit match key. `utf8.h`: decode and encode.
- `keyseq.c`: key sequences. The key of a letter (2 abc ... 9 wxyz; Latin-1 and Latin Extended-A on their base
  letter's key, the Romanian ș ț; Cyrillic on the Russian layout 2 абвг, 3 деёжз, 4 ийкл, 5 мноп, 6 рсту, 7 фхцч,
  8 шщъы, 9 ьэюя, with ґ є і ї ў); the keys of a name with one break between words and where each key's character
  starts (for marking a match); a query at the start of a word (0 or 1 also match a break); a query inside a list of
  numbers. Predictive text's `words_key()` is this with the apostrophe on 1.

### Predictive text dictionary (`src/lib/dict.c`, `myna/tools/mkdict.py`)

32,000 English words (`assets/words/en.txt`: 12dicts 6.0.2, public domain with the AGID notice; ranked by its
frequency bands, from the BYU Corpus of Contemporary American English, a lemma's regular inflections two bands after
it; common contractions added), indexed at build time by key sequence (2 abc ... 9 wxyz, 1 for an apostrophe: "I'm"
is 416). The index is the words sorted by key sequence, then by frequency, in blocks of 16 entries; an entry is a byte
of shared letters and suffix length (front coding within the block), a byte of frequency class (16 log2 of the rank)
and the suffix's letters; a table of block offsets, and the answers for one and two keys made at build time.
195,614 bytes of `.rodata` (entries 186,637, block offsets 8,000, short table 977) and about 2 KB of code.

- `dict_exact(keys, n)`: candidate n of exactly these keys ("4663": good, gone, home, hood ...).
- `dict_prefix(keys, n)`: the beginnings of longer words, best first ("23288": "beaut"), for keys that are no word yet.
- `dict_complete(keys, shown)`: the most frequent longer word with the letters shown, when it is among the 8,000 most
  frequent, adds two letters or more and is more frequent than what is shown ("beau" -> "beauty").

A lookup is a binary search over the 2,000 blocks and a read of entries from there (the words of a key sequence and
of every longer one that starts with it are next to each other). Cost on the ARM926 (instructions, counted with
Unicorn on the firmware's code, -O2): `dict_exact` 500-2,100; `dict_prefix` 70-90 for one or two keys (the table),
2,000-64,000 typically for three or more, 110,000 at most (three keys, "266"); `dict_complete` 2,000-76,000 for three
or more keys (at most "266" "com"), 135,000 at most with two keys ("73" "re": 1,868 entries read). `make host-test` checks the orders (39 checks)
and that the build's table gives what a scan of the index gives.

### Telephony tests

- `make -C myna/firmware host-test`: the codecs on the host (with the address and undefined-behaviour sanitizers).
- `native/.venv/bin/python -I myna/firmware/test/sim_telephony.py [--core own|unicorn] [--frames DIR] [--network host|loopback|both]`
  (default engine: the compiled core when it is built, else Unicorn)
  builds the phone through the launcher's program interface and drives it with keys on Myna's own screens, as a person
  would (multi-tap included), checking the console, the PDUs and the frames. With the host network it plays the cell
  network (`take`, `result`, `incoming`, `set_service`): no service at power-on, registration; Messages, New message,
  a number typed, a text sent to the own number and received back (read where it arrives, no toast); a 3-part text
  (the box counts "3 parts"), sent as three SUBMITs under one reference; a 3-part UCS-2 text in, put together; a
  refusal (RP cause 21) shown with its reason, Retry from Options, a passing refusal (41) retried after 10 s; a 3-part
  text whose second part is refused (RP cause 21), then Retry: only parts 2 and 3 go, under the first part's
  reference; a text written without service (sent when it is back); a draft left with END (its own row in the list,
  back in the box from the list, unchanged on Back: nothing written); a text on standby (toast, envelope, "1 new message"), read in
  Messages; a contact with two numbers and a note, edited, another deleted after the question, the conversation then
  named after the contact; the dialer; the theme switched to Pebble night and the screens again; a power cycle with
  the flash state, switched off from inside a conversation with more text typed into its draft (messages, the unread
  one, the contact, the theme and both drafts come back; the draft is in the box again). With the stand-in's loopback
  network: a one-part and a 3-part text to the own number come back whole. It builds and decodes the PDUs itself.
  `--frames DIR` saves every screen state (58 with the host network, 3 with the loopback one). A build with
  `-DMYNA_TEST_HOOKS=1` and `--hooks` adds a full store (RP cause 22, then RP-SMMA), switched with the dialer's test
  codes. It switches predictive text off first in Settings (it types with multi-tap; `sim_ui.py` tests predictive text).
  Result (2026-10-14): 45 of 45 on Unicorn (33 s host time) and on the compiled core (3.8 s); the 61 frames are byte
  for byte the same on both engines; 43 of 43 with the hooks (host network) on both.
- `native/.venv/bin/python -I myna/firmware/test/stock_free.py [ARGS]` runs the same test (ARGS as above) under an
  import guard: an import of the stock modem stand-in, a stock device profile, the stock firmware's file tools or key
  table, or (without `--core unicorn`) Unicorn is refused and counted, and every file of the repository that the run
  imports must be listed in `web/platform.txt`, the list that the page's archive and the release take. Result
  (2026-10-14): 45 of 45, 51 files imported, nothing refused or unlisted.
- `native/.venv/bin/python -I myna/firmware/test/sim_organiser.py [--core own] [--frames DIR]`: the Clock, driven by
  keys: the alarm set two minutes ahead (the bell), ringing on time on a sleeping standby, Snooze, ringing again 9
  minutes later over the Clock list, unanswered for a minute (it snoozes by itself), Stop; the timer (5 s, pause,
  resume, left: it goes off over standby); the stopwatch (two laps, stop, reset); the alarm off and on; Pebble night;
  a power cycle with the flash state (the alarm and the timer's length come back) and the clock set a minute forward
  in Settings (the alarm rings at its minute of the new time). Result (2026-10-14): 17 of 17 on Unicorn (3.7 s host
  time) and on the compiled core (0.7 s); the 28 frames are byte for byte the same on both engines.
- `native/.venv/bin/python -I myna/firmware/test/sim_ui.py [--core own] [--frames DIR] [--bench]`: text input and the
  phone's own screens, driven by keys, with the host network (what was typed is read back from the PDUs): predictive
  text (one press a letter, * for the next word, 1 and * for signs, "I'm", the capital after a sentence), a word chosen
  over the first learnt and offered first, a completion taken with right, a word no list has spelt with Spell and kept
  in My words, digits on held keys; the case on *, the input methods on # held; multi-tap with # for the space and a
  sign from the symbols (* held); C held; Cyrillic received;
  the setting off and on; the keypad lock; the profiles (Silent in Settings, # held back to Normal); the four
  shortcuts; the calendar; Notes' Options; the settings tree and My words (a word forgotten); a power cycle (My words
  and the theme kept); a master reset (nothing kept). The word order it expects is computed from `assets/words/en.txt`.
  `--bench` (a BENCH build) gives the cost of keys in the text box. Result (2026-10-14): 25 of 25 on Unicorn (8.8 s
  host time) and on the compiled core (1.1 s); the 49 frames are byte for byte the same on both engines.
- `native/.venv/bin/python -I myna/firmware/test/sim_dial.py [--core own|unicorn] [--frames DIR] [--bench]`: smart
  dialling and the search in Contacts, driven by keys, with the host network: eight contacts typed into Contacts (one
  named Élodie, one with a German number), a text from a number no contact has, a text to one contact found by digits
  in the middle of his number (Message on the match: the PDU goes to that number); in the dialer, names whose keys
  clash (266: Anne and Bonn; 2663: Anne; 2666: Bonn), 0 or 1 for the break between words, the accented name by its
  first word (3563) and its second (38726), a number by its middle digits, the stranger's conversation by its digits,
  the ranking of "2" (the name's start with the most recently messaged first, then the alphabet; a later word; a
  number), a match chosen: the call key and Select (calls are not available), Options, View contact and back with the
  match still chosen, Message (the text goes to Anne's number); the setting off (no search, the card) and on again;
  Contacts searched by 5-6 (Joanna Kim, John Ray, then two found by their numbers), 5-6-4 (John Ray), C, C held,
  Back. The checks read the hits each search prints. `--bench` (a build with BENCH=1 and the test hooks) fills the
  index to 500 contacts and gives the cost of each key (see "Measurements"). Result (2026-10-14): 29 of 29 on Unicorn
  (10.4 s host time) and on the compiled core (1.1 s); the 25 frames are byte for byte the same on both engines.
  `make host-test` checks the key sequences (39 checks: the letter groups, accents, Cyrillic, names with hyphens and
  apostrophes, word starts, breaks, numbers).

## Measurements

`make clean all BENCH=1` prints, at start, the cost of drawing operations (on a scratch surface), after each key
and each animation step what it cost (`bench: key on menu: ...`), and at the sixth minute the CPU's awake time for each of minutes 2-6 (everything a minute costs: timer interrupt, event loop, clock,
redraw, panel update). Device time advances in slices of the simulator, so run with `--slice 100` (1 us):

    native/.venv/bin/python -I native/sim/db3210.py --device myna --standard --display --slice 100 --emu-seconds 400 [--core own]

Results (2026-10-14; Unicorn and the compiled core give the same numbers to within 1 us):

| What | Instructions | Emulated time |
|---|---|---|
| Reset to the kernel's event loop, blank chip (format and mount; the wallpaper expanded, the theme's tables made) | - | 10.4 ms (the modem and message tasks registered, the link set up) |
| Reset to the first full frame on the panel | - | 121.2 ms (the panel's 120 ms wake-up; Q2; the modem's bring-up and the stores' start run in it) |
| Fill 240 x 320 | 25,399 | 254 us |
| Copy 240 x 320 | 30,100 | 301 us |
| Text, 13 px, 18 characters, on a known colour / over the picture | 12,159 / 20,760 | 122 / 208 us |
| Clock, all of HH:MM (60 px Light, over the wallpaper) | 47,640 | 476 us |
| A whole minute at the home screen (one wake-up; 20,400 before the telephony; registered, one unread text) | about 21,000 | about 210 us |
| Idle, per emulated second | about 350 | 3.5 us |

A minute's panel update is one digit cell of the clock (about 2,300 pixels), not the screen. It costs about 3,400
instructions more than before the Pebble theme (17,000): the digit is now drawn over its piece of the wallpaper (a copy
of the cell, then each glyph pixel blended with what is there) instead of on a plain colour. Storage and settings add
no periodic work: still one wake-up a minute. The table of the UI's own costs is under "User interface" above.

Storage and settings (`storage:` and `settings:` lines on the console; run with `--slice 100`; instructions are the
time x 100, exact on the compiled core):

| What | Instructions | Emulated time |
|---|---|---|
| NAND: read a page (4 sectors, codes checked) | about 450 | 4-5 us |
| NAND: program a page (4 sectors with codes) | about 550 | 5-6 us |
| Format the system file system (32 blocks), blank chip | 66,800 | 668 us |
| Format the user file system (1976 blocks), blank chip | 59,700 | 597 us |
| Mount, just formatted (either) | 19,100 | 191 us |
| Mount the system file system with the settings files | 36,000-73,500 | 360-735 us (grows with the metadata log, up to 8 KB) |
| Read the settings at start: 3 files missing / 1 file / 2 files | 45,100 / 68,600 / 81,600 | 451 / 686 / 816 us |
| Write one settings file (about 20 bytes, one commit) | 33,000-58,000 | 330-580 us (grows with the metadata log) |
| Write one settings file when the log is full (compaction: erase and rewrite) | about 265,000 | 2.6-2.7 ms (one write in about 20) |

Times on the simulated chip: no time passes for a NAND operation (the chip is busy for three polls). On a phone a
page read adds some 25 us, a program some 200 us and an erase some 2 ms of waiting.

Telephony (2026-10-14, `--slice 100`, loopback network, the compiled core; Unicorn agrees within 1 %). The send and
receive figures come from `make clean all DEFS=-DMYNA_SMS_BENCH=1`, which sends three texts to its own number with the
home screen idle (nothing else runs); they are the CPU's awake time x 100, everything the service causes: link
interrupts, DMA, multiplexer, AT engine, codec, store, console line:

| What | Instructions |
|---|---|
| Bring-up: 20 commands through the multiplexer, from the first `AT` to ready | 58,000 |
| Send a one-part text, from the queue to `+CMGS` answered and the record written | 72,500 |
| Send a 3-part text (GSM 7-bit / UCS-2) | 333,000 / 422,000 |
| Receive a one-part text: `+CMT` to `AT+CNMA` queued (decode, text file, index) | 181,000-187,000 |
| Receive a part of a 3-part text (kept as a part file) | 145,000-358,000 |
| Receive the last part: put together, store, delete the parts | 0.9-1.3 million |
| A whole minute at the home screen, modem registered (BENCH=1, minutes 2-6, both engines; measured on the earlier, plainer UI: 16,870, unchanged by the modem; with the Pebble standby, one unread text: 21,000) | 16,870 / 21,000 |
| Message store start: blank / with messages (any number: one index file) | 1.96 ms / 3.4 ms of emulated time |
| Contacts start: blank / 2 contacts | 0.5 ms / 1.6 ms |

Almost all of the cost of a stored message is littlefs: a path lookup reads and checks the metadata log of every
directory on the path (about 1.1 ms of CPU for `/sms/m/<id>` when the logs are a few KB), and a store operation has two
or three of them. The modem itself adds nothing while idle: no timer runs for it, the receive interrupt wakes the CPU
when the modem has something.

## Memory layout

All addresses physical (MMU off). From `link.ld`:

| address | what |
|---|---|
| `0x00000000..0x00000040` | exception vectors, copied there by crt0 (TCM) |
| `0x48000000` | `_start`, then `.text` (226 KB, 26 KB of it littlefs, about 60 KB modem, messages, contacts and codecs, about 92 KB the applications and screens with smart search), `.rodata` (1,185 KB: about 511 KB of glyph atlases with Cyrillic, about 495 KB of images with the animated dunes, 196 KB the dictionary of predictive text), `.data`, `.bss` (124 KB: My words 15 KB, storage and settings 13 KB, link rings 8 KB, message service buffers 9 KB, the applications 42 KB (the open conversation's texts 8 KB; smart search 17 KB: the dialer's and Contacts' searches, the hits, the alphabetical order), the drawing tables of the theme 8 KB) |
| end of `.bss` (4 KB aligned) `..0x4BEEB000` | heap: the framebuffer (150 KB), the expanded wallpaper (150 KB), the two pictures of the push between screens (2 x 128 KB), the message index (36 KB), the contacts index (64 KB) and what smart search keeps of each contact (30 KB) |
| `0x4BEEB000..0x4BF00000` | stacks: UND 4 KB, ABT 4 KB, FIQ 4 KB, IRQ 8 KB, SVC 64 KB (top) |
| `0x4BF00000..0x4C000000` | reserved: the launcher keeps the stock firmware's boot-ROM stand-ins at `0x4BFFE000` (not planted for Myna); left free |

## CPU state at entry

What the launcher leaves when it jumps to the ELF entry (`_start`):

| | |
|---|---|
| state | ARM (not Thumb) |
| mode | supervisor (SVC) |
| interrupts | IRQ and FIQ masked (CPSR I and F set) |
| CPSR | Unicorn: `0x400001d3` (also A set and Z set); compiled core: `0x000000d3` |
| control register (CP15 c1) | Unicorn: `0x00090078`; compiled core: `0x00000000`. On both: MMU off, caches off, low vectors (V = 0), alignment check off |
| registers, stacks | not set: crt0 sets a stack for each mode |
| TCM | 64 KB of RAM at `0x00000000` (exception vectors go here) |
| SDRAM | `0x48000000..0x4C000000` (64 MB), zeroed except the loaded segments |
| hardware | windows at `0xA0000000` and `0xC0000000` (256 MB each; devices of the hardware models), the display controller at `0xD0000000` with `--display`; probe windows at `0x60000000` and `0x80000000` |
| shared window | `0x28000000` (14 MB): memory shared with the modem CPU; unused by Myna |
| modem CPU | not started |
| modem | the AT modem stand-in on link channel 0 (`myna/spec/14-modem-at.md`); quiet until the firmware sends a byte; Myna starts it right after the kernel starts |
| NAND | a blank chip of the stock phones' geometry (profile `NAND_CHIP`): 2048 + 64 bytes a page, 64 pages a block, 131072 pages, every byte `0xFF` until programmed; kept between runs by the flash state |

The two engines start from different reset values of CPSR and the control register; crt0 does not rely on either: it
sets mode and mask itself, and the control register reads the same in the bits that matter.

## Debug console

UART0 of the application CPU at `0xC0013000` (`spec/02-uart.md`): Myna writes a character after one status read.

## Third-party parts

- `third_party/stb/stb_truetype.h`: Sean Barrett's stb_truetype 1.26, MIT or public domain (`third_party/stb/LICENSE`).
  Compiled into the build-host tool only; nothing of it is in the firmware.
- `assets/fonts/Nunito-Light.ttf`, `Nunito-SemiBold.ttf`, `Nunito-Bold.ttf`, `Nunito-ExtraBold.ttf`: Nunito 3.601
  (the static fonts of the Nunito project), SIL Open Font License 1.1 (`assets/fonts/Nunito-OFL.txt`), no Reserved
  Font Name. The generated `build/gen/fonts_*.c` hold bitmaps rendered from them and carry the same licence.
- `assets/design/`: the design's drawings (icons, wallpapers, lettering, tile, status signs) are the project's own work,
  MIT, like the code.
- `third_party/littlefs/`: littlefs 2.11.3, BSD 3-Clause (`third_party/littlefs/LICENSE.md`), unchanged; `lfs.c` is
  compiled into the firmware. A firmware binary given to others must come with that copyright notice and licence.
- `assets/words/en.txt`: made from 12dicts 6.0.2 (Alan Beale), public domain, with the permissive notice of AGID on which
  its lemmatised lists depend (`assets/words/LICENSE-12dicts.txt`); its index is in the firmware, so a firmware binary
  should come with that file. `assets/words/extra.txt` is the project's own (MIT).

All are listed in the repository's `THIRD_PARTY.md`.
