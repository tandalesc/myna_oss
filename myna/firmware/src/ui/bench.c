/* SPDX-License-Identifier: MIT */
/* Drawing benchmarks (make BENCH=1): the cost of the drawing operations, printed on the console once at start.
 *
 * Time is read from the OS timer, which the simulator advances in 200 us slices, so each operation is repeated until
 * the total is long enough for that not to matter. The emulated CPU runs 100 instructions per microsecond, so the
 * time is also the instruction count (exact on the compiled core; spec 00 5.1). Drawing goes to a scratch surface:
 * the screen is not touched, only its dirty list (merged into the first frame anyway). */
#include <stdint.h>

#include "assets.h"
#include "drivers/display.h"
#include "kernel/heap.h"
#include "kernel/ostimer.h"
#include "kernel/task.h"
#include "lib/print.h"
#include "ui/bench.h"
#include "ui/theme.h"

static void bench_handle(struct task *self, const struct msg *m);
static struct task task = { .name = "bench", .handle = bench_handle };

static void report(const char *what, ktime_t t0, unsigned n)
{
    uint32_t us = ktime_to_us(ktime_now() - t0);
    uint32_t per = us * 100u / n;                  /* instructions: 100 per microsecond */
    kprintf("bench: %7u instructions  %s (%u runs, %u us)\n", per, what, n, us);
}

static void run(void)
{
    const struct theme *t = theme;
    uint16_t *a = heap_take(DISPLAY_W * DISPLAY_H * 2, 32), *b = heap_take(DISPLAY_W * DISPLAY_H * 2, 32);
    if (!a || !b)
        return;
    struct surface s = { a, DISPLAY_W, DISPLAY_H, DISPLAY_W }, s2 = { b, DISPLAY_W, DISPLAY_H, DISPLAY_W };
    struct rect all = { 0, 0, DISPLAY_W, DISPLAY_H };
    ktime_t t0;
    unsigned n;

    t0 = ktime_now();
    for (n = 0; n < 200; n++)
        gfx_fill(&s, &all, (uint16_t)n);
    report("fill 240 x 320", t0, n);

    t0 = ktime_now();
    for (n = 0; n < 200; n++)
        gfx_copy(&s2, 0, 0, &s, &all);
    report("copy 240 x 320", t0, n);

    t0 = ktime_now();
    for (n = 0; n < 1000; n++)
        gfx_text(&s, 0, t->body, 10, 100, "Monday, 20 October", ink.text, (uint16_t)ink.background[100]);
    report("text 13 px, 18 characters, known background", t0, n);

    t0 = ktime_now();
    for (n = 0; n < 1000; n++)
        gfx_text_over(&s, 0, t->body, 10, 100, "Monday, 20 October", ink.text);
    report("text 13 px, 18 characters, over the picture", t0, n);

    t0 = ktime_now();
    for (n = 0; n < 500; n++)
        gfx_text_over(&s, 0, t->clock_font, 50, 90, "12:00", ink.clock);
    report("clock, all of HH:MM (60 px Light, over the wallpaper)", t0, n);

    t0 = ktime_now();
    for (n = 0; n < 2000; n++)
        image_draw(&s, 0, &icon_images[ICON_42][n % ICON_COUNT], 19, 56, 0);
    report("icon 42 px", t0, n);

    t0 = ktime_now();
    for (n = 0; n < 2000; n++)
        image_draw(&s, 0, &icon_images[ICON_50][n % ICON_COUNT], 95, 118, 0);
    report("icon 50 px", t0, n);

    t0 = ktime_now();
    for (n = 0; n < 1000; n++)
        image_draw(&s, 0, t->tile, 90, 110, 0);
    report("selection tile with its shadow", t0, n);

    t0 = ktime_now();
    for (n = 0; n < 50; n++)
        image_expand(t->wallpaper, &s2);
    report("wallpaper expanded (once per theme)", t0, n);

    struct rect cell = { 80, 108, 80, 62 };
    t0 = ktime_now();
    for (n = 0; n < 1000; n++)
        gfx_fill_rows(&s, &cell, ink.background + cell.y);
    report("menu cell background (80 x 62)", t0, n);

    struct rect box = { 7, 200, 226, 42 };
    t0 = ktime_now();
    for (n = 0; n < 1000; n++)
        gfx_round_rect(&s, 0, &box, 9, ink.surface, ink.rule);
    report("message block 226 x 42, radius 9, edge", t0, n);
}

static void bench_handle(struct task *self, const struct msg *m)
{
    (void)self;
    if (m->type == MSG_START)
        run();
}

void bench_start(void)
{
    task_add(&task);
    task_post(&task, MSG_START, 0, 0);
}
