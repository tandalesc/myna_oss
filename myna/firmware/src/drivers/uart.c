/* SPDX-License-Identifier: MIT */
/* Debug console on UART0 of the application CPU, a hardware block at 0xC0013000. The simulator models it
 * (native/emu/uart.py) and prints each line the CPU sends as "APP uart| ..." (and into app-uart.log).
 *
 * The register layout is that of an ARM PrimeCell PL011: data register at +0x00, flag register at +0x18 with bit 5
 * TXFF (transmit FIFO full) and bit 7 TXFE (transmit FIFO empty). What is known of the block is that much: the stock
 * boot code writes characters to +0x00, and the simulator's model answers +0x18 with TXFE set, TXFF clear.
 * No set-up is done (baud rate, enable): the model has no such registers, and what the real block needs before it
 * sends is not known yet. TODO: on a real phone, find out whether it must be clocked and enabled first. */
#include <stdint.h>

#include "drivers/uart.h"

#define UART0_BASE 0xC0013000u
#define UART_DR    0x00u
#define UART_FR    0x18u
#define FR_TXFF    (1u << 5)

static inline volatile uint32_t *reg(uint32_t off)
{
    return (volatile uint32_t *)(UART0_BASE + off);
}

void uart_putc(char c)
{
    /* one flag read per character: the model never reports a full FIFO, so this is no polling loop in the simulator,
       and on hardware it waits only while the FIFO is really full */
    while (*reg(UART_FR) & FR_TXFF)
        ;
    *reg(UART_DR) = (uint8_t)c;
}

void uart_puts(const char *s)
{
    for (; *s; s++) {
        if (*s == '\n')
            uart_putc('\r');        /* a terminal on a real serial line wants CR LF; the simulator ignores the CR */
        uart_putc(*s);
    }
}
