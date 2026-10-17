/* SPDX-License-Identifier: MIT */
/* The event loop (kernel/task.h). */
#include <stdint.h>

#include "cpu.h"
#include "kernel/task.h"
#include "lib/print.h"

static struct task *tasks;          /* priority order: first registered = first served */
static uint32_t sleeps;
static ktime_t busy, awake_since;   /* CPU time spent awake: what the phone costs in host time and battery */

void task_add(struct task *t)
{
    struct task **p = &tasks;
    while (*p)
        p = &(*p)->next;
    t->next = 0;
    t->head = t->tail = 0;
    *p = t;
}

int task_post(struct task *t, uint16_t type, uint16_t a, uint32_t b)
{
    uint32_t psr = cpu_irq_save();
    uint8_t tail = t->tail;
    uint8_t next = (tail + 1) & (TASK_QUEUE - 1);
    int ok = next != t->head;
    if (ok) {
        t->queue[tail] = (struct msg){ .type = type, .a = a, .b = b };
        t->tail = next;
    } else {
        t->dropped++;
    }
    cpu_irq_restore(psr);
    if (!ok)
        kprintf("task %s: queue full, message %u lost\n", t->name, type);
    return ok;
}

/* the most urgent task with a message, or none */
static struct task *ready(void)
{
    for (struct task *t = tasks; t; t = t->next)
        if (t->head != t->tail)
            return t;
    return 0;
}

uint32_t kernel_sleeps(void)
{
    return sleeps;
}

ktime_t kernel_busy(void)
{
    uint32_t psr = cpu_irq_save();
    ktime_t b = busy + (ktime_now() - awake_since);
    cpu_irq_restore(psr);
    return b;
}

void kernel_run(void)
{
    awake_since = ktime_now();
    cpu_irq_enable();
    for (;;) {
        struct task *t = ready();
        if (t) {
            /* only this loop takes from a queue, so the head moves without a lock; the copy is taken before the
               slot is given back to posters */
            struct msg m = t->queue[t->head];
            t->head = (t->head + 1) & (TASK_QUEUE - 1);
            t->handled++;
            t->handle(t, &m);
            continue;
        }
        /* Nothing to do: sleep. IRQ is masked across the last check and the wait, so an interrupt that posts a
           message in between is not missed: with IRQ masked the core still wakes on a pending line, and the
           interrupt is taken when the mask is lifted. kernel/timer.c keeps the OS timer armed at all times, so this
           sleep always ends (an idle with nothing scheduled would end the simulator's run: spec 00 5.2). */
        uint32_t psr = cpu_irq_save();
        if (!ready()) {
            sleeps++;
            busy += ktime_now() - awake_since;
            cpu_wait_for_interrupt();
            awake_since = ktime_now();
        }
        cpu_irq_restore(psr);
    }
}
