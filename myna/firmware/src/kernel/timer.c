/* SPDX-License-Identifier: MIT */
/* Software timers (kernel/timer.h): a list sorted by expiry; the OS timer is armed for the head only.
 *
 * A list is enough: a phone has a handful of armed timers at a time, and insertion is the only walk. With no timer
 * armed the OS timer still gets the longest one-shot it can (262 s): the simulator ends a run whose CPU sleeps with
 * nothing scheduled (spec 00 5.2, gap G7), and a real phone gains nothing from sleeping without a deadline either. */
#include <stdint.h>

#include "cpu.h"
#include "kernel/task.h"
#include "kernel/timer.h"

static struct timer *armed;        /* earliest first */

/* program the hardware for the earliest timer; IRQ masked by the caller */
static void rearm(void)
{
    if (armed)
        ostimer_arm(armed->when);
    else
        ostimer_arm(ktime_now() + KTIME_S(300));     /* longer than the hardware can: it arms its maximum */
}

static void unlink(struct timer *t)
{
    for (struct timer **p = &armed; *p; p = &(*p)->next) {
        if (*p == t) {
            *p = t->next;
            break;
        }
    }
    t->armed = 0;
}

static void insert(struct timer *t)
{
    struct timer **p = &armed;
    while (*p && (*p)->when <= t->when)       /* equal times keep their order of arming */
        p = &(*p)->next;
    t->next = *p;
    *p = t;
    t->armed = 1;
}

void timer_init(struct timer *t, struct task *task, uint16_t id)
{
    *t = (struct timer){ .task = task, .id = id };
}

static void start(struct timer *t, ktime_t when, ktime_t period)
{
    uint32_t psr = cpu_irq_save();
    if (t->armed)
        unlink(t);
    t->when = when;
    t->period = period;
    insert(t);
    if (armed == t)
        rearm();                               /* the new head: the hardware must wake earlier */
    cpu_irq_restore(psr);
}

void timer_start(struct timer *t, ktime_t delay, ktime_t period)
{
    start(t, ktime_now() + delay, period);
}

void timer_start_at(struct timer *t, ktime_t when)
{
    start(t, when, 0);
}

void timer_stop(struct timer *t)
{
    uint32_t psr = cpu_irq_save();
    if (t->armed) {
        int was_head = armed == t;
        unlink(t);
        if (was_head)
            rearm();
    }
    cpu_irq_restore(psr);
}

void timer_expire(void)
{
    ktime_t now = ktime_now();
    while (armed && armed->when <= now) {
        struct timer *t = armed;
        armed = t->next;
        t->armed = 0;
        task_post(t->task, MSG_TIMER, t->id, 0);
        if (t->period) {
            /* keep the cadence (when + period), but after a long stall start again from now rather than post a
               burst of expiries that nobody can use */
            t->when += t->period;
            if (t->when <= now)
                t->when = now + t->period;
            insert(t);
        }
    }
    rearm();
}
