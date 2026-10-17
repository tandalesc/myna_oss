/* SPDX-License-Identifier: MIT */
/* Device register access and the base addresses of the blocks Myna drives (myna/spec/01-memory-map.md).
 * Each driver adds its own offsets; only the bases are shared, so the memory map is in one place. */
#ifndef MYNA_HW_H
#define MYNA_HW_H

#include <stdint.h>

#define NANDC_BASE    0x9F800000u   /* NAND controller (the chip itself is behind 0x80000000) */
#define VIC0_BASE     0xA0001000u   /* interrupt controller, lines 0-31 */
#define VIC1_BASE     0xA0002000u   /* lines 32-63 */
#define I2C0_BASE     0xC0004000u   /* internal bus: power-management chip */
#define I2C1_BASE     0xC0005000u   /* external bus: illumination driver, accelerometer, ... */
#define KEYPAD_BASE   0xC0015000u
#define GPIO_BASE     0xC0016000u   /* five banks of eight pins, 0x30 apart */
#define RTC_BASE      0xC0017000u
#define OSTIMER_BASE  0xC001A000u
#define XGAM_BASE     0xD0000000u   /* display controller */

static inline uint32_t rd32(uint32_t addr)
{
    return *(volatile uint32_t *)addr;
}

static inline void wr32(uint32_t addr, uint32_t v)
{
    *(volatile uint32_t *)addr = v;
}

/* the keypad and GPIO blocks have 16-bit registers */
static inline uint16_t rd16(uint32_t addr)
{
    return *(volatile uint16_t *)addr;
}

static inline void wr16(uint32_t addr, uint16_t v)
{
    *(volatile uint16_t *)addr = v;
}

#endif
