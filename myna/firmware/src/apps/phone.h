/* SPDX-License-Identifier: MIT */
/* The phone's applications: Messages (messages.c), Contacts (people.c), the dialer and Calls (dialer.c), and the
 * glue that brings the services' news to the UI task (phone.c: the status bar's network part and unread envelope,
 * the toast of a new message). They are screens of the UI task (ui/ui.h) and define the menu's weak screens
 * (ui/apps.h); they talk to the services by calls (which run in the UI task) and hear from them by messages
 * (MSG_NETWORK_CHANGED, MSG_SMS_EVENT, through app_event()).
 *
 * Text is UTF-8 in the services and on the screen (ui/widget.h). Everything shown from a service passes text_from_utf8()
 * (malformed bytes made safe); a character the fonts do not have shows as '?'. */
#ifndef MYNA_APPS_PHONE_H
#define MYNA_APPS_PHONE_H

#include <stdint.h>

#include "gfx/font.h"
#include "gfx/gfx.h"
#include "services/contacts.h"

/* ---- text (apps/text.c) ---- */

/* text from a service (UTF-8) made safe to show: a malformed byte becomes '?' (into max bytes with the 0, never a part
   of a character); returns the length */
unsigned text_from_utf8(char *out, unsigned max, const char *in);
/* typed text (UTF-8) for a service: a copy into max bytes with the 0, never a part of a character; returns the length */
unsigned text_to_utf8(char *out, unsigned max, const char *in);
/* one line of at most `width` pixels: line breaks become spaces, a cut ends in an ellipsis */
void text_fit(const struct font *f, const char *in, int width, char *out, unsigned max);
/* when something happened, short: "14:05" today, "Yesterday", "Mon" this week, else "12 Oct" */
void format_when(char *out, uint32_t seconds);
/* the day and the time: "14:05" today, else "12 Oct, 14:05" */
void format_day_time(char *out, uint32_t seconds);

/* ---- people (apps/people.c) ---- */

/* the name to show for a number: the contact's name, or the number */
void people_name(const char *number, char *out, unsigned max);
/* the contacts in alphabetical order (indexes for contacts_at()); returns how many */
unsigned people_sorted(uint16_t *order, unsigned max);
/* A number key on a list of contacts in that order: the position of the first name with one of the key's letters
 * (2 abc ... 9 wxyz; the same key again within 1.5 s: the key's next letter), or -1 for another key. */
int people_jump(const uint16_t *order, unsigned n, unsigned key);
/* the contact's view (a contact of contacts_at()) */
void contacts_view(uint32_t id);
/* the contact editor for a new contact with this number (Add to contacts) */
void contacts_new_with_number(const char *number);
/* the contact's view, if the number belongs to one; 0 if none */
int contacts_show_number(const char *number);

/* ---- smart search (apps/search.c) ---- */

/* What matches keys typed on the keypad, for the dialer and Contacts: contacts with a word of the name that starts
 * with the keys' letters (2 abc ... 9 wxyz, lib/keyseq.h; accents folded, Cyrillic on the Russian layout; 0 and 1 also
 * stand for the break between words), contacts with a number that holds the digits, and in the dialer the recent
 * conversations with a number no contact has. In this order: the name's start, a later word, a number; among equals
 * the most recently messaged first (the dialer), then alphabetical. The contacts service keeps each name's keys, so a
 * key costs comparisons only; a key that continues the query looks only at what matched before. */

#define SEARCH_QUERY_MAX 24
#define SEARCH_SHOWN     24        /* the dialer's best hits kept, in order (Contacts keeps them all) */
#define SEARCH_CONVS     32        /* recent conversations looked at */
#define SEARCH_CONV      0x8000    /* a hit's `contact`: SEARCH_CONV | a conversation with a number no contact has */

struct search_hit {
    uint16_t contact;          /* contacts_at() index, or SEARCH_CONV | conversation */
    uint8_t kind, number, at;  /* as in struct contacts_hit */
};

struct search {
    uint8_t dial;              /* the dialer: contacts with a number, conversations, the most recent first */
    uint8_t valid;             /* cand holds the hits of query */
    char query[SEARCH_QUERY_MAX + 1];
    uint16_t total;            /* hits in all */
    uint16_t count;            /* in hits[], in order: all of them (Contacts), the best SEARCH_SHOWN (the dialer) */
    struct search_hit hits[CONTACTS_MAX];
    uint32_t rank[SEARCH_SHOWN];
    uint16_t ncand, nconv_cand;
    uint16_t cand[CONTACTS_MAX];           /* the contacts of every hit of query, for the next key */
    uint8_t conv_cand[SEARCH_CONVS];
};

/* a screen opens or shows again: the contacts and conversations may have changed (dial: the dialer's kind) */
void search_begin(struct search *s, int dial);
/* the hits of query into s; returns s->count */
unsigned search_run(struct search *s, const char *query);
/* hit i's name (a conversation's: its number) as shown, and the bytes of the match in it, [*from, *to) */
void search_title(const struct search *s, int i, char *out, unsigned max, int *from, int *to);
/* hit i's number (the one that matched, or its first) and the bytes of the match in it; -1 for a conversation */
int search_number(const struct search *s, int i, char *out, unsigned max, int *from, int *to);
/* the time of hit i's latest message, or 0 */
uint32_t search_when(const struct search *s, int i);
uint32_t search_id(const struct search *s, int i);         /* hit i's contact (0: a conversation) */
/* Text in at most `width` pixels (a cut ends in an ellipsis) with bytes [from, to) marked: in the accent, or on the
 * selection bar (sel: everything in the colour on it) underlined. bg: the colour under the text when not sel. */
void search_draw(const struct surface *s, const struct rect *clip, const struct font *f, int x, int y, int width,
                 const char *text, int from, int to, uint16_t fg, int sel, uint16_t bg);

/* ---- messages (apps/messages.c) ---- */

/* New message from anywhere: the recipient picker, then the conversation */
void messages_compose(void);
/* the conversation with this number (opened over the current screen; replaces a passing one) */
void messages_open(const char *number);
void messages_start(void);                 /* the UI is up: the unread count */
void messages_sms_event(unsigned ev, uint32_t id);
void messages_power_off(void);             /* power off: the open conversation's text is kept as its draft */
void messages_network(void);               /* the network changed: "waiting for network" may change */

#endif
