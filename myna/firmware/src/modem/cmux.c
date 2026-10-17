/* SPDX-License-Identifier: MIT */
/* 3GPP TS 27.010 basic-option multiplexer, initiator side (modem/cmux.h). */
#include <stdint.h>

#include "kernel/timer.h"
#include "lib/mem.h"
#include "lib/print.h"
#include "modem/cmux.h"
#include "modem/link.h"

#define FLAG      0xF9
#define EA        0x01
#define CR        0x02
#define PF        0x10

/* control field values without P/F (27.010 5.2.1.3) */
#define SABM      0x2F
#define UA        0x63
#define DM        0x0F
#define DISC      0x43
#define UIH       0xEF
#define UI        0x03

/* control channel message types (27.010 5.4.6.3), with EA = 1 and C/R = 1 (command) */
#define MSG_MSC   0xE3
#define MSG_CLD   0xC3
#define MSG_NSC   0x11         /* response */

#define N1_MAX    512          /* the largest information field Myna asks for and takes */
#define T1_MS     300          /* answer time for SABM: the stand-in answers in one slice, a modem in tens of ms */
#define N2        3            /* retransmissions */

enum state { S_OFF, S_OPEN0, S_OPEN1, S_OPEN, S_FAILED };
enum rx { R_HUNT, R_ADDR, R_CTRL, R_LEN1, R_LEN2, R_INFO, R_FCS, R_END };

static enum state state;
static unsigned n1 = 31, tries;
static struct timer t1;
static cmux_data_fn on_data;
static cmux_event_fn on_event;
static struct cmux_stats stats;

static struct {
    enum rx state;
    uint8_t addr, ctrl, fcs;
    uint8_t hdr[4];            /* address, control, length octet(s): what the check sequence covers */
    unsigned hlen, len, got;
    uint8_t info[N1_MAX];
} rx;

const struct cmux_stats *cmux_stats(void)
{
    return &stats;
}

/* 27.010 5.2.1.6: CRC-8, polynomial x^8 + x^2 + x + 1, reflected, initial 0xFF, sent complemented */
static uint8_t crc_update(uint8_t c, const uint8_t *p, unsigned n)
{
    while (n--) {
        c ^= *p++;
        for (int i = 0; i < 8; i++)
            c = (c & 1) ? (uint8_t)((c >> 1) ^ 0xE0) : (uint8_t)(c >> 1);
    }
    return c;
}

static void send_frame(unsigned dlci, uint8_t control, const uint8_t *info, unsigned len)
{
    uint8_t f[N1_MAX + 8];
    unsigned n = 0;
    f[n++] = FLAG;
    f[n++] = (uint8_t)(dlci << 2 | CR | EA);  /* the initiator's commands and data carry C/R = 1 (27.010 5.2.1.2) */
    f[n++] = control;
    if (len <= 127) {
        f[n++] = (uint8_t)(len << 1 | EA);
    } else {
        f[n++] = (uint8_t)((len & 0x7F) << 1);
        f[n++] = (uint8_t)(len >> 7);
    }
    uint8_t fcs = 0xFF - crc_update(0xFF, f + 1, n - 1);   /* UIH: address, control and length only */
    memcpy(f + n, info, len);
    n += len;
    f[n++] = fcs;
    f[n++] = FLAG;
    link_write(f, n);
    stats.frames_out++;
}

static void sabm(unsigned dlci)
{
    send_frame(dlci, SABM | PF, 0, 0);
    timer_start(&t1, KTIME_MS(T1_MS), 0);
}

static void fail(const char *why)
{
    kprintf("cmux: %s: going on without the multiplexer\n", why);
    timer_stop(&t1);
    state = S_FAILED;
    on_event(CMUX_FAILED);
}

void cmux_init(struct task *t, uint16_t timer_id, cmux_data_fn data, cmux_event_fn event)
{
    timer_init(&t1, t, timer_id);
    on_data = data;
    on_event = event;
}

int cmux_running(void)
{
    return state == S_OPEN0 || state == S_OPEN1 || state == S_OPEN;
}

void cmux_start(unsigned frame_n1)
{
    n1 = frame_n1 > N1_MAX ? N1_MAX : frame_n1;
    state = S_OPEN0;
    tries = 0;
    rx.state = R_HUNT;
    sabm(0);
}

void cmux_timer(void)
{
    if (state != S_OPEN0 && state != S_OPEN1)
        return;
    if (++tries > N2) {
        fail(state == S_OPEN0 ? "no answer to SABM on DLC 0" : "no answer to SABM on DLC 1");
        return;
    }
    sabm(state == S_OPEN0 ? 0 : 1);
}

void cmux_write(const void *data, unsigned n)
{
    const uint8_t *p = data;
    while (n) {
        unsigned k = n > n1 ? n1 : n;
        send_frame(1, UIH, p, k);
        p += k;
        n -= k;
    }
}

void cmux_send_close_down(void)
{
    static const uint8_t cld[2] = { MSG_CLD, EA };   /* type, length 0 */
    send_frame(0, UIH, cld, 2);
}

/* a control message on DLC 0 from the modem */
static void control(const uint8_t *p, unsigned n)
{
    while (n >= 2) {
        uint8_t type = p[0];
        unsigned len = p[1] >> 1;
        if (2 + len > n)
            return;
        if (type == MSG_NSC)
            kprintf("cmux: the modem does not support control message %02x\n", len ? p[2] : 0);
        else if (type == MSG_CLD || type == (MSG_CLD & ~CR)) {
            /* the multiplexer closed (our close down answered): the channel is in AT mode again */
            state = S_OFF;
            on_event(CMUX_CLOSED);
        }
        /* MSC and other responses: nothing to do. The modem sends no commands of its own (spec 14 4.3). */
        p += 2 + len;
        n -= 2 + len;
    }
}

static void frame(void)
{
    unsigned dlci = rx.addr >> 2;
    uint8_t ctl = rx.ctrl & (uint8_t)~PF;
    stats.frames_in++;
    switch (ctl) {
    case UA:
        if (state == S_OPEN0 && dlci == 0) {
            state = S_OPEN1;
            tries = 0;
            sabm(1);
        } else if (state == S_OPEN1 && dlci == 1) {
            timer_stop(&t1);
            state = S_OPEN;
            /* MSC on DLC 1: RTC, RTR, DV set, FC clear (ready to receive) */
            static const uint8_t msc[4] = { MSG_MSC, 2 << 1 | EA, 1 << 2 | CR | EA, 0x8D };
            send_frame(0, UIH, msc, sizeof msc);
            kprintf("cmux: DLC 0 and DLC 1 open, N1 %u\n", n1);
            on_event(CMUX_OPEN);
        }
        break;
    case DM:
        if ((state == S_OPEN0 && dlci == 0) || (state == S_OPEN1 && dlci == 1))
            fail(dlci ? "DLC 1 refused" : "DLC 0 refused");
        else if (state == S_OPEN && dlci <= 1) {
            state = S_OFF;
            on_event(CMUX_CLOSED);
        }
        break;
    case UIH:
    case UI:
        if (dlci == 1)
            on_data(rx.info, rx.len);
        else if (dlci == 0)
            control(rx.info, rx.len);
        break;
    default:
        stats.dropped++;
    }
}

void cmux_input(const uint8_t *p, unsigned n)
{
    for (unsigned i = 0; i < n; i++) {
        uint8_t b = p[i];
        switch (rx.state) {
        case R_HUNT:
            if (b == FLAG)
                rx.state = R_ADDR;
            break;
        case R_ADDR:
            if (b == FLAG)
                break;                  /* extra flags between frames */
            rx.addr = b;
            rx.hdr[0] = b;
            rx.hlen = 1;
            rx.state = R_CTRL;
            break;
        case R_CTRL:
            rx.ctrl = b;
            rx.hdr[rx.hlen++] = b;
            rx.state = R_LEN1;
            break;
        case R_LEN1:
            rx.hdr[rx.hlen++] = b;
            rx.len = b >> 1;
            rx.got = 0;
            if (b & EA)
                rx.state = rx.len ? R_INFO : R_FCS;
            else
                rx.state = R_LEN2;
            break;
        case R_LEN2:
            rx.hdr[rx.hlen++] = b;
            rx.len |= (unsigned)b << 7;
            rx.state = rx.len ? R_INFO : R_FCS;
            if (rx.len > N1_MAX) {
                stats.dropped++;
                rx.state = R_HUNT;
            }
            break;
        case R_INFO:
            rx.info[rx.got++] = b;
            if (rx.got == rx.len)
                rx.state = R_FCS;
            break;
        case R_FCS:
            rx.fcs = b;
            rx.state = R_END;
            break;
        case R_END:
            if (b != FLAG) {
                stats.dropped++;
                rx.state = R_HUNT;
                break;
            }
            {
                /* the check over the covered octets and the FCS gives 0xCF (27.010 5.2.1.6) */
                uint8_t c = crc_update(0xFF, rx.hdr, rx.hlen);
                if ((rx.ctrl & (uint8_t)~PF) == UI)
                    c = crc_update(c, rx.info, rx.len);
                c = crc_update(c, &rx.fcs, 1);
                if (c == 0xCF)
                    frame();
                else
                    stats.bad_fcs++;
            }
            rx.state = R_ADDR;          /* the closing flag may open the next frame */
            break;
        }
    }
}
