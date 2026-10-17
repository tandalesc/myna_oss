/* SPDX-License-Identifier: MIT */
/* The 3GPP TS 27.010 multiplexer, basic option, as the initiator (myna/spec/14-modem-at.md section 4): DLC 0 for
 * control, DLC 1 for AT commands, UIH frames, convergence layer 1. Started after AT+CMUX has been answered OK: SABM
 * on DLC 0, then on DLC 1 (each retried N2 = 3 times, T1 apart), then MSC on DLC 1 (ready to receive). A DM or no
 * answer fails the start: the caller then goes on without the multiplexer. */
#ifndef MYNA_MODEM_CMUX_H
#define MYNA_MODEM_CMUX_H

#include <stdint.h>

struct task;

enum cmux_event { CMUX_OPEN, CMUX_FAILED, CMUX_CLOSED };

typedef void (*cmux_data_fn)(const uint8_t *data, unsigned n);     /* bytes of DLC 1 */
typedef void (*cmux_event_fn)(enum cmux_event ev);

/* timer_id: a timer of `t` that the task passes back with cmux_timer() */
void cmux_init(struct task *t, uint16_t timer_id, cmux_data_fn data, cmux_event_fn event);
void cmux_start(unsigned n1);                  /* the N1 given to AT+CMUX */
void cmux_input(const uint8_t *p, unsigned n); /* bytes from the link while the multiplexer runs */
void cmux_write(const void *data, unsigned n); /* bytes for DLC 1 (cut into frames of at most N1) */
void cmux_timer(void);
int cmux_running(void);                        /* frames are being exchanged (start begun, not failed or closed) */

/* A CLD (close down) frame sent blind: brings a modem that is still in multiplexer mode (from a firmware that ran
 * before) back to AT commands. Harmless for a modem in AT mode, which ignores a line not starting with "AT". */
void cmux_send_close_down(void);

struct cmux_stats {
    uint32_t frames_in, frames_out, bad_fcs, dropped;
};
const struct cmux_stats *cmux_stats(void);

#endif
