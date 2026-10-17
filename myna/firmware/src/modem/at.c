/* SPDX-License-Identifier: MIT */
/* The AT command engine (modem/at.h). */
#include <stdint.h>

#include "kernel/timer.h"
#include "lib/mem.h"
#include "lib/print.h"
#include "modem/at.h"

#define QUEUE            24
#define URCS             12
#define DEFAULT_TIMEOUT  5000
#define CTRL_Z           0x1A
#define ESC              0x1B

struct entry {
    char text[AT_CMD_MAX];
    const char *prefix, *payload;
    uint32_t timeout_ms;
    at_line_fn line;
    at_done_fn done;
    void *ctx;
};

static struct entry queue[QUEUE];
static unsigned head, count;
static uint8_t running, await_prompt;
static struct timer timer;
static at_write_fn transport;

static char line[AT_LINE_MAX + 1];
static unsigned line_len;
static uint8_t line_overflow;

static struct {
    const char *prefix;
    uint8_t len, two_line;
    at_urc_fn fn;
} urcs[URCS];
static unsigned urc_count;
static int pending_urc = -1;               /* a two-line URC waiting for its second line */
static char pending_line[80];

static struct at_stats stats;

const struct at_stats *at_stats(void)
{
    return &stats;
}

static int starts(const char *s, const char *prefix)
{
    while (*prefix)
        if (*s++ != *prefix++)
            return 0;
    return 1;
}

void at_init(struct task *t, uint16_t timer_id, at_write_fn write)
{
    timer_init(&timer, t, timer_id);
    transport = write;
}

void at_set_transport(at_write_fn write)
{
    transport = write;
}

void at_urc(const char *prefix, int two_line, at_urc_fn fn)
{
    if (urc_count >= URCS)
        return;
    urcs[urc_count].prefix = prefix;
    urcs[urc_count].len = (uint8_t)strlen(prefix);
    urcs[urc_count].two_line = (uint8_t)two_line;
    urcs[urc_count].fn = fn;
    urc_count++;
}

int at_idle(void)
{
    return !count;
}

static void send_head(void)
{
    if (running || !count)
        return;
    struct entry *e = &queue[head];
    running = 1;
    await_prompt = e->payload != 0;
#ifdef MYNA_AT_TRACE
    kprintf("at> %s\n", e->text);
#endif
    transport(e->text, (unsigned)strlen(e->text));
    transport("\r", 1);
    stats.commands++;
    timer_start(&timer, KTIME_MS(e->timeout_ms), 0);
}

int at_send(const struct at_cmd *c)
{
    if (count >= QUEUE) {
        kprintf("at: queue full, %s dropped\n", c->text);
        return -1;
    }
    struct entry *e = &queue[(head + count) % QUEUE];
    unsigned n = (unsigned)strlen(c->text);
    if (n >= AT_CMD_MAX)
        n = AT_CMD_MAX - 1;
    memcpy(e->text, c->text, n);
    e->text[n] = 0;
    e->prefix = c->prefix;
    e->payload = c->payload;
    e->timeout_ms = c->timeout_ms ? c->timeout_ms : DEFAULT_TIMEOUT;
    e->line = c->line;
    e->done = c->done;
    e->ctx = c->ctx;
    count++;
    send_head();
    return 0;
}

int at_simple(const char *text, at_done_fn done, void *ctx)
{
    struct at_cmd c = { .text = text, .done = done, .ctx = ctx };
    return at_send(&c);
}

/* the running command ends with this result */
static void finish(int status, int code)
{
    timer_stop(&timer);
    struct entry e = queue[head];          /* a copy: the handler may queue into this slot */
    head = (head + 1) % QUEUE;
    count--;
    running = await_prompt = 0;
    if (status == AT_TIMEOUT) {
        stats.timeouts++;
        stats.consecutive_timeouts++;
    } else {
        stats.consecutive_timeouts = 0;
        if (status != AT_OK)
            stats.errors++;
    }
    struct at_result r = { status, code };
    if (e.done)
        e.done(e.ctx, &r);
    send_head();
}

void at_reset(void)
{
    timer_stop(&timer);
    line_len = 0;
    pending_urc = -1;
    while (count) {
        struct entry e = queue[head];
        head = (head + 1) % QUEUE;
        count--;
        running = await_prompt = 0;
        struct at_result r = { AT_ABORTED, 0 };
        if (e.done)
            e.done(e.ctx, &r);
    }
    running = await_prompt = 0;
}

void at_timer(void)
{
    if (!running)
        return;
    if (await_prompt)
        transport((const uint8_t[]){ ESC }, 1);    /* a prompt may come late: cancel the PDU entry */
    kprintf("at: %s: no answer\n", queue[head].text);
    finish(AT_TIMEOUT, 0);
}

static int parse_code(const char *s)
{
    while (*s == ' ')
        s++;
    if (*s < '0' || *s > '9')
        return -1;             /* +CMEE=2: text */
    int v = 0;
    while (*s >= '0' && *s <= '9')
        v = v * 10 + (*s++ - '0');
    return v;
}

/* a final result code: its status, or 1 when the line is none */
static int final_code(const char *s, int *code)
{
    *code = 0;
    if (!strcmp(s, "OK"))
        return AT_OK;
    if (!strcmp(s, "ERROR") || !strcmp(s, "NO CARRIER") || !strcmp(s, "BUSY") || !strcmp(s, "NO ANSWER") ||
        !strcmp(s, "NO DIALTONE"))
        return AT_ERROR;
    if (starts(s, "+CME ERROR:")) {
        *code = parse_code(s + 11);
        return AT_CME;
    }
    if (starts(s, "+CMS ERROR:")) {
        *code = parse_code(s + 11);
        return AT_CMS;
    }
    return 1;
}

static void handle_line(const char *s)
{
    stats.lines++;
#ifdef MYNA_AT_TRACE
    kprintf("at< %s\n", s);
#endif
    if (pending_urc >= 0) {
        int u = pending_urc;
        pending_urc = -1;
        stats.urcs++;
        urcs[u].fn(pending_line, s);
        return;
    }
    if (running && (s[0] == 'A' || s[0] == 'a') && (s[1] == 'T' || s[1] == 't'))
        return;                /* our command line echoed */
    if (running) {
        int code, st = final_code(s, &code);
        if (st <= 0) {
            finish(st, code);
            return;
        }
        const struct entry *e = &queue[head];
        if (e->prefix && starts(s, e->prefix)) {
            if (e->line)
                e->line(e->ctx, s);
            return;
        }
    }
    for (unsigned i = 0; i < urc_count; i++) {
        if (!starts(s, urcs[i].prefix))
            continue;
        stats.urcs++;
        if (urcs[i].two_line) {
            unsigned n = (unsigned)strlen(s);
            if (n >= sizeof pending_line)
                n = sizeof pending_line - 1;
            memcpy(pending_line, s, n);
            pending_line[n] = 0;
            pending_urc = (int)i;
            stats.urcs--;      /* counted when its second line comes */
        } else {
            urcs[i].fn(s, 0);
        }
        return;
    }
    if (running && !queue[head].prefix) {
        if (queue[head].line)
            queue[head].line(queue[head].ctx, s);
        return;
    }
    if (running)
        return;                /* a line of the answer that the command does not want */
    kprintf("at: unexpected line \"%s\"\n", s);
}

void at_input(const uint8_t *p, unsigned n)
{
    for (unsigned i = 0; i < n; i++) {
        char c = (char)p[i];
        if (c == '\r' || c == '\n') {
            if (line_len && !line_overflow) {
                line[line_len] = 0;
                handle_line(line);
            }
            line_len = 0;
            line_overflow = 0;
            continue;
        }
        if (line_len >= AT_LINE_MAX) {
            line_overflow = 1;
            continue;
        }
        line[line_len++] = c;
        if (await_prompt && line_len == 2 && line[0] == '>' && line[1] == ' ') {
            /* the PDU prompt: no line end follows */
            const char *pl = queue[head].payload;
#ifdef MYNA_AT_TRACE
            kprintf("at< > \nat> %s<Ctrl-Z>\n", pl);
#endif
            transport(pl, (unsigned)strlen(pl));
            transport((const uint8_t[]){ CTRL_Z }, 1);
            await_prompt = 0;
            line_len = 0;
        }
    }
}

/* ---- answer fields ---- */

/* start of field n (after the "prefix:" and blanks), or 0 */
static const char *field(const char *s, unsigned n)
{
    const char *colon = strchr(s, ':');
    if (colon)
        s = colon + 1;
    while (*s == ' ')
        s++;
    int quoted = 0;
    while (n) {
        if (!*s)
            return 0;
        if (*s == '"')
            quoted = !quoted;
        else if (*s == ',' && !quoted)
            n--;
        s++;
    }
    while (*s == ' ')
        s++;
    return s;
}

int at_field_int(const char *s, unsigned n, int *out)
{
    const char *f = field(s, n);
    if (!f)
        return -1;
    if (*f == '"')
        f++;
    int neg = 0, v = 0, digits = 0;
    if (*f == '-' || *f == '+')
        neg = *f++ == '-';
    while (*f >= '0' && *f <= '9') {
        v = v * 10 + (*f++ - '0');
        digits++;
    }
    if (!digits)
        return -1;
    *out = neg ? -v : v;
    return 0;
}

int at_field_str(const char *s, unsigned n, char *out, unsigned max)
{
    const char *f = field(s, n);
    if (!f || !max)
        return -1;
    unsigned k = 0;
    if (*f == '"') {
        f++;
        while (*f && *f != '"' && k + 1 < max)
            out[k++] = *f++;
    } else {
        while (*f && *f != ',' && k + 1 < max)
            out[k++] = *f++;
        while (k && out[k - 1] == ' ')
            k--;
    }
    out[k] = 0;
    return 0;
}
