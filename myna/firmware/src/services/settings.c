/* SPDX-License-Identifier: MIT */
/* Settings (services/settings.h). */
#include <stdint.h>

#include "fs/storage.h"
#include "kernel/task.h"
#include "kernel/timer.h"
#include "lib/mem.h"
#include "lib/print.h"
#include "services/settings.h"

#define WRITE_DELAY_MS 1000
#define FILE_MAX       256     /* a group's file: a few short lines */
#define SUBSCRIBERS    4

enum group { G_CLOCK, G_DISPLAY, G_SOUND, G_INPUT, GROUP_COUNT };
static const char *const group_file[GROUP_COUNT] = { "settings.clock", "settings.display", "settings.sound",
                                                     "settings.input" };

enum kind { K_BOOL, K_ENUM, K_INT };

struct def {
    const char *name;
    uint8_t group, kind;
    int32_t def, min, max;
};

/* the defaults: what a new phone shows */
static const struct def defs[SETTING_COUNT] = {
    [SET_TIME_24H] = { "time_24h", G_CLOCK, K_BOOL, 1, 0, 1 },
    [SET_CLOCK_OFFSET] = { "offset", G_CLOCK, K_INT, 0, -1000000000, 1000000000 },
    [SET_THEME] = { "theme", G_DISPLAY, K_ENUM, THEME_LIGHT, THEME_DARK, THEME_LIGHT },
    [SET_BRIGHTNESS] = { "brightness", G_DISPLAY, K_INT, 4, 1, 5 },
    [SET_KEY_SOUNDS] = { "key_sounds", G_SOUND, K_BOOL, 1, 0, 1 },
    [SET_NET_TIME] = { "net_time", G_CLOCK, K_BOOL, 1, 0, 1 },
    [SET_PREDICTIVE] = { "predictive", G_INPUT, K_BOOL, 1, 0, 1 },
    [SET_PROFILE] = { "profile", G_SOUND, K_ENUM, PROFILE_NORMAL, PROFILE_NORMAL, PROFILE_MEETING },
    [SET_WALLPAPER] = { "wallpaper", G_DISPLAY, K_ENUM, WALLPAPER_ANIMATED, WALLPAPER_STILL, WALLPAPER_ANIMATED },
    [SET_SMART_DIAL] = { "smart_dial", G_INPUT, K_BOOL, 1, 0, 1 },
};

static void settings_handle(struct task *self, const struct msg *m);

static struct task task = { .name = "settings", .handle = settings_handle };
static struct timer write_timer;
static int32_t values[SETTING_COUNT];
static uint8_t dirty[GROUP_COUNT];
static struct task *subscribers[SUBSCRIBERS];
static struct settings_stats stats;
static uint8_t file_cache[STORAGE_FILE_CACHE];

struct task *settings_task(void)
{
    return &task;
}

const struct settings_stats *settings_stats(void)
{
    return &stats;
}

const char *settings_name(enum setting s)
{
    return s < SETTING_COUNT ? defs[s].name : "?";
}

void settings_subscribe(struct task *t)
{
    for (unsigned i = 0; i < SUBSCRIBERS; i++)
        if (!subscribers[i] || subscribers[i] == t) {
            subscribers[i] = t;
            return;
        }
}

int32_t settings_get(enum setting s)
{
    return s < SETTING_COUNT ? values[s] : 0;
}

static int valid(enum setting s, int32_t v)
{
    return v >= defs[s].min && v <= defs[s].max;
}

int settings_set(enum setting s, int32_t v)
{
    if (s >= SETTING_COUNT || !valid(s, v))
        return -1;
    if (values[s] == v)
        return 0;
    values[s] = v;
    dirty[defs[s].group] = 1;
    timer_start(&write_timer, KTIME_MS(WRITE_DELAY_MS), 0);
    for (unsigned i = 0; i < SUBSCRIBERS && subscribers[i]; i++)
        task_post(subscribers[i], MSG_SETTING_CHANGED, (uint16_t)s, (uint32_t)v);
    return 1;
}

int32_t settings_next(enum setting s, int dir)
{
    const struct def *d = &defs[s];
    int32_t v = values[s] + (dir < 0 ? -1 : 1);
    if (v > d->max)
        v = d->min;
    if (v < d->min)
        v = d->max;
    return v;
}

/* ---- files ---- */

static int parse_int(const char *p, const char *end, int32_t *out)
{
    int neg = 0;
    uint32_t v = 0;
    if (p < end && *p == '-') {
        neg = 1;
        p++;
    }
    if (p == end)
        return 0;
    for (; p < end; p++) {
        if (*p < '0' || *p > '9' || v > 200000000u)
            return 0;
        v = v * 10 + (uint32_t)(*p - '0');
    }
    *out = neg ? -(int32_t)v : (int32_t)v;
    return 1;
}

static void parse(unsigned g, const char *text, unsigned len)
{
    const char *p = text, *end = text + len;
    while (p < end) {
        const char *eol = p;
        while (eol < end && *eol != '\n')
            eol++;
        const char *eq = p;
        while (eq < eol && *eq != '=')
            eq++;
        int32_t v;
        if (eq < eol && parse_int(eq + 1, eol, &v)) {
            for (unsigned s = 0; s < SETTING_COUNT; s++) {
                const struct def *d = &defs[s];
                if (d->group == g && strlen(d->name) == (size_t)(eq - p) && memcmp(d->name, p, eq - p) == 0) {
                    if (valid(s, v))
                        values[s] = v;
                    else
                        kprintf("settings: %s=%d out of range, default kept\n", d->name, v);
                }
            }
        }
        p = eol + 1;
    }
}

static unsigned format(unsigned g, char *out)
{
    unsigned n = 0;
    for (unsigned s = 0; s < SETTING_COUNT; s++) {
        if (defs[s].group != g)
            continue;
        for (const char *c = defs[s].name; *c; c++)
            out[n++] = *c;
        out[n++] = '=';
        int32_t v = values[s];
        uint32_t u = v < 0 ? 0u - (uint32_t)v : (uint32_t)v;
        if (v < 0)
            out[n++] = '-';
        char digits[10];
        int k = 0;
        do {
            digits[k++] = (char)('0' + u % 10);
            u /= 10;
        } while (u);
        while (k)
            out[n++] = digits[--k];
        out[n++] = '\n';
    }
    return n;
}

static int read_group(lfs_t *fs, unsigned g)
{
    char text[FILE_MAX];
    lfs_file_t f;
    struct lfs_file_config fc = { .buffer = file_cache };
    int r = lfs_file_opencfg(fs, &f, group_file[g], LFS_O_RDONLY, &fc);
    if (r)
        return r;
    lfs_ssize_t n = lfs_file_read(fs, &f, text, sizeof text);
    lfs_file_close(fs, &f);
    if (n < 0)
        return (int)n;
    parse(g, text, (unsigned)n);
    return 0;
}

static int write_group(lfs_t *fs, unsigned g)
{
    char text[FILE_MAX];
    unsigned n = format(g, text);
    ktime_t t0 = ktime_now();
    lfs_file_t f;
    struct lfs_file_config fc = { .buffer = file_cache };
    int r = lfs_file_opencfg(fs, &f, group_file[g], LFS_O_WRONLY | LFS_O_CREAT | LFS_O_TRUNC, &fc);
    if (!r) {
        lfs_ssize_t w = lfs_file_write(fs, &f, text, n);
        int c = lfs_file_close(fs, &f);          /* the commit: the new content becomes the file's, atomically */
        r = w < 0 ? (int)w : c;
    }
    stats.write_us = ktime_to_us(ktime_now() - t0);
    stats.write_bytes = n;
    stats.writes++;
    if (r)
        kprintf("settings: writing %s failed (%d)\n", group_file[g], r);
    else
        kprintf("settings: %s written, %u bytes, %u us\n", group_file[g], n, stats.write_us);
    return r;
}

void settings_init(void)
{
    timer_init(&write_timer, &task, 0);
    for (unsigned s = 0; s < SETTING_COUNT; s++)
        values[s] = defs[s].def;
    lfs_t *fs = storage_fs(FS_SYSTEM);
    if (!fs) {
        kprintf("settings: no system file system: defaults, not kept\n");
        return;
    }
    ktime_t t0 = ktime_now();
    unsigned found = 0;
    for (unsigned g = 0; g < GROUP_COUNT; g++)
        if (read_group(fs, g) == 0)
            found++;
    stats.load_us = ktime_to_us(ktime_now() - t0);
    kprintf("settings: %u of %u groups read in %u us; 24h %d, theme %d, offset %d s, brightness %d, key sounds %d\n",
            found, GROUP_COUNT, stats.load_us, values[SET_TIME_24H], values[SET_THEME], values[SET_CLOCK_OFFSET],
            values[SET_BRIGHTNESS], values[SET_KEY_SOUNDS]);
}

int settings_sync(void)
{
    lfs_t *fs = storage_fs(FS_SYSTEM);
    timer_stop(&write_timer);
    int result = 0;
    for (unsigned g = 0; g < GROUP_COUNT; g++) {
        if (!dirty[g])
            continue;
        dirty[g] = 0;
        if (!fs)
            continue;
        if (write_group(fs, g))
            result = -1;
    }
    return result;
}

void settings_reset(void)
{
    for (unsigned s = 0; s < SETTING_COUNT; s++)
        if (s != SET_CLOCK_OFFSET)
            settings_set((enum setting)s, defs[s].def);
}

void settings_forget(void)
{
    timer_stop(&write_timer);
    for (unsigned g = 0; g < GROUP_COUNT; g++)
        dirty[g] = 0;
}

static void settings_handle(struct task *self, const struct msg *m)
{
    (void)self;
    if (m->type == MSG_TIMER)
        settings_sync();
}
