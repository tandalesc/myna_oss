/* SPDX-License-Identifier: MIT */
/* kprintf: formatted output on the debug console. */
#ifndef MYNA_PRINT_H
#define MYNA_PRINT_H

/* %s %c %d %u %x %X %p %%, with an optional '0' flag, a width and the length modifiers l and ll (%llu: 64 bits) */
void kprintf(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

#endif
