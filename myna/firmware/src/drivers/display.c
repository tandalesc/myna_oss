/* SPDX-License-Identifier: MIT */
/* Display (drivers/display.h): framebuffer, the refresh controller of the display controller ("XGAM"), and the
 * panel's power-up (myna/spec/05-display.md).
 *
 * The refresh controller reads a rectangle of a RAM surface and sends it to the panel; nothing is sent unless the
 * firmware asks, and there is no vertical blank to wait for. So the UI draws into the framebuffer, marks what it
 * changed, and display_flush() turns the marks into as few updates as is sensible: every update costs a transfer to
 * the panel (and in the simulator a whole picture to the viewer), so near rectangles are merged into one. Updates are
 * chained on the controller's interrupt (line 18): the driver never waits for one.
 *
 * Panel power-up [spec 05 5.1, 8]: sleep out, a 120 ms wait (the time DCS panels ask before further set-up), then
 * colour order, pixel format and window; the first full frame goes out while the panel is still dark, and display on
 * follows when it has arrived, so no stale panel memory is ever shown.
 *
 * Dark (display_dark, the flip's closed lid): display off once the last update has arrived, nothing sent meanwhile,
 * display on again at light. */
#include <stdint.h>

#include "cpu.h"
#include "drivers/display.h"
#include "drivers/panel.h"
#include "hw.h"
#include "kernel/heap.h"
#include "kernel/irq.h"
#include "kernel/task.h"
#include "kernel/timer.h"
#include "lib/print.h"

/* bus and memory controller */
#define XG_VERSION      (XGAM_BASE + 0x000u)
#define XG_BANK(i)      (XGAM_BASE + 0x400u + 4u * (i))   /* 1 MB SDRAM block of GRAM bank i: physical >> 20 */
/* refresh controller */
#define RC_COMMAND      (XGAM_BASE + 0x1404u)              /* 2 = start an update */
#define RC_IRQ_ENABLE   (XGAM_BASE + 0x1418u)
#define RC_IRQ_CLEAR    (XGAM_BASE + 0x1424u)
#define RC_PANEL_SIZE   (XGAM_BASE + 0x1440u)
#define RC_OUT_DEPTH    (XGAM_BASE + 0x1444u)
#define RC_ORIGIN       (XGAM_BASE + 0x1448u)
#define RC_SIZE         (XGAM_BASE + 0x144Cu)
#define RC_SOURCE       (XGAM_BASE + 0x1450u)              /* GRAM offset: bank << 20 | offset */
#define RC_SOURCE_WIDTH (XGAM_BASE + 0x1454u)
#define RC_SOURCE_BPP   (XGAM_BASE + 0x1458u)
#define RC_ORIENTATION  (XGAM_BASE + 0x1460u)

#define PANEL_WAKE_MS   120
#define MAX_DIRTY       4

enum panel_state { PANEL_OFF, PANEL_WAKING, PANEL_FIRST_FRAME, PANEL_ON, PANEL_DARK };

static void display_handle(struct task *self, const struct msg *m);

static struct task task = { .name = "display", .handle = display_handle };
static struct timer wake_timer;
static struct surface fb;
static volatile enum panel_state state;
static struct rect dirty[MAX_DIRTY];
static int ndirty;
static volatile int busy;          /* an update is on its way to the panel */
static volatile int dark_wanted;   /* display_dark(1): display off when the updates on their way have arrived */
static struct display_stats stats;

struct task *display_task(void)
{
    return &task;
}

const struct display_stats *display_stats(void)
{
    return &stats;
}

static int area(const struct rect *r)
{
    return r->w * r->h;
}

static int touch(const struct rect *a, const struct rect *b)
{
    return a->x <= b->x + b->w && b->x <= a->x + a->w && a->y <= b->y + b->h && b->y <= a->y + a->h;
}

/* Take the next rectangle to send off the dirty list (IRQ masked). One update for everything when the union is
 * not much more than the parts: far apart small changes (a clock digit and a soft key) go as separate updates. */
static int next_update(struct rect *out)
{
    if (!ndirty)
        return 0;
    struct rect all = dirty[0];
    int sum = area(&dirty[0]);
    for (int i = 1; i < ndirty; i++) {
        all = rect_union(&all, &dirty[i]);
        sum += area(&dirty[i]);
    }
    if (area(&all) <= 2 * sum) {
        *out = all;
        ndirty = 0;
        return 1;
    }
    *out = dirty[0];
    for (int i = 1; i < ndirty; i++)
        dirty[i - 1] = dirty[i];
    ndirty--;
    return 1;
}

/* start one update (IRQ masked) */
static void send(const struct rect *r)
{
    busy = 1;
    stats.updates++;
    stats.pixels += (uint32_t)area(r);
    if (!stats.first_frame && r->w == DISPLAY_W && r->h == DISPLAY_H)
        stats.first_frame = ktime_now();
    wr32(RC_ORIGIN, (uint32_t)r->x | (uint32_t)r->y << 16);
    wr32(RC_SIZE, (uint32_t)r->w | (uint32_t)r->h << 16);
    wr32(RC_COMMAND, 2);
}

static void update_done_irq(void *arg)
{
    (void)arg;
    wr32(RC_IRQ_CLEAR, 1);
    struct rect r;
    if ((state == PANEL_FIRST_FRAME || state == PANEL_ON) && next_update(&r)) {
        send(&r);
        return;
    }
    busy = 0;
    if (state == PANEL_FIRST_FRAME || (state == PANEL_ON && dark_wanted))
        task_post(&task, MSG_DISPLAY_DONE, 0, 0);
}

void display_invalidate(const struct rect *r)
{
    struct rect screen = { 0, 0, DISPLAY_W, DISPLAY_H }, c;
    if (!rect_intersect(&c, r, &screen))
        return;
    uint32_t psr = cpu_irq_save();
    int i;
    for (i = 0; i < ndirty; i++) {
        if (touch(&dirty[i], &c)) {
            dirty[i] = rect_union(&dirty[i], &c);
            break;
        }
    }
    if (i == ndirty) {
        if (ndirty < MAX_DIRTY)
            dirty[ndirty++] = c;
        else
            dirty[MAX_DIRTY - 1] = rect_union(&dirty[MAX_DIRTY - 1], &c);
    }
    cpu_irq_restore(psr);
}

void display_flush(void)
{
    uint32_t psr = cpu_irq_save();
    struct rect r;
    if (!busy && (state == PANEL_FIRST_FRAME || state == PANEL_ON) && next_update(&r))
        send(&r);
    cpu_irq_restore(psr);
}

/* the panel's set-up once it is awake, then the first frame */
static void panel_configure(void)
{
    static const uint8_t columns[] = { 0, 0, (DISPLAY_W - 1) >> 8, (DISPLAY_W - 1) & 0xFF };
    static const uint8_t rows[] = { 0, 0, (DISPLAY_H - 1) >> 8, (DISPLAY_H - 1) & 0xFF };
    /* colour order BGR (bit 3) as the stock set-up has it (spec 05 8): the panel's own order, so that the RGB565
       framebuffer shows as written [UNCONFIRMED on hardware; the simulator shows the same either way] */
    static const uint8_t access = 0x08;
    static const uint8_t format = 0x05;    /* 16 bits per pixel */
    panel_command(DCS_ACCESS_CONTROL, &access, 1);
    panel_command(DCS_PIXEL_FORMAT, &format, 1);
    panel_command(DCS_COLUMN_WINDOW, columns, 4);
    panel_command(DCS_ROW_WINDOW, rows, 4);

    state = PANEL_FIRST_FRAME;
    struct rect screen = { 0, 0, DISPLAY_W, DISPLAY_H };
    uint32_t psr = cpu_irq_save();
    ndirty = 0;
    cpu_irq_restore(psr);
    display_invalidate(&screen);           /* whatever the UI drew meanwhile, as one full frame */
    display_flush();
}

/* display off, from the task (the panel bus is free: no update on its way) */
static void go_dark(void)
{
    panel_command(DCS_DISPLAY_OFF, 0, 0);
    state = PANEL_DARK;
    dark_wanted = 0;
    kprintf("display: panel dark\n");
}

void display_dark(int dark)
{
    if (dark) {
        display_flush();                   /* what was drawn for the dark time goes first */
        uint32_t psr = cpu_irq_save();
        int now = state == PANEL_ON && !busy;
        if (state != PANEL_DARK)
            dark_wanted = 1;               /* otherwise when the last update has arrived (update_done_irq) */
        cpu_irq_restore(psr);
        if (now)
            go_dark();
        return;
    }
    uint32_t psr = cpu_irq_save();
    int was = state == PANEL_DARK;
    dark_wanted = 0;
    if (was)
        state = PANEL_ON;
    cpu_irq_restore(psr);
    if (was) {
        panel_command(DCS_DISPLAY_ON, 0, 0);
        kprintf("display: panel on\n");
    }
}

static void display_handle(struct task *self, const struct msg *m)
{
    (void)self;
    if (m->type == MSG_TIMER && state == PANEL_WAKING) {
        panel_configure();
    } else if (m->type == MSG_DISPLAY_DONE && state == PANEL_FIRST_FRAME && dark_wanted) {
        /* dark before the panel was ever on (the flip started with its lid closed): it stays off */
        state = PANEL_DARK;
        dark_wanted = 0;
        uint32_t t = ktime_to_us(stats.first_frame);
        kprintf("display: first frame at %u.%03u ms, panel kept dark\n", t / 1000, t % 1000);
    } else if (m->type == MSG_DISPLAY_DONE && state == PANEL_ON && dark_wanted && !busy) {
        go_dark();
    } else if (m->type == MSG_DISPLAY_DONE && state == PANEL_FIRST_FRAME) {
        panel_command(DCS_DISPLAY_ON, 0, 0);
        state = PANEL_ON;
        uint8_t mode = panel_read(DCS_POWER_MODE);
        uint32_t t = ktime_to_us(stats.first_frame);
        kprintf("display: first frame at %u.%03u ms, panel on (power mode %02x)\n", t / 1000, t % 1000, mode);
        display_flush();                   /* changes made while the first frame was on its way */
    }
}

const struct surface *display_init(void)
{
    uint32_t version = rd32(XG_VERSION);
    if (((version >> 8) & 0xFF) != 0x41) {
        kprintf("display: no display controller (version %08x)\n", version);
        return 0;
    }
    uint16_t *pixels = heap_take(DISPLAY_W * DISPLAY_H * 2, 32);
    if (!pixels)
        return 0;
    fb = (struct surface){ pixels, DISPLAY_W, DISPLAY_H, DISPLAY_W };

    /* GRAM banks 1 and 2: the 1 MB blocks that hold the framebuffer (it may cross into the second) */
    uint32_t phys = (uint32_t)pixels;
    wr32(XG_BANK(1), phys >> 20);
    wr32(XG_BANK(2), (phys >> 20) + 1);
    wr32(RC_PANEL_SIZE, DISPLAY_W | DISPLAY_H << 16);
    wr32(RC_SOURCE_BPP, 16);
    wr32(RC_OUT_DEPTH, 0x10);
    wr32(RC_SOURCE, 1u << 20 | (phys & 0xFFFFFu));
    wr32(RC_SOURCE_WIDTH, DISPLAY_W);
    wr32(RC_ORIENTATION, 0);
    wr32(RC_IRQ_CLEAR, 1);
    irq_attach(IRQ_XGAM_UPDATE, update_done_irq, 0);
    wr32(RC_IRQ_ENABLE, 1);

    panel_command(DCS_SLEEP_OUT, 0, 0);
    state = PANEL_WAKING;
    timer_init(&wake_timer, &task, 0);
    timer_start(&wake_timer, KTIME_MS(PANEL_WAKE_MS), 0);
    kprintf("display: controller %08x, framebuffer %p, panel waking\n", version, (void *)pixels);
    return &fb;
}
