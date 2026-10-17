/* SPDX-License-Identifier: MIT */
/* An editable number field: one to three groups of digits with a separator ("14:32" is two groups, hours 0-23 and
 * minutes 0-59; a brightness is one group, 1-5). The digit being edited is underlined in the accent.
 *
 * Keys: a number key types the digit under the cursor and moves on (a group that would pass its maximum takes the
 * maximum); left / right move the cursor; up / down step the cursor's group by one, round from max to min.
 *
 * field_screen_open() shows a field on a screen of its own, with Save and Back. */
#ifndef MYNA_UI_FIELD_H
#define MYNA_UI_FIELD_H

#include <stdint.h>

#include "gfx/gfx.h"

#define FIELD_GROUPS 3

struct field {
    struct rect r;             /* the text is centred in r, on the baseline `base` */
    int16_t base;
    const struct font *font;
    uint8_t groups;
    char sep;                  /* between groups */
    uint8_t width[FIELD_GROUPS];   /* digits of each group */
    int16_t value[FIELD_GROUPS], min[FIELD_GROUPS], max[FIELD_GROUPS];
    uint8_t cursor;            /* the digit being edited, counted over all groups */
    uint8_t dirty;
};

void field_touch(struct field *f);
int field_key(struct field *f, unsigned key);  /* 1 if the key was used */
void field_paint(struct field *f, const struct surface *s);

/* a screen with one field: `title`, a line of help under the field, and save() called with the field on Save */
struct field_request {
    const char *title;
    const char *help;
    struct field field;        /* groups, widths, values and limits; the screen sets the place and the font */
    void (*save)(const struct field *f);
};
void field_screen_open(const struct field_request *req);

#endif
