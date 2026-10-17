/* SPDX-License-Identifier: MIT */
/* The status bar (STYLE.md section 2, 20 px): signal bars, then the network's name on standby or the time elsewhere;
 * on the right the battery and, left of it, the signs of unread messages (in the accent) and of a set alarm. Over the
 * wallpaper on standby it is a veil; elsewhere it is opaque. The setters are in ui/ui.h (ui_status_*). */
#ifndef MYNA_UI_STATUSBAR_H
#define MYNA_UI_STATUSBAR_H

#include <stdint.h>

#include "gfx/gfx.h"

struct statusbar {
    int8_t signal;             /* bars 0-4, or -1 for no network */
    int8_t battery;            /* percent 0-100, or -1 for unknown */
    uint8_t alarm;
    uint8_t profile;           /* PROFILE_* (services/settings.h) */
    uint8_t locked;            /* the keypad lock */
    uint8_t standby;           /* show the network's name (else the time) */
    uint8_t over_wallpaper;
    uint8_t dirty;
    uint16_t unread;
    char network[24];
    char time[12];
};

extern struct statusbar status;

void statusbar_touch(void);
void statusbar_mode(int standby, int over_wallpaper);
void statusbar_time(void);                 /* the time changed (a new minute, the clock or its format set) */
void statusbar_paint(const struct surface *s);

#endif
