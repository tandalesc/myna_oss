/* SPDX-License-Identifier: MIT */
/* The status bar (ui/statusbar.h). Signs are build-time coverage masks (assets.h status_*), drawn in the theme's
 * colour; the text is drawn over the bar's rows, since those change colour from row to row. */
#include <stdint.h>

#include "assets.h"
#include "drivers/clock.h"
#include "drivers/display.h"
#include "lib/mem.h"
#include "services/settings.h"
#include "ui/layout.h"
#include "ui/statusbar.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"

struct statusbar status = { .signal = -1, .battery = -1, .network = "No network" };

void statusbar_touch(void)
{
    status.dirty = 1;
    ui_changed();
}

void statusbar_mode(int standby, int over_wallpaper)
{
    status.standby = (uint8_t)standby;
    status.over_wallpaper = (uint8_t)over_wallpaper;
    statusbar_touch();
}

void statusbar_time(void)
{
    char t[12];
    format_time(t, clock_seconds(), 1);
    if (strcmp(t, status.time) == 0)
        return;
    strcpy(status.time, t);
    if (!status.standby)
        statusbar_touch();
}

void ui_status_signal(int bars)
{
    if (bars < -1 || bars > 4 || bars == status.signal)
        return;
    status.signal = (int8_t)bars;
    statusbar_touch();
}

void ui_status_operator(const char *name)
{
    if (strcmp(name, status.network) == 0)
        return;
    unsigned i = 0;
    for (; name[i] && i + 1 < sizeof status.network; i++)
        status.network[i] = name[i];
    status.network[i] = 0;
    statusbar_touch();
}

void ui_status_unread(int messages)
{
    if (messages < 0 || messages == status.unread)
        return;
    status.unread = (uint16_t)messages;
    statusbar_touch();
}

void ui_status_alarm(int on)
{
    if (!!on == status.alarm)
        return;
    status.alarm = (uint8_t)!!on;
    statusbar_touch();
}

void ui_status_profile(int profile)
{
    if (profile == status.profile)
        return;
    status.profile = (uint8_t)profile;
    statusbar_touch();
}

void ui_status_lock(int locked)
{
    if (!!locked == status.locked)
        return;
    status.locked = (uint8_t)!!locked;
    statusbar_touch();
}

void ui_status_battery(int percent)
{
    if (percent < -1 || percent > 100 || percent == status.battery)
        return;
    status.battery = (int8_t)percent;
    statusbar_touch();
}

/* the bar's rows: opaque over the background, or the veil over the wallpaper */
static void backdrop(const struct surface *s)
{
    const struct rect *r = &layout.status;
    if (!status.over_wallpaper) {
        gfx_fill_rows(s, r, ink.status);
        return;
    }
    ui_backdrop(s, r);
    for (int y = 0; y < r->h; y++) {
        struct rect row = { r->x, (int16_t)(r->y + y), r->w, 1 };
        gfx_blend_fill(s, &row, ink.status_veil[y], ink.status_alpha[y]);
    }
}

void statusbar_paint(const struct surface *s)
{
    if (!status.dirty)
        return;
    status.dirty = 0;
    const struct rect *r = &layout.status;
    backdrop(s);

    int x = r->x + layout.status_pad, y = r->y + layout.status_sign_y;
    const struct image *bars = &status_signal[status.signal < 0 ? 0 : status.signal];
    image_draw(s, r, bars, x, y, ink.status_text);
    x += bars->w + layout.status_gap;
    gfx_text_over(s, r, theme->status_font, x, layout.status_base, status.standby ? status.network : status.time,
                  ink.status_text);

    int level = status.battery < 0 ? 0 : (status.battery + 10) / 20;
    const struct image *bat = &status_battery[level];
    int rx = r->x + r->w - layout.status_pad - bat->w;
    image_draw(s, r, bat, rx, y, ink.status_text);
    if (status.unread) {
        rx -= layout.status_gap + status_message.w;
        image_draw(s, r, &status_message, rx, y, ink.accent);
    }
    if (status.alarm) {
        rx -= layout.status_gap + status_alarm.w;
        image_draw(s, r, &status_alarm, rx, y, ink.status_text);
    }
    if (status.profile) {
        const struct image *p = status.profile == PROFILE_SILENT ? &status_silent : &status_meeting;
        rx -= layout.status_gap + p->w;
        image_draw(s, r, p, rx, y, ink.status_text);
    }
    if (status.locked) {
        rx -= layout.status_gap + status_lock.w;
        image_draw(s, r, &status_lock, rx, y, ink.status_text);
    }
    display_invalidate(r);
}
