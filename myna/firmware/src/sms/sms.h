/* SPDX-License-Identifier: MIT */
/* The text message service: sending with a queue and retry rules, receiving with acknowledgement after storage
 * (3GPP TS 27.005 PDU mode: +CMGS, +CMT, +CNMA; myna/spec/14-modem-at.md section 7).
 *
 * Sending: sms_send() stores the message as "queued" and returns; the service task sends queued messages one at a
 * time, oldest first, part by part (AT+CMGS), whenever the modem is ready and the phone is registered. A message
 * becomes "sent" when the network has taken every part, or "failed" with the cause:
 *   - no service, no card, the channel restarting: not an attempt; the message waits for the network
 *   - a passing refusal (RP causes 27, 38, 41, 42, 47; +CMS ERROR 332, 500; no answer): tried again after 10 s and
 *     60 s, then "failed"
 *   - any other refusal (unassigned number, barred, rejected, bad PDU ...): "failed" at once, never repeated
 * The parts already taken are not sent again: a retry goes on with the next part, under the same reference.
 *
 * Receiving: with +CSMS=1 every +CMT is acknowledged (AT+CNMA) only after the message, or its part, is on flash.
 * When the store is full the message is refused with TP-FCS 0xD3, "memory capacity exceeded" (the network then has
 * RP cause 22 and keeps it); another storage failure refuses it with 0xFF (unspecified). A modem that refuses
 * +CSMS=1 acknowledges by itself (+CSMS=0): then a message is stored as well as it can be.
 *
 * Subscribed tasks get MSG_SMS_EVENT (a = enum sms_event, b = the message id). */
#ifndef MYNA_SMS_SMS_H
#define MYNA_SMS_SMS_H

#include <stdint.h>

#include "kernel/ostimer.h"
#include "sms/store.h"

struct task;

enum sms_event {
    SMS_EV_QUEUED,             /* a message to send was stored */
    SMS_EV_SENT,
    SMS_EV_FAILED,
    SMS_EV_RECEIVED,           /* a new message (whole) */
    SMS_EV_CHANGED,            /* the state of a message changed otherwise (read, a retry waiting, delivered) */
};

void sms_init(void);                           /* URC handlers; called by modem_init() */
struct task *sms_task(void);
void sms_subscribe(struct task *t);

/* called by the modem task */
void sms_bringup(void);                        /* +CMGF=0, +CSMS=1, +CSCA?, +CNMI=2,2,0,0,0 */
void sms_modem_ready(void);

/* Queue a text (UTF-8) for a number. Returns the message id (> 0), or < 0: SMS_CAUSE_* (bad number, too long) as
 * a negative value, or a STORE_* error. */
int32_t sms_send(const char *number, const char *text);

/* Send a failed message again (Retry): it is queued once more and goes on from the first part the network did not
 * take, under the same concatenation reference, so the recipient can still join the parts; a one-part message simply
 * goes again. 0, or < 0 if the message is not a failed outgoing one (or a STORE_* error). */
int sms_retry(uint32_t id);

/* Mark a received message read. */
int sms_mark_read(uint32_t id);

/* The name to show for a number: the contact's name, or the number itself. */
void sms_display_name(const char *number, char *out, unsigned max);

/* A short English text for a failure cause (RP cause, +CMS ERROR code or SMS_CAUSE_*). */
const char *sms_cause_text(unsigned cause);

struct sms_stats {
    uint32_t sent_parts, received_parts, acks, refusals, retries;
    uint32_t last_send_insns;      /* instructions of the CPU (awake time x 100) for the last part sent, from the
                                      queue to the modem's answer handled, without the waiting */
    uint32_t last_receive_insns;   /* the last +CMT, from the URC to the acknowledgement queued */
    ktime_t last_receive_mark;     /* kernel_busy() when the modem task began on the last +CMT (where a received
                                      message's cost starts, for the UI's end-to-end measure) */
    char smsc[24];
    uint8_t ack_mode;              /* 1 = +CSMS=1 (Myna acknowledges) */
};
const struct sms_stats *sms_stats(void);

#endif
