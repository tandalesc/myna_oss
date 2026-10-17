/* SPDX-License-Identifier: MIT */
/* Power-management chip (I2C0, address 0x48): identity, power-on cause, battery-backed clock, battery voltage, and the
 * system supply switch that is the phone's power off. Register numbers: myna/spec/08-i2c-spi-chips.md, section 2. */
#include <stdint.h>

#include "cpu.h"
#include "drivers/i2c.h"
#include "drivers/pmic.h"
#include "lib/print.h"

#define PMIC          0x48
#define R_CHIP_ID     0x20
#define R_EVENT1      0x21     /* 0x21-0x23: events, cleared by reading */
#define R_CLOCK_CTRL  0x53     /* bit 0: time valid */
#define R_CLOCK       0x5A     /* 0x5A-0x5F: 48-bit count of 1/65536 s, little-endian */
#define R_VBAT_HIGH   0x7D     /* battery code bits 9:2 */
#define R_SUPPLY      0x42     /* system supply regulator; bit 4 = on */

/* Battery converter range of this phone's channel (spec 08 2.4): code 0 = 2500 mV, code 1023 = 4500 mV. */
#define VBAT_LOW_MV   2500
#define VBAT_HIGH_MV  4500

int pmic_init(void)
{
    uint8_t id, ev[3];
    int r = i2c_read_regs(I2C_INTERNAL, PMIC, R_CHIP_ID, &id, 1);
    if (r) {
        kprintf("pmic: no answer on I2C0 (%d)\n", r);
        return r;
    }
    /* the events read now are the reason for this power-on; reading also clears them, so a later interrupt on
       line 0 means something new. Every event stays masked (reset value) until a driver wants one. */
    r = i2c_read_regs(I2C_INTERNAL, PMIC, R_EVENT1, ev, 3);
    if (r)
        return r;
    kprintf("pmic: chip %02x, power-on events %02x %02x %02x%s\n", id, ev[0], ev[1], ev[2],
            ev[0] & 1 ? " (power key)" : "");
    return 0;
}

int pmic_read_clock(struct pmic_clock *c)
{
    uint8_t ctrl, b[6];
    int r = i2c_read_regs(I2C_INTERNAL, PMIC, R_CLOCK_CTRL, &ctrl, 1);
    if (!r)
        r = i2c_read_regs(I2C_INTERNAL, PMIC, R_CLOCK, b, 6);   /* one transfer: the bytes belong to one instant */
    if (r)
        return r;
    c->fraction = (uint16_t)(b[0] | b[1] << 8);
    c->seconds = (uint32_t)b[2] | (uint32_t)b[3] << 8 | (uint32_t)b[4] << 16 | (uint32_t)b[5] << 24;
    c->valid = ctrl & 1;
    return 0;
}

int pmic_battery_mv(void)
{
    uint8_t v[2];
    int r = i2c_read_regs(I2C_INTERNAL, PMIC, R_VBAT_HIGH, v, 2);
    if (r)
        return r;
    uint32_t code = (uint32_t)v[0] << 2 | (v[1] & 3u);      /* 10 bits */
    return VBAT_LOW_MV + (int)((code * (VBAT_HIGH_MV - VBAT_LOW_MV) + 511) / 1023);
}

void pmic_power_off(void)
{
    static const uint8_t off = 0x00;
    kprintf("pmic: power off\n");
    cpu_irq_save();
    i2c_write_regs(I2C_INTERNAL, PMIC, R_SUPPLY, &off, 1);
    for (;;)                               /* the supply is gone; on the simulator the run has ended */
        cpu_wait_for_interrupt();
}
