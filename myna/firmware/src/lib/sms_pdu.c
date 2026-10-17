/* SPDX-License-Identifier: MIT */
/* Text message PDUs (lib/sms_pdu.h), written from 3GPP TS 23.040 and TS 23.038. */
#include <stdint.h>

#include "lib/gsm7.h"
#include "lib/sms_pdu.h"
#include "lib/utf8.h"

#define VP_DEFAULT 0xAD        /* relative validity 173: (173 - 166) days = 7 days (TS 23.040 9.2.3.12.1) */

/* ---- planning ---- */

static unsigned ucs2_units(uint32_t c)
{
    return c >= 0x10000 ? 2 : 1;
}

int sms_plan(const char *text, unsigned len, struct sms_plan *plan)
{
    const char *p = text, *end = text + len;
    unsigned septets = 0, units = 0;
    int gsm = 1;
    uint8_t s[2];
    while (p < end) {
        uint32_t c = utf8_next(&p, end);
        units += ucs2_units(c);
        if (gsm) {
            unsigned n = gsm7_from_unicode(c, s);
            if (n)
                septets += n;
            else
                gsm = 0;
        }
    }
    plan->coding = gsm ? SMS_GSM7 : SMS_UCS2;
    plan->units = (uint16_t)(gsm ? septets : units);
    plan->start[0] = 0;
    if (len == 0) {
        plan->parts = 0;
        plan->start[1] = 0;
        return 0;
    }
    unsigned single = gsm ? SMS_GSM7_SINGLE : SMS_UCS2_SINGLE, each = gsm ? SMS_GSM7_PART : SMS_UCS2_PART;
    if (plan->units <= single) {
        plan->parts = 1;
        plan->start[1] = (uint16_t)len;
        return 1;
    }
    /* cut before the character that would overflow a part: an escape pair or a surrogate pair stays whole */
    unsigned parts = 0, used = 0;
    p = text;
    while (p < end) {
        const char *at = p;
        uint32_t c = utf8_next(&p, end);
        unsigned n = gsm ? gsm7_from_unicode(c, s) : ucs2_units(c);
        if (used + n > each) {
            if (++parts >= SMS_PARTS_MAX)
                return -1;
            plan->start[parts] = (uint16_t)(at - text);
            used = 0;
        }
        used += n;
    }
    plan->parts = (uint8_t)(parts + 1);
    plan->start[parts + 1] = (uint16_t)len;
    return plan->parts;
}

/* ---- addresses (TS 23.040 9.1.2.5) ---- */

static const char semi_digit[16] = "0123456789*#abc";

static int digit_value(char c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    switch (c) {
    case '*': return 10;
    case '#': return 11;
    case 'a': case 'A': return 12;
    case 'b': case 'B': return 13;
    case 'c': case 'C': return 14;
    }
    return -1;
}

/* address field: length (digits), type, semi-octets. Returns octets written or -1 */
static int encode_addr(const char *number, uint8_t *o, unsigned max)
{
    uint8_t type = 0x81;       /* unknown type of number, ISDN numbering plan */
    if (*number == '+') {
        type = 0x91;           /* international */
        number++;
    }
    unsigned digits = 0;
    for (const char *c = number; *c; c++) {
        if (digit_value(*c) < 0)
            return -1;
        digits++;
    }
    if (digits == 0 || digits > 20 || 2 + (digits + 1) / 2 > max)
        return -1;
    o[0] = (uint8_t)digits;
    o[1] = type;
    for (unsigned i = 0; i < digits; i += 2) {
        unsigned lo = (unsigned)digit_value(number[i]);
        unsigned hi = i + 1 < digits ? (unsigned)digit_value(number[i + 1]) : 0xF;
        o[2 + i / 2] = (uint8_t)(hi << 4 | lo);
    }
    return 2 + (int)(digits + 1) / 2;
}

/* semi-octet digits to text; stops at a filler */
static void digits_text(const uint8_t *p, unsigned digits, int plus, char *out)
{
    unsigned n = 0;
    if (plus)
        out[n++] = '+';
    for (unsigned i = 0; i < digits && n + 1 < SMS_ADDR_MAX; i++) {
        unsigned v = (i & 1) ? p[i / 2] >> 4 : p[i / 2] & 0x0F;
        if (v == 0xF)
            break;
        out[n++] = semi_digit[v];
    }
    out[n] = 0;
}

/* septets to UTF-8 (escape pairs resolved), at most max bytes; returns the bytes */
static unsigned septets_text(const uint8_t *s, unsigned n, char *out, unsigned max)
{
    unsigned len = 0;
    for (unsigned i = 0; i < n; i++) {
        uint32_t c;
        if (s[i] == GSM7_ESC) {
            if (i + 1 >= n)
                break;         /* a lone escape at the end: nothing to show */
            c = gsm7_to_unicode(s[++i], 1);
        } else {
            c = gsm7_to_unicode(s[i], 0);
        }
        if (len + utf8_len(c) > max)
            break;
        len += utf8_put(c, out + len);
    }
    return len;
}

/* address field at p (len octets left): text into out; returns octets taken or -1 */
static int decode_addr(const uint8_t *p, unsigned len, char *out, uint8_t *type_out)
{
    if (len < 2)
        return -1;
    unsigned digits = p[0], type = p[1], octets = (digits + 1) / 2;
    if (digits > 22 || 2 + octets > len)
        return -1;
    if (type_out)
        *type_out = (uint8_t)type;
    if ((type & 0x70) == 0x50) {
        /* alphanumeric: GSM 7-bit characters packed into the semi-octets (TS 23.040 9.1.2.5) */
        uint8_t s[24];
        unsigned n = digits * 4 / 7;
        gsm7_unpack(p + 2, n, 0, s);
        unsigned b = septets_text(s, n, out, SMS_ADDR_MAX - 1);
        out[b] = 0;
    } else {
        digits_text(p + 2, digits, (type & 0x70) == 0x10, out);
    }
    return 2 + (int)octets;
}

int sms_skip_sca(const uint8_t *pdu, unsigned len, char *sc)
{
    if (len < 1 || 1u + pdu[0] > len)
        return -1;
    unsigned n = pdu[0];
    if (sc) {
        sc[0] = 0;
        if (n >= 2)
            digits_text(pdu + 2, (n - 1) * 2, (pdu[1] & 0x70) == 0x10, sc);
    }
    return 1 + (int)n;
}

/* ---- sending ---- */

int sms_encode_submit(const struct sms_submit *s, const struct sms_plan *plan, const char *text, unsigned part,
                      uint8_t *tpdu, unsigned max)
{
    if (part >= plan->parts || max < 8)
        return -1;
    int concat = plan->parts > 1;
    unsigned n = 0;
    tpdu[n++] = (uint8_t)(0x01 | 0x10 | (s->status_report ? 0x20 : 0) | (concat ? 0x40 : 0));   /* SUBMIT, VP relative */
    tpdu[n++] = 0;                                                                              /* TP-MR: the modem's */
    int a = encode_addr(s->to, tpdu + n, max - n);
    if (a < 0)
        return -1;
    n += (unsigned)a;
    if (n + 4 > max)
        return -1;
    tpdu[n++] = 0x00;                                                   /* TP-PID: plain text */
    tpdu[n++] = plan->coding == SMS_UCS2 ? 0x08 : 0x00;                 /* TP-DCS: UCS-2 or the default alphabet */
    tpdu[n++] = s->validity ? s->validity : VP_DEFAULT;
    unsigned udl_at = n++;

    uint8_t udh[6];
    unsigned hlen = 0;
    if (concat) {
        udh[0] = 5;            /* UDHL */
        udh[1] = 0x00;         /* concatenated short messages, 8-bit reference */
        udh[2] = 3;
        udh[3] = s->ref;
        udh[4] = plan->parts;
        udh[5] = (uint8_t)(part + 1);
        hlen = 6;
    }
    const char *p = text + plan->start[part], *end = text + plan->start[part + 1];
    if (plan->coding == SMS_GSM7) {
        uint8_t septets[SMS_GSM7_SINGLE];
        unsigned ns = 0;
        while (p < end) {
            uint8_t sp[2];
            unsigned k = gsm7_from_unicode(utf8_next(&p, end), sp);
            if (!k || ns + k > sizeof septets)
                return -1;
            septets[ns++] = sp[0];
            if (k == 2)
                septets[ns++] = sp[1];
        }
        unsigned fill = hlen ? (7 - (hlen * 8) % 7) % 7 : 0;
        unsigned hsept = (hlen * 8 + fill) / 7;
        unsigned octets = hlen + (fill + 7 * ns + 7) / 8;
        if (n + octets > max || hsept + ns > SMS_GSM7_SINGLE)
            return -1;
        for (unsigned i = 0; i < hlen; i++)
            tpdu[n + i] = udh[i];
        gsm7_pack(septets, ns, fill, tpdu + n + hlen);
        tpdu[udl_at] = (uint8_t)(hsept + ns);
        n += octets;
    } else {
        for (unsigned i = 0; i < hlen; i++) {
            if (n >= max)
                return -1;
            tpdu[n++] = udh[i];
        }
        unsigned start = n;
        while (p < end) {
            uint32_t c = utf8_next(&p, end);
            if (n + 4 > max)
                return -1;
            if (c >= 0x10000) {
                c -= 0x10000;
                uint32_t hi = 0xD800 | (c >> 10), lo = 0xDC00 | (c & 0x3FF);
                tpdu[n++] = (uint8_t)(hi >> 8);
                tpdu[n++] = (uint8_t)hi;
                tpdu[n++] = (uint8_t)(lo >> 8);
                tpdu[n++] = (uint8_t)lo;
            } else {
                tpdu[n++] = (uint8_t)(c >> 8);
                tpdu[n++] = (uint8_t)c;
            }
        }
        if (hlen + n - start > 140)
            return -1;
        tpdu[udl_at] = (uint8_t)(hlen + n - start);
    }
    return (int)n;
}

int sms_encode_deliver_report_error(uint8_t fcs, uint8_t *tpdu)
{
    tpdu[0] = 0x00;            /* SMS-DELIVER-REPORT, no user data header */
    tpdu[1] = fcs;             /* TP-FCS */
    tpdu[2] = 0x00;            /* TP-PI: no optional fields */
    return 3;
}

/* ---- receiving ---- */

int sms_tpdu_mti(const uint8_t *tpdu, unsigned len)
{
    return len ? tpdu[0] & 3 : -1;
}

int32_t sms_days_from_civil(int y, unsigned m, unsigned d)
{
    y -= m <= 2;
    int era = (y >= 0 ? y : y - 399) / 400;
    unsigned yoe = (unsigned)(y - era * 400);
    unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
    unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + (int32_t)doe - 719468;
}

static int bcd(uint8_t o, unsigned *v)
{
    unsigned lo = o & 0x0F, hi = o >> 4;
    if (lo > 9 || hi > 9)
        return -1;
    *v = lo * 10 + hi;
    return 0;
}

int sms_decode_time(const uint8_t *p, uint32_t *unix_time, int16_t *tz)
{
    unsigned f[6];
    for (int i = 0; i < 6; i++)
        if (bcd(p[i], &f[i]))
            return -1;
    unsigned q = (p[6] & 0x07) * 10 + (p[6] >> 4);
    if ((p[6] >> 4) > 9)
        return -1;
    int minutes = (int)q * 15 * ((p[6] & 0x08) ? -1 : 1);
    if (f[1] < 1 || f[1] > 12 || f[2] < 1 || f[2] > 31 || f[3] > 23 || f[4] > 59 || f[5] > 59)
        return -1;
    int64_t t = (int64_t)sms_days_from_civil(2000 + (int)f[0], f[1], f[2]) * 86400 + f[3] * 3600 + f[4] * 60 + f[5];
    t -= (int64_t)minutes * 60;
    *unix_time = t < 0 ? 0 : (uint32_t)t;
    if (tz)
        *tz = (int16_t)minutes;
    return 0;
}

/* TP-DCS (TS 23.038 section 4) */
static void decode_dcs(uint8_t dcs, struct sms_deliver *d)
{
    d->coding = SMS_GSM7;
    d->msg_class = -1;
    d->mwi = d->discard = 0;
    unsigned group = dcs >> 4;
    if (group <= 0x7) {
        /* general data coding (0x00-0x3F), or the same with automatic deletion (0x40-0x7F) */
        unsigned alphabet = (dcs >> 2) & 3;
        if (dcs & 0x20)
            d->coding = SMS_8BIT;      /* compressed: not supported, shown as data */
        else if (alphabet == 1)
            d->coding = SMS_8BIT;
        else if (alphabet == 2)
            d->coding = SMS_UCS2;
        if (dcs & 0x10)
            d->msg_class = (int8_t)(dcs & 3);
    } else if (group >= 0xC && group <= 0xE) {
        d->mwi = 1;
        d->discard = group == 0xC;
        d->coding = group == 0xE ? SMS_UCS2 : SMS_GSM7;
    } else if (group == 0xF) {
        d->coding = (dcs & 0x04) ? SMS_8BIT : SMS_GSM7;
        d->msg_class = (int8_t)(dcs & 3);
    }
    /* 0x80-0xBF: reserved groups, read as the default alphabet */
}

/* the information elements of a user data header (concatenation only) */
static void decode_udh(const uint8_t *h, unsigned hl, struct sms_deliver *d)
{
    unsigned i = 0;
    while (i + 2 <= hl) {
        unsigned iei = h[i], l = h[i + 1];
        const uint8_t *v = h + i + 2;
        if (i + 2 + l > hl)
            break;
        if (iei == 0x00 && l == 3 && v[1] && v[2] && v[2] <= v[1]) {
            d->ref = v[0];
            d->total = v[1];
            d->seq = v[2];
            d->ref16 = 0;
        } else if (iei == 0x08 && l == 4 && v[2] && v[3] && v[3] <= v[2]) {
            d->ref = (uint16_t)(v[0] << 8 | v[1]);
            d->total = v[2];
            d->seq = v[3];
            d->ref16 = 1;
        }
        i += 2 + l;
    }
    if (d->total == 1)
        d->total = d->seq = 0;     /* "part 1 of 1" is a plain message */
}

int sms_decode_deliver(const uint8_t *t, unsigned len, struct sms_deliver *d)
{
    if (len < 1 || (t[0] & 3) != SMS_MTI_DELIVER)
        return -1;
    uint8_t fo = t[0];
    d->more = !(fo & 0x04);
    d->status_report_ind = !!(fo & 0x20);
    d->reply_path = !!(fo & 0x80);
    d->ref = 0;
    d->total = d->seq = d->ref16 = 0;
    d->text_len = 0;
    d->text[0] = 0;
    unsigned i = 1;
    int a = decode_addr(t + i, len - i, d->from, &d->from_type);
    if (a < 0)
        return -1;
    i += (unsigned)a;
    if (i + 10 > len)          /* PID, DCS, SCTS (7), UDL */
        return -1;
    d->pid = t[i++];
    d->dcs = t[i++];
    decode_dcs(d->dcs, d);
    if (sms_decode_time(t + i, &d->sc_time, &d->sc_tz_minutes)) {
        d->sc_time = 0;
        d->sc_tz_minutes = 0;
    }
    i += 7;
    unsigned udl = t[i++];
    const uint8_t *ud = t + i;
    unsigned left = len - i;

    unsigned hl = 0;           /* header octets with UDHL */
    if (fo & 0x40) {
        if (left < 1 || 1u + ud[0] > left)
            return -1;
        hl = 1u + ud[0];
        decode_udh(ud + 1, ud[0], d);
    }

    if (d->coding == SMS_GSM7) {
        if (udl > SMS_GSM7_SINGLE || (udl * 7 + 7) / 8 > left)
            return -1;
        unsigned hsept = (hl * 8 + 6) / 7, fill = hsept * 7 - hl * 8;
        if (hsept > udl)
            return -1;
        uint8_t septets[SMS_GSM7_SINGLE];
        unsigned ns = udl - hsept;
        gsm7_unpack(ud + hl, ns, fill, septets);
        d->text_len = (uint16_t)septets_text(septets, ns, d->text, SMS_PART_TEXT_MAX);
    } else {
        if (udl > 140 || udl > left || hl > udl)
            return -1;
        const uint8_t *p = ud + hl, *end = ud + udl;
        unsigned n = 0;
        if (d->coding == SMS_8BIT) {
            while (p < end && n + 2 <= SMS_PART_TEXT_MAX)
                n += utf8_put(*p++, d->text + n);
        } else {
            while (p + 1 < end) {
                uint32_t c = (uint32_t)p[0] << 8 | p[1];
                p += 2;
                if (c >= 0xD800 && c <= 0xDBFF && p + 1 < end) {
                    uint32_t lo = (uint32_t)p[0] << 8 | p[1];
                    if (lo >= 0xDC00 && lo <= 0xDFFF) {
                        c = 0x10000 + ((c - 0xD800) << 10) + (lo - 0xDC00);
                        p += 2;
                    }
                }
                if (n + utf8_len(c) > SMS_PART_TEXT_MAX)
                    break;
                n += utf8_put(c, d->text + n);     /* an unpaired surrogate becomes U+FFFD */
            }
        }
        d->text_len = (uint16_t)n;
    }
    d->text[d->text_len] = 0;
    return 0;
}

int sms_decode_status_report(const uint8_t *t, unsigned len, struct sms_status_report *r)
{
    if (len < 2 || (t[0] & 3) != SMS_MTI_STATUS_REPORT)
        return -1;
    r->mr = t[1];
    unsigned i = 2;
    int a = decode_addr(t + i, len - i, r->to, 0);
    if (a < 0)
        return -1;
    i += (unsigned)a;
    if (i + 15 > len)
        return -1;
    int16_t tz;
    if (sms_decode_time(t + i, &r->sc_time, &tz))
        r->sc_time = 0;
    if (sms_decode_time(t + i + 7, &r->done_time, &tz))
        r->done_time = 0;
    r->status = t[i + 14];
    return 0;
}

/* ---- hexadecimal ---- */

void sms_hex(const uint8_t *in, unsigned n, char *out)
{
    static const char hex[] = "0123456789ABCDEF";
    for (unsigned i = 0; i < n; i++) {
        out[2 * i] = hex[in[i] >> 4];
        out[2 * i + 1] = hex[in[i] & 15];
    }
    out[2 * n] = 0;
}

static int nibble(char c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    return -1;
}

int sms_unhex(const char *in, unsigned chars, uint8_t *out, unsigned max)
{
    if (chars & 1 || chars / 2 > max)
        return -1;
    for (unsigned i = 0; i < chars / 2; i++) {
        int hi = nibble(in[2 * i]), lo = nibble(in[2 * i + 1]);
        if (hi < 0 || lo < 0)
            return -1;
        out[i] = (uint8_t)(hi << 4 | lo);
    }
    return (int)(chars / 2);
}
