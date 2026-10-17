/* SPDX-License-Identifier: MIT */
/* The row loops under all of Myna's drawing: fill a row of RGB565 pixels (one colour or two alternating), copy a row
 * of pixels.
 *
 * The emulated ARM926 is charged per instruction, so the loops move 16 pixels (32 bytes) per STM: eight registers
 * hold the colour twice each, or a block of the source. A leading odd pixel brings the destination to a word
 * boundary; the tail (0-15 pixels) is done by testing the bits of the remaining count, without a loop.
 * C callers: gfx/gfx.h. */
    .syntax unified
    .arm
    .text

/* void gfx_fill16(uint16_t *dst, uint32_t count, uint32_t colour) */
    .global gfx_fill16
    .type   gfx_fill16, %function
gfx_fill16:
    cmp     r1, #0
    bxeq    lr
    mov     r2, r2, lsl #16
    orr     r2, r2, r2, lsr #16         /* the pixel in both halves of the word */
    tst     r0, #2
    beq     1f
    strh    r2, [r0], #2                /* one pixel to reach a word boundary */
    subs    r1, r1, #1
    bxeq    lr
1:
.Lfill_words:                           /* r0 word aligned, r1 > 0, r2 the word to store */
    push    {r4-r9}
    mov     r3, r2
    mov     r4, r2
    mov     r5, r2
    mov     r6, r2
    mov     r7, r2
    mov     r8, r2
    mov     r9, r2
    subs    r1, r1, #16
    blt     3f
2:  stmia   r0!, {r2-r9}                /* 16 pixels */
    subs    r1, r1, #16
    bge     2b
3:  /* r1 = remaining - 16: its low four bits are those of the remaining count */
    tst     r1, #8
    stmiane r0!, {r2-r5}
    tst     r1, #4
    stmiane r0!, {r2-r3}
    tst     r1, #2
    strne   r2, [r0], #4
    tst     r1, #1
    strhne  r2, [r0], #2
    pop     {r4-r9}
    bx      lr
    .size   gfx_fill16, . - gfx_fill16

/* void gfx_fill32(uint16_t *dst, uint32_t count, uint32_t pair): a fill with two alternating pixels, for dithering.
 * The low half of `pair` goes to word-aligned pixels (even x in a surface whose rows start on a word), the high half
 * to the others. */
    .global gfx_fill32
    .type   gfx_fill32, %function
gfx_fill32:
    cmp     r1, #0
    bxeq    lr
    tst     r0, #2
    beq     .Lfill_words
    mov     r3, r2, lsr #16
    strh    r3, [r0], #2                /* the odd pixel first: the high half */
    subs    r1, r1, #1
    bxeq    lr
    b       .Lfill_words
    .size   gfx_fill32, . - gfx_fill32

/* void gfx_copy16(uint16_t *dst, const uint16_t *src, uint32_t count): no overlap */
    .global gfx_copy16
    .type   gfx_copy16, %function
gfx_copy16:
    cmp     r2, #0
    bxeq    lr
    eor     r3, r0, r1
    tst     r3, #2
    bne     8f                          /* one is word aligned, the other not: words would need shifting */
    tst     r0, #2
    beq     1f
    ldrh    r3, [r1], #2
    strh    r3, [r0], #2
    subs    r2, r2, #1
    bxeq    lr
1:  push    {r4-r11}
    subs    r2, r2, #16
    blt     3f
2:  ldmia   r1!, {r3-r10}               /* 16 pixels */
    stmia   r0!, {r3-r10}
    subs    r2, r2, #16
    bge     2b
3:  tst     r2, #8
    ldmiane r1!, {r3-r6}
    stmiane r0!, {r3-r6}
    tst     r2, #4
    ldmiane r1!, {r3-r4}
    stmiane r0!, {r3-r4}
    tst     r2, #2
    ldrne   r3, [r1], #4
    strne   r3, [r0], #4
    tst     r2, #1
    ldrhne  r3, [r1], #2
    strhne  r3, [r0], #2
    pop     {r4-r11}
    bx      lr

8:  /* different alignment: two halfwords per step (rare: surfaces and rectangles are mostly even-aligned) */
    subs    r2, r2, #2
    blt     9f
7:  ldrh    r3, [r1], #2
    ldrh    r12, [r1], #2
    strh    r3, [r0], #2
    strh    r12, [r0], #2
    subs    r2, r2, #2
    bge     7b
9:  tst     r2, #1
    ldrhne  r3, [r1]
    strhne  r3, [r0]
    bx      lr
    .size   gfx_copy16, . - gfx_copy16
