/* SPDX-License-Identifier: MIT */
/* mkfont: a build-host tool that turns a TrueType font into Myna glyph atlases (C source, myna/firmware/src/gfx/font.h).
 *
 *   mkfont OUT.c FONT.ttf NAME [phases=N] [gamma=G] SIZE[:CHARS] [SIZE[:CHARS] ...]
 *
 * For each SIZE (em size in pixels) it writes `const struct font font_NAME_SIZE`. CHARS is the set of characters of
 * that size: "text" (the default: printable ASCII, Latin-1 0xA0-0xFF and the typographic signs Latin-1 lacks: the list
 * chevron U+203A, the bullet, the ellipsis, the dashes, curly quotes, the euro sign), "text+cyrillic" (the same with
 * Cyrillic, U+0400-045F and U+0490-0491), or a literal list in UTF-8 such as "0123456789: " for a size that only shows
 * a clock. The firmware's text is UTF-8; an atlas maps U+0000-00FF through a table and every other character through a
 * short list of ranges. The outlines are rasterised by stb_truetype (myna/third_party/stb), anti-aliased, and kept as
 * 4-bit coverage. A character the font does not have is left out (the phone draws '?' for it).
 *
 * phases=N (for the sizes after it) renders each glyph N times, shifted right by 0, 1/N ... (N-1)/N pixel, so that the
 * phone can place glyphs at a third of a pixel (N = 3) and a word keeps the spacing of its font instead of each letter
 * snapping to whole pixels. gamma=G (for the sizes after it) maps coverage a to a^G (G < 1 darkens the edges, as a
 * browser's text rendering does). The defaults are 1 and 1. The phone only copies these bitmaps; it never sees the TrueType file.
 *
 * Built and run by myna/firmware/Makefile with the host's `cc`. A variable font is rendered at its default instance:
 * stb_truetype does not apply variations. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define STB_TRUETYPE_IMPLEMENTATION
#include "stb_truetype.h"

#define CODES      0x10000     /* the characters an atlas can hold: the Basic Multilingual Plane */
#define RANGES_MAX 64

static void die(const char *what, const char *detail)
{
    fprintf(stderr, "mkfont: %s%s%s\n", what, detail ? ": " : "", detail ? detail : "");
    exit(1);
}

static unsigned char *read_file(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        die("cannot open", path);
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char *buf = malloc((size_t)n);
    if (!buf || fread(buf, 1, (size_t)n, f) != (size_t)n)
        die("cannot read", path);
    fclose(f);
    return buf;
}

/* the typographic signs of the texts beyond Latin-1: what Windows-1252 has in 0x80-0x9F */
static const int typographic[] = {
    0x20AC, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021, 0x02C6, 0x2030, 0x0160, 0x2039, 0x0152, 0x017D, 0x2018,
    0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014, 0x02DC, 0x2122, 0x0161, 0x203A, 0x0153, 0x017E, 0x0178,
};

/* the characters of one size, as a membership table of CODES entries */
static void parse_chars(const char *spec, unsigned char *want)
{
    memset(want, 0, CODES);
    if (!spec || !strncmp(spec, "text", 4)) {
        for (int c = 0x20; c <= 0x7E; c++)
            want[c] = 1;
        for (int c = 0xA0; c <= 0xFF; c++)
            want[c] = 1;
        for (unsigned i = 0; i < sizeof typographic / sizeof typographic[0]; i++)
            want[typographic[i]] = 1;
        if (spec && !strcmp(spec, "text+cyrillic")) {
            for (int c = 0x400; c <= 0x45F; c++)
                want[c] = 1;
            want[0x490] = want[0x491] = 1;
        } else if (spec && strcmp(spec, "text")) {
            die("unknown character set", spec);
        }
        return;
    }
    /* a literal list: the command line is UTF-8 (one- to three-byte sequences) */
    for (const unsigned char *p = (const unsigned char *)spec; *p;) {
        int c = *p++;
        if (c >= 0xE0 && (p[0] & 0xC0) == 0x80 && (p[1] & 0xC0) == 0x80) {
            c = ((c & 0x0F) << 12) | ((p[0] & 0x3F) << 6) | (p[1] & 0x3F);
            p += 2;
        } else if (c >= 0xC0 && (*p & 0xC0) == 0x80) {
            c = ((c & 0x1F) << 6) | (*p++ & 0x3F);
        }
        if (c >= 0x80 && c < 0xA0)
            continue;                  /* C1 controls: not characters */
        want[c] = 1;
    }
}

static void emit_size(FILE *out, const stbtt_fontinfo *info, const char *name, int size, const unsigned char *want,
                      int phases, float gamma)
{
    float scale = stbtt_ScaleForMappingEmToPixels(info, (float)size);
    int asc, desc, gap;
    stbtt_GetFontVMetrics(info, &asc, &desc, &gap);

    /* glyph numbers: U+0000-00FF first (their number must fit the 8-bit table), then the ranges above */
    static int index[CODES];
    int count = 0;
    for (int c = 0; c < CODES; c++)
        index[c] = want[c] && stbtt_FindGlyphIndex(info, c) ? count++ : -1;
    if (count == 0)
        die("no glyph of the requested characters in the font", NULL);
    for (int c = 0; c < 256; c++)
        if (index[c] >= 255)
            die("too many glyphs below U+0100", NULL);
    int range_first[RANGES_MAX], range_count[RANGES_MAX], ranges = 0;
    for (int c = 256; c < CODES; c++) {
        if (index[c] < 0)
            continue;
        if (ranges && range_first[ranges - 1] + range_count[ranges - 1] == c) {
            range_count[ranges - 1]++;
            continue;
        }
        if (ranges == RANGES_MAX)
            die("too many ranges of characters", NULL);
        range_first[ranges] = c;
        range_count[ranges++] = 1;
    }

    /* the bitmaps first, collecting each glyph's metrics on the way */
    struct { long offset; int w, h, x, y, adv; } *g = calloc((size_t)(count * phases), sizeof *g);
    int map[256];
    for (int a = 0; a < 256; a++)
        map[a] = (int)lroundf(powf(a / 255.0f, gamma) * 15.0f);
    fprintf(out, "static const uint8_t %s_%d_bitmap[] = {", name, size);
    long offset = 0;
    int cap = 0, col = 0;
    for (int u = 0; u < CODES; u++) {
        if (index[u] < 0)
            continue;
        int adv, lsb;
        stbtt_GetCodepointHMetrics(info, u, &adv, &lsb);
        for (int p = 0; p < phases; p++) {
            int i = index[u] * phases + p, x0, y0, x1, y1;
            float shift = (float)p / (float)phases;
            stbtt_GetCodepointBitmapBoxSubpixel(info, u, scale, scale, shift, 0, &x0, &y0, &x1, &y1);
            int w = x1 - x0, h = y1 - y0;
            if (w > 255 || h > 255 || x0 < -128 || x0 > 127 || y0 < -128 || y0 > 127)
                die("glyph too large for the atlas format", NULL);
            g[i].offset = offset;
            g[i].w = w;
            g[i].h = h;
            g[i].x = x0;
            g[i].y = y0;
            g[i].adv = (int)lroundf(adv * scale * 16.0f);
            if (p == 0 && ((u >= '0' && u <= '9') || (u == 'H' && cap == 0)))
                cap = -y0 > cap ? -y0 : cap;
            if (w <= 0 || h <= 0) {
                g[i].w = g[i].h = 0;
                continue;
            }
            unsigned char *a8 = calloc((size_t)(w * h), 1);
            stbtt_MakeCodepointBitmapSubpixel(info, a8, w, h, w, scale, scale, shift, 0, u);
            int row = (w + 1) / 2;
            for (int y = 0; y < h; y++) {
                for (int bx = 0; bx < row; bx++) {
                    int l = a8[y * w + bx * 2];
                    int r = bx * 2 + 1 < w ? a8[y * w + bx * 2 + 1] : 0;
                    int b = map[l] | map[r] << 4;
                    fprintf(out, "%s0x%02x,", col++ % 16 ? " " : "\n    ", b);
                }
            }
            offset += (long)row * h;
            free(a8);
        }
    }
    fprintf(out, "\n};\n\n");

    fprintf(out, "static const struct font_glyph %s_%d_glyphs[] = {\n", name, size);
    for (int u = 0; u < CODES; u++) {
        if (index[u] < 0)
            continue;
        for (int p = 0; p < phases; p++) {
            int i = index[u] * phases + p;
            fprintf(out, "    { %ld, %d, %d, %d, %d, %d, 0 },   /* U+%04X %d/%d */\n", g[i].offset, g[i].w, g[i].h,
                    g[i].x, g[i].y, g[i].adv, u, p, phases);
        }
    }
    fprintf(out, "};\n\n");

    if (ranges) {
        fprintf(out, "static const struct font_range %s_%d_ranges[] = {\n", name, size);
        for (int r = 0; r < ranges; r++)
            fprintf(out, "    { 0x%04X, %d, %d },\n", range_first[r], range_count[r], index[range_first[r]]);
        fprintf(out, "};\n\n");
    }

    fprintf(out, "const struct font font_%s_%d = {\n", name, size);
    fprintf(out, "    .name = \"%s %d\",\n    .size = %d,\n", name, size, size);
    fprintf(out, "    .ascent = %d,\n    .descent = %d,\n", (int)ceilf(asc * scale), (int)ceilf(-desc * scale));
    fprintf(out, "    .line_height = %d,\n    .cap_height = %d,\n    .phases = %d,\n",
            (int)lroundf((asc - desc + gap) * scale), cap, phases);
    fprintf(out, "    .index = {");
    for (int c = 0; c < 256; c++)
        fprintf(out, "%s%d,", c % 16 ? " " : "\n        ", index[c] < 0 ? 255 : index[c]);
    fprintf(out, "\n    },\n    .range_count = %d,\n", ranges);
    if (ranges)
        fprintf(out, "    .ranges = %s_%d_ranges,\n", name, size);
    fprintf(out, "    .glyph_count = %d,\n", count);
    fprintf(out, "    .glyphs = %s_%d_glyphs,\n    .bitmap = %s_%d_bitmap,\n};\n\n", name, size, name, size);
    fprintf(stderr, "mkfont: %s %d px: %d glyphs x %d phases in %d ranges above U+00FF, %ld bytes of bitmap\n", name,
            size, count, phases, ranges, offset);
    free(g);
}

int main(int argc, char **argv)
{
    if (argc < 5)
        die("usage: mkfont OUT.c FONT.ttf NAME SIZE[:CHARS] ...", NULL);
    unsigned char *ttf = read_file(argv[2]);
    stbtt_fontinfo info;
    if (!stbtt_InitFont(&info, ttf, stbtt_GetFontOffsetForIndex(ttf, 0)))
        die("not a TrueType font", argv[2]);

    FILE *out = fopen(argv[1], "w");
    if (!out)
        die("cannot write", argv[1]);
    fprintf(out, "/* SPDX-License-Identifier: OFL-1.1 */\n");
    fprintf(out, "/* Generated by myna/tools/mkfont from %s: glyph bitmaps of a font under the licence of that font. */\n",
            argv[2]);
    fprintf(out, "#include \"gfx/font.h\"\n\n");
    int phases = 1;
    float gamma = 1.0f;
    static unsigned char want[CODES];
    for (int i = 4; i < argc; i++) {
        if (!strncmp(argv[i], "phases=", 7)) {
            phases = atoi(argv[i] + 7);
            if (phases < 1 || phases > 4)
                die("phases must be 1-4", argv[i]);
            continue;
        }
        if (!strncmp(argv[i], "gamma=", 6)) {
            gamma = (float)atof(argv[i] + 6);
            if (gamma < 0.3f || gamma > 3.0f)
                die("gamma must be 0.3-3", argv[i]);
            continue;
        }
        char *spec = argv[i], *colon = strchr(spec, ':');
        parse_chars(colon ? colon + 1 : NULL, want);
        int size = atoi(spec);
        if (size < 4 || size > 200)
            die("bad size", spec);
        emit_size(out, &info, argv[3], size, want, phases, gamma);
    }
    if (fclose(out))
        die("cannot write", argv[1]);
    free(ttf);
    return 0;
}
