/* SPDX-License-Identifier: MIT */
/* Software timers on the one OS timer event. A timer that expires posts MSG_TIMER (a = its id) to its task, so its
 * work runs in that task like any other message. Timers are owned by their task (static storage, no allocation). */
#ifndef MYNA_KERNEL_TIMER_H
#define MYNA_KERNEL_TIMER_H

#include <stdint.h>

#include "kernel/ostimer.h"

struct task;

struct timer {
    struct timer *next;        /* in the list of armed timers, earliest first */
    ktime_t when;
    ktime_t period;            /* 0 = one-shot */
    struct task *task;
    uint16_t id;
    uint8_t armed;
};

void timer_init(struct timer *t, struct task *task, uint16_t id);

void timer_start(struct timer *t, ktime_t delay, ktime_t period);   /* first expiry after delay; replaces an armed one */
void timer_start_at(struct timer *t, ktime_t when);                 /* one-shot at an absolute time */
void timer_stop(struct timer *t);

/* called by the OS timer interrupt: post the timers that are due, arm the next one */
void timer_expire(void);

#endif
