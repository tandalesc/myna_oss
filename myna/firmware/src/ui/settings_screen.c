/* SPDX-License-Identifier: MIT */
/* Settings (STYLE.md section 2, the numbered list): a tree of two levels, as the phones of the era had it.
 *
 *   1 Sounds & alerts   profile (Normal, Silent, Meeting), key sounds
 *   2 Display           theme, wallpaper (animated or still), brightness
 *   3 Time & date       time, date, time format, network time
 *   4 Text input        predictive text, My words (the words the phone has learnt; each can be forgotten)
 *   5 Calls             smart dialling (the dialer shows the contacts and conversations that match the keys)
 *   6 Phone status      Myna's version, memory, battery, network, own number
 *   7 Reset             reset settings (messages and contacts stay), master reset (everything erased, then off)
 *
 * Every row shows its value; up / down or a number key choose a row and select (or the number key) acts on it: a
 * setting with two values changes at once, the time, the date and the brightness open a field, the profile a choice.
 * A change takes effect at once and is kept by the settings service. Back or C go back a level. Each page is the
 * same screen with another table; My words is a list of its own. */
#include <stdint.h>

#include "assets.h"
#include "drivers/clock.h"
#include "drivers/display.h"
#include "drivers/keypad.h"
#include "fs/storage.h"
#include "lib/mem.h"
#include "lib/print.h"
#include "services/network.h"
#include "services/settings.h"
#include "services/words.h"
#include "ui/apps.h"
#include "ui/choice.h"
#include "ui/field.h"
#include "ui/layout.h"
#include "ui/list.h"
#include "ui/statusbar.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"
#include "version.h"

#define ROWS_MAX 9
#define VALUE_MAX 24

struct row {
    const char *label;
    const char *(*value)(char *buf);   /* the value at the right (buf: VALUE_MAX), or 0 for the chevron */
    void (*act)(void);
};

struct page {
    const char *title;
    int count;
    const struct row *rows;
};

static const char *const profile_names[3] = { "Normal", "Silent", "Meeting" };

/* ---- values ---- */

static const char *on_off(enum setting s)
{
    return settings_get(s) ? "On" : "Off";
}

static const char *v_profile(char *b)
{
    (void)b;
    return profile_names[settings_get(SET_PROFILE)];
}

static const char *v_key_sounds(char *b)
{
    (void)b;
    return on_off(SET_KEY_SOUNDS);
}

static const char *v_theme(char *b)
{
    (void)b;
    return theme_name(settings_get(SET_THEME));
}

static const char *v_wallpaper(char *b)
{
    (void)b;
    return settings_get(SET_WALLPAPER) == WALLPAPER_ANIMATED ? "Animated" : "Still";
}

static const char *v_brightness(char *b)
{
    copy_text(b, "0 of 5", VALUE_MAX);
    b[0] = (char)('0' + settings_get(SET_BRIGHTNESS));
    return b;
}

static const char *v_time(char *b)
{
    format_time(b, clock_seconds(), 1);
    return b;
}

static int put2(char *b, int n, unsigned v)
{
    b[n++] = (char)('0' + v / 10 % 10);
    b[n++] = (char)('0' + v % 10);
    return n;
}

static const char *v_date(char *b)
{
    struct civil_time c;
    clock_civil(clock_seconds(), &c);
    int n = put2(b, 0, c.day);
    b[n++] = '.';
    n = put2(b, n, c.month);
    b[n++] = '.';
    n += format_uint(b + n, c.year);
    return b;
}

static const char *v_time_format(char *b)
{
    (void)b;
    return settings_get(SET_TIME_24H) ? "24-hour" : "12-hour";
}

static const char *v_net_time(char *b)
{
    (void)b;
    return on_off(SET_NET_TIME);
}

static const char *v_predictive(char *b)
{
    (void)b;
    return on_off(SET_PREDICTIVE);
}

static const char *v_my_words(char *b)
{
    unsigned n = 0;
    while (words_user(n))
        n++;
    format_uint(b, n);
    return b;
}

static const char *v_input(char *b)
{
    (void)b;
    return settings_get(SET_PREDICTIVE) ? "Predictive" : "Abc";
}

static const char *v_smart_dial(char *b)
{
    (void)b;
    return on_off(SET_SMART_DIAL);
}

static const char *v_calls(char *b)
{
    (void)b;
    return settings_get(SET_SMART_DIAL) ? "Smart dialling" : "Plain dialling";
}

static const char *v_version(char *b)
{
    (void)b;
    return MYNA_VERSION;
}

/* the user file system's use, in percent of its blocks */
static int memory_percent(void)
{
    lfs_t *fs = storage_fs(FS_USER);
    const struct storage_report *r = storage_report(FS_USER);
    if (!fs || !r->blocks)
        return -1;
    lfs_ssize_t used = lfs_fs_size(fs);
    return used < 0 ? -1 : (int)((used * 100 + r->blocks - 1) / r->blocks);
}

static const char *percent(char *b, int p)
{
    if (p < 0)
        return "-";
    int n = format_uint(b, (unsigned)p);
    b[n++] = '%';
    b[n] = 0;
    return b;
}

static const char *v_memory(char *b)
{
    return percent(b, memory_percent());
}

static const char *v_battery(char *b)
{
    return percent(b, status.battery);
}

static const char *v_network(char *b)
{
    (void)b;
    return status.network[0] ? status.network : "-";
}

static const char *v_number(char *b)
{
    copy_text(b, network_status()->own_number, VALUE_MAX);
    return b[0] ? b : "Unknown";
}

static const char *v_blank(char *b)
{
    (void)b;
    return "";
}

/* ---- actions ---- */

static void toggle(enum setting s)
{
    settings_set(s, settings_next(s, 1));
}

static int profile_chosen(int row)
{
    settings_set(SET_PROFILE, row);
    ui_note(row == PROFILE_NORMAL ? "Normal profile" : row == PROFILE_SILENT ? "Silent: no sounds" :
                                                                              "Meeting: vibration only");
    return 0;
}

static void a_profile(void)
{
    struct choice c = { .title = "Profile", .count = 3, .chosen = profile_chosen };
    for (int i = 0; i < 3; i++)
        c.rows[i] = (struct choice_row){ .label = profile_names[i],
                                         .value = i == settings_get(SET_PROFILE) ? "\xE2\x80\xA2" : 0 };
    choice_open(&c);
}

static void a_key_sounds(void)
{
    toggle(SET_KEY_SOUNDS);
}

static void a_theme(void)
{
    toggle(SET_THEME);
}

static void a_wallpaper(void)
{
    toggle(SET_WALLPAPER);
}

static void save_brightness(const struct field *f)
{
    settings_set(SET_BRIGHTNESS, f->value[0]);
}

static void a_brightness(void)
{
    struct field_request r = {
        .title = "Brightness", .help = "1 (dim) to 5 (bright)", .save = save_brightness,
        .field = { .groups = 1, .width = { 1 }, .value = { (int16_t)settings_get(SET_BRIGHTNESS) }, .min = { 1 },
                   .max = { 5 } },
    };
    field_screen_open(&r);
}

static void save_time(const struct field *f)
{
    /* the time the user sets is an offset to the power chip's clock, kept within a day either way */
    struct civil_time c;
    clock_civil(clock_seconds(), &c);
    int32_t delta = (f->value[0] - c.hour) * 3600 + (f->value[1] - c.minute) * 60 - c.second;
    settings_set(SET_CLOCK_OFFSET, (settings_get(SET_CLOCK_OFFSET) + delta) % 86400);
}

static void a_time(void)
{
    struct civil_time c;
    clock_civil(clock_seconds(), &c);
    struct field_request r = {
        .title = "Time", .help = "Number keys or up and down", .save = save_time,
        .field = { .groups = 2, .sep = ':', .width = { 2, 2 }, .value = { c.hour, c.minute }, .min = { 0, 0 },
                   .max = { 23, 59 } },
    };
    field_screen_open(&r);
}

/* days from 1970-01-01 to a civil date (the proleptic Gregorian calendar) */
static int32_t days_of(int y, int m, int d)
{
    y -= m <= 2;
    int era = y / 400, yoe = y - era * 400;
    int doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
    int doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + doe - 719468;
}

static void save_date(const struct field *f)
{
    static const uint8_t month_days[12] = { 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 };
    int d = f->value[0], m = f->value[1], y = f->value[2];
    if (d > month_days[m - 1] || (m == 2 && d == 29 && (y % 4 || (y % 100 == 0 && y % 400))))
        d = m == 2 ? 28 : month_days[m - 1];
    struct civil_time c;
    clock_civil(clock_seconds(), &c);
    int32_t delta = (days_of(y, m, d) - days_of(c.year, c.month, c.day)) * 86400;
    settings_set(SET_CLOCK_OFFSET, settings_get(SET_CLOCK_OFFSET) + delta);
}

static void a_date(void)
{
    struct civil_time c;
    clock_civil(clock_seconds(), &c);
    struct field_request r = {
        .title = "Date", .help = "Day, month, year", .save = save_date,
        .field = { .groups = 3, .sep = '.', .width = { 2, 2, 4 }, .value = { c.day, c.month, (int16_t)c.year },
                   .min = { 1, 1, 2000 }, .max = { 31, 12, 2099 } },
    };
    field_screen_open(&r);
}

static void a_time_format(void)
{
    toggle(SET_TIME_24H);
}

static void a_net_time(void)
{
    toggle(SET_NET_TIME);
}

static void a_predictive(void)
{
    toggle(SET_PREDICTIVE);
    ui_note(settings_get(SET_PREDICTIVE) ? "Text boxes start in predictive text" : "Text boxes start in Abc");
}

static void a_smart_dial(void)
{
    toggle(SET_SMART_DIAL);
    ui_note(settings_get(SET_SMART_DIAL) ? "The dialer shows the contacts\nthat match the keys" :
                                           "The dialer shows the number only");
}

static const struct screen words_screen;

static void a_my_words(void)
{
    ui_push(&words_screen);
}

static void a_version(void)
{
    ui_note("Myna " MYNA_VERSION "\nOpen-source firmware, MIT");
}

static void a_memory(void)
{
    /* "12 of 1976 blocks in use" */
    lfs_t *fs = storage_fs(FS_USER);
    if (!fs) {
        ui_note("No user memory");
        return;
    }
    char text[48];
    int n = format_uint(text, (unsigned)lfs_fs_size(fs));
    copy_text(text + n, " of ", sizeof text - (unsigned)n);
    n += 4;
    n += format_uint(text + n, storage_report(FS_USER)->blocks);
    copy_text(text + n, " blocks in use", sizeof text - (unsigned)n);
    ui_note(text);
}

static void reset_answer(unsigned key)
{
    if (key != KEY_SELECT)
        return;
    kprintf("ui: settings reset\n");
    settings_reset();
    ui_note("Settings reset");
}

static const struct dialog reset_dialog = {
    .text = "Put every setting back as it\ncame? Messages, contacts and\nthe time stay.", .centre = "Reset",
    .right = "Cancel", .answer = reset_answer,
};

static void a_reset(void)
{
    ui_dialog(&reset_dialog);
}

static void master_answer(unsigned key)
{
    if (key != KEY_SELECT)
        return;
    kprintf("ui: master reset\n");
    settings_forget();
    storage_erase_all();
    ui_power_off();
}

static const struct dialog master_dialog = {
    .text = "Erase everything: messages,\ncontacts, my words, settings?\nMyna then switches off.",
    .centre = "Erase", .right = "Cancel", .answer = master_answer,
};

static void a_master_reset(void)
{
    ui_dialog(&master_dialog);
}

/* ---- the pages ---- */

static const struct row sounds_rows[] = {
    { "Profile", v_profile, a_profile },
    { "Key sounds", v_key_sounds, a_key_sounds },
};
static const struct row display_rows[] = {
    { "Theme", v_theme, a_theme },
    { "Wallpaper", v_wallpaper, a_wallpaper },
    { "Brightness", v_brightness, a_brightness },
};
static const struct row time_rows[] = {
    { "Time", v_time, a_time },
    { "Date", v_date, a_date },
    { "Time format", v_time_format, a_time_format },
    { "Network time", v_net_time, a_net_time },
};
static const struct row input_rows[] = {
    { "Predictive text", v_predictive, a_predictive },
    { "My words", v_my_words, a_my_words },
};
static const struct row calls_rows[] = {
    { "Smart dialling", v_smart_dial, a_smart_dial },
};
static const struct row status_rows[] = {
    { "Myna", v_version, a_version },
    { "Memory", v_memory, a_memory },
    { "Battery", v_battery, 0 },
    { "Network", v_network, 0 },
    { "My number", v_number, 0 },
};
static const struct row reset_rows[] = {
    { "Reset settings", v_blank, a_reset },
    { "Master reset", v_blank, a_master_reset },
};

#define PAGE(t, r) { t, (int)(sizeof r / sizeof r[0]), r }
static const struct page pages[] = {
    PAGE("Sounds & alerts", sounds_rows), PAGE("Display", display_rows), PAGE("Time & date", time_rows),
    PAGE("Text input", input_rows),       PAGE("Calls", calls_rows),         PAGE("Phone status", status_rows),
    PAGE("Reset", reset_rows),
};
#define PAGES (int)(sizeof pages / sizeof pages[0])

/* the top level shows a value of each page */
static const char *(*const top_values[PAGES])(char *) = { v_profile, v_theme,   v_time,   v_input,
                                                          v_calls,   v_version, v_blank };

/* ---- the list screens: the top level and one page ---- */

static struct list top_list, page_list;
static const struct page *open_page;
static char values[ROWS_MAX][VALUE_MAX];

static const char *top_label(int row)
{
    return pages[row].title;
}

static const char *top_value(int row)
{
    const char *v = top_values[row](values[row]);
    return v && v[0] && row != PAGES - 1 ? v : LIST_CHEVRON;
}

static const char *page_label(int row)
{
    return open_page->rows[row].label;
}

static const char *page_value(int row)
{
    const struct row *r = &open_page->rows[row];
    const char *v = r->value ? r->value(values[row]) : 0;
    return v && v[0] ? v : r->act ? LIST_CHEVRON : "";
}

static void list_setup(struct list *l, int count, int fresh)
{
    int sel = l->selected;
    struct rect r = layout.content;
    r.h = (int16_t)(layout.list.rows * layout.list.row_h);
    list_init(l, &r, count);
    l->numbered = 1;
    if (!fresh)
        list_select(l, sel);
}

static void top_enter(int fresh)
{
    list_setup(&top_list, PAGES, fresh);
    top_list.label = top_label;
    top_list.value = top_value;
    ui_title("Settings");
    ui_soft_keys("", "Select", "Back");
}

static void page_enter(int fresh)
{
    list_setup(&page_list, open_page->count, fresh);
    page_list.label = page_label;
    page_list.value = page_value;
    ui_title(open_page->title);
    ui_soft_keys("", "Select", "Back");
}

static void top_paint(const struct surface *fb)
{
    list_paint(&top_list, fb);
}

static void page_paint(const struct surface *fb)
{
    list_paint(&page_list, fb);
}

static const struct screen page_screen;

static int list_screen_key(struct list *l, unsigned k, void (*chosen)(int))
{
    switch (list_key(l, k)) {
    case LIST_CHOSEN:
        chosen(l->selected);
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

static void top_chosen(int row)
{
    open_page = &pages[row];
    ui_push(&page_screen);
}

static void page_chosen(int row)
{
    const struct row *r = &open_page->rows[row];
    if (r->act)
        r->act();
}

static int top_key(unsigned k)
{
    return list_screen_key(&top_list, k, top_chosen);
}

static int page_key(unsigned k)
{
    return list_screen_key(&page_list, k, page_chosen);
}

/* a minute, or a setting changed: the values are drawn again (a list of a few rows: cheap) */
static void top_timer(unsigned id)
{
    if (id == UI_MINUTE)
        list_touch_row(&top_list, 2);
}

static void page_timer(unsigned id)
{
    if (id == UI_MINUTE && open_page == &pages[2])
        list_touch(&page_list);
}

static void top_setting(unsigned id, int32_t v)
{
    (void)id;
    (void)v;
    list_touch(&top_list);
}

static void page_setting(unsigned id, int32_t v)
{
    (void)id;
    (void)v;
    list_touch(&page_list);
}

const struct screen settings_screen = {
    .name = "settings",
    .flags = SCREEN_TITLE,
    .enter = top_enter,
    .paint = top_paint,
    .key = top_key,
    .timer = top_timer,
    .setting = top_setting,
};

static const struct screen page_screen = {
    .name = "settings page",
    .flags = SCREEN_TITLE,
    .enter = page_enter,
    .paint = page_paint,
    .key = page_key,
    .timer = page_timer,
    .setting = page_setting,
};

/* ---- My words: the words the phone learnt, the most recent first; Forget removes one ---- */

static struct list word_list;
static uint8_t words_hint;

static int words_count(void)
{
    int n = 0;
    while (words_user((unsigned)n))
        n++;
    return n;
}

static const char *word_label(int row)
{
    const char *w = words_user((unsigned)row);
    return w ? w : "";
}

static void words_enter(int fresh)
{
    int sel = word_list.selected;
    struct rect r = layout.content;
    r.h = (int16_t)(layout.list.rows * layout.list.row_h);
    list_init(&word_list, &r, words_count());
    word_list.label = word_label;
    if (!fresh && word_list.count)
        list_select(&word_list, sel < word_list.count ? sel : word_list.count - 1);
    words_hint = 1;
    ui_title("My words");
    ui_soft_keys("", word_list.count ? "Forget" : "", "Back");
}

static void words_paint(const struct surface *fb)
{
    list_paint(&word_list, fb);
    if (words_hint) {
        words_hint = 0;
        if (!word_list.count) {
            const struct font *f = theme->body;
            const char *l1 = "No words yet", *l2 = "Words you spell are kept here.";
            struct rect area = { 0, (int16_t)(layout.content.y + 2 * layout.list.row_h), 240, 80 };
            gfx_text_over(fb, &area, f, (240 - gfx_text_width(f, l1)) / 2, area.y + 30, l1, ink.text);
            gfx_text_over(fb, &area, f, (240 - gfx_text_width(f, l2)) / 2, area.y + 50, l2, ink.muted);
            display_invalidate(&area);
        }
    }
}

static void forget_answer(unsigned key)
{
    if (key != KEY_SELECT)
        return;
    words_forget((unsigned)word_list.selected);
    ui_redraw();               /* the list without it */
    ui_note("Forgotten");
}

static char forget_text[64];
static const struct dialog forget_dialog = {
    .text = forget_text, .centre = "Forget", .right = "Keep", .answer = forget_answer,
};

static int mywords_key(unsigned k)
{
    switch (list_key(&word_list, k)) {
    case LIST_CHOSEN:
        copy_text(forget_text, "Forget \"", sizeof forget_text);
        copy_text(forget_text + 8, word_label(word_list.selected), sizeof forget_text - 10);
        copy_text(forget_text + strlen(forget_text), "\"?", 3);
        ui_dialog(&forget_dialog);
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

static const struct screen words_screen = {
    .name = "my words",
    .flags = SCREEN_TITLE,
    .enter = words_enter,
    .paint = words_paint,
    .key = mywords_key,
};
