/* SPDX-License-Identifier: MIT */
/* GSM 7-bit default alphabet (lib/gsm7.h). The tables are written from 3GPP TS 23.038 section 6.2.1. */
#include <stdint.h>

#include "lib/gsm7.h"

/* the default alphabet: septet -> Unicode. 0x1B is the escape to the extension table (shown as a space when it
 * stands alone: TS 23.038 6.2.1, note 1) */
static const uint16_t basic[128] = {
    0x0040, 0x00A3, 0x0024, 0x00A5, 0x00E8, 0x00E9, 0x00F9, 0x00EC,     /* @ £ $ ¥ è é ù ì */
    0x00F2, 0x00C7, 0x000A, 0x00D8, 0x00F8, 0x000D, 0x00C5, 0x00E5,     /* ò Ç LF Ø ø CR Å å */
    0x0394, 0x005F, 0x03A6, 0x0393, 0x039B, 0x03A9, 0x03A0, 0x03A8,     /* Δ _ Φ Γ Λ Ω Π Ψ */
    0x03A3, 0x0398, 0x039E, 0x0020, 0x00C6, 0x00E6, 0x00DF, 0x00C9,     /* Σ Θ Ξ ESC Æ æ ß É */
    0x0020, 0x0021, 0x0022, 0x0023, 0x00A4, 0x0025, 0x0026, 0x0027,     /* SP ! " # ¤ % & ' */
    0x0028, 0x0029, 0x002A, 0x002B, 0x002C, 0x002D, 0x002E, 0x002F,
    0x0030, 0x0031, 0x0032, 0x0033, 0x0034, 0x0035, 0x0036, 0x0037,
    0x0038, 0x0039, 0x003A, 0x003B, 0x003C, 0x003D, 0x003E, 0x003F,
    0x00A1, 0x0041, 0x0042, 0x0043, 0x0044, 0x0045, 0x0046, 0x0047,     /* ¡ A-G */
    0x0048, 0x0049, 0x004A, 0x004B, 0x004C, 0x004D, 0x004E, 0x004F,
    0x0050, 0x0051, 0x0052, 0x0053, 0x0054, 0x0055, 0x0056, 0x0057,
    0x0058, 0x0059, 0x005A, 0x00C4, 0x00D6, 0x00D1, 0x00DC, 0x00A7,     /* X Y Z Ä Ö Ñ Ü § */
    0x00BF, 0x0061, 0x0062, 0x0063, 0x0064, 0x0065, 0x0066, 0x0067,     /* ¿ a-g */
    0x0068, 0x0069, 0x006A, 0x006B, 0x006C, 0x006D, 0x006E, 0x006F,
    0x0070, 0x0071, 0x0072, 0x0073, 0x0074, 0x0075, 0x0076, 0x0077,
    0x0078, 0x0079, 0x007A, 0x00E4, 0x00F6, 0x00F1, 0x00FC, 0x00E0,     /* x y z ä ö ñ ü à */
};

/* the extension table: septet after the escape -> Unicode */
static const struct {
    uint8_t septet;
    uint16_t c;
} ext[] = {
    { 0x0A, 0x000C },          /* form feed (page break) */
    { 0x14, 0x005E },          /* ^ */
    { 0x28, 0x007B },          /* { */
    { 0x29, 0x007D },          /* } */
    { 0x2F, 0x005C },          /* \ */
    { 0x3C, 0x005B },          /* [ */
    { 0x3D, 0x007E },          /* ~ */
    { 0x3E, 0x005D },          /* ] */
    { 0x40, 0x007C },          /* | */
    { 0x65, 0x20AC },          /* € */
};

#define NONE 0xFF

/* Unicode -> septet for U+0000-U+00FF, made from `basic` at the first use (0xFF: not in the default table) */
static uint8_t latin[256];
static uint8_t latin_ready;

static void make_latin(void)
{
    for (unsigned i = 0; i < 256; i++)
        latin[i] = NONE;
    for (unsigned s = 0; s < 128; s++)
        if (s != GSM7_ESC && basic[s] < 256)
            latin[basic[s]] = (uint8_t)s;
    latin_ready = 1;
}

unsigned gsm7_from_unicode(uint32_t c, uint8_t out[2])
{
    if (c < 256) {
        if (!latin_ready)
            make_latin();
        if (latin[c] != NONE) {
            out[0] = latin[c];
            return 1;
        }
    } else if (c >= 0x0393 && c <= 0x03A9) {
        /* the Greek capitals of the table */
        for (unsigned s = 0x10; s < 0x1B; s++)
            if (basic[s] == c) {
                out[0] = (uint8_t)s;
                return 1;
            }
    }
    for (unsigned i = 0; i < sizeof ext / sizeof ext[0]; i++)
        if (ext[i].c == c) {
            out[0] = GSM7_ESC;
            out[1] = ext[i].septet;
            return 2;
        }
    return 0;
}

uint32_t gsm7_to_unicode(uint8_t septet, int extended)
{
    septet &= 0x7F;
    if (extended) {
        for (unsigned i = 0; i < sizeof ext / sizeof ext[0]; i++)
            if (ext[i].septet == septet)
                return ext[i].c;
    }
    return basic[septet];
}

unsigned gsm7_pack(const uint8_t *septets, unsigned n, unsigned fill, uint8_t *out)
{
    unsigned bits = fill, octets = (fill + 7 * n + 7) / 8;
    for (unsigned i = 0; i < octets; i++)
        out[i] = 0;
    for (unsigned i = 0; i < n; i++, bits += 7) {
        uint32_t v = (uint32_t)(septets[i] & 0x7F) << (bits & 7);
        out[bits >> 3] |= (uint8_t)v;
        if ((bits & 7) > 1)
            out[(bits >> 3) + 1] |= (uint8_t)(v >> 8);
    }
    return octets;
}

void gsm7_unpack(const uint8_t *in, unsigned n, unsigned fill, uint8_t *septets)
{
    unsigned bits = fill;
    for (unsigned i = 0; i < n; i++, bits += 7) {
        uint32_t v = in[bits >> 3];
        if ((bits & 7) > 1)
            v |= (uint32_t)in[(bits >> 3) + 1] << 8;
        septets[i] = (uint8_t)((v >> (bits & 7)) & 0x7F);
    }
}
