/* SPDX-License-Identifier: MIT */
/* The standby screen (STYLE.md section 2, Pebble): the theme's wallpaper, the big clock and the date centred on its
 * sky, the status bar as a veil with the network's name, and the soft keys Messages, Menu, Contacts.
 *
 * The time follows the setting SET_TIME_24H: "14:05", or "2:05" with "PM" beside it. It changes on the UI's minute
 * timer; between minutes the phone sleeps. A new minute redraws only the digit cells that changed (each over its own
 * piece of the wallpaper), except when the time's length changes (12-hour form, 9:59 to 10:00) or AM / PM flips: then
 * the clock's row is drawn again whole. Under the date, while there are unread messages, a line in the accent says
 * how many ("1 new message"; the status bar's envelope says it too). Keys: select opens the menu, the soft keys open
 * Messages and Contacts, a number key opens the dialer when the firmware has one (ui/apps.h). With the setting
 * SET_WALLPAPER the dunes drift (ui/livewall.h) for 20 s after the standby shows or a key is pressed on it.
 *
 * The navigation key opens shortcuts: up the Clock, down Notes, left a new message, right Settings.
 *
 * Keypad lock: * then Lock (the right soft key, within 3 s) locks the keys; the padlock shows in the status bar and
 * "Keys locked" under the date, the soft keys offer only Unlock, the dunes stand still. Unlock then * (within 3 s)
 * unlocks; any other key says how. END held still switches the phone off, and a screen that opens by itself (an
 * alarm) takes its keys as usual. * followed by a number key opens the dialer with both. */
#include <stdint.h>

#include "drivers/clock.h"
#include "drivers/display.h"
#include "drivers/keypad.h"
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

static struct digits clock_face;
static struct label ampm, date, news;
static int relayout;           /* the clock's row must be cleared and drawn whole */
static int covered = 1;        /* another screen was over the standby screen (or none yet): the dunes move again */

#define ARM_MS      3000       /* * then Lock, Unlock then *: the second key within this */
#define TIMER_ARM   (UI_TIMER_SCREEN + 0)
enum { ARM_NONE, ARM_LOCK, ARM_UNLOCK };
static uint8_t locked, armed;
static struct timer arm_timer;

static void show_time(void)
{
    static const char *const weekdays[] = { "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
                                            "Sunday" };
    static const char *const months[] = { "January", "February", "March", "April", "May", "June", "July",
                                          "August", "September", "October", "November", "December" };
    uint32_t now = clock_seconds();
    struct civil_time c;
    clock_civil(now, &c);
    char hm[12];
    format_time(hm, now, 0);
    const char *suffix = settings_get(SET_TIME_24H) ? "" : c.hour < 12 ? "AM" : "PM";
    if (strlen(hm) != strlen(clock_face.text) || strcmp(suffix, ampm.text) != 0)
        relayout = 1;
    digits_set(&clock_face, hm);
    label_set(&ampm, suffix);

    char text[40];
    int n = 0;
    for (const char *p = weekdays[c.weekday]; *p; p++)
        text[n++] = *p;
    text[n++] = ' ';
    if (c.day >= 10)
        text[n++] = (char)('0' + c.day / 10);
    text[n++] = (char)('0' + c.day % 10);
    text[n++] = ' ';
    for (const char *p = months[c.month - 1]; *p; p++)
        text[n++] = *p;
    text[n] = 0;
    label_set(&date, text);
    ui_changed();
}

/* the soft keys: the screen's own, or while locked or arming only the lock's (as overrides, which the UI drops
   when another screen opens) */
static void soft_keys(void)
{
    ui_soft_keys("Messages", "Menu", "Contacts");
    int lock = locked || armed == ARM_LOCK;
    ui_soft_override(0, lock ? "" : 0);
    ui_soft_override(1, lock ? "" : 0);
    ui_soft_override(2, locked ? "Unlock" : armed == ARM_LOCK ? "Lock" : 0);
}

static void enter(int fresh)
{
    static int made;
    if (!made) {
        ui_timer_init(&arm_timer, TIMER_ARM);
        made = 1;
    }
    const struct theme *t = theme;
    soft_keys();
    clock_face = (struct digits){ .r = layout.home.clock, .font = t->clock_font, .fg = ink.clock,
                                  .base = layout.home.clock_base, .tracking = -1 };
    ampm = (struct label){ .font = t->date_font, .fg = ink.date, .over = 1, .align = ALIGN_LEFT,
                           .base = layout.home.clock_base };
    date = (struct label){ .r = layout.home.date, .font = t->date_font, .fg = ink.date, .over = 1,
                           .align = ALIGN_CENTRE, .base = layout.home.date_base, .dirty = 1 };
    news = (struct label){ .r = layout.home.news, .font = t->date_font, .fg = ink.accent, .over = 1,
                           .align = ALIGN_CENTRE, .base = layout.home.news_base, .dirty = 1 };
    relayout = 1;
    show_time();
    livewall_enter(fresh || covered);
    covered = 0;
}

static void leave(void)
{
    covered = 1;
    livewall_leave();
}

/* under the date: the lock's hint, "1 new message", "3 new messages", "Keys locked", or nothing */
static void news_text(char *out)
{
    out[0] = 0;
    if (armed) {
        copy_text(out, armed == ARM_LOCK ? "Press Lock to lock the keys" : "Now press * to unlock", 32);
        return;
    }
    if (!status.unread) {
        if (locked)
            copy_text(out, "Keys locked", 32);
        return;
    }
    int n = format_uint(out, status.unread);
    copy_text(out + n, status.unread == 1 ? " new message" : " new messages", 20);
}

static void paint(const struct surface *fb)
{
    livewall_paint(fb);        /* below the clock and the date: never under them */
    if (relayout) {
        relayout = 0;
        /* with AM / PM the clock and its suffix are centred together */
        int sw = ampm.text[0] ? gfx_text_width(ampm.font, ampm.text) + layout.home.ampm_gap : 0;
        clock_face.r = layout.home.clock;
        clock_face.r.w = (int16_t)(clock_face.r.w - sw);
        ui_backdrop(fb, &layout.home.clock);
        display_invalidate(&layout.home.clock);
        digits_touch(&clock_face);
        if (ampm.text[0]) {
            int right = digits_left(&clock_face) + digits_text_width(&clock_face);
            ampm.r = (struct rect){ (int16_t)(right + layout.home.ampm_gap), (int16_t)(layout.home.clock_base - 16),
                                    (int16_t)(sw + 2), 20 };
            label_touch(&ampm);
        }
    }
    digits_paint(&clock_face, fb);
    if (ampm.text[0])
        label_paint(&ampm, fb);
    label_paint(&date, fb);
    char t[32];
    news_text(t);
    label_set(&news, t);       /* the unread count changes through the status bar's setter, which paints */
    label_paint(&news, fb);
}

static void arm(int what)
{
    armed = (uint8_t)what;
    if (what)
        timer_start(&arm_timer, KTIME_MS(ARM_MS), 0);
    else
        timer_stop(&arm_timer);
    soft_keys();
    ui_changed();
}

static void set_locked(int on)
{
    locked = (uint8_t)on;
    kprintf("ui: keypad %s\n", on ? "locked" : "unlocked");
    ui_status_lock(on);
    livewall_hold(on);
    arm(ARM_NONE);
    ui_note(on ? "Keypad locked" : "Keypad unlocked");
}

static int dialing(unsigned k)
{
    return k == KEY_0 || k == KEY_1 || k == KEY_2 || k == KEY_3 || k == KEY_4 || k == KEY_5 || k == KEY_6 || k == KEY_7 ||
           k == KEY_8 || k == KEY_9 || k == KEY_STAR || k == KEY_HASH;
}

/* the keys while the keypad is locked: Unlock then *; every other key says how */
static int locked_key(unsigned k)
{
    if (k & KEY_HELD)
        return 1;
    if (k == KEY_SOFT_RIGHT) {
        arm(ARM_UNLOCK);
        return 1;
    }
    if (k == KEY_STAR && armed == ARM_UNLOCK) {
        set_locked(0);
        return 1;
    }
    arm(ARM_NONE);
    if (k != KEY_END)
        ui_note_ms("The keys are locked.\nPress Unlock, then *.", 2000);
    return 1;
}

static int key(unsigned k)
{
    if (locked)
        return locked_key(k);
    livewall_key();
    if (armed == ARM_LOCK) {
        arm(ARM_NONE);
        if (k == KEY_SOFT_RIGHT) {
            set_locked(1);
            return 1;
        }
        if (dialing(k) && &dialer_screen) {
            /* * and a number key: the dialer with both */
            ui_push(&dialer_screen);
            dialer_screen.key(KEY_STAR);
            dialer_screen.key(k);
            return 1;
        }
    }
    switch (k) {
    case KEY_STAR:
        arm(ARM_LOCK);
        return 1;
    case KEY_UP:
        app_open(ICON_ALARM);
        return 1;
    case KEY_DOWN:
        app_open(ICON_NOTES);
        return 1;
    case KEY_LEFT:
        if (messages_compose)
            messages_compose();
        return 1;
    case KEY_RIGHT:
        app_open(ICON_SETTINGS);
        return 1;
    case KEY_SELECT:
        ui_push(&menu_screen);
        return 1;
    case KEY_SOFT_LEFT:
        app_open(ICON_MESSAGES);
        return 1;
    case KEY_SOFT_RIGHT:
        app_open(ICON_CONTACTS);
        return 1;
    }
    if (dialing(k) && &dialer_screen) {
        ui_push(&dialer_screen);
        dialer_screen.key(k);
        return 1;
    }
    return 0;
}

static void timer(unsigned id)
{
    if (id == UI_MINUTE)
        show_time();
    else if (id == TIMER_ARM)
        arm(ARM_NONE);
    else if (id == LIVEWALL_TIMER)
        livewall_timer();
}

static void setting(unsigned id, int32_t v)
{
    (void)v;
    if (id == SET_TIME_24H || id == SET_CLOCK_OFFSET)
        show_time();
    if (id == SET_WALLPAPER) {
        covered = 1;           /* the new choice shows, and moves if it is the animated one */
        ui_redraw();
    }
}

const struct screen home_screen = {
    .name = "home",
    .flags = SCREEN_WALLPAPER | SCREEN_STANDBY,
    .enter = enter,
    .leave = leave,
    .paint = paint,
    .key = key,
    .timer = timer,
    .setting = setting,
};
