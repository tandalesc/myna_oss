/* SPDX-License-Identifier: MIT */
/* Wall-clock time: the date and time of day that the phone shows. */
#ifndef MYNA_DRIVERS_CLOCK_H
#define MYNA_DRIVERS_CLOCK_H

#include <stdint.h>

#include "kernel/ostimer.h"

struct civil_time {
    uint16_t year;
    uint8_t month;             /* 1-12 */
    uint8_t day;               /* 1-31 */
    uint8_t weekday;           /* 0 = Monday ... 6 = Sunday */
    uint8_t hour, minute, second;
};

void clock_init(void);                         /* take the time from the power chip */
uint32_t clock_seconds(void);                  /* Unix time now: the chip's clock plus the user's offset */
uint32_t clock_chip_seconds(void);             /* the power chip's clock alone (UTC) */
/* The time the user set, as seconds added to the power chip's clock (the setting SET_CLOCK_OFFSET). The chip's own
 * clock is left as it is. */
void clock_set_offset(int32_t seconds);
ktime_t clock_next_minute(void);               /* kernel time at which the next minute starts */
void clock_civil(uint32_t unix_seconds, struct civil_time *out);

#endif
