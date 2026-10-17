/* SPDX-License-Identifier: MIT */
/* The run-time helpers that the compiler calls for ARMv5 (the "ARM run-time ABI", AEABI): integer division, which the
 * ARM926 has no instruction for, and 64-bit shifts and multiplication. A hosted toolchain takes them from libgcc or
 * compiler-rt; Apple's clang ships neither for bare ARM, so Myna carries its own.
 *
 * Division by zero gives the quotient 0 and leaves the dividend as the remainder (the AEABI lets the platform choose;
 * nothing traps). The 64-bit division with its remainder in registers r2:r3 needs a few instructions of assembly:
 * aeabi_s.S, which calls myna_udivmod64 / myna_sdivmod64 below. */
#include <stdint.h>

/* n / d and n % d by shifting and subtracting, starting at the highest bit where d fits under n (CLZ is an ARMv5
 * instruction), so small quotients take few steps */
static uint32_t udivmod32(uint32_t n, uint32_t d, uint32_t *rem)
{
    if (d == 0 || n < d) {
        *rem = n;
        return 0;
    }
    int shift = __builtin_clz(d) - __builtin_clz(n);
    uint32_t q = 0;
    d <<= shift;
    for (; shift >= 0; shift--) {
        q <<= 1;
        if (n >= d) {
            n -= d;
            q |= 1;
        }
        d >>= 1;
    }
    *rem = n;
    return q;
}

static int clz64(uint64_t x)
{
    return (x >> 32) ? __builtin_clz((uint32_t)(x >> 32)) : 32 + __builtin_clz((uint32_t)x);
}

uint64_t myna_udivmod64(uint64_t n, uint64_t d, uint64_t *rem)
{
    if (d == 0 || n < d) {
        *rem = n;
        return 0;
    }
    int shift = clz64(d) - clz64(n);
    uint64_t q = 0;
    d <<= shift;
    for (; shift >= 0; shift--) {
        q <<= 1;
        if (n >= d) {
            n -= d;
            q |= 1;
        }
        d >>= 1;
    }
    *rem = n;
    return q;
}

/* C rounds the quotient toward zero; the remainder takes the sign of the dividend */
int64_t myna_sdivmod64(int64_t n, int64_t d, int64_t *rem)
{
    uint64_t un = n < 0 ? 0 - (uint64_t)n : (uint64_t)n;
    uint64_t ud = d < 0 ? 0 - (uint64_t)d : (uint64_t)d;
    uint64_t ur;
    uint64_t uq = myna_udivmod64(un, ud, &ur);
    *rem = n < 0 ? -(int64_t)ur : (int64_t)ur;
    return (n < 0) != (d < 0) ? -(int64_t)uq : (int64_t)uq;
}

uint32_t __aeabi_uidiv(uint32_t n, uint32_t d)
{
    uint32_t r;
    return udivmod32(n, d, &r);
}

/* returns the quotient in r0 and the remainder in r1: a 64-bit return value is passed in exactly that register pair */
uint64_t __aeabi_uidivmod(uint32_t n, uint32_t d)
{
    uint32_t r;
    uint32_t q = udivmod32(n, d, &r);
    return ((uint64_t)r << 32) | q;
}

static int32_t sdivmod32(int32_t n, int32_t d, int32_t *rem)
{
    uint32_t un = n < 0 ? 0u - (uint32_t)n : (uint32_t)n;
    uint32_t ud = d < 0 ? 0u - (uint32_t)d : (uint32_t)d;
    uint32_t ur;
    uint32_t uq = udivmod32(un, ud, &ur);
    *rem = n < 0 ? -(int32_t)ur : (int32_t)ur;
    return (n < 0) != (d < 0) ? -(int32_t)uq : (int32_t)uq;
}

int32_t __aeabi_idiv(int32_t n, int32_t d)
{
    int32_t r;
    return sdivmod32(n, d, &r);
}

uint64_t __aeabi_idivmod(int32_t n, int32_t d)
{
    int32_t r;
    int32_t q = sdivmod32(n, d, &r);
    return ((uint64_t)(uint32_t)r << 32) | (uint32_t)q;
}

/* population count: what __builtin_popcount becomes on a core without a count instruction (the NAND codes and
 * littlefs use it) */
int __popcountsi2(uint32_t x)
{
    x = x - ((x >> 1) & 0x55555555u);
    x = (x & 0x33333333u) + ((x >> 2) & 0x33333333u);
    return (int)((((x + (x >> 4)) & 0x0F0F0F0Fu) * 0x01010101u) >> 24);
}

/* 64-bit shifts and multiplication: the compiler expands these inline for ARM, so the bodies below do not call
 * themselves; they are here for code that asks for the helpers by name */
uint64_t __aeabi_llsl(uint64_t x, int n) { return x << n; }
uint64_t __aeabi_llsr(uint64_t x, int n) { return x >> n; }
int64_t __aeabi_lasr(int64_t x, int n) { return x >> n; }
uint64_t __aeabi_lmul(uint64_t a, uint64_t b) { return a * b; }
