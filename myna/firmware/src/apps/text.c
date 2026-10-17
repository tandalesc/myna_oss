/* SPDX-License-Identifier: MIT */
/* Text for the applications (apps/phone.h): text from the services made safe to show, a line that fits, short
 * dates. */
#include <stdint.h>

#include "apps/phone.h"
#include "drivers/clock.h"
#include "gfx/gfx.h"
#include "lib/mem.h"
#include "lib/utf8.h"
#include "ui/widget.h"

unsigned text_from_utf8(char *out, unsigned max, const char *in)
{
    const char *p = in, *end = in + strlen(in);
    unsigned n = 0;
    while (p < end) {
        const char *at = p;
        uint32_t c = utf8_next(&p, end);
        if (c == UTF8_REPLACEMENT && p - at == 1 && (uint8_t)*at >= 0x80)
            c = '?';           /* a malformed byte: shown as the fonts' unknown sign, kept one byte */
        unsigned k = utf8_len(c);
        if (n + k + 1 > max)
            break;
        n += utf8_put(c, out + n);
    }
    if (max)
        out[n] = 0;
    return n;
}

unsigned text_to_utf8(char *out, unsigned max, const char *in)
{
    unsigned n = (unsigned)strlen(in);
    if (!max)
        return 0;
    copy_text(out, in, max);
    return n < max ? n : (unsigned)strlen(out);
}

void text_fit(const struct font *f, const char *in, int width, char *out, unsigned max)
{
    unsigned n = 0;
    for (; in[n] && n + 1 < max; n++)
        out[n] = in[n] == '\n' || in[n] == '\r' ? ' ' : in[n];
    while (in[n] && n > 0 && ((uint8_t)in[n] & 0xC0) == 0x80)
        n--;                   /* cut before a whole character */
    out[n] = 0;
    if (gfx_text_width(f, out) <= width)
        return;
    int room = width - gfx_text_width(f, TEXT_ELLIPSIS);
    while (n > 0 && text_width_n(f, out, (int)n) > room)
        n = (unsigned)text_prev(out, (int)n);
    while (n > 0 && out[n - 1] == ' ')
        n--;
    while (n > 0 && n + 4 > max)
        n = (unsigned)text_prev(out, (int)n);     /* room for the ellipsis's three bytes */
    copy_text(out + n, TEXT_ELLIPSIS, max - n);
}

static const char *const months[12] = { "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
                                        "Dec" };
static const char *const days[7] = { "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun" };

/* "12 Oct" */
static int day_month(char *out, const struct civil_time *c)
{
    int n = format_uint(out, c->day);
    out[n++] = ' ';
    memcpy(out + n, months[c->month - 1], 3);
    n += 3;
    out[n] = 0;
    return n;
}

void format_when(char *out, uint32_t t)
{
    uint32_t now = clock_seconds(), today = now - now % 86400u;
    struct civil_time c;
    clock_civil(t, &c);
    if (t >= today && t < today + 86400u)
        format_time(out, t, 1);
    else if (t >= today - 86400u && t < today)
        copy_text(out, "Yesterday", 12);
    else if (t >= today - 6 * 86400u && t < today)
        copy_text(out, days[c.weekday], 12);
    else
        day_month(out, &c);
}

void format_day_time(char *out, uint32_t t)
{
    uint32_t now = clock_seconds(), today = now - now % 86400u;
    int n = 0;
    if (t < today || t >= today + 86400u) {
        struct civil_time c;
        clock_civil(t, &c);
        n = day_month(out, &c);
        out[n++] = ',';
        out[n++] = ' ';
    }
    format_time(out + n, t, 1);
}
