/* SPDX-License-Identifier: MIT */
/* The OS timer (base 0xC001A000): Myna's clock and its only wake-up source, used tickless.
 *
 * The hardware offers a periodic 4 ms tick, but Myna never uses it: every wake-up costs host time in the simulator
 * (and battery on a phone), and a phone at its home screen has nothing to do for a minute at a time. Instead the timer
 * is armed as a one-shot for the earliest software timer (kernel/timer.c) and nothing runs in between. */
#include <stdint.h>

#include "hw.h"
#include "kernel/irq.h"
#include "kernel/ostimer.h"
#include "kernel/timer.h"

#define OST_COARSE    (OSTIMER_BASE + 0x04u)   /* 4 ms steps since power-on */
#define OST_FINE      (OSTIMER_BASE + 0x08u)   /* counts down 0x3FF7 .. 0 within a step */
#define OST_INTERVAL  (OSTIMER_BASE + 0x10u)   /* event 0: n = one-shot n x 4 ms after the write; 0 = periodic */
#define OST_STATUS    (OSTIMER_BASE + 0x28u)   /* bit 0 event 0 pending, write 1 to clear */
#define OST_ENABLE    (OSTIMER_BASE + 0x2Cu)   /* bit 0 event 0 enabled */

#define STEP          16376u                   /* counts per coarse step (4 ms) */
#define MAX_STEPS     0xFFFFu                  /* the longest one-shot: 262 s */

static void ostimer_irq(void *arg)
{
    (void)arg;
    wr32(OST_STATUS, 1);                       /* clears the line: done first, before anything can re-arm */
    timer_expire();
}

void ostimer_init(void)
{
    /* Order matters: with the interval register at 0, enabling the event would start the periodic 4 ms tick.
     * Writing a non-zero interval while the event is disabled arms nothing, stores the value, and starts the
     * COARSE/FINE pair (they read as stopped until the first write to the block). */
    wr32(OST_INTERVAL, MAX_STEPS);
    wr32(OST_STATUS, 1);
    wr32(OST_ENABLE, 1);
    irq_attach(IRQ_OSTIMER, ostimer_irq, 0);
    /* armed from the start, even before any software timer exists: an idle CPU always has a wake-up to come */
    wr32(OST_INTERVAL, MAX_STEPS);
}

ktime_t ktime_now(void)
{
    /* two registers: read the step again to catch a step boundary between the reads */
    uint32_t coarse = rd32(OST_COARSE);
    uint32_t fine = rd32(OST_FINE);
    uint32_t again = rd32(OST_COARSE);
    if (again != coarse) {
        coarse = again;
        fine = rd32(OST_FINE);
    }
    return (ktime_t)coarse * STEP + (STEP - 1u - (fine & 0x7FFFu));
}

uint32_t ktime_to_us(ktime_t t)
{
    /* 1 count = 1000 / 4094 us; t * 1000 fits 64 bits for any uptime */
    return (uint32_t)((t * 1000u) / 4094u);
}

void ostimer_arm(ktime_t deadline)
{
    ktime_t now = ktime_now();
    uint32_t steps = 1;
    if (deadline > now) {
        ktime_t delta = deadline - now;
        if (delta >= (ktime_t)MAX_STEPS * STEP)
            steps = MAX_STEPS;                         /* timer.c re-arms when this one comes early */
        else
            steps = ((uint32_t)delta + STEP - 1u) / STEP;    /* round up: never early */
    }
    wr32(OST_INTERVAL, steps);
}
