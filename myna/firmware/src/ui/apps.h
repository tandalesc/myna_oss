/* SPDX-License-Identifier: MIT */
/* The main menu's items, in the keypad's order (1-9, *, 0, #: STYLE.md section 2), and the screens behind them.
 *
 * An item whose screen is not built yet opens a placeholder ("coming soon", with the item's icon). Other parts of the
 * firmware provide a screen by defining it: this file refers to each one weakly, so a definition anywhere in the
 * firmware (for example `const struct screen messages_screen = { ... };` in src/sms/) replaces the placeholder without
 * a change here. The same holds for `dialer_screen`: a number key on standby opens it and passes it that key. */
#ifndef MYNA_UI_APPS_H
#define MYNA_UI_APPS_H

#include "assets.h"
#include "ui/ui.h"

/* the screens behind the items that other parts of the firmware will provide (weak: their address is 0 until
   something defines them) */
#define APP_WEAK __attribute__((weak))
extern const struct screen messages_screen APP_WEAK, contacts_screen APP_WEAK, calls_screen APP_WEAK,
    camera_screen APP_WEAK, photos_screen APP_WEAK, music_screen APP_WEAK, radio_screen APP_WEAK,
    alarms_screen APP_WEAK, calendar_screen APP_WEAK, web_screen APP_WEAK, dialer_screen APP_WEAK;
/* the items built here */
extern const struct screen notes_screen;

/* The applications' share of the UI task's messages (weak: 0 until something defines it): MSG_START (after the
 * standby screen is up), and the services' news (MSG_NETWORK_CHANGED, MSG_SMS_EVENT). src/apps/phone.c defines it. */
struct msg;
void app_event(const struct msg *m) APP_WEAK;
/* a new message from anywhere (the recipient, then the conversation): src/apps/messages.c */
void messages_compose(void) APP_WEAK;
/* Power off is starting (END held): the applications write what they keep of an open screen (weak; apps/phone.c). */
void app_power_off(void) APP_WEAK;

struct app {
    const char *name;
    unsigned key;              /* the key that opens it from the menu */
    const struct screen *screen;
};

extern const struct app apps[ICON_COUNT];      /* index = enum icon_id */

void app_open(int i);          /* open item i (enum icon_id): its screen, or the placeholder */
int app_of_key(unsigned key);  /* the item a key opens, or -1 */
/* the placeholder screen for something not built yet: its title and an icon (enum icon_id) */
void app_placeholder(const char *title, int icon);

#endif
