/* SPDX-License-Identifier: MIT */
/* The NAND data loops: eight words per LDM/STM between memory and the controller's data port (drivers/nand.c).
 *
 * The data port takes or gives the next bytes of the chip's stream at any address of its window (spec 10 2), and an
 * LDM or STM reaches the port as one word access per register in ascending order (spec 01 4): so the port is read and
 * written eight words at a time at a fixed address, and the ECC engine sees the bytes in stream order. */
    .syntax unified
    .arm
    .text

    .equ    NAND_DATA, 0x80000000

/* void nand_read_words(uint32_t *dst, uint32_t n): n a multiple of 8, dst word-aligned */
    .global nand_read_words
    .type   nand_read_words, %function
nand_read_words:
    push    {r4-r10}
    mov     r2, #NAND_DATA
1:  ldmia   r2, {r3-r10}
    stmia   r0!, {r3-r10}
    subs    r1, r1, #8
    bhi     1b
    pop     {r4-r10}
    bx      lr
    .size   nand_read_words, . - nand_read_words

/* void nand_write_words(const uint32_t *src, uint32_t n): n a multiple of 8, src word-aligned */
    .global nand_write_words
    .type   nand_write_words, %function
nand_write_words:
    push    {r4-r10}
    mov     r2, #NAND_DATA
1:  ldmia   r0!, {r3-r10}
    stmia   r2, {r3-r10}
    subs    r1, r1, #8
    bhi     1b
    pop     {r4-r10}
    bx      lr
    .size   nand_write_words, . - nand_write_words
