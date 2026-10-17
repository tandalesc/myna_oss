/* SPDX-License-Identifier: MIT */
/* The main menu (STYLE.md section 2): a 3 x 4 grid of 80 x 62 cells in the keypad's order. The selected item sits on
 * the theme's tile and its name is the title. Keys: the arrows move (round the grid), select opens, the item's key
 * (1-9, *, 0, #) opens it directly, the right soft key or C goes back.
 *
 * Motion (STYLE.md section 4): the tile appears under the new item at once, with the icon at 42 px; the icon then
 * steps to 46 and 50 px on two timer ticks, from pre-rendered sizes (no scaling at run time). The old item is drawn
 * plain in the first frame. A key press ends the step at once. Each frame redraws only the cells that changed, each
 * with the part of its neighbours that a tile's shadow can reach. */
#include <stdint.h>

#include "assets.h"
#include "drivers/display.h"
#include "drivers/keypad.h"
#include "kernel/timer.h"
#include "ui/apps.h"
#include "ui/layout.h"
#include "ui/theme.h"
#include "ui/ui.h"

#define GROW_MS    40          /* between the steps of the selected icon */
#define TIMER_GROW (UI_TIMER_SCREEN + 0)

static const uint8_t grow_sizes[] = { ICON_42, ICON_46, ICON_50 };

static int focus = ICON_PHOTOS;    /* the centre of the grid, where the menu opens */
static int step;                   /* index in grow_sizes of the selected icon */
static uint16_t dirty;             /* cells to draw, a bit per cell */
static uint8_t only_tile;          /* the next paint is a grow step: the tile's box is enough */
static struct timer grow_timer;

static struct rect cell_rect(int i)
{
    return (struct rect){ (int16_t)((i % 3) * layout.menu.cell_w), (int16_t)(layout.menu.top + (i / 3) * layout.menu.cell_h),
                          layout.menu.cell_w, layout.menu.cell_h };
}

static struct rect grid_rect(void)
{
    return (struct rect){ 0, layout.menu.top, (int16_t)(3 * layout.menu.cell_w), (int16_t)(4 * layout.menu.cell_h) };
}

/* the tile's box (60 x 58) and the whole picture of the tile with its shadow */
static struct rect tile_box(int i)
{
    struct rect c = cell_rect(i);
    return (struct rect){ (int16_t)(c.x + layout.menu.tile_x), (int16_t)(c.y + layout.menu.tile_y), 60, 58 };
}

static struct rect tile_picture(int i)
{
    struct rect b = tile_box(i);
    const struct image *t = theme->tile;
    return (struct rect){ (int16_t)(b.x + t->x), (int16_t)(b.y + t->y), (int16_t)t->w, (int16_t)t->h };
}

static void draw_icon(const struct surface *fb, const struct rect *clip, int i, int size)
{
    const struct image *icon = &icon_images[size][i];
    struct rect c = cell_rect(i);
    image_draw(fb, clip, icon, c.x + (c.w - icon->w) / 2, c.y + (c.h - icon->h) / 2, 0);
}

/* everything inside r: the backdrop, the tile, the icons, limited to the grid */
static void paint_region(const struct surface *fb, struct rect r)
{
    struct rect grid = grid_rect(), c;
    if (!rect_intersect(&c, &r, &grid))
        return;
    ui_backdrop(fb, &c);
    struct rect tp = tile_picture(focus), x;
    if (rect_intersect(&x, &tp, &c))
        image_draw(fb, &c, theme->tile, tile_box(focus).x, tile_box(focus).y, 0);
    for (int i = 0; i < ICON_COUNT; i++) {
        struct rect cr = cell_rect(i);
        if (rect_intersect(&x, &cr, &c))
            draw_icon(fb, &c, i, i == focus ? grow_sizes[step] : ICON_42);
    }
    display_invalidate(&c);
}

static void paint(const struct surface *fb)
{
    if (!dirty)
        return;
    if (only_tile) {
        paint_region(fb, tile_box(focus));
    } else {
        for (int i = 0; i < ICON_COUNT; i++)
            if (dirty & (1u << i)) {
                /* the cell and what a tile's shadow can reach above and below it */
                struct rect r = cell_rect(i);
                r.y = (int16_t)(r.y - layout.menu.shadow);
                r.h = (int16_t)(r.h + 2 * layout.menu.shadow);
                paint_region(fb, r);
            }
    }
    dirty = 0;
    only_tile = 0;
}

static void finish_grow(void)
{
    timer_stop(&grow_timer);
    if (step != (int)sizeof grow_sizes - 1) {
        step = sizeof grow_sizes - 1;
        dirty |= 1u << focus;
        only_tile = 0;
    }
}

static void set_focus(int i)
{
    i = (i % ICON_COUNT + ICON_COUNT) % ICON_COUNT;
    if (i == focus)
        return;
    dirty |= 1u << focus | 1u << i;
    focus = i;
    step = 0;
    only_tile = 0;
    timer_start(&grow_timer, KTIME_MS(GROW_MS), KTIME_MS(GROW_MS));
    ui_title(apps[focus].name);
    ui_changed();
}

static void enter(int fresh)
{
    static int timer_made;
    if (!timer_made) {
        ui_timer_init(&grow_timer, TIMER_GROW);
        timer_made = 1;
    }
    if (fresh)
        focus = ICON_PHOTOS;
    step = sizeof grow_sizes - 1;
    dirty = 0xFFF;
    only_tile = 0;
    ui_title(apps[focus].name);
    ui_soft_keys("Options", "Open", "Back");
}

static void leave(void)
{
    timer_stop(&grow_timer);
}

static int key(unsigned k)
{
    finish_grow();
    int col = focus % 3, row = focus / 3;
    switch (k) {
    case KEY_LEFT:
        set_focus(focus - 1);
        return 1;
    case KEY_RIGHT:
        set_focus(focus + 1);
        return 1;
    case KEY_UP:
        set_focus(((row + 3) % 4) * 3 + col);
        return 1;
    case KEY_DOWN:
        set_focus(((row + 1) % 4) * 3 + col);
        return 1;
    case KEY_SELECT:
        app_open(focus);
        return 1;
    case KEY_SOFT_LEFT:
        ui_note("No options yet");
        return 1;
    case KEY_SOFT_RIGHT:
        ui_pop();
        return 1;
    }
    int i = app_of_key(k);
    if (i >= 0) {
        set_focus(i);
        finish_grow();
        app_open(i);
        return 1;
    }
    return 0;
}

static void timer(unsigned id)
{
    if (id != TIMER_GROW)
        return;
    if (step < (int)sizeof grow_sizes - 1) {
        step++;
        only_tile = !dirty;
        dirty |= 1u << focus;
        ui_changed();
    }
    if (step == (int)sizeof grow_sizes - 1)
        timer_stop(&grow_timer);
}

const struct screen menu_screen = {
    .name = "menu",
    .flags = SCREEN_TITLE,
    .enter = enter,
    .leave = leave,
    .paint = paint,
    .key = key,
    .timer = timer,
};
