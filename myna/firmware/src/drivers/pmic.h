/* SPDX-License-Identifier: MIT */
/* The power-management chip on the internal I2C bus (myna/spec/08-i2c-spi-chips.md, section 2). */
#ifndef MYNA_DRIVERS_PMIC_H
#define MYNA_DRIVERS_PMIC_H

#include <stdint.h>

struct pmic_clock {
    uint32_t seconds;          /* Unix time */
    uint16_t fraction;         /* 1/65536 s */
    uint8_t valid;             /* the chip says the time survived (its "time valid" bit) */
};

int pmic_init(void);                           /* identify the chip, take the power-on cause; 0 = ok */
int pmic_read_clock(struct pmic_clock *c);     /* 0 = ok */
int pmic_battery_mv(void);                     /* battery voltage in mV, or < 0 on a bus error */
__attribute__((noreturn)) void pmic_power_off(void);

#endif
