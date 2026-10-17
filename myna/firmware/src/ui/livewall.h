/* SPDX-License-Identifier: MIT */
/* The animated standby (STYLE.md section 4, Motion): the theme's dunes drift slowly sideways, each band at its own
 * speed (the far ones slower), as the "living wallpapers" of the era. The setting SET_WALLPAPER chooses it (animated,
 * the default) or the still picture.
 *
 * A frame is copies: the sky alone over the rows that move, then each dune band from a strip made at build time
 * (assets.h, struct livewall_art) at its own offset, into the UI's expanded wallpaper (ui_wallpaper(), what
 * ui_backdrop() copies from, so a widget redrawn over the standby sees the current frame); then only the rows that
 * changed go to the framebuffer. The clock, the date and the status bar are above those rows and are never touched.
 *
 * It moves only while the standby screen is shown with no toast or dialog over it, at 10 frames a second, easing in.
 * After 20 s without a key it eases to a stop and its timer is stopped: an idle phone sleeps from minute to minute as
 * before. A key on standby, or coming back to standby, starts it again; livewall_hold() keeps it still (the keypad
 * lock). The standby screen (ui/home.c) calls it. */
#ifndef MYNA_UI_LIVEWALL_H
#define MYNA_UI_LIVEWALL_H

#include "gfx/gfx.h"
#include "ui/ui.h"

#define LIVEWALL_TIMER (UI_TIMER_SCREEN + 8)   /* the frame timer, a timer of the standby screen */

/* the standby screen is shown (its enter()): put the frame into the wallpaper; wake = 1 starts the motion (the screen
   was opened, or another one over it closed), 0 keeps it as it was (a toast went away, the theme changed) */
void livewall_enter(int wake);
void livewall_leave(void);                 /* another screen covers the standby screen: stop */
void livewall_key(void);                   /* a key on standby: move again, the 20 s start again */
void livewall_timer(void);                 /* LIVEWALL_TIMER: the next frame */
void livewall_paint(const struct surface *fb);     /* the rows that changed to the framebuffer */
void livewall_hold(int on);                /* 1: no motion until 0 (the keypad lock) */
int livewall_moving(void);                 /* the frame timer runs */

#endif
