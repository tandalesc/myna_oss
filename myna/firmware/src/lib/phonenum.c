/* SPDX-License-Identifier: MIT */
/* Phone numbers (lib/phonenum.h). */
#include <stdint.h>

#include "lib/phonenum.h"

int phonenum_normalize(const char *in, char *out, unsigned max)
{
    unsigned n = 0, digits = 0;
    const char *p = in;
    while (*p == ' ')
        p++;
    if (*p == '+') {
        if (max < 2)
            return -1;
        out[n++] = '+';
        p++;
    }
    for (; *p; p++) {
        char c = *p;
        if ((c >= '0' && c <= '9') || c == '*' || c == '#') {
            if (n + 1 >= max)
                return -1;
            out[n++] = c;
            digits += c >= '0' && c <= '9';
        } else if (c != ' ' && c != '-' && c != '(' && c != ')' && c != '.' && c != '/') {
            return -1;
        }
    }
    out[n] = 0;
    return digits ? (int)n : -1;
}

uint32_t phonenum_key(const char *number)
{
    /* the last 9 digits as a number (below 10^9); a shorter number gets 10^9 + its digit count x 10^8 added, which
       keeps numbers of different lengths apart (their values are below 10^8) and stays below 2^32 */
    static const uint32_t mod = 1000000000u;
    uint32_t tail = 0, digits = 0;
    for (const char *p = number; *p; p++)
        if (*p >= '0' && *p <= '9') {
            tail = (tail % (mod / 10)) * 10 + (uint32_t)(*p - '0');
            digits++;
        }
    if (digits >= PHONENUM_MATCH_DIGITS)
        return tail;
    return mod + digits * 100000000u + tail;
}
