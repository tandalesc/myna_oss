/* SPDX-License-Identifier: MIT */
/* Contacts: name, up to four numbers with labels, a note; kept on the user file system, one vCard 3.0 file each
 * (/contacts/<id in hex>.vcf), so that a contact is shared by giving its file as it is.
 *
 * An index in RAM (name, the numbers and their match keys) is read at the first use, so a lookup by number
 * (lib/phonenum.h: the last 9 digits) costs no flash read: messages show the contact's name. Changes are written
 * at once (one littlefs commit each). With the index the service keeps, in RAM only, what smart search needs: each
 * name's key sequence (lib/keyseq.h) and the alphabetical order, made when the index is read and again for a change,
 * so a key typed costs no more than comparing keys. */
#ifndef MYNA_SERVICES_CONTACTS_H
#define MYNA_SERVICES_CONTACTS_H

#include <stdint.h>

#include "lib/vcard.h"

#define CONTACTS_MAX      500
#define CONTACT_NAME_MAX  40       /* the display name kept in the index */
#define CONTACT_NUMBERS_TEXT 64    /* its numbers kept in the index (normal forms between spaces) */

/* Each returns 0 or a negative error (-1 not found / invalid, -2 storage, -3 full). */
int contacts_init(void);                                       /* read the index (also done at the first use) */
int32_t contacts_add(const struct vcard_contact *c);           /* the new id (> 0) or an error */
int contacts_update(uint32_t id, const struct vcard_contact *c);
int contacts_delete(uint32_t id);
int contacts_get(uint32_t id, struct vcard_contact *c);

/* The display name of the contact with this number, or 0 (pointer into the index: valid until the next change). */
const char *contacts_lookup(const char *number);
uint32_t contacts_lookup_id(const char *number);               /* 0: none */

unsigned contacts_count(void);
/* the index-th contact (in the order of their ids): its id and display name */
int contacts_at(unsigned index, uint32_t *id, const char **name);
unsigned contacts_numbers_at(unsigned index);                  /* how many numbers it has (no flash read) */

/* the contacts in alphabetical order (letters without regard to case, then the bytes; equal names in the order of
   their ids): indexes for contacts_at(); returns how many */
unsigned contacts_sorted(uint16_t *order, unsigned max);
unsigned contacts_rank(unsigned index);                        /* the contact's place in that order */
/* number k of the index-th contact (its normal form) into out (max bytes with the 0); 0, or -1 if it has none */
int contacts_number_at(unsigned index, unsigned k, char *out, unsigned max);
/* the match keys of its numbers (lib/phonenum.h), *n of them */
const uint32_t *contacts_number_keys_at(unsigned index, unsigned *n);

/* ---- smart search (apps/search.c) ---- */

enum { CONTACTS_HIT_NAME, CONTACTS_HIT_WORD, CONTACTS_HIT_NUMBER };
struct contacts_hit {
    uint16_t index;            /* contacts_at() */
    uint8_t kind;              /* the name's first word, a later word, a number */
    uint8_t number;            /* CONTACTS_HIT_NUMBER: which number (contacts_number_at) */
    uint8_t at;                /* where the query starts: a key of the name (lib/keyseq.h), a character of the number */
};

/* The contacts that match query, keys typed ('0'-'9'; in a number also + * #): a word of the name starts with them
 * (a query of digits only), or one of the numbers holds them. Looks at every contact, or only at within[0..n) (the
 * hits of a shorter query that this one continues: they are all there can be). with_number: only contacts with a
 * number. Hits into out (room for CONTACTS_MAX), in index order; returns how many. */
unsigned contacts_search(const char *query, const uint16_t *within, unsigned n, int with_number,
                         struct contacts_hit *out);

#ifdef MYNA_TEST_HOOKS
/* test builds: made-up contacts in the RAM index (no files) up to n, for measuring smart search with a full book */
void contacts_test_fill(unsigned n);
#endif

/* Sharing: write one contact as a vCard file at `path` (any folder of the user file system), or take a contact in
 * from such a file (it is added; returns the new id). */
int contacts_export(uint32_t id, const char *path);
int32_t contacts_import(const char *path);

#endif
