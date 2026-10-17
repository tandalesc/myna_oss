/* SPDX-License-Identifier: MIT */
/* The Clock (menu item 8): an alarm, a timer and a stopwatch (apps/clock.c, apps/stopwatch.c).
 *
 * The alarm and the timer must go off while the phone sleeps and whatever screen is shown, so their timers belong to
 * a task of their own, "clock", which opens the alert screen over the current one when one is due. The alarm is a
 * time of day: its timer is aimed at the kernel time of that minute's start (from clock_next_minute()), and aimed
 * again when the user's clock offset changes (the task hears MSG_SETTING_CHANGED). An armed alarm adds no wake-up:
 * the minute timer of the UI always comes first. The stopwatch needs no timer at all: it is arithmetic on the kernel
 * clock, drawn ten times a second only while its screen is shown and it runs.
 *
 * Kept on the system file system, in "organiser.clock" (lines "name=value", replaced whole, as the settings are): the
 * alarm's time and whether it is on, the timer's length. A snooze, a running timer and the stopwatch live in RAM. */
#ifndef MYNA_APPS_CLOCK_H
#define MYNA_APPS_CLOCK_H

struct task;

struct task *clock_task(void);     /* for task_add() and settings_subscribe(); MSG_START reads the file */

/* the stopwatch's line in the Clock list: "Running", "Stopped" or "" (apps/stopwatch.c) */
const char *stopwatch_state(void);
extern const struct screen stopwatch_screen;

#endif
