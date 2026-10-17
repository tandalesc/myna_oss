/* SPDX-License-Identifier: MIT */
/* Phone numbers: one written form, and the rule by which two numbers are the same person's.
 *
 * Normal form: an optional '+' first, then digits, '*' and '#'; the separators people write ("+1 (555) 010-0123",
 * "555.0123", "555/0123") are dropped. Two numbers match when their last 9 digits are the same, so "+15550100123"
 * and "05550100123" (a national prefix) are one person; numbers of fewer than 9 digits (short codes) match only a
 * number of the same digits. The rule is a single 32-bit key, so a lookup compares words. */
#ifndef MYNA_LIB_PHONENUM_H
#define MYNA_LIB_PHONENUM_H

#include <stdint.h>

#define PHONENUM_MATCH_DIGITS 9

/* The normal form of `in` into out (max bytes with its 0). Returns its length, or -1 when `in` holds a character
 * that is not a digit, '*', '#', a leading '+' or a separator (space, '-', '(', ')', '.', '/'), or no digit at all. */
int phonenum_normalize(const char *in, char *out, unsigned max);

/* The match key: equal keys = the same number by the rule above. Characters other than digits are skipped. */
uint32_t phonenum_key(const char *number);

static inline int phonenum_match(const char *a, const char *b)
{
    return phonenum_key(a) == phonenum_key(b);
}

#endif
