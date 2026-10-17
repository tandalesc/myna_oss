/* SPDX-License-Identifier: MIT */
/* 64-bit division with remainder, as the AEABI wants it: numerator r0:r1, denominator r2:r3; quotient back in r0:r1 and
 * remainder in r2:r3. C cannot return four registers, so these wrappers call the C routines of aeabi.c with a pointer
 * to a slot on the stack and load the remainder from it. */
    .syntax unified
    .arm
    .text

    .macro  divmod64 name, impl
    .global \name
    .type   \name, %function
\name:
    push    {r4, lr}                /* 8 bytes: the stack stays 8-byte aligned, as the procedure call standard requires */
    sub     sp, sp, #16             /* [sp] = the fifth argument (the pointer), [sp + 8] = the remainder */
    add     r4, sp, #8
    str     r4, [sp]
    bl      \impl
    ldrd    r2, r3, [sp, #8]
    add     sp, sp, #16
    pop     {r4, pc}
    .size   \name, . - \name
    .endm

    divmod64 __aeabi_uldivmod, myna_udivmod64
    divmod64 __aeabi_ldivmod, myna_sdivmod64
