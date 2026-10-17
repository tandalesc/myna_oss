/* SPDX-License-Identifier: MIT */
/* Kernel time: the OS timer's count since power-on, and its one-shot event (myna/spec/04-timers-clock.md, section 1). */
#ifndef MYNA_KERNEL_OSTIMER_H
#define MYNA_KERNEL_OSTIMER_H

#include <stdint.h>

/* Time is kept in the OS timer's own counts, 4.094 MHz: 1 ms is exactly 4094 counts and 4 ms (one coarse step of the
 * timer) exactly 16376, so no conversion is needed on the hot path and none loses time. 64 bits never wrap. */
typedef uint64_t ktime_t;

#define KTIME_PER_MS  4094u
#define KTIME_PER_S   4094000u
#define KTIME_MS(ms)  ((ktime_t)(ms) * KTIME_PER_MS)
#define KTIME_S(s)    ((ktime_t)(s) * KTIME_PER_S)

void ostimer_init(void);
ktime_t ktime_now(void);
uint32_t ktime_to_us(ktime_t t);        /* for reports; t below 17 minutes */

/* Arm the one event so that it comes at `deadline` or up to 4 ms after it (the hardware counts whole 4 ms steps
 * from the write), never before. A new call replaces the armed event. */
void ostimer_arm(ktime_t deadline);

#endif
