/* SPDX-License-Identifier: MIT */
/* Themes: the look of every screen as data, so that a theme changes everything without touching the screens' code.
 *
 * A theme is a palette (0xRRGGBB, as the design writes them), its type scale (glyph atlases of gfx/font.h), its
 * wallpaper and selection tile (images of gfx/image.h, made at build time) and a few shape numbers. The screens and
 * widgets only ever read `theme` (the data) and `ink` (what theme_select() made of it for drawing: RGB565 colours,
 * the per-row colours of every gradient, the blends that are constant). The structure of the screens is the same in
 * every theme (STYLE.md section 2): status bar, title bar, content, soft-key bar.
 *
 * Themes now: Pebble (light) and Pebble night (dark), chosen by the setting SET_THEME. Instrument and Lantern
 * (design round 2) fit the same structure: a palette, Plex or Atkinson atlases, their wallpaper and tile. */
#ifndef MYNA_UI_THEME_H
#define MYNA_UI_THEME_H

#include <stdint.h>

#include "gfx/font.h"
#include "gfx/image.h"

struct livewall_art;

/* a vertical linear gradient over its box: colours at the top and at the bottom (0xRRGGBB) */
struct vgrad {
    uint32_t top, bottom;
};

/* a translucent vertical gradient: colour and opacity (0-255) at the top and at the bottom */
struct veil {
    uint32_t top, bottom;
    uint8_t alpha_top, alpha_bottom;
};

struct theme {
    const char *name;
    uint8_t dark;

    /* palette */
    struct vgrad background;   /* the content area (the whole screen behind the bars) */
    uint32_t text, muted;      /* main and secondary text */
    uint32_t rule;             /* 1 px lines between rows, edges of blocks */
    uint32_t accent;           /* the theme's one colour: centre soft key, selection, outgoing headers */
    struct vgrad accent_fill;  /* the selection bar and tile: accent_hi to accent */
    uint8_t accent_light;      /* opacity of the 1 px light inside the top of the selection bar */
    uint32_t on_accent;        /* text on the selection */
    uint32_t surface;          /* cards: an incoming message, the text box */
    uint32_t outgoing;         /* an outgoing message block */
    uint8_t value_opacity;     /* opacity of a list row's value (0-255) */

    struct veil status;        /* status bar, over the wallpaper or the background */
    uint32_t status_line;      /* its lower edge, and its opacity */
    uint8_t status_line_alpha;
    uint32_t status_text;      /* signs and text of the status bar */

    struct vgrad title;        /* title bar, its 1 px top light (opacity) and its lower edge */
    uint8_t title_light;
    uint32_t title_line;

    struct vgrad bar;          /* soft-key bar, its upper edge and its top light (opacity) */
    uint32_t bar_line;
    uint8_t bar_light;
    uint32_t bar_text;

    uint32_t clock, date;      /* the standby clock and date, on the wallpaper */
    uint32_t toast, toast_text;

    /* type scale (the design's sizes and weights) */
    const struct font *status_font;    /* status bar: the time or the network, 11 */
    const struct font *title_font;     /* title bar, 15 */
    const struct font *body;           /* text, messages, the text box, 13 */
    const struct font *meta;           /* message headers, small labels, 11 */
    const struct font *soft;           /* soft keys left and right, 13 */
    const struct font *soft_centre;    /* the centre soft key, 13, in the accent */
    const struct font *row, *row_selected;         /* list rows, 14 */
    const struct font *number, *number_selected;   /* list numbers, 11 */
    const struct font *value, *value_selected;     /* list values, 12 */
    const struct font *clock_font;     /* the standby clock: digits, ':' and space only */
    const struct font *date_font;      /* the standby date, 14 */
    const struct font *dial_font;      /* a phone number being dialled: digits, + * # and space only */

    /* pictures and shapes */
    const struct image *wallpaper;     /* 240 x 320, opaque */
    const struct image *tile;          /* the selected menu item's tile (60 x 58 box, with its shadow) */
    const struct livewall_art *live;   /* the wallpaper's animated version (ui/livewall.h), or 0 */
    uint8_t block_radius;              /* message blocks */
    uint8_t field_radius;              /* the text box */
    uint8_t toast_radius;
};

/* what the drawing code uses: the theme in RGB565, gradients as one dithered pair of pixels per row (rgb565_pair) */
struct ink {
    uint32_t background[320];          /* per screen row */
    uint32_t status[20];               /* the status bar over the background, per row (opaque) */
    uint16_t status_veil[20];          /* the status bar's colour per row, and its opacity 0..32, for the wallpaper */
    uint8_t status_alpha[20];
    uint32_t title[26];                /* title bar rows (the light and the edge included) */
    uint32_t bar[26];                  /* soft-key bar rows (the edge and the light included) */
    uint32_t selection[27];            /* the selected list row's bar, light included */
    uint32_t selection_tall[41];       /* the same for a two-line row (LIST_TALL_H) */
    uint16_t text, muted, rule, accent, on_accent, surface, outgoing, bar_text, status_text, clock, date;
    uint16_t value;                    /* a list value: text at value_opacity over the background (middle row) */
    uint16_t toast, toast_text;
};

extern const struct theme *theme;
extern struct ink ink;

/* THEME_DARK or THEME_LIGHT (services/settings.h); the screens must be redrawn after a change */
void theme_select(int which);
/* the name of the theme a setting value selects, for the settings list */
const char *theme_name(int which);

#endif
