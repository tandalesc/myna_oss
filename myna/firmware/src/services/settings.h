/* SPDX-License-Identifier: MIT */
/* Settings: typed values with defaults compiled in, kept in the system file system, one small file per group.
 *
 * Reading is from RAM (settings_get) and costs nothing. A change (settings_set) takes effect at once: subscribed tasks
 * get MSG_SETTING_CHANGED (a = the setting, b = the new value), and the group's file is written a second later by the
 * settings task, so a burst of changes is one write. A file is replaced whole, which littlefs makes atomic: after a
 * power cut it holds the old or the new values, never a mixture. settings_sync() writes at once (before power off).
 *
 * Files: "settings.<group>" in the root of the system file system, one line "name=value" per setting (decimal).
 * A missing file, a missing line, an unknown name or a value out of range gives the default. */
#ifndef MYNA_SERVICES_SETTINGS_H
#define MYNA_SERVICES_SETTINGS_H

#include <stdint.h>

struct task;

enum setting {
    SET_TIME_24H,              /* bool: 1 = 24-hour clock, 0 = 12-hour with AM / PM */
    SET_CLOCK_OFFSET,          /* int: seconds added to the power chip's clock: the time the user set */
    SET_THEME,                 /* enum: THEME_DARK, THEME_LIGHT */
    SET_BRIGHTNESS,            /* int 1-5: display brightness (stored; the backlight's commands are not known yet) */
    SET_KEY_SOUNDS,            /* bool: key sounds (stored; no sound output yet) */
    SET_NET_TIME,              /* bool: the clock follows the network's time at registration (services/network.c) */
    SET_PREDICTIVE,            /* bool: text boxes start in predictive text (services/words.h); # changes it in a box */
    SET_PROFILE,               /* enum: PROFILE_NORMAL, PROFILE_SILENT, PROFILE_MEETING */
    SET_WALLPAPER,             /* enum: WALLPAPER_STILL, WALLPAPER_ANIMATED: the standby's dunes drift (ui/livewall.h) */
    SET_SMART_DIAL,            /* bool: the dialer shows the contacts and conversations that match (apps/search.c) */
    SETTING_COUNT
};

enum { THEME_DARK = 0, THEME_LIGHT = 1 };
enum { PROFILE_NORMAL = 0, PROFILE_SILENT = 1, PROFILE_MEETING = 2 };
enum { WALLPAPER_STILL = 0, WALLPAPER_ANIMATED = 1 };

void settings_init(void);                      /* read every group from the system file system (or the defaults) */
struct task *settings_task(void);              /* the task that writes, for task_add() */
void settings_subscribe(struct task *t);       /* MSG_SETTING_CHANGED to this task from now on */

int32_t settings_get(enum setting s);
/* Change a setting. Returns 1 if it changed, 0 if it had that value already, -1 if the value is out of range. */
int settings_set(enum setting s, int32_t value);
/* the next value for a "change" key: bools and enums cycle, numbers go up and wrap */
int32_t settings_next(enum setting s, int dir);
const char *settings_name(enum setting s);

/* Write every changed group now. 0 = all written (or nothing to write). */
int settings_sync(void);
/* every setting back to its default, except the clock's offset (the time the user set); each change is announced */
void settings_reset(void);
/* forget the changes not written yet (the file system was erased: master reset) */
void settings_forget(void);

/* figures of the last read and write, for reports */
struct settings_stats {
    uint32_t load_us;          /* settings_init: all groups read */
    uint32_t write_us;         /* the last group written */
    uint32_t writes;           /* groups written since start */
    uint32_t write_bytes;      /* size of the last file written */
};
const struct settings_stats *settings_stats(void);

#endif
