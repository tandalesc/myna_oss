/* SPDX-License-Identifier: MIT */
/* The main menu's items (ui/apps.h) and the placeholder screen of the items not built yet. */
#include <stdint.h>

#include "assets.h"
#include "drivers/display.h"
#include "drivers/keypad.h"
#include "ui/apps.h"
#include "ui/layout.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "ui/widget.h"

const struct app apps[ICON_COUNT] = {
    [ICON_MESSAGES] = { "Messages", KEY_1, &messages_screen },
    [ICON_CONTACTS] = { "Contacts", KEY_2, &contacts_screen },
    [ICON_CALLS] = { "Calls", KEY_3, &calls_screen },
    [ICON_CAMERA] = { "Camera", KEY_4, &camera_screen },
    [ICON_PHOTOS] = { "Photos", KEY_5, &photos_screen },
    [ICON_MUSIC] = { "Music", KEY_6, &music_screen },
    [ICON_RADIO] = { "Radio", KEY_7, &radio_screen },
    [ICON_ALARM] = { "Clock", KEY_8, &alarms_screen },
    [ICON_CALENDAR] = { "Calendar", KEY_9, &calendar_screen },
    [ICON_NOTES] = { "Notes", KEY_STAR, &notes_screen },
    [ICON_WEB] = { "Web", KEY_0, &web_screen },
    [ICON_SETTINGS] = { "Settings", KEY_HASH, &settings_screen },
};

int app_of_key(unsigned key)
{
    for (int i = 0; i < ICON_COUNT; i++)
        if (apps[i].key == key)
            return i;
    return -1;
}

/* ---- the placeholder: the item's icon and "Coming soon" ---- */

static int shown;              /* the icon of what it stands for */
static const char *shown_title;
static uint8_t drawn;

static void enter(int fresh)
{
    (void)fresh;
    ui_title(shown_title);
    ui_soft_keys("", "", "Back");
    drawn = 0;
}

static void paint(const struct surface *fb)
{
    if (drawn)
        return;
    drawn = 1;
    const struct rect *c = &layout.content;
    const struct image *icon = &icon_images[ICON_64][shown];
    int y = c->y + 52;
    image_draw(fb, c, icon, (DISPLAY_W - icon->w) / 2, y, 0);
    const struct font *f = theme->row_selected, *b = theme->body;
    const char *head = "Coming soon", *line1 = "This part of Myna", *line2 = "is not built yet.";
    y += icon->h + 34;
    gfx_text_over(fb, c, f, (DISPLAY_W - gfx_text_width(f, head)) / 2, y, head, ink.text);
    y += 24;
    gfx_text_over(fb, c, b, (DISPLAY_W - gfx_text_width(b, line1)) / 2, y, line1, ink.muted);
    y += 17;
    gfx_text_over(fb, c, b, (DISPLAY_W - gfx_text_width(b, line2)) / 2, y, line2, ink.muted);
    display_invalidate(c);
}

static int key(unsigned k)
{
    if (k == KEY_SOFT_RIGHT || k == KEY_SELECT) {
        ui_pop();
        return 1;
    }
    return 0;
}

static const struct screen placeholder_screen = {
    .name = "placeholder",
    .flags = SCREEN_TITLE,
    .enter = enter,
    .paint = paint,
    .key = key,
};

void app_open(int i)
{
    if (i < 0 || i >= ICON_COUNT)
        return;
    if (apps[i].screen) {
        ui_push(apps[i].screen);
        return;
    }
    app_placeholder(apps[i].name, i);
}

void app_placeholder(const char *title, int icon)
{
    shown = icon;
    shown_title = title;
    ui_push(&placeholder_screen);
}
