/* SPDX-License-Identifier: MIT */
/* The modem task (modem/modem.h). */
#include <stdint.h>

#include "kernel/task.h"
#include "kernel/timer.h"
#include "lib/print.h"
#include "modem/at.h"
#include "modem/cmux.h"
#include "modem/link.h"
#include "modem/modem.h"
#include "services/network.h"
#include "sms/sms.h"

#define N1            256      /* information field of a frame: a +CMT PDU line (up to 360 characters) in two */
#ifdef MYNA_CMUX_REFUSE_TEST
#define CMUX_COMMAND  "AT+CMUX=1,0,5,256"    /* the advanced option, which the stand-in refuses: tests the raw path */
#else
#define CMUX_COMMAND  "AT+CMUX=0,0,5,256"    /* basic option, UIH frames, 115200 (stored only), N1 */
#endif
#define PROBE_MS      1000
#define PROBES        5
#define RESTART_MS    30000
#define MAX_TIMEOUTS  3

enum { T_AT, T_CMUX, T_RESTART };

static void modem_handle(struct task *self, const struct msg *m);

static struct task task = { .name = "modem", .handle = modem_handle };
static enum modem_state state;
static uint8_t muxed;          /* AT commands go over DLC 1 */
static uint8_t mux_rx;         /* bytes from the link are multiplexer frames */
static unsigned probes;
static struct timer restart_timer;
static ktime_t started, started_busy, rx_mark;

struct task *modem_task(void)
{
    return &task;
}

enum modem_state modem_state(void)
{
    return state;
}

ktime_t modem_rx_mark(void)
{
    return rx_mark;
}

int modem_muxed(void)
{
    return muxed;
}

static void raw_write(const void *data, unsigned n)
{
    link_write(data, n);
}

static void fail(const char *why)
{
    kprintf("modem: %s; trying again in %u s\n", why, RESTART_MS / 1000);
    state = MODEM_FAILED;
    network_modem_lost();
    timer_start(&restart_timer, KTIME_MS(RESTART_MS), 0);
}

static void ready_done(void *ctx, const struct at_result *r)
{
    (void)ctx;
    if (r->status != AT_OK) {
        fail("no answer at the end of the bring-up");
        return;
    }
    state = MODEM_READY;
    kprintf("modem: ready in %u ms (%s), %u commands, %u instructions\n", ktime_to_us(ktime_now() - started) / 1000,
            muxed ? "27.010 multiplexer, DLC 1" : "raw AT channel", at_stats()->commands,
            ktime_to_us(kernel_busy() - started_busy) * 100);
    sms_modem_ready();
}

/* the AT channel works (raw or DLC 1): bring the services up, in the order of modem.h */
static void services(void)
{
    at_simple("ATE0", 0, 0);
    at_simple("AT+CMEE=1", 0, 0);
    network_bringup_card();
    network_bringup_reg();
    sms_bringup();
    network_bringup_identity();
    at_simple("AT", ready_done, 0);
}

static void mux_event(enum cmux_event ev)
{
    switch (ev) {
    case CMUX_OPEN:
        muxed = 1;
        at_set_transport(cmux_write);
        services();
        break;
    case CMUX_FAILED:
        /* close whatever the modem opened, and go on with AT commands on the raw channel */
        cmux_send_close_down();
        mux_rx = 0;
        muxed = 0;
        at_set_transport(raw_write);
        services();
        break;
    case CMUX_CLOSED:
        if (state == MODEM_READY || state == MODEM_STARTING) {
            kprintf("modem: the multiplexer closed; starting again\n");
            mux_rx = muxed = 0;
            at_reset();
            network_modem_lost();
            timer_start(&restart_timer, KTIME_MS(100), 0);
        }
        break;
    }
}

static void cmux_done(void *ctx, const struct at_result *r)
{
    (void)ctx;
    if (r->status == AT_OK) {
        mux_rx = 1;            /* every byte after the OK is a frame */
        cmux_start(N1);
    } else {
        kprintf("modem: AT+CMUX refused: AT commands on the raw channel\n");
        services();
    }
}

static void probe(void);

static void probe_done(void *ctx, const struct at_result *r)
{
    (void)ctx;
    if (r->status == AT_OK) {
        at_simple("ATE0", 0, 0);
        struct at_cmd c = { .text = CMUX_COMMAND, .done = cmux_done };
        at_send(&c);
        return;
    }
    if (++probes >= PROBES) {
        fail("the modem does not answer");
        return;
    }
    if (probes == 2)
        cmux_send_close_down();    /* a modem left in multiplexer mode by an earlier start goes back to AT */
    probe();
}

static void probe(void)
{
    struct at_cmd c = { .text = "AT", .timeout_ms = PROBE_MS, .done = probe_done };
    at_send(&c);
}

static void begin(void)
{
    state = MODEM_STARTING;
    started = ktime_now();
    started_busy = kernel_busy();
    muxed = mux_rx = 0;
    probes = 0;
    at_reset();
    at_set_transport(raw_write);
    probe();
}

static void modem_handle(struct task *self, const struct msg *m)
{
    (void)self;
    switch (m->type) {
    case MSG_START:
        begin();
        break;
    case MSG_LINK_RX: {
        uint8_t buf[256];
        unsigned n;
        rx_mark = kernel_busy();
        while ((n = link_read(buf, sizeof buf))) {
            if (mux_rx)
                cmux_input(buf, n);
            else
                at_input(buf, n);
        }
        break;
    }
    case MSG_TIMER:
        if (m->a == T_AT) {
            at_timer();
            if (state == MODEM_READY && at_stats()->consecutive_timeouts >= MAX_TIMEOUTS) {
                kprintf("modem: %u commands without an answer; starting again\n", MAX_TIMEOUTS);
                network_modem_lost();
                begin();
            }
        } else if (m->a == T_CMUX) {
            cmux_timer();
        } else if (m->a == T_RESTART) {
            begin();
        }
        break;
    }
}

void modem_init(void)
{
    timer_init(&restart_timer, &task, T_RESTART);
    at_init(&task, T_AT, raw_write);
    cmux_init(&task, T_CMUX, at_input, mux_event);
    network_init();
    sms_init();
    link_init(&task);
}
