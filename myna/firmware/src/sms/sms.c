/* SPDX-License-Identifier: MIT */
/* The text message service (sms/sms.h). */
#include <stdint.h>

#include "drivers/clock.h"
#include "kernel/task.h"
#include "kernel/timer.h"
#include "lib/mem.h"
#include "lib/phonenum.h"
#include "lib/print.h"
#include "lib/sms_pdu.h"
#include "modem/at.h"
#include "modem/modem.h"
#include "services/contacts.h"
#include "services/network.h"
#include "sms/sms.h"
#include "sms/store.h"

#define CMGS_TIMEOUT_MS  90000     /* the modem gives up after 60 s itself (+CMS ERROR 332) */
#define MAX_ATTEMPTS     3
#define SUBSCRIBERS      4
#define SLOTS            4         /* received PDUs waiting for the task */
#define WAITS            8         /* messages waiting for a retry time */
#define STATUS_BIAS      8         /* enum at_status in a message's a field, made positive */

static const uint32_t retry_ms[MAX_ATTEMPTS - 1] = { 10000, 60000 };

enum { T_RETRY, T_BENCH };

static void sms_handle(struct task *self, const struct msg *m);

static struct task task = { .name = "sms", .handle = sms_handle };
static struct timer retry_timer;
static struct task *subscribers[SUBSCRIBERS];
static struct sms_stats stats;
static uint8_t memory_full_reported;       /* a message was refused for lack of room: tell the network when there
                                              is room again (+CNMI, spec 14 7.2) */

static struct {
    uint8_t used, report;
    uint16_t len;              /* <length> of the URC: octets of the TPDU */
    ktime_t mark;              /* CPU time (kernel_busy) when its bytes began to be handled */
    char hex[2 * (SMS_TPDU_MAX + 12) + 1];
} slots[SLOTS];

static struct {
    uint32_t id;
    ktime_t at;
} waits[WAITS];

/* the message being sent */
static struct {
    uint8_t busy;
    int mr;
    struct sms_record rec;
    struct sms_plan plan;
    char text[SMS_TEXT_MAX + 1];
    char cmd[24];
    char pdu[2 + 2 * SMS_TPDU_MAX + 1];
    ktime_t mark;
} out;

/* a received message being put together, and the joined text */
static struct sms_deliver deliver;
static char joined[SMS_TEXT_MAX + 1];

static const char refuse_full[] = "00D300";        /* SMS-DELIVER-REPORT, TP-FCS 0xD3: memory capacity exceeded */
static const char refuse_other[] = "00FF00";       /* TP-FCS 0xFF: unspecified error */

struct task *sms_task(void)
{
    return &task;
}

const struct sms_stats *sms_stats(void)
{
    return &stats;
}

void sms_subscribe(struct task *t)
{
    for (unsigned i = 0; i < SUBSCRIBERS; i++)
        if (!subscribers[i] || subscribers[i] == t) {
            subscribers[i] = t;
            return;
        }
}

static void event(enum sms_event ev, uint32_t id)
{
    for (unsigned i = 0; i < SUBSCRIBERS && subscribers[i]; i++)
        task_post(subscribers[i], MSG_SMS_EVENT, (uint16_t)ev, id);
}

static uint32_t insns_since(ktime_t mark)
{
    return ktime_to_us(kernel_busy() - mark) * 100;    /* 10 ns per instruction (spec 00) */
}

void sms_display_name(const char *number, char *out_name, unsigned max)
{
    const char *name = contacts_lookup(number);
    const char *s = name ? name : number;
    unsigned n = 0;
    while (s[n] && n + 1 < max) {
        out_name[n] = s[n];
        n++;
    }
    if (max)
        out_name[n] = 0;
}

const char *sms_cause_text(unsigned cause)
{
    switch (cause) {
    case 1: return "Unassigned number";
    case 8: return "Operator determined barring";
    case 10: return "Call barred";
    case 21: return "Message rejected";
    case 22: return "Memory capacity exceeded";
    case 27: return "Destination out of order";
    case 28: return "Unidentified subscriber";
    case 29: return "Facility rejected";
    case 30: return "Unknown subscriber";
    case 38: return "Network out of order";
    case 41: return "Temporary failure";
    case 42: return "Congestion";
    case 47: return "Resources unavailable";
    case 50: return "Facility not subscribed";
    case 69: return "Facility not implemented";
    case 81: return "Invalid message reference";
    case 95: return "Invalid message";
    case 96: return "Invalid mandatory information";
    case 97: return "Message type not implemented";
    case 98: return "Message not compatible";
    case 99: return "Information element not implemented";
    case 111: return "Protocol error";
    case 127: return "Interworking error";
    case 304: return "Invalid message (PDU)";
    case 310: return "No SIM card";
    case 330: return "Service centre unknown";
    case 331: return "No network service";
    case 332: return "Network timeout";
    case 500: return "Unknown error";
    case SMS_CAUSE_NO_ANSWER: return "No answer from the modem";
    case SMS_CAUSE_TOO_LONG: return "Message too long";
    case SMS_CAUSE_BAD_NUMBER: return "Invalid number";
    }
    return cause < 128 ? "Refused by the network" : "Error";
}

/* ---- sending ---- */

enum fate { WAIT, RETRY, FAIL };

/* what a failed send means (TS 24.011 table 8.4 for the RP causes, TS 27.005 3.2.5 for +CMS ERROR) */
static enum fate classify(int status, int code)
{
    switch (status) {
    case AT_ABORTED:
        return WAIT;           /* the channel restarted: not the message's fault */
    case AT_TIMEOUT:
    case AT_ERROR:
    case AT_CME:
        return RETRY;
    }
    if (code >= 1 && code <= 127)
        return code == 27 || code == 38 || code == 41 || code == 42 || code == 47 ? RETRY : FAIL;
    if (code == 331 || (code >= 310 && code <= 318))
        return WAIT;           /* no service, card not ready: send when the network is back */
    if (code == 332 || code == 500 || code < 0)
        return RETRY;
    return FAIL;
}

static ktime_t wait_until(uint32_t id)
{
    for (unsigned i = 0; i < WAITS; i++)
        if (waits[i].id == id)
            return waits[i].at;
    return 0;
}

static void wait_set(uint32_t id, ktime_t at)
{
    unsigned free_slot = WAITS;
    for (unsigned i = 0; i < WAITS; i++) {
        if (waits[i].id == id) {
            waits[i].at = at;
            return;
        }
        if (!waits[i].id && free_slot == WAITS)
            free_slot = i;
    }
    if (free_slot < WAITS) {
        waits[free_slot].id = id;
        waits[free_slot].at = at;
    }
}

static void wait_clear(uint32_t id)
{
    for (unsigned i = 0; i < WAITS; i++)
        if (waits[i].id == id)
            waits[i].id = 0;
}

static void try_send(void);
static void send_part(void);

static void finish_send(void)
{
    out.busy = 0;
    task_post(&task, MSG_SMS_KICK, 0, 0);      /* the next one, after this event */
}

static void fail_send(unsigned cause)
{
    out.rec.state = SMS_FAILED;
    out.rec.cause = (uint16_t)cause;
    store_update(&out.rec);
    wait_clear(out.rec.id);
    kprintf("sms: message %u to %s failed: %s (%u)\n", out.rec.id, out.rec.number, sms_cause_text(cause), cause);
    event(SMS_EV_FAILED, out.rec.id);
    finish_send();
}

static void cmgs_line(void *ctx, const char *line)
{
    (void)ctx;
    at_field_int(line, 0, &out.mr);
}

static void cmgs_done(void *ctx, const struct at_result *r)
{
    (void)ctx;
    task_post(&task, MSG_SMS_SENT, (uint16_t)(r->status + STATUS_BIAS), (uint32_t)r->code);
}

static void sent(int status, int code)
{
    if (!out.busy)
        return;
    struct sms_record *r = &out.rec;
    if (status == AT_OK) {
        stats.sent_parts++;
        if (r->parts_done < sizeof r->mr)
            r->mr[r->parts_done] = (uint8_t)out.mr;
        r->parts_done++;
        if (r->parts_done < r->parts) {
            store_update(r);               /* the parts taken are not sent again after a restart */
            send_part();
            return;
        }
        r->state = SMS_SENT;
        r->sc_time = clock_seconds();
        store_update(r);
        wait_clear(r->id);
        stats.last_send_insns = insns_since(out.mark);
        kprintf("sms: message %u to %s sent (%u part%s, reference %d), %u instructions\n", r->id, r->number,
                r->parts, r->parts > 1 ? "s" : "", out.mr, stats.last_send_insns);
        event(SMS_EV_SENT, r->id);
        finish_send();
        return;
    }
    enum fate f = classify(status, code);
    unsigned cause = status == AT_CMS ? (unsigned)code : status == AT_TIMEOUT ? SMS_CAUSE_NO_ANSWER : 500;
    if (f == WAIT) {
        kprintf("sms: message %u waits for the network (%s)\n", r->id,
                status == AT_ABORTED ? "channel restarted" : sms_cause_text(cause));
        out.busy = 0;                      /* a network change kicks it again */
        return;
    }
    if (f == RETRY && r->attempts + 1 < MAX_ATTEMPTS) {
        uint32_t ms = retry_ms[r->attempts];
        r->attempts++;
        r->cause = (uint16_t)cause;
        store_update(r);
        wait_set(r->id, ktime_now() + KTIME_MS(ms));
        stats.retries++;
        kprintf("sms: message %u: %s (%u), trying again in %u s\n", r->id, sms_cause_text(cause), cause, ms / 1000);
        event(SMS_EV_CHANGED, r->id);
        finish_send();
        return;
    }
    fail_send(cause);
}

static void send_part(void)
{
    struct sms_submit s = { .to = out.rec.number, .ref = out.rec.ref };
    uint8_t tpdu[SMS_TPDU_MAX];
    int n = sms_encode_submit(&s, &out.plan, out.text, out.rec.parts_done, tpdu, sizeof tpdu);
    if (n < 0) {
        fail_send(SMS_CAUSE_BAD_NUMBER);
        return;
    }
    out.pdu[0] = out.pdu[1] = '0';     /* no service centre: the card's (+CSCA) */
    sms_hex(tpdu, (unsigned)n, out.pdu + 2);
    char *c = out.cmd;
    memcpy(c, "AT+CMGS=", 8);
    c += 8;
    if (n >= 100)
        *c++ = (char)('0' + n / 100);
    if (n >= 10)
        *c++ = (char)('0' + n / 10 % 10);
    *c++ = (char)('0' + n % 10);
    *c = 0;
    out.mr = -1;
    struct at_cmd cmd = { .text = out.cmd, .prefix = "+CMGS:", .payload = out.pdu, .timeout_ms = CMGS_TIMEOUT_MS,
                          .line = cmgs_line, .done = cmgs_done };
    if (at_send(&cmd))
        out.busy = 0;                  /* the queue is full: a later kick tries again */
}

static void start_send(uint32_t id)
{
    if (store_read(id, &out.rec, out.text, sizeof out.text) < 0) {
        kprintf("sms: message %u cannot be read\n", id);
        return;
    }
    if (sms_plan(out.text, out.rec.text_len, &out.plan) != out.rec.parts) {
        fail_send(SMS_CAUSE_TOO_LONG);
        return;
    }
    out.busy = 1;
    out.mark = kernel_busy();
    send_part();
}

static void try_send(void)
{
    if (out.busy || modem_state() != MODEM_READY || !network_registered() || !store_ready())
        return;
    unsigned n;
    const struct store_entry *e = store_index(&n);
    ktime_t now = ktime_now(), earliest = 0;
    for (unsigned i = 0; i < n; i++) {
        if (e[i].dir != SMS_OUT || e[i].state != SMS_QUEUED)
            continue;
        ktime_t at = wait_until(e[i].id);
        if (at <= now) {
            start_send(e[i].id);
            if (out.busy)
                return;
            continue;
        }
        if (!earliest || at < earliest)
            earliest = at;
    }
    if (earliest)
        timer_start_at(&retry_timer, earliest);
}

int32_t sms_send(const char *number, const char *text)
{
    struct sms_record r = { 0 };
    if (phonenum_normalize(number, r.number, sizeof r.number) < 0)
        return -SMS_CAUSE_BAD_NUMBER;
    unsigned len = (unsigned)strlen(text);
    struct sms_plan plan;
    int parts = sms_plan(text, len, &plan);
    if (parts <= 0 || len > SMS_TEXT_MAX)
        return -SMS_CAUSE_TOO_LONG;
    static uint8_t ref;
    r.dir = SMS_OUT;
    r.state = SMS_QUEUED;
    r.time = clock_seconds();
    r.parts = (uint8_t)parts;
    r.ref = ++ref;             /* a new reference for each text (wraps at 255) */
    r.text_len = (uint16_t)len;
    int e = store_add(&r, text);
    if (e)
        return e;
    kprintf("sms: message %u to %s queued: %u bytes, %u part%s (%s)\n", r.id, r.number, len, parts,
            parts > 1 ? "s" : "", plan.coding == SMS_UCS2 ? "UCS-2" : "GSM 7-bit");
    event(SMS_EV_QUEUED, r.id);
    task_post(&task, MSG_SMS_KICK, 0, 0);
    return (int32_t)r.id;
}

int sms_retry(uint32_t id)
{
    struct sms_record r;
    if (store_read(id, &r, 0, 0) < 0 || r.dir != SMS_OUT || r.state != SMS_FAILED)
        return -1;
    r.state = SMS_QUEUED;
    r.cause = 0;
    r.attempts = 0;
    int e = store_update(&r);
    if (e)
        return e;
    wait_clear(id);
    kprintf("sms: message %u to %s queued again from part %u of %u\n", id, r.number, r.parts_done + 1u, r.parts);
    event(SMS_EV_CHANGED, id);
    task_post(&task, MSG_SMS_KICK, 0, 0);
    return 0;
}

int sms_mark_read(uint32_t id)
{
    struct sms_record r;
    if (store_read(id, &r, 0, 0) < 0 || r.state != SMS_RECEIVED)
        return -1;
    r.state = SMS_READ;
    int e = store_update(&r);
    if (!e)
        event(SMS_EV_CHANGED, id);
    return e;
}

/* ---- receiving ---- */

static void ack_done(void *ctx, const struct at_result *r)
{
    (void)ctx;
    if (r->status != AT_OK)
        kprintf("sms: acknowledgement not taken (%d %d)\n", r->status, r->code);
}

/* the answer to the network for one +CMT / +CDS */
static void acknowledge(int stored)
{
    if (!stats.ack_mode)
        return;                /* +CSMS=0: the modem has acknowledged already */
    if (stored == STORE_OK) {
        stats.acks++;
        at_simple("AT+CNMA", ack_done, 0);
        return;
    }
    stats.refusals++;
    if (stored == STORE_FULL)
        memory_full_reported = 1;
    struct at_cmd c = { .text = "AT+CNMA=2,3", .payload = stored == STORE_FULL ? refuse_full : refuse_other,
                        .done = ack_done };
    at_send(&c);
}

/* the parts of a concatenated message: wait for the others, or put them together */
static int receive_part(struct sms_record *r, const struct sms_deliver *d)
{
    struct store_part_key k = { phonenum_key(d->from), d->ref, d->total };
    for (unsigned seq = 1; seq <= d->total; seq++)
        if (seq != d->seq && !store_part_exists(&k, seq)) {
            r->parts = d->total;
            r->parts_done = d->seq;
            int e = store_part_put(&k, d->seq, r, d->text, d->text_len);
            if (!e)
                kprintf("sms: part %u of %u from %s kept\n", d->seq, d->total, d->from);
            return e;
        }
    /* every part is here: the text in order, the first part's times */
    unsigned n = 0;
    for (unsigned seq = 1; seq <= d->total; seq++) {
        if (seq == d->seq) {
            unsigned l = d->text_len < SMS_TEXT_MAX - n ? d->text_len : SMS_TEXT_MAX - n;
            memcpy(joined + n, d->text, l);
            n += l;
        } else {
            struct sms_record pr;
            int l = store_part_read(&k, seq, &pr, joined + n, SMS_TEXT_MAX + 1 - n);
            if (l < 0)
                return STORE_ERROR;
            n += (unsigned)l;
            if (seq == 1) {
                r->sc_time = pr.sc_time;
                r->time = pr.time;
            }
        }
    }
    joined[n] = 0;
    r->parts = d->total;
    r->parts_done = d->total;
    r->text_len = (uint16_t)n;
    int e = store_add(r, joined);
    if (e)
        return e;
    for (unsigned seq = 1; seq <= d->total; seq++)
        if (seq != d->seq)
            store_part_delete(&k, seq);
    return STORE_OK;
}

static int receive(const struct sms_deliver *d)
{
    if (d->pid == 0x40) {
        kprintf("sms: a type 0 message from %s: acknowledged, not kept (TS 23.040 9.2.3.9)\n", d->from);
        return STORE_OK;
    }
    if (d->mwi && d->discard) {
        kprintf("sms: a message-waiting indication from %s (discard group)\n", d->from);
        return STORE_OK;
    }
    struct sms_record r = { 0 };
    r.dir = SMS_IN;
    r.state = SMS_RECEIVED;
    r.time = clock_seconds();
    r.sc_time = d->sc_time;
    r.parts = 1;
    r.parts_done = 1;
    r.flags = d->msg_class == 0 ? SMS_FLAG_CLASS0 : 0;
    unsigned i = 0;
    for (; d->from[i] && i + 1 < sizeof r.number; i++)
        r.number[i] = d->from[i];
    r.number[i] = 0;
    int e;
    if (d->total > 1 && d->total <= SMS_PARTS_MAX) {
        e = receive_part(&r, d);
        if (e || !r.id)
            return e;          /* a part kept (r.id still 0), or an error */
    } else {
        r.text_len = d->text_len;
        e = store_add(&r, d->text);
        if (e)
            return e;
    }
    kprintf("sms: message %u from %s received: \"%s\"\n", r.id, r.number, d->total > 1 ? joined : d->text);
    event(SMS_EV_RECEIVED, r.id);
    return STORE_OK;
}

/* a status report: the sent message whose part had this reference */
static void report(const struct sms_status_report *rep)
{
    unsigned n;
    const struct store_entry *e = store_index(&n);
    uint32_t key = phonenum_key(rep->to);
    for (unsigned i = n; i-- > 0;) {
        if (e[i].dir != SMS_OUT || e[i].key != key || (e[i].state != SMS_SENT && e[i].state != SMS_DELIVERED))
            continue;
        struct sms_record r;
        if (store_read(e[i].id, &r, 0, 0) < 0)
            continue;
        for (unsigned p = 0; p < r.parts && p < sizeof r.mr; p++)
            if (r.mr[p] == rep->mr) {
                if (SMS_ST_DELIVERED(rep->status))
                    r.state = SMS_DELIVERED;
                else if (SMS_ST_FAILED(rep->status) && !SMS_ST_TRYING(rep->status)) {
                    r.state = SMS_FAILED;
                    r.cause = rep->status;
                }
                store_update(&r);
                event(SMS_EV_CHANGED, r.id);
                return;
            }
    }
}

static void incoming(unsigned slot)
{
    static uint8_t pdu[SMS_TPDU_MAX + 16];
    char *hex = slots[slot].hex;
    int n = sms_unhex(hex, (unsigned)strlen(hex), pdu, sizeof pdu);
    int skip = n > 0 ? sms_skip_sca(pdu, (unsigned)n, 0) : -1;
    int stored = STORE_ERROR;
    if (skip < 0) {
        kprintf("sms: unreadable PDU \"%s\"\n", hex);
    } else {
        const uint8_t *t = pdu + skip;
        unsigned tl = (unsigned)(n - skip);
        if (slots[slot].len && tl != slots[slot].len)
            kprintf("sms: PDU of %u octets, the URC said %u\n", tl, slots[slot].len);
        stats.received_parts++;
        int mti = sms_tpdu_mti(t, tl);
        if (slots[slot].report || mti == SMS_MTI_STATUS_REPORT) {
            struct sms_status_report rep;
            if (!sms_decode_status_report(t, tl, &rep))
                report(&rep);
            stored = STORE_OK;
        } else if (mti == SMS_MTI_DELIVER && !sms_decode_deliver(t, tl, &deliver)) {
            stored = !store_ready() ? STORE_ERROR : receive(&deliver);
        } else {
            kprintf("sms: a TPDU of type %d that Myna does not read: acknowledged\n", mti);
            stored = STORE_OK;
        }
    }
    if (stored)
        kprintf("sms: message refused (%s)\n", stored == STORE_FULL ? "memory full" : "storage error");
    acknowledge(stored);
    stats.last_receive_insns = insns_since(slots[slot].mark);
    stats.last_receive_mark = slots[slot].mark;
    kprintf("sms: +CMT handled in %u instructions (decode, store, acknowledgement queued)\n", stats.last_receive_insns);
    slots[slot].used = 0;
}

/* "+CMT: [<alpha>],<length>" with the PDU on the next line; "+CDS: <length>" the same for a status report */
static void pdu_urc(const char *line, const char *next, int is_report)
{
    if (!next)
        return;
    int len = 0;
    at_field_int(line, is_report ? 0 : 1, &len);
    for (unsigned i = 0; i < SLOTS; i++) {
        if (slots[i].used)
            continue;
        unsigned n = (unsigned)strlen(next);
        if (n >= sizeof slots[i].hex)
            n = sizeof slots[i].hex - 1;
        memcpy(slots[i].hex, next, n);
        slots[i].hex[n] = 0;
        slots[i].len = (uint16_t)len;
        slots[i].report = (uint8_t)is_report;
        slots[i].mark = modem_rx_mark();
        slots[i].used = 1;
        task_post(&task, MSG_SMS_INCOMING, (uint16_t)i, 0);
        return;
    }
    kprintf("sms: no room for a received PDU: refused\n");
    acknowledge(STORE_ERROR);
}

static void cmt_urc(const char *line, const char *next)
{
    pdu_urc(line, next, 0);
}

static void cds_urc(const char *line, const char *next)
{
    pdu_urc(line, next, 1);
}

/* ---- bring-up ---- */

static void csms_done(void *ctx, const struct at_result *r)
{
    (void)ctx;
    stats.ack_mode = r->status == AT_OK;
    if (!stats.ack_mode)
        kprintf("sms: +CSMS=1 refused: the modem acknowledges messages itself\n");
}

static void csca_line(void *ctx, const char *line)
{
    (void)ctx;
    at_field_str(line, 0, stats.smsc, sizeof stats.smsc);
}

static void cnmi_done(void *ctx, const struct at_result *r)
{
    (void)ctx;
    if (r->status != AT_OK)
        kprintf("sms: +CNMI refused (%d): no messages will be received\n", r->code);
    else
        memory_full_reported = 0;
}

void sms_bringup(void)
{
    at_simple("AT+CMGF=0", 0, 0);
    struct at_cmd csms = { .text = "AT+CSMS=1", .prefix = "+CSMS:", .done = csms_done };
    at_send(&csms);
    struct at_cmd csca = { .text = "AT+CSCA?", .prefix = "+CSCA:", .line = csca_line };
    at_send(&csca);
    at_simple("AT+CNMI=2,2,0,0,0", cnmi_done, 0);
}

#ifdef MYNA_SMS_BENCH
/* make DEFS=-DMYNA_SMS_BENCH=1: with the loopback network, texts to the own number with nothing else running (the
   home screen idle), so that the console's instruction counts are the service's alone. Run with --slice 100. */
static struct timer bench_timer;
static unsigned bench_step;

static void bench(void)
{
    static char text[SMS_TEXT_MAX + 1];
    const char *own = network_status()->own_number;
    switch (bench_step++) {
    case 0:
        sms_send(own, "Bench: one part");
        break;
    case 1: {
        unsigned n = 0;
        while (n < 400) {
            static const char w[] = "Grüße {Ärger} [x] €5 Ñoño ";
            memcpy(text + n, w, sizeof w - 1);
            n += sizeof w - 1;
        }
        text[n] = 0;
        sms_send(own, text);
        break;
    }
    case 2: {
        unsigned n = 0;
        while (n < 300) {
            static const char w[] = "Привет κόσμε 你好 \xF0\x9F\x98\x80 ok ";
            memcpy(text + n, w, sizeof w - 1);
            n += sizeof w - 1;
        }
        text[n] = 0;
        sms_send(own, text);
        break;
    }
    default:
        return;
    }
    timer_start(&bench_timer, KTIME_S(15), 0);
}
#endif

void sms_modem_ready(void)
{
#ifdef MYNA_SMS_BENCH
    timer_init(&bench_timer, &task, T_BENCH);
    timer_start(&bench_timer, KTIME_S(2), 0);
#endif
    kprintf("sms: service centre %s, %s\n", stats.smsc[0] ? stats.smsc : "(none)",
            stats.ack_mode ? "Myna acknowledges each message after storing it" : "the modem acknowledges");
    task_post(&task, MSG_SMS_KICK, 0, 0);
}

/* room again after a refusal for a full store: +CNMI tells the network (RP-SMMA, spec 14 7.2) */
static void room_again(void)
{
    if (memory_full_reported && modem_state() == MODEM_READY && !store_simulating_full()) {
        memory_full_reported = 0;
        kprintf("sms: room for messages again: telling the network\n");
        at_simple("AT+CNMI=2,2,0,0,0", cnmi_done, 0);
    }
}

void sms_init(void)
{
    timer_init(&retry_timer, &task, T_RETRY);
    at_urc("+CMT:", 1, cmt_urc);
    at_urc("+CDS:", 1, cds_urc);
}

static void sms_handle(struct task *self, const struct msg *m)
{
    (void)self;
    switch (m->type) {
    case MSG_START:
        store_init();
        contacts_init();
        break;
    case MSG_SMS_KICK:
    case MSG_NETWORK_CHANGED:
        room_again();
        try_send();
        break;
    case MSG_TIMER:
#ifdef MYNA_SMS_BENCH
        if (m->a == T_BENCH) {
            bench();
            break;
        }
#endif
        try_send();
        break;
    case MSG_SMS_SENT:
        sent((int)m->a - STATUS_BIAS, (int)m->b);
        break;
    case MSG_SMS_INCOMING:
        if (m->a < SLOTS && slots[m->a].used)
            incoming(m->a);
        break;
    }
}
