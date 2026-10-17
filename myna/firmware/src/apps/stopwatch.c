/* SPDX-License-Identifier: MIT */
/* The stopwatch (Clock, row 3; apps/clock.h): minutes and seconds in large figures with the tenths beside them
 * ("01:23" ".4"; from an hour on "1:02:03"), and the laps under them as a list, the newest first, each with its own
 * time. Select starts and stops; the left soft key takes a lap while it runs and resets it when it is stopped. It runs
 * on when its screen is left: it is only the kernel time at which it started and what it had counted before. While its
 * screen is shown and it runs, a timer redraws it ten times a second (only the cells that changed). */
#include <stdint.h>

#include "apps/clock.h"
#include "drivers/display.h"
#include "drivers/keypad.h"
#include "kernel/timer.h"
#include "lib/mem.h"
#include "lib/print.h"
#include "ui/layout.h"
#include "ui/list.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"

#define LAPS        99
#define TICK_MS     100
#define TIMER_TICK  (UI_TIMER_SCREEN + 0)

static uint8_t running;
static ktime_t started;        /* running: when it was last started */
static ktime_t counted;        /* what it counted before that */
static uint32_t laps[LAPS];    /* the total at each lap, in ms */
static int lap_count;

static struct timer tick;
static struct digits figures;
static struct label tenths, hint;
static struct list lap_list;
static char lap_label[16], lap_value[16];
static uint8_t long_form;      /* the figures are H:MM:SS (no tenths) */

static uint32_t elapsed_ms(void)
{
    ktime_t t = counted + (running ? ktime_now() - started : 0);
    return (uint32_t)(t / KTIME_PER_MS);
}

const char *stopwatch_state(void)
{
    return running ? "Running" : counted ? "Stopped" : "";
}

static int two(char *out, unsigned v)
{
    out[0] = (char)('0' + v / 10 % 10);
    out[1] = (char)('0' + v % 10);
    return 2;
}

/* "01:23.4" (or "1:02:03.4" from an hour on) */
static void format_lap(char *out, uint32_t ms)
{
    unsigned s = ms / 1000, n = 0;
    if (s >= 3600) {
        n += (unsigned)format_uint(out, s / 3600);
        out[n++] = ':';
    }
    n += (unsigned)two(out + n, s / 60 % 60);
    out[n++] = ':';
    n += (unsigned)two(out + n, s % 60);
    out[n++] = '.';
    out[n++] = (char)('0' + ms / 100 % 10);
    out[n] = 0;
}

static const char *row_label(int row)
{
    char *p = lap_label;
    copy_text(p, "Lap ", sizeof lap_label);
    format_uint(p + 4, (unsigned)(lap_count - row));
    return p;
}

static const char *row_value(int row)
{
    int i = lap_count - 1 - row;
    format_lap(lap_value, laps[i] - (i ? laps[i - 1] : 0));
    return lap_value;
}

/* the figures' place: centred, with room for the tenths beside them (or none, from an hour on) */
static void place(int long_)
{
    const struct rect *c = &layout.content;
    long_form = (uint8_t)long_;
    struct rect row = { 0, (int16_t)(c->y + 14), DISPLAY_W, 64 };
    int sw = long_ ? 0 : gfx_text_width(theme->title_font, ".0") + 4;
    figures = (struct digits){ .r = { 0, row.y, (int16_t)(DISPLAY_W - sw), 64 }, .font = theme->clock_font,
                               .fg = ink.text, .base = (int16_t)(row.y + 52), .tracking = -1 };
    digits_set(&figures, long_ ? "0:00:00" : "00:00");
    int right = digits_left(&figures) + digits_text_width(&figures);
    tenths = (struct label){ .r = { (int16_t)(right + 3), (int16_t)(row.y + 34), (int16_t)(sw + 2), 22 },
                             .font = theme->title_font, .fg = ink.muted, .over = 1, .align = ALIGN_LEFT,
                             .base = (int16_t)(row.y + 52), .dirty = 1 };
    figures.text[0] = 0;
}

static void show(void)
{
    uint32_t ms = elapsed_ms(), s = ms / 1000;
    char t[12];
    int n = 0;
    if (s >= 3600) {
        if (!long_form)
            place(1);          /* the row is cleared at the next paint */
        n += format_uint(t, s / 3600);
        t[n++] = ':';
    }
    n += two(t + n, s / 60 % 60);
    t[n++] = ':';
    n += two(t + n, s % 60);
    t[n] = 0;
    digits_set(&figures, t);
    char d[3] = { '.', (char)('0' + ms / 100 % 10), 0 };
    label_set(&tenths, long_form ? "" : d);
    ui_changed();
}

static void soft_keys(void)
{
    ui_soft_keys(running ? "Lap" : counted ? "Reset" : "", running ? "Stop" : "Start", "Back");
}

static void laps_shown(void)
{
    const struct rect *c = &layout.content;
    struct rect r = { c->x, (int16_t)(c->y + 84), c->w, (int16_t)(6 * layout.list.row_h) };
    list_init(&lap_list, &r, lap_count);
    lap_list.label = row_label;
    lap_list.value = row_value;
    hint = (struct label){ .r = { 0, (int16_t)(c->y + 84), DISPLAY_W, 40 }, .font = theme->body, .fg = ink.muted,
                           .over = 1, .align = ALIGN_CENTRE, .base = (int16_t)(c->y + 112), .dirty = 1 };
    label_set(&hint, lap_count ? "" : running ? "Lap takes a lap time" : "Start, then Lap for lap times");
}

static void enter(int fresh)
{
    (void)fresh;
    static int made;
    if (!made) {
        ui_timer_init(&tick, TIMER_TICK);
        made = 1;
    }
    ui_title("Stopwatch");
    place(elapsed_ms() >= 3600000u);
    laps_shown();
    show();
    soft_keys();
    if (running)
        timer_start(&tick, KTIME_MS(TICK_MS), KTIME_MS(TICK_MS));
}

static void leave(void)
{
    timer_stop(&tick);
}

static void paint(const struct surface *fb)
{
    if (!figures.shown[0] && strlen(figures.text) > 5) {
        /* the long form starts: the row is cleared, the tenths go */
        struct rect row = { 0, figures.r.y, DISPLAY_W, 64 };
        ui_backdrop(fb, &row);
        display_invalidate(&row);
    }
    digits_paint(&figures, fb);
    label_paint(&tenths, fb);
    if (lap_count)
        list_paint(&lap_list, fb);
    else
        label_paint(&hint, fb);
}

static int key(unsigned k)
{
    switch (k) {
    case KEY_SELECT:
        if (running) {
            counted += ktime_now() - started;
            running = 0;
            timer_stop(&tick);
            kprintf("stopwatch: stopped at %u ms\n", elapsed_ms());
        } else {
            started = ktime_now();
            running = 1;
            timer_start(&tick, KTIME_MS(TICK_MS), KTIME_MS(TICK_MS));
            kprintf("stopwatch: started at %u ms\n", elapsed_ms());
        }
        show();
        soft_keys();
        if (!lap_count) {
            label_set(&hint, running ? "Lap takes a lap time" : "Start, then Lap for lap times");
            label_touch(&hint);
        }
        return 1;
    case KEY_SOFT_LEFT:
        if (running) {
            if (lap_count == LAPS) {
                memmove(laps, laps + 1, sizeof laps - sizeof laps[0]);
                lap_count--;
            }
            laps[lap_count++] = elapsed_ms();
            kprintf("stopwatch: lap %u at %u ms\n", lap_count, laps[lap_count - 1]);
            laps_shown();      /* the list takes the hint's place */
        } else if (counted) {
            counted = 0;
            lap_count = 0;
            kprintf("stopwatch: reset\n");
            ui_redraw();
        }
        return 1;
    case KEY_SOFT_RIGHT:
        ui_pop();
        return 1;
    case KEY_UP:
    case KEY_DOWN:
        if (lap_count)
            list_key(&lap_list, k);
        return 1;
    }
    return 0;
}

static void timer(unsigned id)
{
    if (id == TIMER_TICK)
        show();
}

const struct screen stopwatch_screen = {
    .name = "stopwatch",
    .flags = SCREEN_TITLE,
    .enter = enter,
    .leave = leave,
    .paint = paint,
    .key = key,
    .timer = timer,
};
