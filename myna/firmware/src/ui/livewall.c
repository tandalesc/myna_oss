/* SPDX-License-Identifier: MIT */
/* The animated standby (ui/livewall.h). */
#include <stdint.h>

#include "assets.h"
#include "drivers/display.h"
#include "gfx/image.h"
#include "kernel/timer.h"
#include "lib/print.h"
#include "services/settings.h"
#include "ui/livewall.h"
#include "ui/theme.h"
#include "ui/ui.h"

#define FRAME_MS    100        /* 10 frames a second */
#define IDLE_FRAMES 200        /* 20 s without a key, then it comes to rest */
#define EASE_IN     16         /* speed gained per frame, of 256: full speed in 1.6 s */
#define EASE_OUT    10         /* and lost: at rest 2.6 s after it starts slowing */
#define PERIOD      240        /* a band's picture repeats every 240 px */
#define NONE        DISPLAY_H  /* no row to draw */

/* each band's speed at full speed, in 1/256 px a frame, far to near: 1.5, 2.5, 4 and 6.5 px a second */
static const uint16_t speed[LIVEWALL_LAYERS] = { 38, 64, 102, 166 };

static struct timer frame_timer;
static const struct livewall_art *shown;   /* the art whose frame the wallpaper holds, 0: the still picture */
static uint32_t acc[LIVEWALL_LAYERS];      /* each band's offset in 1/65536 px, below PERIOD */
static int16_t off[LIVEWALL_LAYERS];       /* and in whole pixels, as drawn */
static int16_t dirty = NONE;               /* the first row to draw again */
static uint16_t vel;                       /* 0..256 of full speed */
static uint16_t idle;                      /* frames since the last key */
static uint32_t frames;
static uint8_t moving, held, made;
static uint8_t paused;                     /* stopped under a toast: moves on when it goes */

/* the art to show: the theme's, if it has one and the setting wants it */
static const struct livewall_art *art(void)
{
    return settings_get(SET_WALLPAPER) ? theme->live : 0;
}

/* the frame from row y0 down, into the wallpaper: the sky alone, then each band at its offset (twice: the part that
   left at the left comes in at the right) */
static void compose(const struct livewall_art *a, const struct surface *w, int y0)
{
    struct rect clip = { 0, (int16_t)y0, PERIOD, (int16_t)(a->bottom - y0) };
    if (y0 < a->top + a->sky->h)
        image_draw(w, &clip, a->sky, 0, a->top, 0);
    for (int k = 0; k < LIVEWALL_LAYERS; k++) {
        image_draw(w, &clip, a->layer[k], -off[k], a->layer_top[k], 0);
        if (off[k])
            image_draw(w, &clip, a->layer[k], PERIOD - off[k], a->layer_top[k], 0);
    }
}

static void stop(void)
{
    timer_stop(&frame_timer);
    moving = 0;
    paused = 0;
    vel = 0;
}

static void start(void)
{
    if (moving || held || !shown || ui_current() != &home_screen)
        return;
    moving = 1;
    timer_start(&frame_timer, KTIME_MS(FRAME_MS), KTIME_MS(FRAME_MS));
}

int livewall_moving(void)
{
    return moving;
}

void livewall_enter(int wake)
{
    const struct surface *w = ui_wallpaper();
    if (!made) {
        ui_timer_init(&frame_timer, LIVEWALL_TIMER);
        made = 1;
    }
    if (!w)
        return;
    const struct livewall_art *a = art();
    if (!a) {
        stop();
        if (shown) {
            /* back to the still picture in the rows that moved */
            struct rect rows = { 0, shown->top, PERIOD, (int16_t)(shown->bottom - shown->top) };
            image_draw(w, &rows, theme->wallpaper, 0, 0, 0);
            shown = 0;
        }
        return;
    }
    /* the whole screen is drawn again from the wallpaper after enter(): the frame only needs to be in it */
    compose(a, w, a->top);
    shown = a;
    dirty = NONE;
    if (wake)
        idle = 0;
    if (wake || paused) {
        paused = 0;
        start();
    }
}

void livewall_leave(void)
{
    stop();
}

void livewall_key(void)
{
    idle = 0;
    start();
}

void livewall_hold(int on)
{
    held = (uint8_t)on;
    idle = 0;
    if (on)
        stop();
    else
        start();
}

void livewall_timer(void)
{
    if (!moving || !shown)
        return;                /* a late message */
    if (ui_overlay()) {
        /* a toast or a dialog over the standby: no frames under it (each would draw it again); the standby is drawn
           again when it goes (livewall_enter) */
        timer_stop(&frame_timer);
        moving = 0;
        paused = 1;
        return;
    }
    if (idle < IDLE_FRAMES) {
        idle++;
        vel = vel + EASE_IN < 256 ? (uint16_t)(vel + EASE_IN) : 256;
    } else if (vel > EASE_OUT) {
        vel -= EASE_OUT;
    } else {
        stop();
        kprintf("livewall: at rest after %u frames\n", frames);
        return;
    }
    frames++;
    for (int k = 0; k < LIVEWALL_LAYERS; k++) {
        acc[k] += (uint32_t)vel * speed[k];
        if (acc[k] >= (uint32_t)PERIOD << 16)
            acc[k] -= (uint32_t)PERIOD << 16;
        int16_t o = (int16_t)(acc[k] >> 16);
        if (o != off[k]) {
            off[k] = o;
            if (shown->layer_top[k] < dirty)
                dirty = shown->layer_top[k];
        }
    }
    if (dirty != NONE)
        ui_changed();
}

void livewall_paint(const struct surface *fb)
{
    const struct surface *w = ui_wallpaper();
    if (dirty == NONE || !shown || !w)
        return;
    compose(shown, w, dirty);
    struct rect r = { 0, dirty, PERIOD, (int16_t)(shown->bottom - dirty) };
    gfx_copy(fb, 0, dirty, w, &r);
    display_invalidate(&r);
    dirty = NONE;
}
