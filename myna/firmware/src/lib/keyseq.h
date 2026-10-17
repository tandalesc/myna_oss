/* SPDX-License-Identifier: MIT */
/* Key sequences: text as the keys of a phone's keypad spell it (2 abc, 3 def, 4 ghi, 5 jkl, 6 mno, 7 pqrs, 8 tuv,
 * 9 wxyz), for predictive text (services/words.h) and smart search (apps/search.c).
 *
 * A letter is on the key of its base letter, its accents folded (é on 3 as e, ł on 5 as l: Latin-1, Latin
 * Extended-A and the Romanian comma letters). Cyrillic is on the Russian layout: 2 абвг, 3 деёжз, 4 ийкл, 5 мноп,
 * 6 рсту, 7 фхцч, 8 шщъы, 9 ьэюя (the Ukrainian ґ, є, і, ї with г, е, и; the Belarusian ў with у).
 *
 * A name's keys are its letters' keys and its digits, with one ' ' where a word ends: a run of spaces, hyphens and
 * other signs is one break, an apostrophe joins ("O'Neil" is one word). "Jean-Luc O'Neil" is "5326 582 66345". Smart
 * search looks for a query at the start of a word; in a query, 0 and 1 also stand for a break, so 5326-1-582 is
 * "Jean-Luc". Freestanding: no allocation, nothing but lib/utf8.h. */
#ifndef MYNA_LIB_KEYSEQ_H
#define MYNA_LIB_KEYSEQ_H

#include <stdint.h>

/* the key of a letter: '2'-'9', or 0 for anything that is not a letter */
char keyseq_letter(uint32_t c);

/* The keys of a name (UTF-8) into keys (max bytes with the 0). at (may be 0) gets for each key the byte where its
 * character starts (a break: its first sign). Returns the number of keys. */
int keyseq_name(const char *name, char *keys, uint8_t *at, unsigned max);

/* Where in a name's keys (keyseq_name) a word starts with the n keys of query ('0'-'9'): the key position (0: the
 * name's start; the first such word), or -1. */
int keyseq_word(const char *keys, const char *query, unsigned n);

/* The first place of query's n characters in text: a number, or several numbers separated by single spaces (a space
 * is never matched). Returns the position in that number and its place in the list in *which, or -1. */
int keyseq_find(const char *text, const char *query, unsigned n, unsigned *which);

#endif
