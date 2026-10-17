/* SPDX-License-Identifier: MIT */
/* kprintf: a small printf for the debug console. No floating point, no allocation, no locks (one CPU, no threads yet). */
#include <stdarg.h>
#include <stdint.h>

#include "lib/print.h"
#include "drivers/uart.h"

/* digits of v in `base` (10 or 16), most significant first, into buf (at least 20 bytes: 2^64 - 1 in decimal).
 * Values that fit 32 bits take the 32-bit division: the 64-bit one is a software loop on the ARM926 (aeabi.c). */
static int to_digits(char *buf, unsigned long long v, unsigned base, int upper)
{
    const char *digits = upper ? "0123456789ABCDEF" : "0123456789abcdef";
    char tmp[24];
    int n = 0;
    do {
        if (v >> 32) {
            tmp[n++] = digits[v % base];
            v /= base;
        } else {
            uint32_t w = (uint32_t)v;
            tmp[n++] = digits[w % base];
            v = w / base;
        }
    } while (v);
    for (int i = 0; i < n; i++)
        buf[i] = tmp[n - 1 - i];
    return n;
}

static void pad(char c, int count)
{
    while (count-- > 0)
        uart_putc(c);
}

void kprintf(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    for (const char *p = fmt; *p; p++) {
        if (*p != '%') {
            if (*p == '\n')
                uart_putc('\r');
            uart_putc(*p);
            continue;
        }
        p++;
        char fill = ' ';
        if (*p == '0') {
            fill = '0';
            p++;
        }
        int width = 0;
        while (*p >= '0' && *p <= '9')
            width = width * 10 + (*p++ - '0');
        int longs = 0;
        while (*p == 'l') {
            longs++;
            p++;
        }

        char buf[24];
        int n = 0, negative = 0;
        unsigned long long v;
        switch (*p) {
        case 's': {
            const char *s = va_arg(ap, const char *);
            if (!s)
                s = "(null)";
            int len = 0;
            while (s[len])
                len++;
            pad(' ', width - len);
            uart_puts(s);
            continue;
        }
        case 'c':
            pad(' ', width - 1);
            uart_putc((char)va_arg(ap, int));
            continue;
        case 'd': {
            long long s = longs >= 2 ? va_arg(ap, long long) : longs ? va_arg(ap, long) : va_arg(ap, int);
            negative = s < 0;
            v = negative ? 0ull - (unsigned long long)s : (unsigned long long)s;
            n = to_digits(buf, v, 10, 0);
            break;
        }
        case 'u':
        case 'x':
        case 'X':
            v = longs >= 2 ? va_arg(ap, unsigned long long) : longs ? va_arg(ap, unsigned long) : va_arg(ap, unsigned);
            n = to_digits(buf, v, *p == 'u' ? 10 : 16, *p == 'X');
            break;
        case 'p':
            uart_puts("0x");
            n = to_digits(buf, (uintptr_t)va_arg(ap, void *), 16, 0);
            fill = '0';
            width = 8;
            break;
        case '%':
            uart_putc('%');
            continue;
        default:                    /* an unknown conversion is printed as it stands, so a mistake shows */
            uart_putc('%');
            if (!*p)
                goto out;
            uart_putc(*p);
            continue;
        }
        if (negative && fill == '0')
            uart_putc('-');
        pad(fill, width - n - negative);
        if (negative && fill == ' ')
            uart_putc('-');
        for (int i = 0; i < n; i++)
            uart_putc(buf[i]);
    }
out:
    va_end(ap);
}
