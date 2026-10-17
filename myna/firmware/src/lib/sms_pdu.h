/* SPDX-License-Identifier: MIT */
/* Text message PDUs (3GPP TS 23.040 section 9.2): SMS-SUBMIT out, SMS-DELIVER and SMS-STATUS-REPORT in, the
 * SMS-DELIVER-REPORT of a refusal; user data in the GSM 7-bit default alphabet (with its extension table) or UCS-2
 * (TS 23.038), and concatenated messages with the 8-bit or 16-bit reference header (TS 23.040 9.2.3.24.1 / .8).
 *
 * Text is UTF-8 on Myna's side. A text goes out in the default alphabet when every character has a septet there,
 * else in UCS-2; characters outside the Basic Multilingual Plane go as UTF-16 surrogate pairs (what phones send for
 * them; TS 23.038 names only UCS-2), never split across two parts. Nothing here allocates or keeps state. */
#ifndef MYNA_LIB_SMS_PDU_H
#define MYNA_LIB_SMS_PDU_H

#include <stdint.h>

#define SMS_PARTS_MAX     6        /* the longest text Myna sends or puts together */
#define SMS_TPDU_MAX      176      /* largest TPDU in octets (an SMS-DELIVER with a 12-octet address is 164) */
#define SMS_ADDR_MAX      40       /* an address as text with its 0: 20 digits and '+', or 11 characters of a name */
#define SMS_PART_TEXT_MAX 484      /* the UTF-8 of one part: 160 septets, each up to 3 bytes (the euro sign) */

#define SMS_GSM7_SINGLE   160      /* septets of a text in one message */
#define SMS_GSM7_PART     153      /* ... in each part of a concatenated one (8-bit reference header) */
#define SMS_UCS2_SINGLE   70       /* UTF-16 units */
#define SMS_UCS2_PART     67

enum sms_coding { SMS_GSM7 = 0, SMS_8BIT = 1, SMS_UCS2 = 2 };

/* TP-MTI of a TPDU from the network (TS 23.040 9.2.3.1) */
enum sms_mti { SMS_MTI_DELIVER = 0, SMS_MTI_SUBMIT_REPORT = 1, SMS_MTI_STATUS_REPORT = 2, SMS_MTI_RESERVED = 3 };

/* ---- sending ---- */

/* How a text is cut into parts: the coding and where each part starts in the UTF-8 text. */
struct sms_plan {
    uint8_t coding;                        /* SMS_GSM7 or SMS_UCS2 */
    uint8_t parts;                         /* 1 - SMS_PARTS_MAX */
    uint16_t units;                        /* septets (GSM7) or UTF-16 units (UCS2) of the whole text */
    uint16_t start[SMS_PARTS_MAX + 1];     /* byte offsets: part i is [start[i], start[i + 1]) */
};

/* Plan a text of len bytes. Returns the number of parts, 0 for an empty text, or -1 when it needs more than
 * SMS_PARTS_MAX parts. */
int sms_plan(const char *text, unsigned len, struct sms_plan *plan);

struct sms_submit {
    const char *to;            /* digits, '+' first for an international number; '*' and '#' allowed */
    uint8_t ref;               /* concatenation reference (the same for every part of one text) */
    uint8_t status_report;     /* TP-SRR: ask for a status report */
    uint8_t validity;          /* TP-VP, relative format (TS 23.040 9.2.3.12.1); 0 = the default (7 days) */
};

/* Build the SMS-SUBMIT of part `part` (0-based) of a planned text. Returns its length in octets, or -1 (bad
 * address, buffer too small). TP-MR is 0: the modem sets it. The service-centre field is not included: give
 * "00" before it to +CMGS for the card's service centre. */
int sms_encode_submit(const struct sms_submit *s, const struct sms_plan *plan, const char *text, unsigned part,
                      uint8_t *tpdu, unsigned max);

/* An SMS-DELIVER-REPORT for RP-ERROR (TS 23.040 9.2.2.1a) with the given TP-FCS (0xD3: memory capacity exceeded).
 * Returns its length (3). */
int sms_encode_deliver_report_error(uint8_t fcs, uint8_t *tpdu);

/* ---- receiving ---- */

struct sms_deliver {
    char from[SMS_ADDR_MAX];   /* the originating address as text: "+4912345", "12345" or a name ("Bank") */
    uint8_t from_type;         /* its type-of-address octet */
    uint8_t pid, dcs;
    uint8_t coding;            /* enum sms_coding of the user data */
    int8_t msg_class;          /* 0-3, or -1 when the DCS gives none */
    uint8_t more;              /* TP-MMS = 0: more messages are waiting at the centre */
    uint8_t reply_path, status_report_ind;
    uint8_t mwi;               /* a message-waiting indication group (DCS 0xC0-0xEF) */
    uint8_t discard;           /* DCS 0xC0-0xCF: "discard message" */
    uint32_t sc_time;          /* TP-SCTS as Unix time (UTC) */
    int16_t sc_tz_minutes;     /* its time zone, minutes east of UTC */
    /* concatenation, from the user data header; total = 0 for a message of one part */
    uint16_t ref;
    uint8_t total, seq;
    uint8_t ref16;             /* the reference was 16 bits */
    /* the text of this part, UTF-8 (8-bit data as Latin-1 characters) */
    uint16_t text_len;
    char text[SMS_PART_TEXT_MAX + 1];
};

/* Decode a TPDU from the network. Returns its TP-MTI (enum sms_mti) or -1 if it cannot be read. */
int sms_tpdu_mti(const uint8_t *tpdu, unsigned len);

/* Decode an SMS-DELIVER. Returns 0, or -1 when the TPDU is malformed. */
int sms_decode_deliver(const uint8_t *tpdu, unsigned len, struct sms_deliver *out);

struct sms_status_report {
    uint8_t mr;                /* TP-MR of the message it reports on */
    char to[SMS_ADDR_MAX];     /* TP-RA */
    uint32_t sc_time;          /* TP-SCTS (UTC) */
    uint32_t done_time;        /* TP-DT (UTC) */
    uint8_t status;            /* TP-ST */
};

int sms_decode_status_report(const uint8_t *tpdu, unsigned len, struct sms_status_report *out);

/* TP-ST classes (TS 23.040 9.2.3.15) */
#define SMS_ST_DELIVERED(st)   ((st) <= 0x1F)
#define SMS_ST_TRYING(st)      ((st) >= 0x20 && (st) <= 0x3F)
#define SMS_ST_FAILED(st)      ((st) >= 0x40)

/* The service-centre address before a TPDU in a +CMT or +CMGS PDU: its length octet and what follows. Returns the
 * octets it takes (1 + its length), or -1. `sc` gets the number as text (may be 0). */
int sms_skip_sca(const uint8_t *pdu, unsigned len, char *sc);

/* ---- helpers ---- */

/* hexadecimal (upper case) of n octets into out (2n characters and a 0) */
void sms_hex(const uint8_t *in, unsigned n, char *out);
/* octets of a hexadecimal text (either case); returns the octets, or -1 for an odd length or a bad digit */
int sms_unhex(const char *in, unsigned chars, uint8_t *out, unsigned max);

/* A semi-octet time stamp (7 octets, TS 23.040 9.2.3.11) to Unix time (UTC); tz gets minutes east of UTC. Returns
 * -1 for a time stamp with a non-decimal digit. */
int sms_decode_time(const uint8_t *p, uint32_t *unix_time, int16_t *tz);

/* days since 1970-01-01 of a civil date (proleptic Gregorian) */
int32_t sms_days_from_civil(int y, unsigned m, unsigned d);

#endif
