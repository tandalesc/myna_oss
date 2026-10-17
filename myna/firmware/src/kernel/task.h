/* SPDX-License-Identifier: MIT */
/* Tasks and messages: Myna's unit of work.
 *
 * A task is an event handler with a message queue. The kernel delivers one message at a time to the most urgent task
 * that has one; a handler runs to its end (no preemption between tasks), and when no task has a message the CPU
 * sleeps. Interrupt handlers and timers talk to tasks only by posting messages. A task never waits: it keeps its
 * state in its own structure and returns. (If preemption is ever needed, each task gets a stack and the post becomes
 * the place where a switch may happen; the interface below stays.) */
#ifndef MYNA_KERNEL_TASK_H
#define MYNA_KERNEL_TASK_H

#include <stdint.h>

#include "kernel/msg.h"
#include "kernel/ostimer.h"

struct msg {
    uint16_t type;             /* enum msg_type (kernel/msg.h) */
    uint16_t a;                /* small argument (a key index, a timer id) */
    uint32_t b;                /* word argument */
};

#define TASK_QUEUE 32          /* messages per task; a power of two */

struct task;
typedef void (*task_handler)(struct task *self, const struct msg *m);

struct task {
    const char *name;
    task_handler handle;
    struct task *next;         /* in priority order */
    struct msg queue[TASK_QUEUE];
    volatile uint8_t head, tail;
    uint16_t dropped;          /* posts lost to a full queue */
    uint32_t handled;          /* messages delivered */
};

/* Register a task; tasks registered first are served first. Done at start-up, before kernel_run(). */
void task_add(struct task *t);

/* Queue a message for a task. Safe from interrupt handlers and from tasks. Returns 0 if the queue was full. */
int task_post(struct task *t, uint16_t type, uint16_t a, uint32_t b);

/* The event loop: deliver messages for ever, sleeping in wait-for-interrupt when there are none. */
__attribute__((noreturn)) void kernel_run(void);

/* how often the CPU went to sleep (wake-ups) since start */
uint32_t kernel_sleeps(void);
/* kernel time the CPU spent awake since kernel_run() began. The simulator advances device time in slices (200 us by
 * default; option --slice), so this is as fine as the slice. */
ktime_t kernel_busy(void);

#endif
