/* SPDX-License-Identifier: MIT */
/* Wall-clock time (drivers/clock.h).
 *
 * The power chip's clock is the one that survives (battery-backed, 1/65536 s). It is read once at start over I2C;
 * after that the time is that reading plus the kernel time elapsed since, so showing the time needs no bus traffic and
 * the minute boundary is known to the OS timer's resolution. The SoC's real-time clock (whole seconds, with an alarm)
 * is loaded with the same seconds for later use by alarms (myna/spec/04-timers-clock.md, section 3).
 * In the simulator the power chip starts at a fixed date [MOCK, spec 08 2.3] unless the run sets EMU_PMIC_RTC. */
#include <stdint.h>

#include "drivers/clock.h"
#include "drivers/pmic.h"
#include "hw.h"
#include "lib/print.h"

#define RTC_LOAD (RTC_BASE + 0x04u)

static uint32_t base_seconds;      /* Unix seconds at base_ktime ... */
static ktime_t base_ktime;         /* ... minus the fraction of a second the chip had counted: base_ktime is the
                                      kernel time at which the chip's seconds count last went up */
static int32_t offset;             /* the user's time minus the chip's (a setting: the chip's clock is never set) */

void clock_set_offset(int32_t seconds)
{
    offset = seconds;
}

void clock_init(void)
{
    struct pmic_clock pc = { 0 };
    ktime_t now = ktime_now();
    if (pmic_read_clock(&pc)) {
        kprintf("clock: power chip not readable, starting at 2000-01-01\n");
        pc.seconds = 946684800u;
    }
    base_seconds = pc.seconds;
    base_ktime = now - (ktime_t)pc.fraction * KTIME_PER_S / 65536u;
    wr32(RTC_LOAD, pc.seconds);

    struct civil_time t;
    clock_civil(pc.seconds, &t);
    kprintf("clock: %04u-%02u-%02u %02u:%02u:%02u UTC%s\n", t.year, t.month, t.day, t.hour, t.minute, t.second,
            pc.valid ? "" : " (the power chip says the time is not valid)");
}

/* whole seconds since base, and the kernel time at which the current second began */
static uint32_t elapsed(ktime_t now, ktime_t *second_start)
{
    ktime_t d = now - base_ktime;
    /* 64-bit division by a constant: done once per call, a few times a minute at most */
    uint32_t s = (uint32_t)(d / KTIME_PER_S);
    if (second_start)
        *second_start = base_ktime + (ktime_t)s * KTIME_PER_S;
    return s;
}

uint32_t clock_seconds(void)
{
    return base_seconds + (uint32_t)offset + elapsed(ktime_now(), 0);
}

uint32_t clock_chip_seconds(void)
{
    return base_seconds + elapsed(ktime_now(), 0);
}

ktime_t clock_next_minute(void)
{
    ktime_t start;
    uint32_t s = base_seconds + (uint32_t)offset + elapsed(ktime_now(), &start);
    return start + KTIME_S(60 - s % 60);
}

/* Unix seconds to the civil calendar (proleptic Gregorian, UTC): days counted forward from 1970 by whole years and
 * months. A loop of at most a few dozen steps, run once a minute: clearer than the closed formulas, and fast enough. */
static int leap(uint32_t y)
{
    return (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
}

void clock_civil(uint32_t unix_seconds, struct civil_time *out)
{
    static const uint8_t month_days[12] = { 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 };
    uint32_t days = unix_seconds / 86400u, rest = unix_seconds % 86400u;
    out->hour = (uint8_t)(rest / 3600u);
    out->minute = (uint8_t)(rest / 60u % 60u);
    out->second = (uint8_t)(rest % 60u);
    out->weekday = (uint8_t)((days + 3u) % 7u);    /* 1970-01-01 was a Thursday (3 counting from Monday = 0) */

    uint32_t year = 1970;
    for (;;) {
        uint32_t len = leap(year) ? 366u : 365u;
        if (days < len)
            break;
        days -= len;
        year++;
    }
    uint32_t month = 0;
    for (;;) {
        uint32_t len = month_days[month] + (month == 1 && leap(year));
        if (days < len)
            break;
        days -= len;
        month++;
    }
    out->year = (uint16_t)year;
    out->month = (uint8_t)(month + 1);
    out->day = (uint8_t)(days + 1);
}
