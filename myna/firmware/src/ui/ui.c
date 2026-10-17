/* SPDX-License-Identifier: MIT */
/* The user interface task (ui/ui.h): the screen stack, the bars, toasts and dialogs, power off, the slide and the
 * flip's lid. */
#include <stdint.h>

#include "drivers/backlight.h"
#include "drivers/board.h"
#include "drivers/clock.h"
#include "drivers/display.h"
#include "drivers/keypad.h"
#include "drivers/pmic.h"
#include "drivers/slide.h"
#include "fs/storage.h"
#include "kernel/heap.h"
#include "kernel/task.h"
#include "kernel/timer.h"
#include "lib/mem.h"
#include "lib/print.h"
#include "services/settings.h"
#include "ui/apps.h"
#include "ui/layout.h"
#include "ui/livewall.h"
#include "ui/statusbar.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"

#define NOTE_MS        1500
#define POWER_HOLD_MS  3000
#define POWER_NOTE_MS  500     /* "Switching off" stays this long at least */
#define FLASH_QUIET_MS 1600    /* the simulator keeps the chip from a moment 1.5 s after the last write (spec 10 4) */
#define STACK_MAX      8
#define SOFT_TEXT      20

enum { TIMER_MINUTE, TIMER_NOTE, TIMER_POWER_HOLD, TIMER_POWER_OFF, TIMER_KEY_HELD, TIMER_SLIDE };

static void ui_handle(struct task *self, const struct msg *m);

static struct task task = { .name = "ui", .handle = ui_handle };
static const struct surface *fb;
static struct surface wall;                /* the theme's wallpaper, expanded once for fast copies */
static const struct screen *stack[STACK_MAX];
static int depth;
static struct timer minute_timer, note_timer, hold_timer, off_timer, held_timer;
static unsigned held_key;      /* the key whose holding held_timer waits for */
static int paint_posted, full_redraw, switching_off;
static uint8_t asleep;         /* the flip's lid is closed: the panel is dark and nothing is drawn (lid_sleep) */

/* title bar and soft-key bar: each one widget, drawn whole when it changed */
static char title_text[32];
static char soft[3][SOFT_TEXT], soft_saved[3][SOFT_TEXT];
static uint8_t title_dirty, soft_dirty;
static const char *soft_over[3];          /* labels shown in place of the screen's (ui_soft_override) */

/* a toast or a dialog over the screen */
static char overlay_text[160];
static const struct dialog *dialog;
static struct rect overlay_box;
static uint8_t overlay_shown;

struct task *ui_task(void)
{
    return &task;
}

const struct screen *ui_current(void)
{
    return depth ? stack[depth - 1] : 0;
}

void ui_changed(void)
{
    if (!paint_posted)
        paint_posted = task_post(&task, MSG_PAINT, 0, 0);
}

void ui_timer_init(struct timer *t, unsigned id)
{
    timer_init(t, &task, (uint16_t)id);
}

const struct surface *ui_wallpaper(void)
{
    return wall.pixels ? &wall : 0;
}

int ui_overlay(void)
{
    return overlay_shown;
}

const struct rect *ui_content(void)
{
    const struct screen *s = ui_current();
    return s && (s->flags & SCREEN_TITLE) ? &layout.content : &layout.content_full;
}

void ui_backdrop(const struct surface *s, const struct rect *r)
{
    const struct screen *cur = ui_current();
    if (cur && (cur->flags & SCREEN_WALLPAPER) && wall.pixels)
        gfx_copy(s, r->x, r->y, &wall, r);
    else {
        struct rect all = { 0, 0, DISPLAY_W, DISPLAY_H }, c;
        if (rect_intersect(&c, r, &all))
            gfx_fill_rows(s, &c, ink.background + c.y);
    }
}

void ui_title(const char *text)
{
    if (strcmp(text, title_text) == 0)
        return;
    copy_text(title_text, text, sizeof title_text);
    title_dirty = 1;
    ui_changed();
}

void ui_soft_override(int which, const char *label)
{
    if (which < 0 || which > 2 || soft_over[which] == label)
        return;
    soft_over[which] = label;
    soft_dirty = 1;
    ui_changed();
}

/* the label of soft key i as shown: a dialog's, an override, or the screen's */
static const char *soft_label(int i)
{
    return !dialog && soft_over[i] ? soft_over[i] : soft[i];
}

static void clear_overrides(void)
{
    soft_over[0] = soft_over[1] = soft_over[2] = 0;
}

void ui_soft_keys(const char *left, const char *centre, const char *right)
{
    const char *t[3] = { left ? left : "", centre ? centre : "", right ? right : "" };
    for (int i = 0; i < 3; i++)
        if (strcmp(soft[i], t[i])) {
            copy_text(soft[i], t[i], SOFT_TEXT);
            soft_dirty = 1;
        }
    ui_changed();
}

/* ---- drawing of the shared parts ---- */

static void paint_title(void)
{
    if (!title_dirty || !(ui_current()->flags & SCREEN_TITLE))
        return;
    title_dirty = 0;
    const struct rect *r = &layout.title;
    gfx_fill_rows(fb, r, ink.title);
    const struct font *f = theme->title_font;
    int w = gfx_text_width(f, title_text);
    gfx_text_over(fb, r, f, r->x + (r->w - w) / 2, layout.title_base, title_text, ink.text);
    display_invalidate(r);
}

static void paint_soft_keys(void)
{
    if (!soft_dirty)
        return;
    soft_dirty = 0;
    const struct rect *r = &layout.soft_bar;
    gfx_fill_rows(fb, r, ink.bar);
    const struct font *f = theme->soft, *fc = theme->soft_centre;
    int base = layout.soft_base, pad = layout.soft_pad;
    gfx_text_over(fb, r, f, r->x + pad, base, soft_label(0), ink.bar_text);
    gfx_text_over(fb, r, f, r->x + r->w - pad - gfx_text_width(f, soft_label(2)), base, soft_label(2), ink.bar_text);
    gfx_text_over(fb, r, fc, r->x + (r->w - gfx_text_width(fc, soft_label(1))) / 2, base, soft_label(1), ink.accent);
    display_invalidate(r);
}

/* the overlay's lines: the text split at '\n' */
static int overlay_lines(const char **starts, int *lens, int max)
{
    int n = 0;
    const char *p = overlay_text;
    while (*p && n < max) {
        starts[n] = p;
        while (*p && *p != '\n')
            p++;
        lens[n] = (int)(p - starts[n]);
        n++;
        if (*p)
            p++;
    }
    return n;
}

static void paint_overlay(void)
{
    if (!overlay_shown)
        return;
    const struct font *f = theme->body;
    const char *starts[4];
    int lens[4], n = overlay_lines(starts, lens, 4), wmax = 0;
    char line[4][80];
    for (int i = 0; i < n; i++) {
        memcpy(line[i], starts[i], (size_t)lens[i]);
        line[i][lens[i]] = 0;
        int w = gfx_text_width(f, line[i]);
        wmax = w > wmax ? w : wmax;
    }
    int pad = layout.toast.pad, lh = layout.toast.line_h;
    int w = wmax + 2 * pad, h = n * lh + pad + pad / 2 + 4;
    if (w > DISPLAY_W - 24)
        w = DISPLAY_W - 24;
    const struct rect *c = ui_content();
    int y = dialog ? c->y + (c->h - h) / 2 : layout.toast.y;
    overlay_box = (struct rect){ (int16_t)((DISPLAY_W - w) / 2), (int16_t)y, (int16_t)w, (int16_t)h };
    gfx_round_rect(fb, 0, &overlay_box, theme->toast_radius, ink.toast, GFX_NO_BORDER);
    for (int i = 0; i < n; i++) {
        int lw = gfx_text_width(f, line[i]);
        gfx_text_over(fb, &overlay_box, f, overlay_box.x + (w - lw) / 2, y + pad + 1 + f->cap_height + i * lh, line[i],
                      ink.toast_text);
    }
    display_invalidate(&overlay_box);
}

/* ---- the push between screens (STYLE.md section 4): the content area slides, the bars stay ----
 *
 * Opening a screen (ui_push) or going back (ui_pop) keeps a copy of what was shown, paints the new screen as always,
 * keeps a copy of that too, and then shows SLIDE_FRAMES frames 25 ms apart in which the new picture pushes the old
 * one out sideways (from the right going in, from the left going back): each frame is two row copies per row. Paints
 * wait until it ends; a key ends it at once. A toast, END (standby), a passing step or a redraw are cuts. */
#define SLIDE_FRAMES 4
#define SLIDE_MS     25
static const int16_t slide_x[SLIDE_FRAMES] = { 156, 84, 32, 8 };  /* the old picture's share, easing out */
static uint16_t *slide_old, *slide_new;    /* the content area (layout.content_full) before and after */
static int8_t slide_dir, slide_pending;   /* +1 in, -1 back; the next paint starts it */
static uint8_t slide_step;
static struct timer slide_timer;

static void slide_keep(uint16_t *buf)
{
    const struct rect *r = &layout.content_full;
    for (int y = 0; y < r->h; y++)
        gfx_copy16(buf + y * DISPLAY_W, fb->pixels + (r->y + y) * fb->stride, DISPLAY_W);
}

/* the frame in which `old` pixels of the old picture are still in view */
static void slide_frame(int old)
{
    const struct rect *r = &layout.content_full;
    int shown = DISPLAY_W - old;
    for (int y = 0; y < r->h; y++) {
        uint16_t *row = fb->pixels + (r->y + y) * fb->stride;
        const uint16_t *o = slide_old + y * DISPLAY_W, *n = slide_new + y * DISPLAY_W;
        if (slide_dir > 0) {
            gfx_copy16(row, o + shown, (uint32_t)old);
            gfx_copy16(row + old, n, (uint32_t)shown);
        } else {
            gfx_copy16(row, n + old, (uint32_t)shown);
            gfx_copy16(row + shown, o, (uint32_t)old);
        }
    }
    display_invalidate(r);
    display_flush();
}

static void slide_end(void)
{
    if (!slide_dir)
        return;
    timer_stop(&slide_timer);
    slide_frame(0);
    slide_dir = 0;
    ui_changed();              /* what changed meanwhile */
}

static void slide_next(void)
{
    if (++slide_step < SLIDE_FRAMES)
        slide_frame(slide_x[slide_step]);
    else
        slide_end();
}

static void slide_arm(int dir)
{
    if (slide_old && depth && !overlay_shown && !asleep) {
        slide_end();
        slide_keep(slide_old);
        slide_pending = (int8_t)dir;
    }
}

static void paint(void)
{
    if (!depth || slide_dir || asleep)
        return;                /* before the first screen (MSG_START), while the push runs, or with the lid closed */
    if (full_redraw) {
        struct rect all = { 0, 0, DISPLAY_W, DISPLAY_H };
        ui_backdrop(fb, &all);
        display_invalidate(&all);
        full_redraw = 0;
    }
    ui_current()->paint(fb);
    statusbar_paint(fb);
    paint_title();
    paint_soft_keys();
    if (slide_pending) {
        slide_dir = overlay_shown ? 0 : slide_pending;
        slide_pending = 0;
        if (slide_dir) {
            slide_keep(slide_new);
            slide_step = 0;
            slide_frame(slide_x[0]);
            timer_start(&slide_timer, KTIME_MS(SLIDE_MS), KTIME_MS(SLIDE_MS));
            return;
        }
    }
    paint_overlay();
    display_flush();
}

/* everything again, from the current screen's enter(0) */
static void restyle(int fresh)
{
    slide_end();
    const struct screen *s = ui_current();
    statusbar_mode(!!(s->flags & SCREEN_STANDBY), !!(s->flags & SCREEN_WALLPAPER));
    title_dirty = 1;
    soft_dirty = 1;
    full_redraw = 1;
    s->enter(fresh);
    ui_changed();
}

void ui_redraw(void)
{
    restyle(0);
}

/* ---- the stack ---- */

static void hide_overlay(int redraw)
{
    if (!overlay_shown)
        return;
    overlay_shown = 0;
    if (dialog) {
        dialog = 0;
        memcpy(soft, soft_saved, sizeof soft);
    }
    timer_stop(&note_timer);
    if (redraw)
        ui_redraw();
}

void ui_push(const struct screen *s)
{
    hide_overlay(0);
    slide_arm(1);
    if (depth && stack[depth - 1]->leave)
        stack[depth - 1]->leave();
    if (depth == STACK_MAX)
        depth--;               /* never happens with this firmware's screens; the top is replaced */
    stack[depth++] = s;
    clear_overrides();
    title_text[0] = 0;
    restyle(1);
}

void ui_pop(void)
{
    if (depth <= 1)
        return;
    hide_overlay(0);
    slide_arm(-1);
    if (stack[depth - 1]->leave)
        stack[depth - 1]->leave();
    depth--;
    clear_overrides();
    restyle(0);
}

void ui_replace(const struct screen *s)
{
    if (depth <= 1) {
        ui_push(s);
        return;
    }
    hide_overlay(0);
    if (stack[depth - 1]->leave)
        stack[depth - 1]->leave();
    stack[depth - 1] = s;
    clear_overrides();
    title_text[0] = 0;
    restyle(1);
}

void ui_open(const struct screen *s)
{
    if (ui_in_stack(s)) {
        /* a screen keeps its state in itself, so it is on the stack once: back to it, and it starts again */
        while (ui_current() != s)
            ui_pop();
        ui_replace(s);
        return;
    }
    const struct screen *cur = ui_current();
    if (cur && (cur->flags & SCREEN_PASSING))
        ui_replace(s);
    else
        ui_push(s);
}

int ui_in_stack(const struct screen *s)
{
    for (int i = 0; i < depth; i++)
        if (stack[i] == s)
            return 1;
    return 0;
}

void ui_home(void)
{
    if (depth <= 1)
        return;
    hide_overlay(0);
    while (depth > 1) {
        if (stack[depth - 1]->leave)
            stack[depth - 1]->leave();
        depth--;
    }
    clear_overrides();
    restyle(0);
}

/* ---- toasts and dialogs ---- */

void ui_note(const char *text)
{
    ui_note_ms(text, NOTE_MS);
}

void ui_note_ms(const char *text, unsigned ms)
{
    if (dialog)
        return;                /* a dialog waits for its answer */
    if (!text[0]) {
        hide_overlay(1);
        return;
    }
    if (overlay_shown)
        ui_redraw();           /* the old box may be larger */
    copy_text(overlay_text, text, sizeof overlay_text);
    overlay_shown = 1;
    timer_start(&note_timer, KTIME_MS(ms), 0);
    ui_changed();
}

void ui_dialog(const struct dialog *d)
{
    if (overlay_shown)
        hide_overlay(1);
    dialog = d;
    copy_text(overlay_text, d->text, sizeof overlay_text);
    overlay_shown = 1;
    memcpy(soft_saved, soft, sizeof soft);
    ui_soft_keys(d->left, d->centre, d->right);
    ui_changed();
}

static void dialog_key(unsigned key)
{
    if (key != KEY_SOFT_LEFT && key != KEY_SELECT && key != KEY_SOFT_RIGHT && key != KEY_CLEAR && key != KEY_END)
        return;
    const struct dialog *d = dialog;
    hide_overlay(1);
    if (d->answer)
        d->answer(key);
}

/* ---- events ---- */

#ifdef MYNA_BENCH
/* What a minute costs: the CPU's awake time between two minute timers (the redraw, the panel update, the timer
 * interrupt, the event loop). Printed once, at the sixth minute, so that the printing is not part of what it
 * measures. Exact to the simulator's slice: run with --slice 100 for 1 us. */
static void idle_report(void)
{
    static ktime_t last;
    static uint32_t us[6];
    static unsigned n;
    ktime_t b = kernel_busy();
    if (n < 6)
        us[n] = ktime_to_us(b - last);
    last = b;
    if (++n == 6) {
        uint32_t sum = us[1] + us[2] + us[3] + us[4] + us[5];
        kprintf("bench: awake per minute (minutes 2-6): %u %u %u %u %u us; mean %u instructions per minute, "
                "%u per emulated second\n", us[1], us[2], us[3], us[4], us[5], sum * 100 / 5, sum * 100 / 300);
        kprintf("bench: start-up to the first minute: %u us awake, %u sleeps so far\n", us[0], kernel_sleeps());
        const struct display_stats *d = display_stats();
        kprintf("bench: panel updates so far %u, %u pixels (the first frame is %u)\n", d->updates, d->pixels,
                DISPLAY_W * DISPLAY_H);
    }
}

/* What a key (or a screen's timer: an animation step) costs: the CPU's awake time from its message to the end of its
 * paint (the panel update runs on after, on its interrupt). Printed for each. */
static ktime_t key_busy;
static unsigned key_pending;
static const char *key_what;
static void key_report_start(const char *what)
{
    key_busy = kernel_busy();
    key_pending = 1;
    key_what = what;
}
void ui_bench_from(uint64_t busy, const char *what)
{
    key_busy = busy;
    key_pending = 1;
    key_what = what;
}
static void key_report_end(void)
{
    if (!key_pending)
        return;
    key_pending = 0;
    const struct display_stats *d = display_stats();
    kprintf("bench: %s on %s: %u instructions to the end of its paint (panel so far %u updates, %u pixels)\n",
            key_what, ui_current()->name, ktime_to_us(kernel_busy() - key_busy) * 100, d->updates, d->pixels);
}
#endif

/* Power off: write what is pending, then wait until the chip has been quiet long enough for the simulator's flash
 * state to take it (spec 07 2.3, 10 4), then cut the system supply. */
static void begin_power_off(void)
{
    hide_overlay(1);
    ui_note("Switching off");
    switching_off = 1;
    timer_stop(&note_timer);
    if (app_power_off)
        app_power_off();       /* the applications keep what is open (a draft) */
    settings_sync();
    ktime_t now = ktime_now(), at = now + KTIME_MS(POWER_NOTE_MS), last = storage_last_write();
    if (last && last + KTIME_MS(FLASH_QUIET_MS) > at)
        at = last + KTIME_MS(FLASH_QUIET_MS);
    kprintf("ui: switching off in %u ms\n", ktime_to_us(at - now) / 1000);
    timer_start_at(&off_timer, at);
}

void ui_power_off(void)
{
    if (!switching_off)
        begin_power_off();
}

static void on_timer(unsigned id)
{
    if (id >= UI_TIMER_SCREEN) {
#ifdef MYNA_BENCH
        key_report_start("timer");
#endif
        if (ui_current()->timer)
            ui_current()->timer(id);
        return;
    }
    switch (id) {
    case TIMER_MINUTE:
#ifdef MYNA_BENCH
        idle_report();
#endif
        timer_start_at(&minute_timer, clock_next_minute());
        statusbar_time();
        if (ui_current()->timer)
            ui_current()->timer(UI_MINUTE);
        break;
    case TIMER_NOTE:
        hide_overlay(1);
        break;
    case TIMER_POWER_HOLD:
        begin_power_off();
        break;
    case TIMER_POWER_OFF:
        pmic_power_off();
        break;
    case TIMER_SLIDE:
#ifdef MYNA_BENCH
        ui_bench_from(kernel_busy(), "slide frame");
#endif
        slide_next();
#ifdef MYNA_BENCH
        key_report_end();
#endif
        break;
    case TIMER_KEY_HELD:
        if (!switching_off && !dialog) {
            kprintf("ui: key %s held (%s)\n", key_name(held_key), ui_current()->name);
            ui_current()->key(KEY_HELD | held_key);
        }
        break;
    }
}

static void key_down(unsigned key)
{
    slide_end();               /* a key ends the push at once */
    kprintf("ui: key %s down (%s)\n", key_name(key), depth ? ui_current()->name : "-");
    if (switching_off)
        return;
    if (key == KEY_END) {
        timer_start(&hold_timer, KTIME_MS(POWER_HOLD_MS), 0);
    } else {
        held_key = key;
        timer_start(&held_timer, KTIME_MS(UI_HELD_MS), 0);
    }
    if (dialog) {
        dialog_key(key);
        return;
    }
    if (overlay_shown)
        hide_overlay(1);       /* a key takes a toast away */
    if (ui_current()->key(key))
        return;
    /* what no screen uses: back goes back, END goes to standby */
    if (key == KEY_CLEAR)
        ui_pop();
    else if (key == KEY_END)
        ui_home();
}

/* ---- the flip's lid (drivers/board.h): closed, the phone sleeps; open, it is where it was ----
 *
 * Closing: the push ends, the animated standby stops, the screen is drawn black (the simulator shows every update,
 * spec 05 5.1) and the panel goes dark; nothing is drawn while the lid is closed, but everything else goes on (a text
 * arrives, a toast comes and goes, the clock turns). The keypad driver passes only the side keys meanwhile. Opening:
 * the panel lights and the screen that was shown is drawn whole, as it is now. The backlight stays as it is: its
 * commands are not known (myna/spec/QUESTIONS.md Q4). */
static void lid_sleep(void)
{
    slide_end();
    slide_pending = 0;
    asleep = 1;
    if (ui_current() == &home_screen)
        livewall_leave();
    struct rect all = { 0, 0, DISPLAY_W, DISPLAY_H };
    gfx_fill(fb, &all, 0);
    display_invalidate(&all);
    display_dark(1);
    kprintf("ui: lid closed: asleep (%s)\n", ui_current()->name);
}

static void lid_wake(void)
{
    asleep = 0;
    display_dark(0);
    kprintf("ui: lid open: awake (%s)\n", ui_current()->name);
    ui_redraw();
    if (ui_current() == &home_screen)
        livewall_key();
}

static void setting_changed(unsigned id, int32_t v)
{
    kprintf("ui: setting %s = %d\n", settings_name(id), v);
    switch (id) {
    case SET_THEME:
        theme_select(v);
        image_expand(theme->wallpaper, &wall);
        ui_redraw();
        break;
    case SET_CLOCK_OFFSET:
        clock_set_offset(v);
        timer_start_at(&minute_timer, clock_next_minute());
        statusbar_time();
        break;
    case SET_TIME_24H:
        statusbar_time();
        break;
    case SET_BRIGHTNESS:
        backlight_set_level(v);
        break;
    case SET_PROFILE:
        ui_status_profile(v);
        break;
    }
    if (ui_current()->setting)
        ui_current()->setting(id, v);
}

static void ui_handle(struct task *self, const struct msg *m)
{
    (void)self;
    switch (m->type) {
    case MSG_START:
#ifdef MYNA_UI_DEMO
        /* make DEFS=-DMYNA_UI_DEMO=1: the status bar as the telephony services will set it (the design's mock-ups) */
        ui_status_signal(3);
        ui_status_operator("Loopback");
        ui_status_unread(1);
#endif
        ui_status_profile(settings_get(SET_PROFILE));
        timer_start_at(&minute_timer, clock_next_minute());
        statusbar_time();
        stack[0] = &home_screen;
        depth = 1;
        restyle(1);
        if (board_is_flip() && !slide_is_open())
            lid_sleep();       /* switched on with the lid closed: dark until it opens */
        if (app_event)
            app_event(m);
        break;
    case MSG_TIMER:
        on_timer(m->a);
        break;
    case MSG_KEY_DOWN:
#ifdef MYNA_BENCH
        key_report_start("key");
#endif
        key_down(m->a);
        break;
    case MSG_KEY_UP:
        if (m->a == KEY_END)
            timer_stop(&hold_timer);
        else if (m->a == held_key)
            timer_stop(&held_timer);
        if (!dialog && ui_current()->key_up)
            ui_current()->key_up(m->a);
        break;
    case MSG_SLIDE:
        if (board_is_flip()) {
            /* before MSG_START the first screen is not there yet: MSG_START looks at the lid itself */
            if (depth && m->a && asleep)
                lid_wake();
            else if (depth && !m->a && !asleep)
                lid_sleep();
            break;
        }
        kprintf("ui: slide %s\n", m->a ? "open" : "closed");
        if (!switching_off)
            ui_note(m->a ? "Slide open" : "Slide closed");
        break;
    case MSG_SETTING_CHANGED:
        setting_changed(m->a, (int32_t)m->b);
        break;
    case MSG_NETWORK_CHANGED:
    case MSG_SMS_EVENT:
        /* the services' news: the applications' glue (src/apps/phone.c) shows it */
        if (app_event)
            app_event(m);
        break;
    case MSG_PAINT:
        paint_posted = 0;
        paint();
#ifdef MYNA_BENCH
        key_report_end();
#endif
        return;
    }
    ui_changed();
}

void ui_init(const struct surface *framebuffer, int battery_percent)
{
    fb = framebuffer;
    ui_status_battery(battery_percent);
    timer_init(&minute_timer, &task, TIMER_MINUTE);
    timer_init(&note_timer, &task, TIMER_NOTE);
    timer_init(&hold_timer, &task, TIMER_POWER_HOLD);
    timer_init(&off_timer, &task, TIMER_POWER_OFF);
    timer_init(&held_timer, &task, TIMER_KEY_HELD);
    timer_init(&slide_timer, &task, TIMER_SLIDE);
    slide_old = heap_take(DISPLAY_W * 274 * 2, 32);
    slide_new = heap_take(DISPLAY_W * 274 * 2, 32);
    if (!slide_new)
        slide_old = 0;
    uint16_t *px = heap_take(DISPLAY_W * DISPLAY_H * 2, 32);
    if (px) {
        wall = (struct surface){ px, DISPLAY_W, DISPLAY_H, DISPLAY_W };
        image_expand(theme->wallpaper, &wall);
    }
}
