/* SPDX-License-Identifier: MIT */
/* I2C masters (myna/spec/08-i2c-spi-chips.md, section 1): register reads and writes of the chips on the two buses. */
#ifndef MYNA_DRIVERS_I2C_H
#define MYNA_DRIVERS_I2C_H

#include <stddef.h>
#include <stdint.h>

enum i2c_bus { I2C_INTERNAL = 0, I2C_EXTERNAL = 1 };

enum i2c_result {
    I2C_OK = 0,
    I2C_NO_ACK = -1,       /* nobody answered the address, or a data byte was refused */
    I2C_TIMEOUT = -2,      /* the controller did not finish a step */
};

/* write `n` bytes starting at register `reg` (the chip's register pointer protocol) */
int i2c_write_regs(enum i2c_bus bus, uint8_t addr, uint8_t reg, const uint8_t *data, size_t n);
/* read `n` bytes starting at register `reg` */
int i2c_read_regs(enum i2c_bus bus, uint8_t addr, uint8_t reg, uint8_t *data, size_t n);
/* raw write transfer of `n` bytes (for chips without a register pointer); n = 0 only checks the address */
int i2c_write(enum i2c_bus bus, uint8_t addr, const uint8_t *data, size_t n);

#endif
