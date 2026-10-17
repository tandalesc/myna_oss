/* SPDX-License-Identifier: MIT */
/* The AT command engine (ITU-T V.250, 3GPP TS 27.007 / 27.005; myna/spec/14-modem-at.md section 5).
 *
 * Commands wait in a queue and go out one at a time; each has a timeout. The answer is cut into lines: an
 * information line goes to the command's line handler, the final result code (OK, ERROR, +CME ERROR: n,
 * +CMS ERROR: n, and the V.250 call codes) ends the command and calls its done handler. Unsolicited result codes are
 * recognised by their prefix wherever they come, also in the middle of an answer, and go to their handlers; a URC
 * whose answer line is the next line (+CMT, +CDS) is given both lines. A command with a payload (+CMGS, +CNMA=2)
 * waits for the "> " prompt, then sends the payload and Ctrl-Z. Echoed command lines are ignored.
 *
 * Everything runs in the modem task: the handlers too. A handler may queue further commands. */
#ifndef MYNA_MODEM_AT_H
#define MYNA_MODEM_AT_H

#include <stdint.h>

struct task;

enum at_status {
    AT_OK = 0,
    AT_ERROR = -1,             /* ERROR (or a V.250 call result such as NO CARRIER) */
    AT_CME = -2,               /* +CME ERROR: code */
    AT_CMS = -3,               /* +CMS ERROR: code */
    AT_TIMEOUT = -4,           /* no final result code in time */
    AT_ABORTED = -5,           /* the channel was restarted with the command queued */
};

struct at_result {
    int status;                /* enum at_status */
    int code;                  /* the number of +CME / +CMS ERROR; -1 when the modem gave text */
};

typedef void (*at_line_fn)(void *ctx, const char *line);
typedef void (*at_done_fn)(void *ctx, const struct at_result *r);
/* a URC: its line, and for a two-line URC the line after it (else 0) */
typedef void (*at_urc_fn)(const char *line, const char *next);

#define AT_CMD_MAX   48        /* command text, without the CR */
#define AT_LINE_MAX  600       /* the longest line taken: a +CMT PDU line is up to 2 x 176 hex characters */

struct at_cmd {
    const char *text;          /* "AT+CREG?" (copied) */
    const char *prefix;        /* lines of the answer begin with this ("+CREG:"); 0: every line that is no URC */
    const char *payload;       /* sent after the "> " prompt, then Ctrl-Z; must stay valid until done (not copied) */
    uint32_t timeout_ms;       /* 0: the default (5 s) */
    at_line_fn line;
    at_done_fn done;
    void *ctx;
};

/* The engine's transport: bytes to the modem (the link in raw mode, DLC 1 under the multiplexer). */
typedef void (*at_write_fn)(const void *data, unsigned n);

void at_init(struct task *t, uint16_t timer_id, at_write_fn write);
void at_set_transport(at_write_fn write);

/* Queue a command. Returns 0, or -1 when the queue is full. */
int at_send(const struct at_cmd *c);
/* the short form: a command with no information lines expected */
int at_simple(const char *text, at_done_fn done, void *ctx);

/* bytes from the modem */
void at_input(const uint8_t *p, unsigned n);
/* the engine's timer (from the owner task) */
void at_timer(void);

/* Drop every queued command (each gets AT_ABORTED) and any half-received line: a new channel starts. */
void at_reset(void);

/* Register a URC handler for lines that begin with prefix ("+CREG:"); two_line: the line after it belongs to it. */
void at_urc(const char *prefix, int two_line, at_urc_fn fn);

int at_idle(void);             /* nothing queued or running */

struct at_stats {
    uint32_t commands, timeouts, errors, urcs, lines;
    uint32_t consecutive_timeouts;
};
const struct at_stats *at_stats(void);

/* parse helpers for answers: the n-th (0-based) comma-separated field after "prefix: " as a number / a string
 * (quotes removed). Return 0, or -1 when the field is missing. */
int at_field_int(const char *line, unsigned n, int *out);
int at_field_str(const char *line, unsigned n, char *out, unsigned max);

#endif
