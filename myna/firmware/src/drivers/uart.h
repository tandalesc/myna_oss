/* SPDX-License-Identifier: MIT */
/* The debug console: the application CPU's UART0 (transmit only). */
#ifndef MYNA_UART_H
#define MYNA_UART_H

void uart_putc(char c);
void uart_puts(const char *s);

#endif
