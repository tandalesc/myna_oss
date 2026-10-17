/* SPDX-License-Identifier: MIT */
/* One contact as a vCard 3.0 text (RFC 2426; property meanings as in RFC 6350): what Myna writes to share a contact
 * and reads to take one in.
 *
 * Written: BEGIN, VERSION:3.0, N, FN, one TEL per number (TYPE=CELL / HOME / WORK / VOICE), NOTE, END; CRLF line ends,
 * lines folded at 75 octets (never inside a UTF-8 character), text escaped (\\ \; \, \n). UTF-8 throughout.
 * Read: the first card of the text; vCard 2.1 and 4.0 forms that phones write are taken too: bare type parameters
 * (TEL;CELL:), lower-case names, groups (item1.TEL), ENCODING=QUOTED-PRINTABLE (with soft line breaks), TYPE lists,
 * "tel:" URIs. Properties Myna does not keep (PHOTO, EMAIL, ADR, ...) are skipped. */
#ifndef MYNA_LIB_VCARD_H
#define MYNA_LIB_VCARD_H

#include <stdint.h>

#define VCARD_NUMBERS     4
#define VCARD_NAME_MAX    48       /* bytes of a name part with its 0 */
#define VCARD_NUMBER_MAX  32
#define VCARD_NOTE_MAX    256

enum vcard_label { VCARD_MOBILE, VCARD_HOME, VCARD_WORK, VCARD_OTHER, VCARD_LABELS };

struct vcard_number {
    char number[VCARD_NUMBER_MAX];         /* normal form (lib/phonenum.h) when it has one, else as written */
    uint8_t label;                         /* enum vcard_label */
};

struct vcard_contact {
    char given[VCARD_NAME_MAX];
    char family[VCARD_NAME_MAX];
    uint8_t count;                         /* numbers in use */
    struct vcard_number numbers[VCARD_NUMBERS];
    char note[VCARD_NOTE_MAX];
};

/* The vCard of a contact into out (max bytes; a 0 follows). Returns its length, or -1 if it does not fit. */
int vcard_format(const struct vcard_contact *c, char *out, unsigned max);

/* Read the first vCard of a text. Returns 0, or -1 when there is no card, or it has neither a name nor a number.
 * Fields too long for the contact are cut (at a character boundary); numbers beyond the fourth are dropped. */
int vcard_parse(const char *in, unsigned len, struct vcard_contact *c);

/* "given family", or the one that is set, or the first number */
void vcard_display_name(const struct vcard_contact *c, char *out, unsigned max);

const char *vcard_label_name(unsigned label);      /* "Mobile", "Home", "Work", "Other" */

#endif
