/* SPDX-License-Identifier: MIT */
/* The themes (ui/theme.h): Pebble, the design's chosen theme (round 2, STYLE.md section 2: warm paper, terracotta,
 * Nunito), and Pebble night, its dark variant drawn for this firmware in the same spirit (warm dark brown, the same
 * terracotta, a night version of the dunes). Fonts: Nunito (OFL), in the weights the design names. */
#include <stdint.h>

#include "assets.h"
#include "fonts.h"
#include "gfx/gfx.h"
#include "services/settings.h"
#include "ui/layout.h"
#include "ui/theme.h"

#define PEBBLE_TYPE                                                                     \
    .status_font = &font_nunito_bold_11, .title_font = &font_nunito_extrabold_15,       \
    .body = &font_nunito_semibold_13, .meta = &font_nunito_bold_11,                     \
    .soft = &font_nunito_bold_13, .soft_centre = &font_nunito_extrabold_13,             \
    .row = &font_nunito_semibold_14, .row_selected = &font_nunito_extrabold_14,         \
    .number = &font_nunito_semibold_11, .number_selected = &font_nunito_extrabold_11,   \
    .value = &font_nunito_semibold_12, .value_selected = &font_nunito_extrabold_12,     \
    .clock_font = &font_nunito_light_60, .date_font = &font_nunito_bold_14,             \
    .dial_font = &font_nunito_light_30,                                                 \
    .block_radius = 9, .field_radius = 8, .toast_radius = 10

static const struct theme pebble = {
    .name = "Pebble",
    .dark = 0,
    .background = { 0xf8f4ed, 0xefe7dc },
    .text = 0x2f2822, .muted = 0x85796d, .rule = 0xe2d8ca,
    .accent = 0xc9603e, .accent_fill = { 0xe8916a, 0xc9603e }, .accent_light = 102, .on_accent = 0xffffff,
    .surface = 0xfffdf9, .outgoing = 0xf7e0d3, .value_opacity = 178,
    .status = { 0xfffbf5, 0xfaf3e9, 199, 158 }, .status_line = 0x785f46, .status_line_alpha = 46,
    .status_text = 0x3b2e26,
    .title = { 0xfffcf7, 0xf1e8dc }, .title_light = 255, .title_line = 0xe2d8ca,
    .bar = { 0xfdf9f3, 0xede3d5 }, .bar_line = 0xd6c9b8, .bar_light = 191, .bar_text = 0x2f2822,
    .clock = 0x3b2e26, .date = 0x7a5e4c,
    .toast = 0x3b2e26, .toast_text = 0xfffaf3,
    PEBBLE_TYPE,
    .wallpaper = &wallpaper_dunes,
    .tile = &tile_pebble,
    .live = &livewall_dunes,
};

static const struct theme pebble_night = {
    .name = "Pebble night",
    .dark = 1,
    .background = { 0x241f1b, 0x181411 },
    .text = 0xf2eadf, .muted = 0xa6998b, .rule = 0x3a322b,
    .accent = 0xe07650, .accent_fill = { 0xee8f68, 0xd96a45 }, .accent_light = 89, .on_accent = 0xffffff,
    .surface = 0x2c2621, .outgoing = 0x4b2f24, .value_opacity = 178,
    .status = { 0x181411, 0x14110e, 184, 153 }, .status_line = 0xffebd2, .status_line_alpha = 20,
    .status_text = 0xeadfd2,
    .title = { 0x302925, 0x241f1b }, .title_light = 18, .title_line = 0x3a322b,
    .bar = { 0x2e2823, 0x1e1a16 }, .bar_line = 0x463c33, .bar_light = 18, .bar_text = 0xf2eadf,
    .clock = 0xf6eadc, .date = 0xd8b89f,
    .toast = 0x4a3f36, .toast_text = 0xf6eadc,
    PEBBLE_TYPE,
    .wallpaper = &wallpaper_dunes_night,
    .tile = &tile_pebble_night,
    .live = &livewall_dunes_night,
};

const struct theme *theme = &pebble;
struct ink ink;

/* colour of row i of n of a vertical gradient: the middle of the row, as a browser samples it */
static uint32_t grad_at(const struct vgrad *g, int i, int n)
{
    return rgb_mix(g->top, g->bottom, (unsigned)((2 * i + 1) * 256 / (2 * n)));
}

static uint32_t over(uint32_t fg, uint32_t bg, unsigned alpha)
{
    return rgb_mix(bg, fg, alpha + (alpha >> 7));     /* 0..255 to 0..256 */
}

static void make_ink(const struct theme *t)
{
    uint32_t bg[320];
    for (int y = 0; y < 320; y++) {
        bg[y] = grad_at(&t->background, y, 320);
        ink.background[y] = rgb565_pair(bg[y], y);
    }

    /* status bar: 19 rows of the veil and the 1 px edge */
    int sh = layout.status.h - 1;
    for (int y = 0; y < sh; y++) {
        uint32_t c = grad_at(&(struct vgrad){ t->status.top, t->status.bottom }, y, sh);
        unsigned a = t->status.alpha_top + ((int)t->status.alpha_bottom - (int)t->status.alpha_top) * (2 * y + 1) /
                     (2 * sh);
        ink.status[y] = rgb565_pair(over(c, bg[y], a), y);
        ink.status_veil[y] = rgb565(c);
        ink.status_alpha[y] = (uint8_t)((a * 32 + 127) / 255);
    }
    ink.status[sh] = rgb565_pair(over(t->status_line, bg[sh], t->status_line_alpha), sh);
    ink.status_veil[sh] = rgb565(t->status_line);
    ink.status_alpha[sh] = (uint8_t)((t->status_line_alpha * 32 + 127) / 255);

    /* title bar: 25 rows of gradient (the first under the light), then the edge */
    int th = layout.title.h - 1;
    for (int y = 0; y < th; y++) {
        uint32_t c = grad_at(&t->title, y, th);
        ink.title[y] = rgb565_pair(y == 0 ? over(0xffffff, c, t->title_light) : c, layout.title.y + y);
    }
    ink.title[th] = rgb565_pair(t->title_line, 0);

    /* soft-key bar: the edge, then 25 rows of gradient (the first under the light) */
    int bh = layout.soft_bar.h - 1;
    ink.bar[0] = rgb565_pair(t->bar_line, 0);
    for (int y = 0; y < bh; y++) {
        uint32_t c = grad_at(&t->bar, y, bh);
        ink.bar[y + 1] = rgb565_pair(y == 0 ? over(0xffffff, c, t->bar_light) : c, layout.soft_bar.y + 1 + y);
    }

    /* the selected list row */
    for (int y = 0; y < 27; y++) {
        uint32_t c = grad_at(&t->accent_fill, y, 27);
        ink.selection[y] = rgb565_pair(y == 0 ? over(0xffffff, c, t->accent_light) : c, y);
    }
    for (int y = 0; y < 41; y++) {
        uint32_t c = grad_at(&t->accent_fill, y, 41);
        ink.selection_tall[y] = rgb565_pair(y == 0 ? over(0xffffff, c, t->accent_light) : c, y);
    }

    ink.text = rgb565(t->text);
    ink.muted = rgb565(t->muted);
    ink.rule = rgb565(t->rule);
    ink.accent = rgb565(t->accent);
    ink.on_accent = rgb565(t->on_accent);
    ink.surface = rgb565(t->surface);
    ink.outgoing = rgb565(t->outgoing);
    ink.bar_text = rgb565(t->bar_text);
    ink.status_text = rgb565(t->status_text);
    ink.clock = rgb565(t->clock);
    ink.date = rgb565(t->date);
    ink.value = rgb565(over(t->text, bg[160], t->value_opacity));
    ink.toast = rgb565(t->toast);
    ink.toast_text = rgb565(t->toast_text);
}

void theme_select(int which)
{
    theme = which == THEME_LIGHT ? &pebble : &pebble_night;
    make_ink(theme);
}

const char *theme_name(int which)
{
    return which == THEME_LIGHT ? pebble.name : pebble_night.name;
}
