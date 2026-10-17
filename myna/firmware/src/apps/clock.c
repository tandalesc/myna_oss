/* SPDX-License-Identifier: MIT */
/* The Clock (apps/clock.h): its task, the Clock list (menu item 8), the alarm, the timer and the alert screen.
 *
 * Clock list: 1 Alarm (its time, "Off" or "Snoozed"), 2 Timer (its length, "Running" or "Paused"), 3 Stopwatch.
 *
 * Alarm: the time in large figures, a line that says when it rings ("Rings in 7 h 12 min") or that it is off. Select
 * turns it on or off; Options: Set time (the time field; saving turns the alarm on), Turn on / off. While it is on
 * (or snoozed) the status bar shows the bell.
 *
 * Timer: minutes and seconds in large figures. Select starts, pauses and resumes; the left soft key sets the length
 * (when stopped) or resets it (when running or paused). It runs on when its screen is left.
 *
 * Alert: when the alarm or the timer goes off, a screen opens over whatever is shown: the alarm clock's icon, which
 * nudges from side to side (there is no sound output yet), the time in large figures and the date (alarm) or "Time is
 * up" (timer). Alarm: select snoozes for 9 minutes, the right soft key or END stops it; after a minute without an
 * answer it snoozes by itself. Timer: select, the right soft key, C or END close it; after a minute it closes. */
#include <stdint.h>

#include "apps/clock.h"
#include "assets.h"
#include "drivers/clock.h"
#include "drivers/display.h"
#include "drivers/keypad.h"
#include "fs/storage.h"
#include "kernel/task.h"
#include "kernel/timer.h"
#include "lib/mem.h"
#include "lib/print.h"
#include "services/settings.h"
#include "ui/apps.h"
#include "ui/choice.h"
#include "ui/field.h"
#include "ui/layout.h"
#include "ui/list.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"

#define FILE_NAME     "organiser.clock"
#define SNOOZE_MIN    9
#define RING_MS       60000    /* an alert nobody answers: the alarm snoozes, the timer's alert closes */
#define NUDGE_MS      250      /* the icon's step while an alert is shown */
#define DAY_MIN       1440

enum { T_ALARM, T_SNOOZE, T_COUNTDOWN };   /* the clock task's timers */
enum { CD_IDLE, CD_RUNNING, CD_PAUSED };
enum { ALERT_ALARM, ALERT_TIMER };

static void handle(struct task *self, const struct msg *m);

static struct task task = { .name = "clock", .handle = handle };
static struct timer alarm_timer, snooze_timer, countdown_timer;
static uint8_t file_cache[STORAGE_FILE_CACHE];

static int16_t alarm_minute = 7 * 60;   /* minute of the day; a new phone offers 07:00 */
static uint8_t alarm_on, snoozed, started;
static uint16_t countdown_s = 5 * 60;   /* the timer's length */
static uint8_t cd_state;
static ktime_t cd_end;                  /* running: when it ends */
static uint32_t cd_left_ms;             /* paused: what is left */

static const struct screen clock_alarm_screen, timer_screen, alert_screen;
static void ring(int kind);

struct task *clock_task(void)
{
    return &task;
}

/* ---- the file ---- */

static int put(char *out, int n, const char *name, unsigned v)
{
    while (*name)
        out[n++] = *name++;
    n += format_uint(out + n, v);
    out[n++] = '\n';
    return n;
}

static void save(void)
{
    lfs_t *fs = storage_fs(FS_SYSTEM);
    if (!fs)
        return;
    char text[64];
    int n = put(text, 0, "alarm=", (unsigned)alarm_minute);
    n = put(text, n, "alarm_on=", alarm_on);
    n = put(text, n, "timer=", countdown_s);
    lfs_file_t f;
    struct lfs_file_config fc = { .buffer = file_cache };
    int r = lfs_file_opencfg(fs, &f, FILE_NAME, LFS_O_WRONLY | LFS_O_CREAT | LFS_O_TRUNC, &fc);
    if (!r) {
        lfs_ssize_t w = lfs_file_write(fs, &f, text, (lfs_size_t)n);
        int c = lfs_file_close(fs, &f);        /* the commit: old or new content, never a mixture */
        r = w < 0 ? (int)w : c;
    }
    if (r)
        kprintf("clock: writing %s failed (%d)\n", FILE_NAME, r);
}

static void load(void)
{
    lfs_t *fs = storage_fs(FS_SYSTEM);
    if (!fs)
        return;
    char text[64];
    lfs_file_t f;
    struct lfs_file_config fc = { .buffer = file_cache };
    if (lfs_file_opencfg(fs, &f, FILE_NAME, LFS_O_RDONLY, &fc))
        return;
    lfs_ssize_t n = lfs_file_read(fs, &f, text, sizeof text - 1);
    lfs_file_close(fs, &f);
    if (n <= 0)
        return;
    text[n] = 0;
    for (char *p = text; *p;) {
        char *eq = p;
        while (*eq && *eq != '=' && *eq != '\n')
            eq++;
        unsigned v = 0;
        char *q = *eq == '=' ? eq + 1 : eq;
        while (*q >= '0' && *q <= '9')
            v = v * 10 + (unsigned)(*q++ - '0');
        if (*eq == '=') {
            int len = (int)(eq - p);
            if (len == 5 && memcmp(p, "alarm", 5) == 0 && v < DAY_MIN)
                alarm_minute = (int16_t)v;
            else if (len == 8 && memcmp(p, "alarm_on", 8) == 0)
                alarm_on = v != 0;
            else if (len == 5 && memcmp(p, "timer", 5) == 0 && v && v <= 99 * 60 + 59)
                countdown_s = (uint16_t)v;
        }
        while (*q && *q != '\n')
            q++;
        p = *q ? q + 1 : q;
    }
}

/* ---- the alarm and the timer ---- */

static int minute_now(void)
{
    struct civil_time c;
    clock_civil(clock_seconds(), &c);
    return c.hour * 60 + c.minute;
}

/* whole minutes from the start of the next minute to the alarm's minute: 0 = it rings at the next minute */
static int minutes_after_next(void)
{
    return (alarm_minute - minute_now() - 1 + 2 * DAY_MIN) % DAY_MIN;
}

static void show_sign(void)
{
    ui_status_alarm(alarm_on || snoozed);
}

/* aim the alarm's timer at the start of its minute (a minute already begun: tomorrow) */
static void arm(void)
{
    if (!alarm_on) {
        timer_stop(&alarm_timer);
        return;
    }
    timer_start_at(&alarm_timer, clock_next_minute() + KTIME_S(60) * (ktime_t)minutes_after_next());
}

static void alarm_changed(void)
{
    save();
    arm();
    show_sign();
    kprintf("clock: alarm %02u:%02u %s\n", alarm_minute / 60, alarm_minute % 60, alarm_on ? "on" : "off");
}

static uint32_t countdown_left_ms(void)
{
    if (cd_state == CD_PAUSED)
        return cd_left_ms;
    if (cd_state == CD_RUNNING) {
        ktime_t now = ktime_now();
        return cd_end > now ? (uint32_t)((cd_end - now) / KTIME_PER_MS) : 0;
    }
    return countdown_s * 1000u;
}

static void handle(struct task *self, const struct msg *m)
{
    (void)self;
    switch (m->type) {
    case MSG_START:
        timer_init(&alarm_timer, &task, T_ALARM);
        timer_init(&snooze_timer, &task, T_SNOOZE);
        timer_init(&countdown_timer, &task, T_COUNTDOWN);
        load();
        started = 1;
        arm();
        show_sign();
        kprintf("clock: alarm %02u:%02u %s, timer %u s\n", alarm_minute / 60, alarm_minute % 60,
                alarm_on ? "on" : "off", countdown_s);
        break;
    case MSG_SETTING_CHANGED:
        if (m->a == SET_CLOCK_OFFSET && started)
            arm();                     /* the time of day moved: the alarm's minute is somewhere else now */
        break;
    case MSG_TIMER:
        switch (m->a) {
        case T_ALARM:
            if (minute_now() != alarm_minute) {
                arm();                 /* the clock was moved under the timer: aim again */
                break;
            }
            arm();                     /* tomorrow */
            ring(ALERT_ALARM);
            break;
        case T_SNOOZE:
            snoozed = 0;
            ring(ALERT_ALARM);
            break;
        case T_COUNTDOWN:
            cd_state = CD_IDLE;
            ring(ALERT_TIMER);
            break;
        }
        break;
    }
}

/* "Rings in 7 h 12 min" */
static void rings_in(char *out, unsigned max)
{
    int m = minutes_after_next() + 1, n = 0;
    char text[40];
    copy_text(text, "Rings in ", sizeof text);
    n = 9;
    if (m >= 60) {
        n += format_uint(text + n, (unsigned)(m / 60));
        copy_text(text + n, " h ", sizeof text - (unsigned)n);
        n += 3;
    }
    if (m % 60 || m < 60) {
        n += format_uint(text + n, (unsigned)(m % 60));
        copy_text(text + n, " min", sizeof text - (unsigned)n);
    }
    copy_text(out, text, max);
}

/* minutes and seconds: "05:00" */
static void format_ms(char *out, uint32_t s)
{
    unsigned m = s / 60, k = s % 60;
    out[0] = (char)('0' + m / 10 % 10);
    out[1] = (char)('0' + m % 10);
    out[2] = ':';
    out[3] = (char)('0' + k / 10);
    out[4] = (char)('0' + k % 10);
    out[5] = 0;
}

/* ---- big figures with an AM / PM beside them (as on standby) ---- */

struct big_time {
    struct digits figures;
    struct label suffix;
};

static void big_time_init(struct big_time *b, int y, uint16_t fg)
{
    const struct theme *t = theme;
    b->figures = (struct digits){ .r = { 0, (int16_t)y, DISPLAY_W, 64 }, .font = t->clock_font, .fg = fg,
                                  .base = (int16_t)(y + 52), .tracking = -1 };
    b->suffix = (struct label){ .font = t->date_font, .fg = ink.date, .over = 1, .align = ALIGN_LEFT,
                                .base = (int16_t)(y + 52) };
}

/* the figures and the suffix, centred together; the row is drawn whole when either changes */
static void big_time_set(struct big_time *b, const char *figures, const char *suffix, const struct surface *fb)
{
    if (strcmp(figures, b->figures.text) == 0 && strcmp(suffix, b->suffix.text) == 0 && b->figures.shown[0])
        return;
    struct rect row = { 0, b->figures.r.y, DISPLAY_W, 64 };
    ui_backdrop(fb, &row);
    display_invalidate(&row);
    digits_set(&b->figures, figures);
    label_set(&b->suffix, suffix);
    int sw = suffix[0] ? gfx_text_width(b->suffix.font, suffix) + 4 : 0;
    b->figures.r = row;
    b->figures.r.w = (int16_t)(row.w - sw);
    digits_touch(&b->figures);
    digits_paint(&b->figures, fb);
    if (suffix[0]) {
        int right = digits_left(&b->figures) + digits_text_width(&b->figures);
        b->suffix.r = (struct rect){ (int16_t)(right + 4), (int16_t)(b->figures.base - 16), (int16_t)(sw + 2), 20 };
        label_touch(&b->suffix);
        label_paint(&b->suffix, fb);
    }
}

/* the alarm's time as the user reads times: "07:30" or "7:30" and "AM" */
static void alarm_figures(char *figures, const char **suffix)
{
    format_time(figures, (uint32_t)alarm_minute * 60u, 0);
    *suffix = settings_get(SET_TIME_24H) ? "" : alarm_minute < 12 * 60 ? "AM" : "PM";
}

/* ---- the Clock list (menu item 8) ---- */

enum { ROW_ALARM, ROW_TIMER, ROW_STOPWATCH, CLOCK_ROWS };
static const char *const clock_rows[CLOCK_ROWS] = { "Alarm", "Timer", "Stopwatch" };
static struct list clock_list;
static char clock_values[CLOCK_ROWS][16];

static const char *clock_label(int row)
{
    return clock_rows[row];
}

static const char *clock_value(int row)
{
    char *v = clock_values[row];
    switch (row) {
    case ROW_ALARM:
        if (snoozed)
            return "Snoozed";
        if (!alarm_on)
            return "Off";
        format_time(v, (uint32_t)alarm_minute * 60u, 1);
        return v;
    case ROW_TIMER:
        if (cd_state == CD_RUNNING)
            return "Running";
        if (cd_state == CD_PAUSED)
            return "Paused";
        format_ms(v, countdown_s);
        return v;
    default: {
        const char *s = stopwatch_state();
        return s[0] ? s : LIST_CHEVRON;
    }
    }
}

static void clock_enter(int fresh)
{
    int sel = clock_list.selected;
    struct rect r = layout.content;
    r.h = (int16_t)(layout.list.rows * layout.list.row_h);
    list_init(&clock_list, &r, CLOCK_ROWS);
    clock_list.numbered = 1;
    clock_list.label = clock_label;
    clock_list.value = clock_value;
    if (!fresh)
        list_select(&clock_list, sel);
    ui_title("Clock");
    ui_soft_keys("", "Select", "Back");
}

static void clock_paint(const struct surface *fb)
{
    list_paint(&clock_list, fb);
}

static int clock_key(unsigned k)
{
    switch (list_key(&clock_list, k)) {
    case LIST_CHOSEN:
        ui_push(clock_list.selected == ROW_ALARM ? &clock_alarm_screen
                : clock_list.selected == ROW_TIMER ? &timer_screen : &stopwatch_screen);
        return 1;
    case LIST_USED:
        return 1;
    }
    if (k == KEY_SOFT_RIGHT) {
        ui_pop();
        return 1;
    }
    return 0;
}

const struct screen alarms_screen = {
    .name = "clock",
    .flags = SCREEN_TITLE,
    .enter = clock_enter,
    .paint = clock_paint,
    .key = clock_key,
};

/* ---- the alarm ---- */

static struct big_time alarm_big;
static struct label alarm_line;
static uint8_t alarm_dirty;
static char alarm_note[64];            /* shown when the screen is back (after the time field closed) */

static void alarm_show(void)
{
    char line[40];
    if (snoozed) {
        copy_text(line, "Snoozed for 9 minutes", sizeof line);
        alarm_line.fg = ink.accent;
    } else if (alarm_on) {
        rings_in(line, sizeof line);
        alarm_line.fg = ink.accent;
    } else {
        copy_text(line, "The alarm is off", sizeof line);
        alarm_line.fg = ink.muted;
    }
    label_set(&alarm_line, line);
    label_touch(&alarm_line);
    alarm_dirty = 1;
    ui_soft_keys("Options", alarm_on ? "Turn off" : "Turn on", "Back");
    ui_changed();
}

static void alarm_enter(int fresh)
{
    (void)fresh;
    const struct rect *c = &layout.content;
    ui_title("Alarm");
    big_time_init(&alarm_big, c->y + 30, ink.text);
    alarm_line = (struct label){ .r = { 0, (int16_t)(c->y + 100), DISPLAY_W, 22 }, .font = theme->date_font,
                                 .over = 1, .align = ALIGN_CENTRE, .base = (int16_t)(c->y + 116) };
    alarm_show();
    if (alarm_note[0]) {
        ui_note_ms(alarm_note, 2500);
        alarm_note[0] = 0;
    }
}

static void alarm_paint(const struct surface *fb)
{
    if (alarm_dirty) {
        alarm_dirty = 0;
        char figures[12];
        const char *suffix;
        alarm_figures(figures, &suffix);
        alarm_big.figures.fg = alarm_on ? ink.text : ink.muted;
        alarm_big.figures.text[0] = 0;          /* the colour may have changed: draw it whole */
        big_time_set(&alarm_big, figures, suffix, fb);
    }
    label_paint(&alarm_line, fb);
}

static void alarm_toggle(void)
{
    alarm_on = !alarm_on;
    if (!alarm_on && snoozed) {
        snoozed = 0;
        timer_stop(&snooze_timer);
    }
    alarm_changed();
    alarm_show();
    if (alarm_on) {
        char line[40];
        rings_in(line, sizeof line);
        ui_note(line);
    } else {
        ui_note("Alarm off");
    }
}

static void alarm_save_time(const struct field *f)
{
    alarm_minute = (int16_t)(f->value[0] * 60 + f->value[1]);
    alarm_on = 1;
    alarm_changed();
    /* "Alarm set for 07:30" and when it rings, once the alarm's screen is back */
    char t[12], line[40];
    format_time(t, (uint32_t)alarm_minute * 60u, 1);
    copy_text(alarm_note, "Alarm set for ", sizeof alarm_note);
    copy_text(alarm_note + 14, t, sizeof alarm_note - 14);
    rings_in(line, sizeof line);
    unsigned n = (unsigned)strlen(alarm_note);
    alarm_note[n++] = '\n';
    copy_text(alarm_note + n, line, sizeof alarm_note - n);
}

static void alarm_set_time(void)
{
    struct field_request r = {
        .title = "Alarm time", .help = "Number keys or up and down", .save = alarm_save_time,
        .field = { .groups = 2, .sep = ':', .width = { 2, 2 },
                   .value = { (int16_t)(alarm_minute / 60), (int16_t)(alarm_minute % 60) }, .min = { 0, 0 },
                   .max = { 23, 59 } },
    };
    field_screen_open(&r);
}

static int alarm_option(int row)
{
    if (row == 0) {
        ui_pop();              /* the Options first, so that the field returns to the alarm */
        alarm_set_time();
        return 1;
    }
    ui_pop();
    alarm_toggle();
    return 1;
}

static int alarm_key(unsigned k)
{
    switch (k) {
    case KEY_SELECT:
        alarm_toggle();
        return 1;
    case KEY_SOFT_LEFT: {
        struct choice c = { .title = "Alarm", .count = 2, .chosen = alarm_option };
        c.rows[0].label = "Set time";
        c.rows[1].label = alarm_on ? "Turn off" : "Turn on";
        choice_open(&c);
        return 1;
    }
    case KEY_SOFT_RIGHT:
        ui_pop();
        return 1;
    }
    return 0;
}

static void alarm_minute_tick(unsigned id)
{
    if (id == UI_MINUTE)
        alarm_show();
}

static void alarm_setting(unsigned id, int32_t v)
{
    (void)v;
    if (id == SET_TIME_24H || id == SET_CLOCK_OFFSET)
        alarm_show();
}

static const struct screen clock_alarm_screen = {
    .name = "alarm",
    .flags = SCREEN_TITLE,
    .enter = alarm_enter,
    .paint = alarm_paint,
    .key = alarm_key,
    .timer = alarm_minute_tick,
    .setting = alarm_setting,
};

/* ---- the timer ---- */

#define TIMER_TICK (UI_TIMER_SCREEN + 0)

static struct timer tick_timer;
static struct big_time cd_big;
static struct label cd_line;
static uint8_t cd_dirty;

/* the next change of the shown seconds (the remaining time rounded up) */
static void cd_schedule(void)
{
    if (cd_state != CD_RUNNING) {
        timer_stop(&tick_timer);
        return;
    }
    uint32_t left = countdown_left_ms(), secs = (left + 999) / 1000;
    if (secs)
        timer_start_at(&tick_timer, cd_end - KTIME_S(secs - 1));
}

static void cd_show(void)
{
    static const char *const states[3] = { "Ready", "Running", "Paused" };
    label_set(&cd_line, states[cd_state]);
    cd_line.fg = cd_state == CD_RUNNING ? ink.accent : ink.muted;
    label_touch(&cd_line);
    ui_soft_keys(cd_state == CD_IDLE ? "Set" : "Reset",
                 cd_state == CD_IDLE ? "Start" : cd_state == CD_RUNNING ? "Pause" : "Resume", "Back");
    cd_dirty = 1;
    cd_schedule();
    ui_changed();
}

static void cd_enter(int fresh)
{
    (void)fresh;
    static int made;
    if (!made) {
        ui_timer_init(&tick_timer, TIMER_TICK);
        made = 1;
    }
    const struct rect *c = &layout.content;
    ui_title("Timer");
    big_time_init(&cd_big, c->y + 30, ink.text);
    cd_line = (struct label){ .r = { 0, (int16_t)(c->y + 100), DISPLAY_W, 22 }, .font = theme->date_font,
                              .over = 1, .align = ALIGN_CENTRE, .base = (int16_t)(c->y + 116) };
    cd_show();
}

static void cd_leave(void)
{
    timer_stop(&tick_timer);
}

static void cd_paint(const struct surface *fb)
{
    if (cd_dirty) {
        cd_dirty = 0;
        char t[8];
        format_ms(t, (countdown_left_ms() + 999) / 1000);
        if (!cd_big.figures.shown[0])
            big_time_set(&cd_big, t, "", fb);
        else {
            digits_set(&cd_big.figures, t);     /* only the cells that changed */
            digits_paint(&cd_big.figures, fb);
        }
    }
    label_paint(&cd_line, fb);
}

static void cd_save(const struct field *f)
{
    unsigned s = (unsigned)(f->value[0] * 60 + f->value[1]);
    if (!s)
        return;                /* nothing to count: the length stays */
    countdown_s = (uint16_t)s;
    cd_state = CD_IDLE;
    save();
    kprintf("clock: timer set to %u s\n", s);
}

static int cd_key(unsigned k)
{
    switch (k) {
    case KEY_SELECT:
        if (cd_state == CD_RUNNING) {
            cd_left_ms = countdown_left_ms();
            timer_stop(&countdown_timer);
            cd_state = CD_PAUSED;
        } else {
            uint32_t ms = cd_state == CD_PAUSED ? cd_left_ms : countdown_s * 1000u;
            cd_end = ktime_now() + KTIME_MS(ms);
            timer_start_at(&countdown_timer, cd_end);
            cd_state = CD_RUNNING;
            kprintf("clock: timer running, %u ms left\n", ms);
        }
        cd_show();
        return 1;
    case KEY_SOFT_LEFT:
        if (cd_state == CD_IDLE) {
            struct field_request r = {
                .title = "Timer", .help = "Minutes and seconds", .save = cd_save,
                .field = { .groups = 2, .sep = ':', .width = { 2, 2 },
                           .value = { (int16_t)(countdown_s / 60), (int16_t)(countdown_s % 60) }, .min = { 0, 0 },
                           .max = { 99, 59 } },
            };
            field_screen_open(&r);
        } else {
            timer_stop(&countdown_timer);
            cd_state = CD_IDLE;
            cd_show();
        }
        return 1;
    case KEY_SOFT_RIGHT:
        ui_pop();
        return 1;
    }
    return 0;
}

static void cd_timer(unsigned id)
{
    if (id == TIMER_TICK) {
        cd_dirty = 1;
        cd_schedule();
        ui_changed();
    }
}

static const struct screen timer_screen = {
    .name = "timer",
    .flags = SCREEN_TITLE,
    .enter = cd_enter,
    .leave = cd_leave,
    .paint = cd_paint,
    .key = cd_key,
    .timer = cd_timer,
};

/* ---- the alert ---- */

#define TIMER_NUDGE (UI_TIMER_SCREEN + 1)
#define TIMER_RING  (UI_TIMER_SCREEN + 2)

static struct timer nudge_timer, ring_timer;
static uint8_t alert_kind, alert_drawn, nudge_step, nudge_dirty, ringing;
static struct big_time alert_big;
static struct label alert_line;

static struct rect icon_box(void)
{
    const struct rect *c = &layout.content;
    int s = icon_px[ICON_64];
    return (struct rect){ (int16_t)((DISPLAY_W - s) / 2 - 3), (int16_t)(c->y + 22), (int16_t)(s + 6), (int16_t)s };
}

static void alert_enter(int fresh)
{
    (void)fresh;
    static int made;
    if (!made) {
        ui_timer_init(&nudge_timer, TIMER_NUDGE);
        ui_timer_init(&ring_timer, TIMER_RING);
        made = 1;
    }
    const struct rect *c = &layout.content;
    int alarm = alert_kind == ALERT_ALARM;
    ui_title(alarm ? "Alarm" : "Timer");
    ui_soft_keys("", alarm ? "Snooze" : "OK", alarm ? "Stop" : "");
    big_time_init(&alert_big, c->y + 100, ink.text);
    alert_line = (struct label){ .r = { 0, (int16_t)(c->y + 170), DISPLAY_W, 22 }, .font = theme->date_font,
                                 .fg = alarm ? ink.date : ink.accent, .over = 1, .align = ALIGN_CENTRE,
                                 .base = (int16_t)(c->y + 186), .dirty = 1 };
    if (alarm) {
        /* the day, as on standby: "Monday 20 October" */
        static const char *const days[7] = { "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
                                             "Sunday" };
        static const char *const months[12] = { "January", "February", "March", "April", "May", "June", "July",
                                                "August", "September", "October", "November", "December" };
        struct civil_time t;
        clock_civil(clock_seconds(), &t);
        char text[40];
        copy_text(text, days[t.weekday], sizeof text);
        unsigned n = (unsigned)strlen(text);
        text[n++] = ' ';
        n += (unsigned)format_uint(text + n, t.day);
        text[n++] = ' ';
        copy_text(text + n, months[t.month - 1], sizeof text - n);
        label_set(&alert_line, text);
    } else {
        label_set(&alert_line, "Time is up");
    }
    alert_drawn = 0;
    timer_start(&nudge_timer, KTIME_MS(NUDGE_MS), KTIME_MS(NUDGE_MS));
}

static void alert_leave(void)
{
    timer_stop(&nudge_timer);
}

static void alert_paint(const struct surface *fb)
{
    if (!alert_drawn || nudge_dirty) {
        static const int8_t step_x[4] = { 0, 2, 0, -2 };
        struct rect box = icon_box();
        ui_backdrop(fb, &box);
        image_draw(fb, &box, &icon_images[ICON_64][ICON_ALARM], box.x + 3 + step_x[nudge_step & 3], box.y, 0);
        display_invalidate(&box);
        nudge_dirty = 0;
    }
    if (!alert_drawn) {
        alert_drawn = 1;
        char figures[12];
        const char *suffix = "";
        if (alert_kind == ALERT_ALARM)
            alarm_figures(figures, &suffix);
        else
            format_ms(figures, 0);
        alert_big.figures.text[0] = 0;
        big_time_set(&alert_big, figures, suffix, fb);
    }
    label_paint(&alert_line, fb);
}

static void alert_close(const char *note)
{
    ringing = 0;
    timer_stop(&ring_timer);
    if (ui_current() == &alert_screen)
        ui_pop();
    if (note)
        ui_note(note);
}

static void snooze(void)
{
    snoozed = 1;
    timer_start(&snooze_timer, KTIME_S(SNOOZE_MIN * 60), 0);
    show_sign();
    kprintf("clock: alarm snoozed for %u min\n", SNOOZE_MIN);
    alert_close("Snoozed for 9 minutes");
}

static void stop(void)
{
    snoozed = 0;
    timer_stop(&snooze_timer);
    show_sign();
    kprintf("clock: alarm stopped\n");
    alert_close(alarm_on ? "Alarm stopped\nIt rings again tomorrow" : "Alarm stopped");
}

static int alert_key(unsigned k)
{
    if (alert_kind == ALERT_ALARM) {
        if (k == KEY_SELECT)
            snooze();
        else if (k == KEY_SOFT_RIGHT || k == KEY_END)
            stop();
    } else if (k == KEY_SELECT || k == KEY_SOFT_RIGHT || k == KEY_CLEAR || k == KEY_END) {
        kprintf("clock: timer alert closed\n");
        alert_close(0);
    }
    return 1;                  /* every other key waits: the alert is answered first */
}

static void alert_timer(unsigned id)
{
    if (id == TIMER_NUDGE) {
        nudge_step++;
        nudge_dirty = 1;
        ui_changed();
    } else if (id == TIMER_RING && ringing) {
        if (alert_kind == ALERT_ALARM)
            snooze();
        else
            alert_close(0);
    }
}

static const struct screen alert_screen = {
    .name = "alert",
    .flags = SCREEN_TITLE,
    .enter = alert_enter,
    .leave = alert_leave,
    .paint = alert_paint,
    .key = alert_key,
    .timer = alert_timer,
};

static void ring(int kind)
{
#ifdef MYNA_BENCH
    ui_bench_from(kernel_busy(), kind == ALERT_ALARM ? "alarm" : "timer end");
#endif
    kprintf("clock: %s\n", kind == ALERT_ALARM ? "alarm rings" : "timer done");
    alert_kind = (uint8_t)kind;
    nudge_step = 0;
    ringing = 1;
    if (ui_current() == &alert_screen)
        ui_redraw();           /* the other alert is replaced by this one */
    else
        ui_push(&alert_screen);
    timer_start(&ring_timer, KTIME_MS(RING_MS), 0);
}
