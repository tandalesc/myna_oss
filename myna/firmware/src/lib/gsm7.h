/* SPDX-License-Identifier: MIT */
/* The GSM 7-bit default alphabet and its extension table (3GPP TS 23.038 section 6.2.1), and septet packing
 * (TS 23.038 section 6.1.2.1). National language shift tables are not supported: a message that names one in its
 * header is decoded with the default tables. */
#ifndef MYNA_LIB_GSM7_H
#define MYNA_LIB_GSM7_H

#include <stdint.h>

#define GSM7_ESC 0x1B

/* The septets of a Unicode character: 1 (out[0]), 2 (escape, then out[1]: the extension table), or 0 when the
 * default alphabet cannot carry it. */
unsigned gsm7_from_unicode(uint32_t c, uint8_t out[2]);

/* The character of a septet; ext = 1 for the septet after an escape. A septet the extension table does not define
 * is shown as its default-table character (TS 23.038: "shall be displayed as ... the default alphabet"). */
uint32_t gsm7_to_unicode(uint8_t septet, int ext);

/* Pack n septets into octets after `fill` padding bits (0-6, before the first septet, used after a user data
 * header). Returns the octets written: (fill + 7 n + 7) / 8. */
unsigned gsm7_pack(const uint8_t *septets, unsigned n, unsigned fill, uint8_t *out);

/* Unpack n septets that start `fill` bits into `in` (which holds at least (fill + 7 n + 7) / 8 octets). */
void gsm7_unpack(const uint8_t *in, unsigned n, unsigned fill, uint8_t *septets);

#endif
