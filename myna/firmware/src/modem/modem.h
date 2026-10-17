/* SPDX-License-Identifier: MIT */
/* The modem task: the link, the multiplexer and the AT engine, and the bring-up of the services that use them.
 *
 * Bring-up (myna/spec/14-modem-at.md):
 *   raw channel   AT (until it answers), ATE0, AT+CMUX=0,0,5,<N1>
 *   multiplexer   SABM DLC 0, SABM DLC 1, MSC: the AT commands go on DLC 1 from here. If AT+CMUX is refused, or
 *                 a DLC cannot be opened, the commands stay on the raw channel.
 *   AT channel    ATE0, AT+CMEE=1, then the services' commands in this order:
 *                 network  +CPIN?, +CFUN=1, +CREG=2, +CIND=?, +CMER=3,0,0,1, +CIND?
 *                 sms      +CMGF=0, +CSMS=1, +CSCA?, +CNMI=2,2,0,0,0
 *                 network  +CNUM, +COPS=3,0, +COPS?, +CREG?  (+CCLK? once registered)
 * Then the modem is ready (the message service starts sending what waits). Three commands in a row without an
 * answer restart the bring-up. */
#ifndef MYNA_MODEM_MODEM_H
#define MYNA_MODEM_MODEM_H

#include "kernel/ostimer.h"

struct task;

enum modem_state { MODEM_OFF, MODEM_STARTING, MODEM_READY, MODEM_FAILED };

void modem_init(void);                 /* the link and the engines; the bring-up starts with the task's MSG_START */
struct task *modem_task(void);
enum modem_state modem_state(void);
int modem_muxed(void);                 /* the AT commands run on DLC 1 of the multiplexer */
/* kernel_busy() when the modem task began to handle the bytes it is handling now: where the CPU cost of something
 * the modem sent (a received message) starts */
ktime_t modem_rx_mark(void);

#endif
