/* SPDX-License-Identifier: MIT */
/* The user interface task, its screen stack and what every screen shares.
 *
 * One task ("ui") owns the framebuffer and everything on it. It keeps the parts every screen shares: the status bar,
 * the title bar, the soft-key bar (three labels: left, centre in the accent, right), toasts and dialogs, the power-off
 * hold of END, the slide's messages, the theme and a timer at each new minute. Screens are on a stack: the standby
 * screen at the bottom, ui_push() opens one over the current, ui_pop() goes back to the one under it, which finds its
 * state as it left it. Like every task the UI paints once per batch of events (a MSG_PAINT it posts to itself), and
 * only what changed: widgets remember whether they changed, and only their rectangles go to the panel.
 *
 * Every function here is for the UI task's own code or for other tasks' message handlers (the kernel runs one handler
 * at a time, so a setter called from another task is safe); none may be called from an interrupt handler. */
#ifndef MYNA_UI_UI_H
#define MYNA_UI_UI_H

#include <stdint.h>

#include "gfx/gfx.h"

struct task;
struct timer;

/* timer ids of a screen start here (ui_timer_init); smaller ones are the UI's own */
#define UI_TIMER_SCREEN 16
/* the id a screen's timer() gets at each new minute */
#define UI_MINUTE       0
/* A key held down for UI_HELD_MS comes to the screen's key() a second time, as KEY_HELD | key (its first press came
 * as the key alone). A screen that does not use it returns 0, and a held key nobody uses does nothing. END is not
 * passed on held: holding it switches the phone off. */
#define KEY_HELD        0x100
#define UI_HELD_MS      700

/* screen flags */
#define SCREEN_TITLE     1     /* a title bar under the status bar (ui_title); content is layout.content */
#define SCREEN_WALLPAPER 2     /* the theme's wallpaper behind everything (standby); content is layout.content_full */
#define SCREEN_STANDBY   4     /* the status bar shows the network's name, not the time */
#define SCREEN_PASSING   8     /* a step on the way (a choice, an editor, a picker): ui_open() replaces it */

struct screen {
    const char *name;
    uint8_t flags;
    /* Build the widgets from the current theme and mark everything for drawing (the UI has cleared the content).
       fresh = 1 when the screen is opened; 0 when it shows again (the screen over it was closed, the theme changed,
       a toast went away): keep the screen's state. */
    void (*enter)(int fresh);
    void (*leave)(void);                   /* closed (popped); may be 0 */
    void (*paint)(const struct surface *fb);
    int (*key)(unsigned key);              /* a key went down; return 1 if the screen used it */
    void (*key_up)(unsigned key);          /* a key went up; may be 0 */
    void (*timer)(unsigned id);            /* UI_MINUTE, or a timer of the screen's own; may be 0 */
    void (*setting)(unsigned id, int32_t value);    /* a setting changed (after the UI applied it); may be 0 */
};

void ui_init(const struct surface *framebuffer, int battery_percent);
struct task *ui_task(void);

/* ---- the screen stack ---- */
void ui_push(const struct screen *s);      /* open s over the current screen */
void ui_pop(void);                         /* close the current screen (not the standby screen) */
void ui_replace(const struct screen *s);   /* close the current screen and open s in its place */
void ui_home(void);                        /* close everything over the standby screen */
/* open s: ui_replace() over a SCREEN_PASSING screen, else ui_push(); a screen already open is gone back to and
   started again (a screen keeps its state in itself, so it is on the stack once) */
void ui_open(const struct screen *s);
const struct screen *ui_current(void);
int ui_in_stack(const struct screen *s);   /* s is open (shown, or under the current screen) */
#ifdef MYNA_BENCH
/* report the CPU's work from `busy` (a kernel_busy() value) to the end of the next paint, as "bench: what on ..." */
void ui_bench_from(uint64_t busy, const char *what);
#endif

/* ---- shared parts, for the screens ---- */
void ui_title(const char *text);           /* the title bar's text (SCREEN_TITLE) */
/* the three soft-key labels; 0 or "" for none. The texts are copied. */
void ui_soft_keys(const char *left, const char *centre, const char *right);
/* a label shown on soft key `which` (0 left, 1 centre, 2 right) in place of the screen's, until 0 is given or the
   screen changes (a text box offers Spell with it); `label` must stay valid */
void ui_soft_override(int which, const char *label);
void ui_note(const char *text);            /* a toast for 1.5 s; "" takes it away; '\n' between lines (at most 4) */
void ui_note_ms(const char *text, unsigned ms);    /* a toast for ms */
void ui_changed(void);                     /* something changed: paint soon */
void ui_redraw(void);                      /* draw the whole screen again (calls enter(0)) */
void ui_power_off(void);                   /* write what is pending and switch off (as END held 3 s) */
void ui_timer_init(struct timer *t, unsigned id);   /* a timer that comes back as screen->timer(id), id >= 16 */
/* what is behind the content in r: the background gradient, or the wallpaper (SCREEN_WALLPAPER) */
void ui_backdrop(const struct surface *fb, const struct rect *r);
const struct rect *ui_content(void);       /* the current screen's content area */
/* the theme's wallpaper expanded into RAM, what ui_backdrop() copies from (0 if there was no room for it): the
   animated standby (ui/livewall.h) draws its frames into it */
const struct surface *ui_wallpaper(void);
int ui_overlay(void);                      /* a toast or a dialog is shown */

/* A dialog: a box over the screen with a text and its own soft keys, which takes the keys until answered. `answer`
 * gets the key that closed it (KEY_SOFT_LEFT, KEY_SELECT or KEY_SOFT_RIGHT, or KEY_CLEAR / KEY_END for "no"). */
struct dialog {
    const char *text;                      /* may hold '\n' */
    const char *left, *centre, *right;
    void (*answer)(unsigned key);
};
void ui_dialog(const struct dialog *d);

/* ---- the status bar: for any task (the telephony services set the network part) ---- */
void ui_status_signal(int bars);           /* 0-4, or -1: no network */
void ui_status_operator(const char *name); /* the network's name, shown on standby; copied */
void ui_status_unread(int messages);       /* unread messages: the envelope sign when > 0 */
void ui_status_alarm(int on);              /* an alarm is set: the bell sign */
void ui_status_battery(int percent);       /* 0-100, or -1: unknown */
void ui_status_profile(int profile);       /* PROFILE_*: the Silent and Meeting signs */
void ui_status_lock(int locked);           /* the keypad is locked: the padlock sign */

/* the screens of this firmware (ui/apps.c has the menu's) */
extern const struct screen home_screen, menu_screen, settings_screen;

#endif
