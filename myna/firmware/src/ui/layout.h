/* SPDX-License-Identifier: MIT */
/* Where the pieces of the screens are: geometry only, the same in every theme (STYLE.md section 2). Colours and fonts
 * are in the theme (ui/theme.c), behaviour in ui/ui.c, the widgets and the screens. Baselines are absolute screen
 * rows, measured on the design's mock-ups (240 x 320, design/r2/ui/png). */
#ifndef MYNA_UI_LAYOUT_H
#define MYNA_UI_LAYOUT_H

#include "gfx/gfx.h"

struct layout {
    /* on every screen */
    struct rect status;        /* status bar, its lower edge included */
    int16_t status_base;       /* text baseline */
    int16_t status_sign_y;     /* top of the 10 px signs */
    int16_t status_pad, status_gap;
    struct rect title;         /* title bar, its lower edge included */
    int16_t title_base;
    struct rect soft_bar;      /* soft-key bar, its upper edge included */
    int16_t soft_base, soft_pad, soft_side_w;
    struct rect content;       /* between the title bar and the soft-key bar */
    struct rect content_full;  /* between the status bar and the soft-key bar (no title bar) */

    struct {
        int16_t clock_base;    /* the clock's baseline */
        struct rect clock;     /* the clock's box (cleared when its width changes) */
        int16_t date_base;
        struct rect date;
        int16_t ampm_gap;
        int16_t news_base;     /* "1 new message" under the date */
        struct rect news;
    } home;
    struct {
        int16_t top, cell_w, cell_h;
        int16_t tile_x, tile_y;            /* the tile's box in its cell */
        int16_t shadow;                    /* how far below its cell a tile's shadow reaches */
    } menu;
    struct {
        int16_t row_h, rows, pad, number_w, gap;
        int16_t number_base, label_base, value_base;            /* from the row's top, unselected */
        int16_t number_base_sel, label_base_sel, value_base_sel;
    } list;
    struct {
        struct rect blocks;    /* where the message blocks are, the newest at the bottom */
        int16_t pad_x, pad_top, pad_bottom, gap, head_h, line_h;
        struct rect compose;   /* the text box under them */
        int16_t box_pad_x, box_pad_y;
    } convo;
    struct {
        int16_t w, pad, line_h, y;
    } toast;
};

static const struct layout layout = {
    .status = { 0, 0, 240, 20 },
    .status_base = 13, .status_sign_y = 5, .status_pad = 7, .status_gap = 6,
    .title = { 0, 20, 240, 26 },
    .title_base = 37,
    .soft_bar = { 0, 294, 240, 26 },
    .soft_base = 311, .soft_pad = 9, .soft_side_w = 76,
    .content = { 0, 46, 240, 248 },
    .content_full = { 0, 20, 240, 274 },
    .home = {
        .clock_base = 90,
        .clock = { 0, 40, 240, 60 },
        .date_base = 119,
        .date = { 0, 104, 240, 22 },
        .ampm_gap = 4,
        .news_base = 141,
        .news = { 0, 127, 240, 20 },
    },
    .menu = { .top = 46, .cell_w = 80, .cell_h = 62, .tile_x = 10, .tile_y = 2, .shadow = 9 },
    .list = {
        .row_h = 27, .rows = 9, .pad = 9, .number_w = 9, .gap = 8,
        .number_base = 16, .label_base = 17, .value_base = 17,
        .number_base_sel = 17, .label_base_sel = 18, .value_base_sel = 17,
    },
    .convo = {
        .blocks = { 7, 52, 226, 206 },
        .pad_x = 8, .pad_top = 4, .pad_bottom = 6, .gap = 5, .head_h = 14, .line_h = 16,
        .compose = { 7, 262, 226, 27 },
        .box_pad_x = 9, .box_pad_y = 5,
    },
    .toast = { .w = 200, .pad = 12, .line_h = 17, .y = 200 },
};

#endif
