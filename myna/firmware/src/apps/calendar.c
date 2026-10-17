/* SPDX-License-Identifier: MIT */
/* Calendar (menu item 9): a month as a grid of weeks, Monday first, in the Pebble style. Today is a round mark in the
 * accent; the chosen day has a ring. Left / right move a day, up / down a week (into the next or the last month when
 * the grid ends), the left soft key goes back to today, select tells the chosen day in full with its week number.
 * There are no appointments yet: the calendar shows the days.
 *
 * Moving within a month redraws two cells; a new month redraws the grid. The title is the month and the year. */
#include <stdint.h>

#include "drivers/clock.h"
#include "drivers/display.h"
#include "drivers/keypad.h"
#include "lib/mem.h"
#include "ui/apps.h"
#include "ui/layout.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"

#define CELL_W 32
#define CELL_H 30
#define GRID_X ((240 - 7 * CELL_W) / 2)
#define HEAD_Y (46 + 8)                /* the weekdays' row, under the title bar */
#define GRID_Y (HEAD_Y + 22)

static const char *const month_names[12] = { "January", "February", "March", "April", "May", "June", "July",
                                             "August", "September", "October", "November", "December" };
static const char *const day_names[7] = { "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
                                          "Sunday" };

static int year, month, day;           /* the chosen day */
static int today_y, today_m, today_d;
static int shown_y, shown_m, drawn_day;   /* the month on the screen and its chosen day as drawn */
static uint8_t full;
static char title[24];

/* days from 1970-01-01 (proleptic Gregorian) */
static int32_t days_of(int y, int m, int d)
{
    y -= m <= 2;
    int era = y / 400, yoe = y - era * 400;
    int doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
    return era * 146097 + yoe * 365 + yoe / 4 - yoe / 100 + doy - 719468;
}

static int month_days(int y, int m)
{
    static const uint8_t n[12] = { 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 };
    return m == 2 && (y % 4 == 0 && (y % 100 || y % 400 == 0)) ? 29 : n[m - 1];
}

static int weekday(int y, int m, int d)   /* 0 = Monday */
{
    return (int)((days_of(y, m, d) % 7 + 10) % 7);
}

/* the ISO week of a day */
static int week_of(int y, int m, int d)
{
    int32_t n = days_of(y, m, d);
    int32_t thursday = n - weekday(y, m, d) + 3;
    struct civil_time c;
    clock_civil((uint32_t)thursday * 86400u, &c);
    return (int)((thursday - days_of(c.year, 1, 1)) / 7 + 1);
}

static struct rect cell(int d)
{
    int i = weekday(shown_y, shown_m, 1) + d - 1;
    return (struct rect){ (int16_t)(GRID_X + i % 7 * CELL_W), (int16_t)(GRID_Y + i / 7 * CELL_H), CELL_W, CELL_H };
}

static void paint_cell(const struct surface *fb, int d)
{
    struct rect r = cell(d);
    ui_backdrop(fb, &r);
    int is_today = shown_y == today_y && shown_m == today_m && d == today_d;
    struct rect mark = { (int16_t)(r.x + 3), (int16_t)(r.y + 2), (int16_t)(r.w - 6), (int16_t)(r.h - 4) };
    if (is_today)
        gfx_round_rect(fb, &r, &mark, 13, ink.accent, GFX_NO_BORDER);
    if (d == day) {
        if (is_today) {
            struct rect inner = { (int16_t)(mark.x + 2), (int16_t)(mark.y + 2), (int16_t)(mark.w - 4),
                                  (int16_t)(mark.h - 4) };
            gfx_round_rect(fb, &r, &mark, 13, ink.text, GFX_NO_BORDER);
            gfx_round_rect(fb, &r, &inner, 11, ink.accent, GFX_NO_BORDER);
        } else {
            gfx_round_rect(fb, &r, &mark, 13, ink.surface, ink.accent);
        }
    }
    char num[4];
    format_uint(num, (unsigned)d);
    const struct font *f = is_today || d == day ? theme->row_selected : theme->row;
    int wd = weekday(shown_y, shown_m, d);
    uint16_t fg = is_today ? ink.on_accent : wd >= 5 ? ink.muted : ink.text;
    gfx_text_over(fb, &r, f, r.x + (r.w - gfx_text_width(f, num)) / 2, r.y + 20, num, fg);
    display_invalidate(&r);
}

/* the line under the grid: the chosen day in full */
static void paint_line(const struct surface *fb)
{
    struct rect r = { 0, (int16_t)(GRID_Y + 6 * CELL_H + 4), 240, 22 };
    ui_backdrop(fb, &r);
    char text[48];
    int n = 0;
    copy_text(text, day_names[weekday(year, month, day)], sizeof text);
    n = (int)strlen(text);
    copy_text(text + n, ", week ", sizeof text - (unsigned)n);
    n += 7;
    format_uint(text + n, (unsigned)week_of(year, month, day));
    const struct font *f = theme->body;
    gfx_text_over(fb, &r, f, (240 - gfx_text_width(f, text)) / 2, r.y + 15, text, ink.muted);
    display_invalidate(&r);
}

static void paint_grid(const struct surface *fb)
{
    const struct font *f = theme->meta;
    static const char *const heads[7] = { "Mo", "Tu", "We", "Th", "Fr", "Sa", "Su" };
    struct rect all = { 0, HEAD_Y, 240, (int16_t)(GRID_Y + 6 * CELL_H - HEAD_Y) };
    ui_backdrop(fb, &all);
    for (int i = 0; i < 7; i++) {
        int x = GRID_X + i * CELL_W;
        gfx_text_over(fb, &all, f, x + (CELL_W - gfx_text_width(f, heads[i])) / 2, HEAD_Y + 12, heads[i],
                      i >= 5 ? ink.accent : ink.muted);
    }
    struct rect rule = { GRID_X, (int16_t)(HEAD_Y + 17), 7 * CELL_W, 1 };
    gfx_fill(fb, &rule, ink.rule);
    display_invalidate(&all);
    for (int d = 1; d <= month_days(shown_y, shown_m); d++)
        paint_cell(fb, d);
}

static void retitle(void)
{
    copy_text(title, month_names[month - 1], sizeof title);
    int n = (int)strlen(title);
    title[n++] = ' ';
    format_uint(title + n, (unsigned)year);
    ui_title(title);
}

static void today(void)
{
    struct civil_time c;
    clock_civil(clock_seconds(), &c);
    today_y = c.year;
    today_m = c.month;
    today_d = c.day;
}

static void enter(int fresh)
{
    today();
    if (fresh) {
        year = today_y;
        month = today_m;
        day = today_d;
    }
    full = 1;
    retitle();
    ui_soft_keys("Today", "", "Back");
}

static void paint(const struct surface *fb)
{
    if (full || shown_y != year || shown_m != month) {
        full = 0;
        shown_y = year;
        shown_m = month;
        paint_grid(fb);
        paint_line(fb);
    } else if (drawn_day != day) {
        paint_cell(fb, drawn_day);
        paint_cell(fb, day);
        paint_line(fb);
    }
    drawn_day = day;
}

/* the chosen day moved by n days (into another month when it leaves this one) */
static void move(int n)
{
    struct civil_time c;
    clock_civil((uint32_t)(days_of(year, month, day) + n) * 86400u, &c);
    year = c.year;
    month = c.month;
    day = c.day;
    retitle();
    ui_changed();
}

static int key(unsigned k)
{
    switch (k) {
    case KEY_LEFT:
        move(-1);
        return 1;
    case KEY_RIGHT:
        move(1);
        return 1;
    case KEY_UP:
        move(-7);
        return 1;
    case KEY_DOWN:
        move(7);
        return 1;
    case KEY_SOFT_LEFT:
        today();
        move(days_of(today_y, today_m, today_d) - days_of(year, month, day));
        return 1;
    case KEY_SELECT: {
        char text[64];
        copy_text(text, day_names[weekday(year, month, day)], sizeof text);
        int n = (int)strlen(text);
        text[n++] = ' ';
        n += format_uint(text + n, (unsigned)day);
        text[n++] = ' ';
        copy_text(text + n, month_names[month - 1], sizeof text - (unsigned)n);
        n = (int)strlen(text);
        copy_text(text + n, "\nNo appointments", sizeof text - (unsigned)n);
        ui_note(text);
        return 1;
    }
    case KEY_SOFT_RIGHT:
        ui_pop();
        return 1;
    }
    return 0;
}

static void timer(unsigned id)
{
    if (id == UI_MINUTE) {
        int d = today_d;
        today();
        if (d != today_d)
            full = 1;          /* midnight: today moves */
    }
}

const struct screen calendar_screen = {
    .name = "calendar",
    .flags = SCREEN_TITLE,
    .enter = enter,
    .paint = paint,
    .key = key,
    .timer = timer,
};
