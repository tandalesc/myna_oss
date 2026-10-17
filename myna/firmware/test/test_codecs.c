/* SPDX-License-Identifier: MIT */
/* Host tests of Myna's codecs: GSM 7-bit alphabet, text message PDUs, vCard, phone numbers.
 *
 *   make -C myna/firmware host-test
 *
 * The vectors are worked out by hand from the standards (3GPP TS 23.038, TS 23.040; RFC 2426 / RFC 6350) and from
 * the examples of myna/spec/14-modem-at.md; each says where it comes from. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "lib/gsm7.h"
#include "lib/keyseq.h"
#include "lib/phonenum.h"
#include "lib/sms_pdu.h"
#include "lib/vcard.h"

static int failures, checks;

#define CHECK(cond)                                                                                                    \
    do {                                                                                                               \
        checks++;                                                                                                      \
        if (!(cond)) {                                                                                                 \
            failures++;                                                                                                \
            printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                                                     \
        }                                                                                                              \
    } while (0)

#define CHECK_STR(a, b)                                                                                                \
    do {                                                                                                               \
        checks++;                                                                                                      \
        if (strcmp((a), (b))) {                                                                                        \
            failures++;                                                                                                \
            printf("FAIL %s:%d: \"%s\" != \"%s\"\n", __FILE__, __LINE__, (a), (b));                                    \
        }                                                                                                              \
    } while (0)

/* the SMS-SUBMIT of a whole text part as hex */
static int submit_hex(const char *to, const char *text, unsigned part, uint8_t ref, uint8_t vp, char *hex,
                      struct sms_plan *plan)
{
    struct sms_submit s = { .to = to, .ref = ref, .validity = vp };
    uint8_t t[SMS_TPDU_MAX];
    if (sms_plan(text, (unsigned)strlen(text), plan) <= 0)
        return -1;
    int n = sms_encode_submit(&s, plan, text, part, t, sizeof t);
    if (n < 0)
        return -1;
    sms_hex(t, (unsigned)n, hex);
    return n;
}

/* what a network does with a submit: the same user data in an SMS-DELIVER from `from`, time 08/10/20 12:00:00 */
static int submit_to_deliver(const uint8_t *s, int n, const char *from_hex, uint8_t *d)
{
    int i = 2 + 2 + (s[2] + 1) / 2;           /* first octet, MR, DA */
    int k = 0;
    d[k++] = (uint8_t)(0x04 | (s[0] & 0x40)); /* DELIVER, no more messages, UDHI as sent */
    k += sms_unhex(from_hex, (unsigned)strlen(from_hex), d + k, 16);
    d[k++] = s[i];                            /* PID */
    d[k++] = s[i + 1];                        /* DCS */
    static const uint8_t scts[7] = { 0x80, 0x01, 0x02, 0x21, 0x00, 0x00, 0x00 };
    memcpy(d + k, scts, 7);
    k += 7;
    i += 3;                                   /* PID, DCS, VP (relative: one octet) */
    memcpy(d + k, s + i, (size_t)(n - i));    /* UDL and UD */
    return k + n - i;
}

static void test_gsm7(void)
{
    uint8_t s[2];
    CHECK(gsm7_from_unicode('@', s) == 1 && s[0] == 0x00);
    CHECK(gsm7_from_unicode('A', s) == 1 && s[0] == 0x41);
    CHECK(gsm7_from_unicode(0x00E9, s) == 1 && s[0] == 0x05);      /* é */
    CHECK(gsm7_from_unicode(0x03A3, s) == 1 && s[0] == 0x18);      /* Σ */
    CHECK(gsm7_from_unicode(0x20AC, s) == 2 && s[0] == 0x1B && s[1] == 0x65);     /* € */
    CHECK(gsm7_from_unicode('[', s) == 2 && s[1] == 0x3C);
    CHECK(gsm7_from_unicode('`', s) == 0);                          /* not in the default alphabet */
    CHECK(gsm7_from_unicode(0x00E1, s) == 0);                       /* á */
    CHECK(gsm7_to_unicode(0x1B, 0) == ' ');
    CHECK(gsm7_to_unicode(0x65, 1) == 0x20AC);
    CHECK(gsm7_to_unicode(0x41, 1) == 'A');                         /* undefined extension: default character */

    /* TS 23.038 6.1.2.1.1: "hellohello" packs into 9 octets */
    const char *hello = "hellohello";
    uint8_t sep[10], packed[16], back[10];
    for (int i = 0; i < 10; i++)
        sep[i] = (uint8_t)hello[i];
    unsigned n = gsm7_pack(sep, 10, 0, packed);
    char hex[40];
    sms_hex(packed, n, hex);
    CHECK_STR(hex, "E8329BFD4697D9EC37");
    gsm7_unpack(packed, 10, 0, back);
    CHECK(memcmp(back, sep, 10) == 0);
    /* with one fill bit (after a 6-octet header): "abc" -> C2 E2 31 */
    sep[0] = 'a', sep[1] = 'b', sep[2] = 'c';
    n = gsm7_pack(sep, 3, 1, packed);
    sms_hex(packed, n, hex);
    CHECK_STR(hex, "C2E231");
}

static void test_submit(void)
{
    char hex[400];
    struct sms_plan plan;
    /* myna/spec/14-modem-at.md 7.1: "Hi" to 5550199, validity FF: 0011000781550591F90000FF02C834 after "00" */
    CHECK(submit_hex("5550199", "Hi", 0, 0, 0xFF, hex, &plan) == 14);
    CHECK_STR(hex, "11000781550591F90000FF02C834");
    /* the default validity is 7 days (0xAD), and an international number has type 0x91 */
    submit_hex("+4915551234567", "Hi", 0, 0, 0, hex, &plan);
    CHECK_STR(hex, "11000D91945155214365F70000AD02C834");
    /* the euro sign is an escape pair: two septets */
    submit_hex("5550199", "\xE2\x82\xAC", 0, 0, 0, hex, &plan);
    CHECK_STR(hex, "11000781550591F90000AD029B32");
    /* a character outside the default alphabet: UCS-2 (TS 23.038 DCS 0x08) */
    submit_hex("5550199", "\xD0\x9F\xD1\x80\xD0\xB8\xD0\xB2\xD0\xB5\xD1\x82", 0, 0, 0, hex, &plan);   /* Привет */
    CHECK_STR(hex, "11000781550591F90008AD0C041F04400438043204350442");
    /* outside the BMP: a surrogate pair (U+1F600) */
    submit_hex("5550199", "\xF0\x9F\x98\x80", 0, 0, 0, hex, &plan);
    CHECK_STR(hex, "11000781550591F90008AD04D83DDE00");
    CHECK(plan.units == 2);
    /* a bad address */
    CHECK(submit_hex("55x0199", "Hi", 0, 0, 0, hex, &plan) < 0);
    /* status report requested: TP-SRR 0x20 */
    {
        struct sms_submit s = { .to = "5550199", .status_report = 1 };
        uint8_t t[SMS_TPDU_MAX];
        sms_plan("Hi", 2, &plan);
        CHECK(sms_encode_submit(&s, &plan, "Hi", 0, t, sizeof t) > 0 && t[0] == 0x31);
    }
    /* deliver report for "memory capacity exceeded" (TS 23.040 9.2.3.22: TP-FCS 0xD3) */
    uint8_t r[4];
    CHECK(sms_encode_deliver_report_error(0xD3, r) == 3 && r[0] == 0 && r[1] == 0xD3 && r[2] == 0);
}

static void test_plan(void)
{
    char text[1200];
    struct sms_plan plan;
    memset(text, 'a', sizeof text);
    CHECK(sms_plan(text, 0, &plan) == 0);
    CHECK(sms_plan(text, 160, &plan) == 1 && plan.coding == SMS_GSM7);
    CHECK(sms_plan(text, 161, &plan) == 2 && plan.start[1] == 153 && plan.start[2] == 161);
    CHECK(sms_plan(text, 918, &plan) == 6);
    CHECK(sms_plan(text, 919, &plan) == -1);
    /* an escape pair is never cut: 152 'a' + '€' + 10 'a' -> the euro starts part 2 */
    memcpy(text + 152, "\xE2\x82\xAC", 3);
    CHECK(sms_plan(text, 165, &plan) == 2 && plan.start[1] == 152);
    /* ... while 152 'a' + '€' + 5 'a' is 159 septets: one message */
    CHECK(sms_plan(text, 160, &plan) == 1 && plan.units == 159);
    /* UCS-2: 70 units in one message, 71 in two (67 + 4) */
    unsigned n = 0;
    for (int i = 0; i < 71; i++) {
        memcpy(text + n, "\xD0\xB6", 2);      /* ж */
        n += 2;
    }
    CHECK(sms_plan(text, 140, &plan) == 1 && plan.coding == SMS_UCS2);
    CHECK(sms_plan(text, 142, &plan) == 2 && plan.start[1] == 134);
    /* a surrogate pair is not cut: 66 ж + U+1F600 + 4 ж -> the emoji (units 67-68) starts part 2 */
    n = 0;
    for (int i = 0; i < 66; i++, n += 2)
        memcpy(text + n, "\xD0\xB6", 2);
    memcpy(text + n, "\xF0\x9F\x98\x80", 4);
    n += 4;
    for (int i = 0; i < 4; i++, n += 2)
        memcpy(text + n, "\xD0\xB6", 2);
    CHECK(sms_plan(text, n, &plan) == 2 && plan.start[1] == 132);
}

static void test_deliver(void)
{
    /* myna/spec/14-modem-at.md 7.2: the loopback network's answer to "Hi" */
    const char *pdu_hex = "0581550501F0040781550591F900008001022100000002C834";
    uint8_t pdu[200];
    int n = sms_unhex(pdu_hex, (unsigned)strlen(pdu_hex), pdu, sizeof pdu);
    char sc[SMS_ADDR_MAX];
    int skip = sms_skip_sca(pdu, (unsigned)n, sc);
    CHECK(skip == 6);
    CHECK_STR(sc, "5550100");
    CHECK(n - skip == 19);                    /* the <length> of the +CMT */
    struct sms_deliver d;
    CHECK(sms_tpdu_mti(pdu + skip, (unsigned)(n - skip)) == SMS_MTI_DELIVER);
    CHECK(sms_decode_deliver(pdu + skip, (unsigned)(n - skip), &d) == 0);
    CHECK_STR(d.from, "5550199");
    CHECK_STR(d.text, "Hi");
    CHECK(d.sc_time == 1224504000u);           /* 2008-10-20 12:00:00 UTC */
    CHECK(d.sc_tz_minutes == 0 && d.total == 0 && d.coding == SMS_GSM7 && !d.more);

    /* time zones (TS 23.040 9.2.3.11): -01:00 is 4 quarters with the sign bit: 0x48; +05:30 = 22 quarters: 0x22 */
    uint8_t t1[7] = { 0x80, 0x01, 0x02, 0x21, 0x00, 0x00, 0x48 }, t2[7] = { 0x80, 0x01, 0x02, 0x21, 0x00, 0x00, 0x22 };
    uint32_t u;
    int16_t tz;
    CHECK(sms_decode_time(t1, &u, &tz) == 0 && u == 1224504000u + 3600 && tz == -60);
    CHECK(sms_decode_time(t2, &u, &tz) == 0 && u == 1224504000u - 19800 && tz == 330);
    uint8_t bad[7] = { 0x80, 0x31, 0x02, 0x21, 0x00, 0x00, 0x00 };   /* month 13 */
    CHECK(sms_decode_time(bad, &u, &tz) < 0);

    /* an alphanumeric sender (TS 23.040 9.1.2.5): "Bank" = 7 semi-octets, type 0xD0 */
    const char *alpha = "0407D0C2B07B0D00008001022100000002C834";
    n = sms_unhex(alpha, (unsigned)strlen(alpha), pdu, sizeof pdu);
    CHECK(sms_decode_deliver(pdu, (unsigned)n, &d) == 0);
    CHECK_STR(d.from, "Bank");
    /* an international sender, UCS-2, class 0 (DCS 0x18) */
    const char *ucs = "040B919471238967F50018800102210000000C041F04400438043204350442";
    n = sms_unhex(ucs, (unsigned)strlen(ucs), pdu, sizeof pdu);
    CHECK(sms_decode_deliver(pdu, (unsigned)n, &d) == 0);
    CHECK_STR(d.from, "+49173298765");
    CHECK_STR(d.text, "\xD0\x9F\xD1\x80\xD0\xB8\xD0\xB2\xD0\xB5\xD1\x82");
    CHECK(d.coding == SMS_UCS2 && d.msg_class == 0);
    /* 16-bit concatenation reference (IEI 0x08), part 1 of 3, GSM 7-bit "Hi" after a 7-octet header (no fill) */
    const char *c16 = "440781550591F900008001022100000000"
                      "0A" "0608041234030148" "34";
    /* UDL = 8 header septets + 2 text septets = 10; header 06 08 04 12 34 03 01 is 56 bits = 8 septets, no fill;
       "Hi" packs to C8 34 */
    char buf[128];
    snprintf(buf, sizeof buf, "%s", "440781550591F9000080010221000000" "0A" "06080412340301" "C834");
    n = sms_unhex(buf, (unsigned)strlen(buf), pdu, sizeof pdu);
    CHECK(sms_decode_deliver(pdu, (unsigned)n, &d) == 0);
    CHECK(d.ref == 0x1234 && d.ref16 && d.total == 3 && d.seq == 1);
    CHECK_STR(d.text, "Hi");
    (void)c16;
    /* 8-bit reference, one fill bit: header 05 00 03 CC 02 01, then "abc" = C2 E2 31; UDL 7 + 3 = 10 */
    snprintf(buf, sizeof buf, "%s", "440781550591F9000080010221000000" "0A" "050003CC0201" "C2E231");
    n = sms_unhex(buf, (unsigned)strlen(buf), pdu, sizeof pdu);
    CHECK(sms_decode_deliver(pdu, (unsigned)n, &d) == 0);
    CHECK(d.ref == 0xCC && !d.ref16 && d.total == 2 && d.seq == 2 - 1);
    CHECK_STR(d.text, "abc");
    /* malformed: UDL beyond the data, an SMS-SUBMIT, a truncated address */
    snprintf(buf, sizeof buf, "%s", "040781550591F9000080010221000000" "05" "C834");
    n = sms_unhex(buf, (unsigned)strlen(buf), pdu, sizeof pdu);
    CHECK(sms_decode_deliver(pdu, (unsigned)n, &d) < 0);
    CHECK(sms_decode_deliver((const uint8_t *)"\x01\x00", 2, &d) < 0);
    CHECK(sms_decode_deliver((const uint8_t *)"\x04\x0B\x91\x94", 4, &d) < 0);
    /* message waiting, discard (DCS 0xC8) */
    snprintf(buf, sizeof buf, "%s", "040781550591F900C88001022100000002C834");
    n = sms_unhex(buf, (unsigned)strlen(buf), pdu, sizeof pdu);
    CHECK(sms_decode_deliver(pdu, (unsigned)n, &d) == 0 && d.mwi && d.discard);
}

static void test_status_report(void)
{
    /* TS 23.040 9.2.2.3: MTI 10, MR 0x2A, RA 5550199, SCTS 12:00:00, DT 12:00:03, ST 0 (delivered) */
    const char *h = "062A0781550591F9" "80010221000000" "80010221003000" "00";
    uint8_t t[64];
    int n = sms_unhex(h, (unsigned)strlen(h), t, sizeof t);
    struct sms_status_report r;
    CHECK(sms_tpdu_mti(t, (unsigned)n) == SMS_MTI_STATUS_REPORT);
    CHECK(sms_decode_status_report(t, (unsigned)n, &r) == 0);
    CHECK(r.mr == 0x2A && r.status == 0 && SMS_ST_DELIVERED(r.status));
    CHECK_STR(r.to, "5550199");
    CHECK(r.sc_time == 1224504000u && r.done_time == 1224504003u);
    CHECK(sms_decode_status_report(t, 10, &r) < 0);
}

/* a long mixed text out and back: plan, SUBMIT per part, the network's DELIVER, decode, put together */
static void test_round_trip(const char *text, int parts_expected, int coding)
{
    struct sms_plan plan;
    int parts = sms_plan(text, (unsigned)strlen(text), &plan);
    CHECK(parts == parts_expected);
    if (parts != parts_expected)
        return;
    CHECK(plan.coding == coding);
    char joined[4000] = "";
    unsigned jl = 0;
    for (int p = 0; p < parts; p++) {
        struct sms_submit s = { .to = "+15550123", .ref = 0x5A };
        uint8_t t[SMS_TPDU_MAX], d[SMS_TPDU_MAX + 8];
        int n = sms_encode_submit(&s, &plan, text, (unsigned)p, t, sizeof t);
        CHECK(n > 0 && n <= 175);              /* +CMGS takes 7-175 octets */
        int dn = submit_to_deliver(t, n, "0B915155101032F0", d);
        struct sms_deliver m;
        CHECK(sms_decode_deliver(d, (unsigned)dn, &m) == 0);
        CHECK_STR(m.from, "+15550101230");
        if (parts > 1)
            CHECK(m.total == parts && m.seq == p + 1 && m.ref == 0x5A);
        memcpy(joined + jl, m.text, m.text_len);
        jl += m.text_len;
    }
    joined[jl] = 0;
    CHECK_STR(joined, text);
}

static void test_long(void)
{
    char text[1200];
    /* 3 parts of GSM 7-bit with escape pairs and accented letters */
    unsigned n = 0;
    while (n < 400) {
        const char *w = "Grüße {Ärger} [x] €5 Ñoño ";
        size_t l = strlen(w);
        memcpy(text + n, w, l);
        n += (unsigned)l;
    }
    text[n] = 0;
    struct sms_plan plan;
    sms_plan(text, n, &plan);
    printf("  gsm7 long text: %u bytes, %u septets, %u parts\n", n, plan.units, plan.parts);
    test_round_trip(text, plan.units > 306 ? 3 : 2, SMS_GSM7);
    /* 3 parts of UCS-2: Cyrillic, Greek, CJK, an emoji (surrogate pair) */
    n = 0;
    while (n < 300) {
        const char *w = "Привет κόσμε 你好 \xF0\x9F\x98\x80 ok ";
        size_t l = strlen(w);
        memcpy(text + n, w, l);
        n += (unsigned)l;
    }
    text[n] = 0;
    sms_plan(text, n, &plan);
    printf("  ucs2 long text: %u bytes, %u units, %u parts\n", n, plan.units, plan.parts);
    CHECK(plan.parts == 3);
    test_round_trip(text, 3, SMS_UCS2);
    test_round_trip("Hi", 1, SMS_GSM7);
}

static void test_phonenum(void)
{
    char out[32];
    CHECK(phonenum_normalize("+1 (555) 010-0123", out, sizeof out) == 12);
    CHECK_STR(out, "+15550100123");
    CHECK(phonenum_normalize("555.0123", out, sizeof out) > 0);
    CHECK_STR(out, "5550123");
    CHECK(phonenum_normalize("12a4", out, sizeof out) < 0);
    CHECK(phonenum_normalize("--", out, sizeof out) < 0);
    CHECK(phonenum_normalize("*100#", out, sizeof out) > 0);
    CHECK_STR(out, "*100#");
    CHECK(phonenum_match("+15550100123", "05550100123"));
    CHECK(phonenum_match("+44 7700 900123", "07700900123"));
    CHECK(!phonenum_match("+15550100123", "+15550100124"));
    CHECK(phonenum_match("1234", "1234"));
    CHECK(!phonenum_match("1234", "01234"));
    CHECK(!phonenum_match("5550123", "15550123"));      /* 7 vs 8 digits: short numbers match only exactly */
    CHECK(phonenum_key("999999999") == 999999999u);
}

/* key sequences (lib/keyseq.h): the keypad's letter groups (ITU-T E.161), accents folded, the Russian layout */
static void test_keyseq(void)
{
    char keys[40];
    uint8_t at[40];
    unsigned which = 9;
    CHECK(keyseq_letter('a') == '2' && keyseq_letter('Z') == '9' && keyseq_letter('s') == '7');
    CHECK(keyseq_letter('5') == 0 && keyseq_letter(' ') == 0 && keyseq_letter('@') == 0);
    CHECK(keyseq_letter(0xE9) == '3' && keyseq_letter(0xC9) == '3');     /* é É */
    CHECK(keyseq_letter(0xF1) == '6' && keyseq_letter(0xDF) == '7');     /* ñ ß */
    CHECK(keyseq_letter(0xF7) == 0 && keyseq_letter(0xD7) == 0);         /* ÷ × */
    CHECK(keyseq_letter(0x142) == '5' && keyseq_letter(0x141) == '5');   /* ł Ł */
    CHECK(keyseq_letter(0x10D) == '2' && keyseq_letter(0x17E) == '9');   /* č ž */
    CHECK(keyseq_letter(0x15F) == '7' && keyseq_letter(0x219) == '7');   /* ş ș */
    CHECK(keyseq_letter(0x430) == '2' && keyseq_letter(0x433) == '2');   /* а г */
    CHECK(keyseq_letter(0x434) == '3' && keyseq_letter(0x451) == '3');   /* д ё */
    CHECK(keyseq_letter(0x41C) == '5' && keyseq_letter(0x41F) == '5');   /* М П */
    CHECK(keyseq_letter(0x448) == '8' && keyseq_letter(0x44F) == '9');   /* ш я */
    CHECK(keyseq_letter(0x401) == '3' && keyseq_letter(0x456) == '4');   /* Ё і */
    CHECK(keyseq_letter(0x3B1) == 0);                                    /* Greek: no key */

    CHECK(keyseq_name("Jean-Luc O'Neil", keys, at, sizeof keys) == 14);
    CHECK_STR(keys, "5326 582 66345");
    CHECK(at[4] == 4 && at[5] == 5 && at[9] == 9 && at[10] == 11);       /* the hyphen; N after the apostrophe */
    CHECK(keyseq_name("  Anne -- Moss ", keys, 0, sizeof keys) == 9);
    CHECK_STR(keys, "2663 6677");
    CHECK(keyseq_name("\xC3\x89lodie Durand", keys, at, sizeof keys) == 13);   /* Élodie: É is two bytes */
    CHECK_STR(keys, "356343 387263");
    CHECK(at[0] == 0 && at[1] == 2);
    CHECK(keyseq_name("\xD0\x90\xD0\xBD\xD1\x8F 2", keys, 0, sizeof keys) == 5);   /* Аня 2 */
    CHECK_STR(keys, "259 2");
    CHECK(keyseq_name("Annabelle", keys, 0, 5) == 4);                    /* cut at max */
    CHECK_STR(keys, "2662");

    keyseq_name("Anne Moss", keys, 0, sizeof keys);
    CHECK(keyseq_word(keys, "266", 3) == 0);
    CHECK(keyseq_word(keys, "2666", 4) < 0);                             /* Bonn's, not Anne's */
    CHECK(keyseq_word(keys, "667", 3) == 5);                             /* the second word */
    CHECK(keyseq_word(keys, "677", 3) < 0);                              /* inside a word: no */
    CHECK(keyseq_word(keys, "266316", 6) == 0 && keyseq_word(keys, "266306", 6) == 0);  /* 0 and 1: the break */
    CHECK(keyseq_word(keys, "26637", 5) < 0);
    CHECK(keyseq_word(keys, "2663667", 7) < 0);                          /* the break is needed */
    CHECK(keyseq_word(keys, "2663166778", 10) < 0);                      /* past the end */

    CHECK(keyseq_find("+15550101 +4915551234567", "5123", 4, &which) == 6 && which == 1);
    CHECK(keyseq_find("+15550101 +4915551234567", "+49", 3, &which) == 0 && which == 1);
    CHECK(keyseq_find("+15550101", "0101", 4, &which) == 5 && which == 0);
    CHECK(keyseq_find("+15550101 +4915551234567", "1 +", 3, &which) < 0);   /* never across numbers */
    CHECK(keyseq_find("+15550101", "999", 3, &which) < 0);
}

static void test_vcard(void)
{
    struct vcard_contact c = { 0 }, back;
    strcpy(c.given, "Ana María");
    strcpy(c.family, "O'Neil; Jr.");
    c.count = 2;
    strcpy(c.numbers[0].number, "+15550100123");
    c.numbers[0].label = VCARD_MOBILE;
    strcpy(c.numbers[1].number, "5550199");
    c.numbers[1].label = VCARD_WORK;
    strcpy(c.note, "Met at the café, line one\nline two, with a long tail that goes past seventy-five octets so the "
                   "line is folded ✓✓✓");
    char out[1024];
    int n = vcard_format(&c, out, sizeof out);
    CHECK(n > 0);
    CHECK(strstr(out, "BEGIN:VCARD\r\nVERSION:3.0\r\nN:O'Neil\\; Jr.;Ana María;;;\r\nFN:Ana María O'Neil\\; Jr.\r\n"));
    CHECK(strstr(out, "TEL;TYPE=CELL:+15550100123\r\nTEL;TYPE=WORK:5550199\r\n"));
    CHECK(strstr(out, "NOTE:Met at the café\\, line one\\nline two\\,"));
    CHECK(strstr(out, "\r\nEND:VCARD\r\n"));
    /* every physical line at most 75 octets, plus its CRLF */
    unsigned line = 0, longest = 0;
    for (int i = 0; i < n; i++) {
        if (out[i] == '\r')
            continue;
        if (out[i] == '\n') {
            line = 0;
            continue;
        }
        if (++line > longest)
            longest = line;
    }
    CHECK(longest <= 75);
    CHECK(vcard_parse(out, (unsigned)n, &back) == 0);
    CHECK_STR(back.given, c.given);
    CHECK_STR(back.family, c.family);
    CHECK_STR(back.note, c.note);
    CHECK(back.count == 2 && back.numbers[1].label == VCARD_WORK);
    CHECK_STR(back.numbers[0].number, "+15550100123");
    CHECK(vcard_format(&c, out, 100) < 0);              /* does not fit */

    /* vCard 2.1 as older phones write it: bare types, quoted-printable with a soft line break, LF line ends */
    const char *v21 = "BEGIN:VCARD\nVERSION:2.1\nN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:M=C3=BCller;J=\n"
                      "=C3=BCrgen\nTEL;CELL;PREF:+49 (171) 555-0101\nTEL;HOME:030 5550102\nTEL;FAX:1\nTEL;WORK:2\n"
                      "TEL:3\nitem1.EMAIL:x@example.org\nPHOTO;ENCODING=BASE64;TYPE=JPEG:/9j/4AAQ\n AAAA\nEND:VCARD\n";
    CHECK(vcard_parse(v21, (unsigned)strlen(v21), &back) == 0);
    CHECK_STR(back.family, "Müller");
    CHECK_STR(back.given, "Jürgen");
    CHECK(back.count == 4);
    CHECK_STR(back.numbers[0].number, "+491715550101");
    CHECK(back.numbers[0].label == VCARD_MOBILE && back.numbers[1].label == VCARD_HOME);
    CHECK(back.numbers[2].label == VCARD_OTHER && back.numbers[3].label == VCARD_WORK);
    /* vCard 4.0: lower-case names, TYPE lists in quotes, tel: URIs, only FN */
    const char *v40 = "begin:vcard\r\nversion:4.0\r\nfn:Bo\r\ntel;type=\"cell,voice\";value=uri:tel:+1-555-010-0199;ext=2\r\n"
                      "end:vcard\r\n";
    CHECK(vcard_parse(v40, (unsigned)strlen(v40), &back) == 0);
    CHECK_STR(back.given, "Bo");
    CHECK_STR(back.numbers[0].number, "+15550100199");
    CHECK(back.numbers[0].label == VCARD_MOBILE);
    char name[64];
    vcard_display_name(&back, name, sizeof name);
    CHECK_STR(name, "Bo");
    CHECK(vcard_parse("hello", 5, &back) < 0);
    CHECK(vcard_parse("BEGIN:VCARD\r\nEND:VCARD\r\n", 24, &back) < 0);
}

int main(void)
{
    test_gsm7();
    test_submit();
    test_plan();
    test_deliver();
    test_status_report();
    test_long();
    test_phonenum();
    test_keyseq();
    test_vcard();
    printf("%d checks, %d failed\n", checks, failures);
    return failures != 0;
}
