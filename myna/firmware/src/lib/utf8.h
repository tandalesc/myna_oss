/* SPDX-License-Identifier: MIT */
/* UTF-8: the text form of every string in Myna (messages, contacts, names). Malformed input decodes to U+FFFD and
 * never stops a decoder; nothing here allocates. */
#ifndef MYNA_LIB_UTF8_H
#define MYNA_LIB_UTF8_H

#include <stdint.h>

#define UTF8_REPLACEMENT 0xFFFDu

/* Decode one character at *p (before end) and advance *p past it. A malformed or truncated sequence gives
 * U+FFFD and advances one byte. */
static inline uint32_t utf8_next(const char **p, const char *end)
{
    const uint8_t *s = (const uint8_t *)*p;
    uint32_t c = *s;
    unsigned n;
    uint32_t min;
    if (c < 0x80) {
        *p += 1;
        return c;
    } else if ((c & 0xE0) == 0xC0) {
        n = 1, c &= 0x1F, min = 0x80;
    } else if ((c & 0xF0) == 0xE0) {
        n = 2, c &= 0x0F, min = 0x800;
    } else if ((c & 0xF8) == 0xF0) {
        n = 3, c &= 0x07, min = 0x10000;
    } else {
        *p += 1;
        return UTF8_REPLACEMENT;
    }
    if ((const char *)s + 1 + n > end) {          /* fewer than n continuation bytes left */
        *p += 1;
        return UTF8_REPLACEMENT;
    }
    for (unsigned i = 1; i <= n; i++) {
        if ((s[i] & 0xC0) != 0x80) {
            *p += 1;
            return UTF8_REPLACEMENT;
        }
        c = (c << 6) | (s[i] & 0x3F);
    }
    if (c < min || c > 0x10FFFF || (c >= 0xD800 && c <= 0xDFFF)) {
        *p += 1;
        return UTF8_REPLACEMENT;
    }
    *p += 1 + n;
    return c;
}

/* Write a character as UTF-8 (1-4 bytes) and return the count. Surrogates and values above U+10FFFF become
 * U+FFFD. */
static inline unsigned utf8_put(uint32_t c, char *out)
{
    uint8_t *o = (uint8_t *)out;
    if (c >= 0xD800 && (c <= 0xDFFF || c > 0x10FFFF))
        c = UTF8_REPLACEMENT;
    if (c < 0x80) {
        o[0] = (uint8_t)c;
        return 1;
    }
    if (c < 0x800) {
        o[0] = (uint8_t)(0xC0 | c >> 6);
        o[1] = (uint8_t)(0x80 | (c & 0x3F));
        return 2;
    }
    if (c < 0x10000) {
        o[0] = (uint8_t)(0xE0 | c >> 12);
        o[1] = (uint8_t)(0x80 | ((c >> 6) & 0x3F));
        o[2] = (uint8_t)(0x80 | (c & 0x3F));
        return 3;
    }
    o[0] = (uint8_t)(0xF0 | c >> 18);
    o[1] = (uint8_t)(0x80 | ((c >> 12) & 0x3F));
    o[2] = (uint8_t)(0x80 | ((c >> 6) & 0x3F));
    o[3] = (uint8_t)(0x80 | (c & 0x3F));
    return 4;
}

/* the bytes of the UTF-8 form of c */
static inline unsigned utf8_len(uint32_t c)
{
    return c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4;
}

#endif
