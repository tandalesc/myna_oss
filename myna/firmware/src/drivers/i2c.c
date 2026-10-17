/* SPDX-License-Identifier: MIT */
/* I2C masters (drivers/i2c.h), polled.
 *
 * Polled on purpose for now: Myna talks I2C only at start-up (the power chip's clock and identity), where a few
 * hundred microseconds of waiting on a real bus do not matter, and the simulator completes every step at once.
 * When the UI needs I2C while running (accelerometer, light sensor), this becomes a small state machine on the
 * controllers' interrupt lines (42, 43) driven from a bus task, with the same interface.
 *
 * The controller follows ST's I2C cell (spec 08 1.1): every step is a write to CR or DR, then a wait for a flag in SR1. */
#include <stddef.h>
#include <stdint.h>

#include "drivers/i2c.h"
#include "hw.h"

#define CR   0x00u
#define SR1  0x04u
#define SR2  0x08u
#define DR   0x18u

#define CR_PE    0x20u
#define CR_START 0x08u
#define CR_ACK   0x04u
#define CR_STOP  0x02u

#define SR1_BTF  0x08u
#define SR1_SB   0x01u
#define SR2_ENDAD 0x20u
#define SR2_AF    0x10u

#define WAIT_TRIES 10000       /* a step on a 400 kHz bus takes ~25 us; this bounds a hung controller, not a slow one */

static uint32_t base(enum i2c_bus bus)
{
    return bus == I2C_INTERNAL ? I2C0_BASE : I2C1_BASE;
}

static int wait_sr1(uint32_t b, uint32_t flag)
{
    for (int i = 0; i < WAIT_TRIES; i++)
        if (rd32(b + SR1) & flag)
            return I2C_OK;
    return I2C_TIMEOUT;
}

static void stop(uint32_t b)
{
    wr32(b + CR, CR_PE | CR_STOP);
}

/* start (or repeated start) and the address byte; on success the controller is ready for data */
static int address(uint32_t b, uint8_t addr, int read, uint32_t ack)
{
    wr32(b + CR, CR_PE | CR_START);
    if (wait_sr1(b, SR1_SB))
        return I2C_TIMEOUT;
    wr32(b + DR, (uint32_t)(addr << 1) | (read ? 1u : 0u));
    if (!(rd32(b + SR2) & SR2_ENDAD))      /* reading SR2 is also the first half of clearing ENDAD */
        return I2C_NO_ACK;
    wr32(b + CR, CR_PE | ack);             /* the second half; for a read, the first byte is clocked in now */
    return wait_sr1(b, SR1_BTF);
}

static int send(uint32_t b, uint8_t byte)
{
    wr32(b + DR, byte);
    int r = wait_sr1(b, SR1_BTF);
    if (r)
        return r;
    return (rd32(b + SR2) & SR2_AF) ? I2C_NO_ACK : I2C_OK;
}

int i2c_write(enum i2c_bus bus, uint8_t addr, const uint8_t *data, size_t n)
{
    uint32_t b = base(bus);
    wr32(b + CR, CR_PE);
    int r = address(b, addr, 0, 0);
    for (size_t i = 0; r == I2C_OK && i < n; i++)
        r = send(b, data[i]);
    stop(b);
    return r;
}

int i2c_write_regs(enum i2c_bus bus, uint8_t addr, uint8_t reg, const uint8_t *data, size_t n)
{
    uint32_t b = base(bus);
    wr32(b + CR, CR_PE);
    int r = address(b, addr, 0, 0);
    if (r == I2C_OK)
        r = send(b, reg);
    for (size_t i = 0; r == I2C_OK && i < n; i++)
        r = send(b, data[i]);
    stop(b);
    return r;
}

int i2c_read_regs(enum i2c_bus bus, uint8_t addr, uint8_t reg, uint8_t *data, size_t n)
{
    uint32_t b = base(bus);
    if (n == 0)
        return I2C_OK;
    wr32(b + CR, CR_PE);
    int r = address(b, addr, 0, 0);
    if (r == I2C_OK)
        r = send(b, reg);
    /* repeated start into the read; ACK on every byte but the last, and the STOP before the last byte is taken
       from DR, so the chip is not asked for one byte more (spec 08 1.2) */
    if (r == I2C_OK)
        r = address(b, addr, 1, n > 1 ? CR_ACK : 0);
    for (size_t i = 0; r == I2C_OK && i < n; i++) {
        if (i > 0)
            r = wait_sr1(b, SR1_BTF);
        if (r)
            break;
        if (i + 1 < n) {
            wr32(b + CR, CR_PE | (i + 2 < n ? CR_ACK : 0));
        } else {
            stop(b);
        }
        data[i] = (uint8_t)rd32(b + DR);
    }
    if (r)
        stop(b);
    return r;
}
