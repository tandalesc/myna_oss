# 14 The AT modem (standard protocols on the link)

## 1. Overview

A device profile can give the link a modem stand-in that speaks standard protocols. The `myna` profile does.

| Layer | Standard | Use |
|---|---|---|
| Link | `11-modem-link.md` | Channel 0, one byte stream in each direction |
| Multiplexer | 3GPP TS 27.010, basic option | Optional. DLC 0 control, DLC 1 AT commands, DLC 2 reserved for audio |
| Commands | ITU-T V.250, 3GPP TS 27.007, 3GPP TS 27.005 | Identity, SIM card state, registration, signal, clock, radio, text messages in PDU mode |
| Text messages | 3GPP TS 23.040 (TPDUs), 3GPP TS 24.011 (RP causes) | SMS-SUBMIT out, SMS-DELIVER in |

Behind the stand-in is the simulator's cell network: the same network that the stock phones use. The configuration chooses it (section 9). A network can be "loopback" (a message comes back to the same phone) or "host" (the program around the simulator carries it, for example a web page with a connection to a relay).

The stand-in never sends first. Nothing reaches the firmware before the firmware has sent a byte on channel 0. A firmware that does not use the link sees nothing of the modem.

What is not in this interface: voice calls, packet data, USSD, cell broadcast, status reports, message storage (no `+CMGR`, `+CMGL`, `+CPMS`), text mode (`+CMGF=1`), phone book. PIN, PUK and SIM lock are a closed area: the card is always "READY" and asks for nothing.

## 2. The link channel

Use link channel 0 in both directions (`11-modem-link.md`).

| Register | Address | Value for the AT modem |
|---|---|---|
| TX_CONTROL 0 | 0xC0022000 | Bit 0 = 1. Bit 1 = 1 if transmit DMA is used. |
| TX_DATA 0 | 0xC0022020 | Bytes to the modem (1, 2 or 4 bytes per write). DMA port. |
| RX_CONTROL 0 | 0xC0022200 | Bit 0 = 1. Bit 1 = 1 if receive DMA is used. Bytes from the modem arrive only while bit 0 = 1. |
| RX_DATA 0 | 0xC0022220 | Bytes from the modem. DMA port. |
| RX_IRQ_ENABLE 0 | 0xC002220C | Bit 3 = 1: interrupt while data is available. |
| CHANNEL_IRQ_ENABLE | 0xC0022500 | Write 0x100: receive channel 0 may interrupt. |
| SLEEP | 0xC0022404 | Optional. Bit 0 = 1: data on receive channel 0 also raises line 8. |

Interrupt: line 5 (RECEIVE) is high while receive channel 0 holds data (with the two enables above). Enable line 5 in VIC0 (`03-interrupts.md`). Line 8 (WAKE) also works while SLEEP bit 0 = 1.

Rules:

- The stream has no message boundaries. The stand-in never ends a message (`TX_COMMAND`). If the firmware ends messages, the stand-in ignores the boundaries.
- The stand-in sends no wake-up kick. Its data alone raises line 5 (and line 8 while the link is asleep).
- Flow control is the FIFO only: 64 bytes in each FIFO. A byte that does not fit into TX FIFO 0 is lost (`11-modem-link.md` 2.1): check TX_STATUS bit 3 or TX_LEVEL before a write, or use DMA, which waits for space.
- Programmed I/O and DMA both work. Any DMA channel can serve a port (`13-dma.md`).

Timing [MODEL]:

- The stand-in takes the firmware's bytes after the slice in which they were written: within 200 us of emulated time. It answers in the same step. A command that needs nothing from the network is answered within one slice.
- The answer bytes enter RX FIFO 0 at once, up to 64 bytes. The stand-in refills the FIFO after each slice in which the firmware read it. Plan for at least 64 bytes per 200 us.
- A network event (a message arrives, a send is answered, the service changes) reaches the stand-in at the emulated time it happens. The bytes go into the link at once, and line 5 rises. A CPU that sleeps in wait-for-interrupt wakes at that time, also when no timer is armed. [VALIDATED by the stand-in's self-test on both CPU engines.]

## 3. Modes of the channel

At power-on the channel is in **raw mode**: it carries AT command lines and their answers (section 5) directly.

The channel changes to **multiplexer mode** in one of two ways:

1. The command `AT+CMUX=0` (section 6.10). The `OK` comes in raw mode. Every byte after the command line belongs to the multiplexer.
2. A byte 0xF9 (the 27.010 flag) where a command line would start: no line is half typed, no command is running. The multiplexer starts with the default parameters and takes the frame. [MOCK: a convenience of the stand-in; a real modem needs `AT+CMUX` first.]

The channel returns to raw mode when DLC 0 is closed: DISC on DLC 0, or the CLD message (section 4.4). The settings of the AT interpreter (echo, `+CMEE`, `+CNMI` and the others) stay.

## 4. Multiplexer (3GPP TS 27.010, basic option)

### 4.1 Parameters

| Parameter | Value |
|---|---|
| Option | Basic (flag 0xF9, no transparency). Advanced option: not supported. |
| Frame type | UIH for data and control messages (subset 0). UI frames are accepted as data. I frames: not supported. |
| Convergence layer | Type 1 (unstructured octet stream) |
| N1 | Default 31 octets, or the value of `AT+CMUX`. PN changes it for one DLC. The stand-in accepts at most 1024 [MOCK]. A received frame with a longer information field is dropped. The stand-in's own frames to the firmware are never longer than N1 of their DLC. |
| T1, N2, T2, T3, k | Stored and echoed. The stand-in never retransmits and never times out. |
| Initiator | The firmware. It opens DLC 0 first. |

### 4.2 Frames

```
F9 | address | control | length | information | FCS | F9
```

| Field | Content |
|---|---|
| Address | Bit 0 EA = 1. Bit 1 C/R. Bits 7:2 DLCI. |
| Control | SABM 0x2F, UA 0x63, DM 0x0F, DISC 0x43, UIH 0xEF, UI 0x03. Bit 4 (0x10) is P/F. |
| Length | Bit 0 EA. EA = 1: one octet, length in bits 7:1 (0 to 127). EA = 0: a second octet follows, it holds bits 14:7 of the length. |
| FCS | CRC-8 of 27.010 section 5.2.1.6: polynomial x^8 + x^2 + x + 1, bits processed least significant first, initial value 0xFF, the result is sent complemented. It covers address, control and length. For UI frames it also covers the information field. A receiver that runs the CRC over the covered octets and the FCS gets 0xCF. |

Table-free C version of the FCS:

```c
uint8_t fcs(const uint8_t *p, int n) {
    uint8_t c = 0xFF;
    while (n--) { c ^= *p++; for (int i = 0; i < 8; i++) c = (c & 1) ? (c >> 1) ^ 0xE0 : c >> 1; }
    return 0xFF - c;
}
```

C/R bit in the address (27.010 5.2.1.2). The firmware is the initiator:

| Frame | From the firmware | From the stand-in |
|---|---|---|
| SABM, DISC (commands) | C/R = 1 | (never sent) |
| UA, DM (responses) | - | C/R = 1 |
| UIH data and control messages | C/R = 1 | C/R = 0 |

The stand-in does not check the C/R bit of received frames.

A frame with a bad FCS, without a closing flag, or with a too long information field is dropped; the run log says so. The parser then looks for the next flag. A closing flag can also be the opening flag of the next frame. Extra flags between frames are allowed.

### 4.3 DLCs

| DLCI | Service | SABM is answered with |
|---|---|---|
| 0 | Control channel (section 4.4) | UA |
| 1 | AT commands (section 5) | UA, once DLC 0 is open |
| 2 | Reserved for an audio service (play a file or a tone). Not available yet. | DM |
| 3-63 | Reserved for more services (for example data) | DM |

- UA and DM carry F = 1 when the SABM or DISC had P = 1.
- DISC of an open DLC: UA, then the DLC is closed. DISC of a DLC that is not open: DM.
- DISC of DLC 0: UA, then all DLCs are closed and the channel is in raw mode.
- A UIH frame on a DLC that is not open is answered with DM (only while DLC 0 is open).
- Closing DLC 1 drops a half-typed command line and an open `>` prompt. Unsolicited result codes for a closed DLC 1 are lost; a text message for the phone is then refused (section 7.2).
- The stand-in sends no SABM, no DISC and no MSC by itself.

Examples (hexadecimal):

| What | Bytes |
|---|---|
| Firmware: SABM DLC 0, P = 1 | `F9 03 3F 01 1C F9` |
| Stand-in: UA DLC 0, F = 1 | `F9 03 73 01 D7 F9` |
| Firmware: SABM DLC 1 | `F9 07 3F 01 DE F9` |
| Stand-in: UA DLC 1 | `F9 07 73 01 15 F9` |
| Stand-in: DM DLC 2 (answer to its SABM) | `F9 0B 1F 01 73 F9` |
| Firmware: UIH DLC 1 "AT\r" | `F9 07 EF 07 41 54 0D D3 F9` |
| Stand-in: UIH DLC 1 "\r\nOK\r\n" | `F9 05 EF 0D 0D 0A 4F 4B 0D 0A 5F F9` |
| Firmware: DISC DLC 0 | `F9 03 53 01 FD F9` |

### 4.4 Control channel (DLC 0)

A control message is in the information field of a UIH frame on DLC 0: type octet, length octet(s) (as the frame length field), value. Type octet: bit 0 EA = 1, bit 1 C/R (1 = command, 0 = response), bits 7:2 the type. Several messages can share one frame.

The firmware sends commands. The stand-in answers each in its own UIH frame on DLC 0.

| Command (type octet) | Answer of the stand-in |
|---|---|
| PN 0x83, value 8 octets: DLCI, frame type and convergence layer, priority, T1, N1 (2 octets, low first), N2, k | PN response 0x81: DLCI, 0x00 (UIH, type 1), priority, T1, N1 = the asked N1 limited to 1..1024, N2, k. The N1 applies to that DLC from now on. |
| MSC 0xE3, value: address octet of the DLC (EA = 1, C/R = 1, DLCI), V.24 signals octet | MSC response 0xE1 with the same value. Signals bit 1 (FC) = 1: the stand-in sends nothing more on that DLC until an MSC with FC = 0. The other signals are ignored. |
| Test 0x23, any value | Test response 0x21 with the same value |
| FCoff 0x63 | FCoff response 0x61. The stand-in sends no more frames on DLC 1 (it keeps the bytes) until FCon. Control-channel frames still go out. |
| FCon 0xA3 | FCon response 0xA1. The kept bytes go out. |
| CLD 0xC3 | CLD response 0xC1, then the multiplexer closes: raw mode. |
| PSC, RPN, RLS, SNC and any other type | NSC response 0x11, value = the received type octet |

Responses that the firmware sends (C/R = 0) are ignored.

MSC example: firmware `F9 03 EF 09 E3 05 07 8D FB F9` (DLC 1: RTC, RTR, DV, FC = 0), stand-in `F9 01 EF 09 E1 05 07 8D 9A F9`.
CLD example: firmware `F9 03 EF 05 C3 01 F2 F9`, stand-in `F9 01 EF 05 C1 01 93 F9`.

## 5. AT command syntax

The AT channel is the raw channel in raw mode, DLC 1 in multiplexer mode. The rules are those of ITU-T V.250.

- A command line starts with `AT` (any case) and ends with CR (0x0D). LF (0x0A) is ignored. Characters before `AT` on a line are not allowed: a line that does not start with `AT` is ignored and gets no answer.
- Backspace (0x08) and DEL (0x7F) delete the last character.
- At most 560 characters per line. Characters beyond that are dropped.
- Several commands in one line: basic commands follow each other (`ATE0I`); extended commands are separated by `;` (`AT+CMEE=1;+CREG=2`). Execution stops at the first error.
- Forms: `+CMD` (action), `+CMD?` (read), `+CMD=?` (test), `+CMD=a,b` (set). Strings are in double quotes.
- Echo: on at power-on (`ATE1`). Every character of a command line, and of a PDU after a prompt, is sent back as it arrives. Turn it off with `ATE0`.
- Answers: an information line is `CR LF text CR LF`. The final result code is `CR LF OK CR LF`, `CR LF ERROR CR LF`, `CR LF +CME ERROR: n CR LF` or `CR LF +CMS ERROR: n CR LF`. Only verbose result codes (`ATV1`) exist.
- While a command line runs, the input is kept and taken after its final result code.
- A command that waits for the network (`+CMGS`) keeps the line running until the network answers.

Unsolicited result codes (URCs) have the form `CR LF text CR LF`. A URC that comes while a command line runs (also during a `>` prompt) is sent after that line's final result code.

## 6. Commands

Errors: section 8. "Card" means the configuration key `sim.present` (section 9).

### 6.1 Basic commands

| Command | Answer |
|---|---|
| `AT` | `OK` |
| `ATE0`, `ATE1` (`ATE` = `ATE0`) | Echo off / on. `OK` |
| `ATV1` | `OK` (`ATV0`: `ERROR`) |
| `ATQ0` | `OK` |
| `ATZ`, `AT&F` | The channel settings return to their power-on values: echo on, `+CMEE=0`, `+CREG=0`, `+CMER=0,0,0,0,0`, `+CNMI=0,0,0,0,0`, `+CSMS=0`, `+COPS=3,0`, the `+CMUX` parameters. Not changed: `+CFUN`, the `+COPS` mode, `+CSCA`. `OK` |
| `ATI` | Three lines: manufacturer, model, revision (as `+CGMI`, `+CGMM`, `+CGMR`). `OK` |

### 6.2 Identity (27.007) [MOCK values]

| Command | Answer |
|---|---|
| `AT+CGMI` | `Simulator` |
| `AT+CGMM` | `DB3210 AT modem stand-in` |
| `AT+CGMR` | `emu_modem_at 1` |
| `AT+CGSN` | `001010000000016` (15 digits, the last one a Luhn check digit; a made-up IMEI) |

The test form (`=?`) of each answers `OK`.

### 6.3 Errors: `AT+CMEE`

`AT+CMEE=<n>`: 0 = `ERROR` (power-on), 1 = `+CME ERROR: <code>`, 2 = `+CME ERROR: <text>`. `AT+CMEE?` gives `+CMEE: <n>`. `AT+CMEE=?` gives `+CMEE: (0-2)`.

### 6.4 The card

| Command | Card | No card |
|---|---|---|
| `AT+CPIN?` | `+CPIN: READY` | `+CME ERROR: 10` |
| `AT+CPIN=<code>` | `+CME ERROR: 3` (the card asks for nothing) | `+CME ERROR: 10` |
| `AT+CIMI` | The IMSI, for example `001010123456789` | `+CME ERROR: 10` |
| `AT+CNUM` | `+CNUM: ,"<number>",<type>` (type 145 when the number starts with `+`, else 129), then `OK`; just `OK` when no number is known | `+CME ERROR: 10` |

The number of `+CNUM` is the phone's number on the network. The program around the simulator gives it (a page: the number that the relay gave), or the configuration key `phone.number`.

### 6.5 Radio: `AT+CFUN`

| Form | Meaning |
|---|---|
| `AT+CFUN=1` | Radio on (the power-on state [MOCK]) |
| `AT+CFUN=0`, `AT+CFUN=4` | Radio off: not registered, no messages |
| `AT+CFUN?` | `+CFUN: <fun>` |
| `AT+CFUN=?` | `+CFUN: (0,1,4),(0)` |

A second parameter other than 0 (reset) is not supported: `+CME ERROR: 50`.

### 6.6 Network: `AT+COPS`, `AT+CREG`

Registration state `<stat>`:

| Stat | When |
|---|---|
| 0 | Not registered, not searching: no card, radio off, or `AT+COPS=2` |
| 1 | Registered, home network: card, radio on, and the cell network has service |
| 2 | Not registered, searching: card and radio on, and the cell network has no service, or there is no cell network (`cell.network` "off") |

Stat 5 (roaming) and 3 (denied) do not occur.

| Command | Answer |
|---|---|
| `AT+COPS?` | Registered: `+COPS: <mode>,<format>,<oper>,0` (access technology 0 = GSM). Else `+COPS: <mode>`. |
| `AT+COPS=0` | Automatic selection (power-on). `OK`. With no card: `+CME ERROR: 10`. |
| `AT+COPS=2` | Deregister. `OK`. Stat becomes 0. |
| `AT+COPS=3,<format>` | Format of `<oper>`: 0 long name, 1 short name, 2 numeric. `OK` |
| `AT+COPS=?` | Registered: `+COPS: (2,"<long>","<short>","<numeric>",0),,(0,2,3),(0-2)`. Else `+COPS: ,,(0,2,3),(0-2)`. |
| `AT+CREG=<n>` | 0 no URC (power-on), 1 URC `+CREG: <stat>`, 2 URC `+CREG: <stat>[,<lac>,<ci>,<AcT>]` |
| `AT+CREG?` | `+CREG: <n>,<stat>`; with n = 2 and stat 1 also `,"0001","00000001",0` |
| `AT+CREG=?` | `+CREG: (0-2)` |

Operator [MOCK]: long and short name = the card's service provider name (`sim.spn`, default `Simulator`); numeric = the first 5 digits of the IMSI (`00101`). Location area `0001` and cell `00000001` are [MOCK].

URC: `+CREG: <stat>` (n = 1) or `+CREG: <stat>,"0001","00000001",0` (n = 2, stat 1) each time the stat changes: service gained or lost, `+CFUN`, `+COPS=0/2`. No URC is sent when `+CREG` is set.

### 6.7 Signal: `AT+CSQ`, `AT+CIND`, `AT+CMER`

The signal follows the network's service, as on the stock phones: full signal while registered, none otherwise. It is not a radio measurement [MOCK].

| Command | Answer |
|---|---|
| `AT+CSQ` | Registered: `+CSQ: 31,99`. Else `+CSQ: 99,99`. |
| `AT+CSQ=?` | `+CSQ: (0-31,99),(0-7,99)` |
| `AT+CIND=?` | `+CIND: ("signal",(0-5)),("service",(0,1)),("roam",(0,1))` |
| `AT+CIND?` | `+CIND: <signal>,<service>,0`: registered `5,1,0`, else `0,0,0` |
| `AT+CMER=3,0,0,1` | Indicator events on: URC `+CIEV: <index>,<value>` when "signal" (index 1) or "service" (index 2) changes |
| `AT+CMER=0` | Off (power-on). Accepted values: mode 0 or 3, keyp 0, disp 0, ind 0 or 1, bfr 0. |
| `AT+CMER?` | `+CMER: <mode>,0,0,<ind>,0` |
| `AT+CMER=?` | `+CMER: (0,3),(0),(0),(0,1),(0)` |

Order of the URCs of one change: `+CREG` first, then `+CIEV: 1,...`, then `+CIEV: 2,...`.

### 6.8 Clock: `AT+CCLK?`

`+CCLK: "yy/MM/dd,hh:mm:ss+00"`: the network's time, UTC. It is 2008-10-20 12:00:00 at emulated time 0, plus the emulated time [MOCK]. Example at power-on: `+CCLK: "08/10/20,12:00:00+00"`. `AT+CCLK=...` gives `+CME ERROR: 3`.

### 6.9 Text messages (27.005), PDU mode only

| Command | Answer |
|---|---|
| `AT+CMGF=0` | `OK`. `AT+CMGF=1` (text mode): `+CMS ERROR: 303`. `AT+CMGF?`: `+CMGF: 0`. `AT+CMGF=?`: `+CMGF: (0)`. |
| `AT+CSMS=<service>` | 0 (power-on): the stand-in acknowledges each received message itself. 1: the firmware must acknowledge with `+CNMA`. Answer `+CSMS: 1,1,0` then `OK`. `AT+CSMS?`: `+CSMS: <service>,1,1,0`. |
| `AT+CSCA?` | `+CSCA: "5550100",129`: the service centre of the card [MOCK] |
| `AT+CSCA="<number>"[,<type>]` | Sets the service centre for PDUs that carry none. Kept until power-off. |
| `AT+CNMI=<mode>,<mt>,<bm>,<ds>,<bfr>` | `<mt>` = 2: received messages come as `+CMT` URCs (the only way: there is no message storage). `<mt>` = 0 (power-on): the phone takes no message; the network is told that it cannot be reached. Accepted: mode 0-2, mt 0 or 2, bm 0, ds 0, bfr 0 or 1. Other values: `+CMS ERROR: 303`. The mode is stored; URCs are always held while a command line runs and sent after it. `AT+CNMI?`: `+CNMI: <mode>,<mt>,0,0,<bfr>`. |
| `AT+CMGS=<length>` | Send a message (section 7.1). |
| `AT+CNMA` | Acknowledge a received message (section 7.2). |

### 6.10 Multiplexer: `AT+CMUX`

`AT+CMUX=<mode>[,<subset>[,<port_speed>[,<N1>[,<T1>[,<N2>[,<T2>[,<T3>[,<k>]]]]]]]]`

| Parameter | Accepted | Default |
|---|---|---|
| mode | 0 (basic option) | - |
| subset | 0 (UIH frames) | 0 |
| port_speed | 1-6 (stored, no effect) | 5 |
| N1 | 1-1024 | 31 |
| T1 | 1-255 | 10 |
| N2 | 0-100 | 3 |
| T2 | 2-255 | 30 |
| T3 | 1-255 | 10 |
| k | 1-7 | 2 |

Answer `OK`; then the channel is in multiplexer mode (section 3). Another mode or subset: `+CME ERROR: 50`. On DLC 1 (already multiplexed): `+CME ERROR: 3`. `AT+CMUX?` gives the current values, for example `+CMUX: 0,0,5,31,10,3,30,10,2`. `AT+CMUX=?` gives `+CMUX: (0),(0),(1-6),(1-1024),(1-255),(0-100),(2-255),(1-255),(1-7)`.

## 7. Text messages

### 7.1 Sending

1. The firmware sends `AT+CMGS=<length>` CR. `<length>` is the number of octets of the TPDU (the SMS-SUBMIT), without the service centre part. Range 7-175.
2. The stand-in answers with the prompt `CR LF > ` (0x0D 0x0A 0x3E 0x20).
3. The firmware sends the PDU as hexadecimal characters (upper or lower case), then Ctrl-Z (0x1A). Other characters (for example CR, LF) are ignored. ESC (0x1B) instead of Ctrl-Z cancels: `OK`, nothing is sent.
4. The PDU: the service centre address (a length octet, then type of number and swapped digits; `00` = use `+CSCA`), then the SMS-SUBMIT of 3GPP TS 23.040. Only SMS-SUBMIT (TP-MTI = 01) is accepted.
5. The stand-in gives the message a reference: it writes TP-MR (the second octet of the TPDU) with a counter 1, 2, ... 255, 0, 1 ...
6. When the network has accepted the message: `+CMGS: <mr>` then `OK`. With `+CSMS=1` and a report from the network: `+CMGS: <mr>,<SMS-SUBMIT-REPORT in hex>`.
7. When the network refuses it: `+CMS ERROR: <RP cause>` (1-127, 3GPP TS 24.011 table 8.4; a network that gives no cause: 500).

Example: "Hi" to 5550199, service centre from `+CSCA`:

```
-> AT+CMGS=14<CR>
<- <CR><LF>> 
-> 0011000781550591F90000FF02C834<Ctrl-Z>
<- <CR><LF>+CMGS: 1<CR><LF><CR><LF>OK<CR><LF>          (loopback network: 1.5 s later)
```

Errors before the message goes to the network: wrong length or not a PDU `+CMS ERROR: 304`; no service centre `+CMS ERROR: 330`; no card `+CMS ERROR: 310`; not registered (no network, no service, radio off, `+COPS=2`) `+CMS ERROR: 331`.

The stand-in sends one message at a time: the command line runs until the network answers. If the network has not answered after 60 s: `+CMS ERROR: 332` [MOCK limit]. A late answer is then ignored.

### 7.2 Receiving

Needs `AT+CNMI=<mode>,2`, the card, registration and an open AT channel. Otherwise the network is told that the phone cannot be reached, and the message is not delivered.

URC:

```
+CMT: ,<length><CR><LF><PDU in hexadecimal>
```

`<length>` is the number of octets of the TPDU. The PDU is the service centre address (length octet, type, digits) followed by the SMS-DELIVER of 3GPP TS 23.040.

Example (the loopback network gives back the message of 7.1; the sender is the number it was sent to):

```
<CR><LF>+CMT: ,19<CR><LF>0581550501F0040781550591F900008001022100000002C834<CR><LF>
```

Acknowledgement:

- `+CSMS=0` (power-on): the stand-in acknowledges the message to the network when the URC has gone out. `AT+CNMA` then gives `+CMS ERROR: 340`.
- `+CSMS=1`: the firmware must answer each `+CMT` within 30 s (TR2M):

  | Command | Effect |
  |---|---|
  | `AT+CNMA`, `AT+CNMA=0`, `AT+CNMA=1` | Accepted (RP-ACK). `OK` |
  | `AT+CNMA=2` | Refused, RP cause 111. `OK` |
  | `AT+CNMA=2,<length>` then prompt `> `, an SMS-DELIVER-REPORT in hex, Ctrl-Z | Refused. TP-FCS (the second octet) 0xD0 or 0xD3 (storage full): RP cause 22 "memory capacity exceeded", else 111. `OK` |
  | none in 30 s | The network hears RP-ERROR 111. `+CNMI` `<mt>` and `<ds>` become 0 (27.005): the firmware must give `AT+CNMI` again to receive. |
  | `AT+CNMA` with nothing to acknowledge | `+CMS ERROR: 340` |

- One message at a time: the next `+CMT` comes after the acknowledgement of the one before.
- After a refusal with cause 22, the next `AT+CNMI` with `<mt>` = 2 tells the network that the phone has room again (RP-SMMA) [MOCK: 27.005 has no command for it]. The loopback network then delivers the kept message again.

## 8. Error codes

`+CME ERROR` (27.007; with `AT+CMEE=1` the number, with 2 the text, with 0 plain `ERROR`):

| Code | Text | When |
|---|---|---|
| 3 | operation not allowed | `+CPIN=`, `+CCLK=`, `+CMUX` on DLC 1 |
| 4 | operation not supported | A form of a command that does not exist (for example `AT+CSQ?`) |
| 10 | SIM not inserted | Card commands with no card |
| 50 | incorrect parameters | A value out of range, a missing value |

`+CMS ERROR` (27.005; always the number, whatever `+CMEE` says):

| Code | When |
|---|---|
| 1-127 | The network refused the message: the RP cause |
| 302 | operation not allowed: a form of an SMS command that does not exist |
| 303 | operation not supported: `+CMGF=1`, `+CNMI` values out of range |
| 304 | invalid PDU mode parameter: bad length, bad hex, not an SMS-SUBMIT |
| 310 | SIM not inserted |
| 330 | SMSC address unknown |
| 331 | no network service |
| 332 | network timeout: no answer of the network in 60 s |
| 340 | no +CNMA acknowledgement expected |
| 500 | unknown error: the network refused without a cause |

`ERROR`: an unknown command, a syntax error, a basic command with a value it does not take.

## 9. Configuration (simulator)

The stand-in reads the configuration file of the stock modem stand-in (`docs/USING.md`, the variable `MOCK_CONFIG`), or the object that a program (a web page) gives. The keys:

| Key | Effect here |
|---|---|
| `sim.present` | Card in the holder. Default `false`: no card. |
| `sim.imsi` | `+CIMI`; MCC and MNC of the network |
| `sim.spn` | The operator name in `+COPS` [MOCK] |
| `cell.network` | `"off"` (default): no network, stat 2 for ever. `"loopback"`: every message is accepted after 1.5 s and comes back to the same phone 3 s later [MOCK]; always in service. `"host"`: the program carries the messages; no service until the program says so. |
| `phone.number` | Only this stand-in: the number for `+CNUM` (`""` = none) |

The other keys of the file have no effect here. A program can also give the number at run time.

## 10. What is [MOCK]

Identity strings and the IMEI; the operator name, numeric code, location area and cell; `+CSQ: 31,99` and 5 bars while registered; the clock's start at 2008-10-20 12:00:00 UTC; the radio on at power-on; the 60 s limit of `+CMGS`; the start of the multiplexer on a flag without `AT+CMUX`; RP-SMMA on `+CNMI`; the N1 limit of 1024; the loopback network and its delays; the service centre `5550100`.
