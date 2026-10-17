/* SPDX-License-Identifier: MIT */
/* Message blocks (STYLE.md section 2, conversations): full-width blocks with a header (sender and time) and the text,
 * the newest at the bottom; no chat bubbles, no left / right alignment. An outgoing block takes the theme's outgoing
 * colour and an accent header, an incoming one the surface colour and a muted header. A block can carry a state at the
 * right of its header ("Sending...", "Failed") and a note under its text (why it failed).
 *
 * The messages are the caller's (an array it keeps); the widget lays them out from the bottom up. Up / down scroll:
 * each step brings the next block's edge to the edge of the area, and never more than the area less two lines, so a
 * message longer than the screen is read a screenful at a time. The focused message is the lowest one in view (the
 * newest when nothing is scrolled); once scrolled it shows an accent edge. A Messages screen puts this widget over a
 * text box (ui/textentry.h), as Notes does. */
#ifndef MYNA_UI_CONVO_H
#define MYNA_UI_CONVO_H

#include <stdint.h>

#include "gfx/gfx.h"

#define CONVO_MAX 32           /* messages one widget lays out */

struct convo_msg {
    uint8_t out;               /* sent by the phone's owner */
    uint8_t alert;             /* the state and the note in the accent (a failure) */
    const char *who;           /* "Me", "Juno" */
    const char *time;          /* "14:03" */
    const char *text;
    const char *state;         /* at the right of the header, or 0 */
    const char *note;          /* a line under the text, or 0 */
};

struct convo {
    struct rect r;             /* the blocks' area */
    const struct convo_msg *msgs;
    int16_t count;
    int16_t off;               /* pixels the content is scrolled up from its bottom (0: the newest at the bottom) */
    int16_t below;             /* pixels kept free under the newest block, besides the gap (the area reaches a box
                                  under it, so that a box that gets smaller is cleared with the area) */
    int16_t h[CONVO_MAX];      /* each block's height */
    uint8_t dirty;
};

/* the messages (at most CONVO_MAX), the newest in view */
void convo_set(struct convo *c, const struct convo_msg *msgs, int count);
/* the messages changed in place (a state, a note): measure them again, keep the place */
void convo_refresh(struct convo *c);
int convo_key(struct convo *c, unsigned key);  /* up / down scroll; 1 if used */
int convo_focus(const struct convo *c);        /* the focused message's index, -1 if none */
void convo_touch(struct convo *c);
void convo_paint(struct convo *c, const struct surface *s);

#endif
