/* SPDX-License-Identifier: MIT */
/* crt0: the first instructions of Myna, the exception vectors, and the way into C.
 *
 * Entered at _start in ARM state with the MMU and caches off (myna/README.md, "CPU state at entry"). Nothing here trusts
 * the mode or the interrupt mask it was entered with: a boot loader on a real phone may leave them otherwise than the
 * simulator's launcher does. Everything is ARM code (not Thumb): the ARM926 runs both, and ARM keeps crt0 simple. */

#define MODE_FIQ 0x11
#define MODE_IRQ 0x12
#define MODE_SVC 0x13
#define MODE_ABT 0x17
#define MODE_UND 0x1B
#define NO_INT   0xC0           /* CPSR I and F: IRQ and FIQ masked */

    .syntax unified
    .arm

    .section .text.start, "ax"
    .global _start
_start:
    mrs     r4, cpsr                    /* the state we were handed: kept in r4 (no code below uses it) for main() to report */

    /* one stack per exception mode, all with interrupts masked; we finish in SVC mode, where main() runs */
    msr     cpsr_c, #(MODE_UND | NO_INT)
    ldr     sp, =__stack_und_top
    msr     cpsr_c, #(MODE_ABT | NO_INT)
    ldr     sp, =__stack_abt_top
    msr     cpsr_c, #(MODE_FIQ | NO_INT)
    ldr     sp, =__stack_fiq_top
    msr     cpsr_c, #(MODE_IRQ | NO_INT)
    ldr     sp, =__stack_irq_top
    msr     cpsr_c, #(MODE_SVC | NO_INT)
    ldr     sp, =__stack_svc_top

    /* exception vectors to address 0 (TCM): the control register's V bit is 0, so the CPU takes exceptions there.
       The table is position independent (each slot loads its target from a word 32 bytes on), so a copy works */
    ldr     r0, =__vectors_start
    ldr     r1, =__vectors_end
    mov     r2, #0
1:  ldr     r3, [r0], #4
    str     r3, [r2], #4
    cmp     r0, r1
    blo     1b

    /* .data: the launcher loads it where it runs (load address = run address); copy only if a later layout separates them */
    ldr     r0, =__data_load
    ldr     r1, =__data_start
    ldr     r2, =__data_end
    cmp     r0, r1
    beq     3f
2:  cmp     r1, r2
    ldrlo   r3, [r0], #4
    strlo   r3, [r1], #4
    blo     2b
3:
    /* .bss to zero: the launcher's memory starts zeroed, a boot loader's need not */
    ldr     r0, =__bss_start
    ldr     r1, =__bss_end
    mov     r2, #0
4:  cmp     r0, r1
    strlo   r2, [r0], #4
    blo     4b
    ldr     r0, =myna_entry_cpsr
    str     r4, [r0]

    bl      main

    /* main() does not return; if it ever does, sleep for good */
5:  mcr     p15, 0, r0, c7, c0, 4       /* ARM926 wait for interrupt */
    b       5b
    .ltorg

/* ---- exception vectors (copied to 0) ---- */
    .section .vectors, "ax"
    ldr     pc, .Lreset
    ldr     pc, .Lundef
    ldr     pc, .Lswi
    ldr     pc, .Lpabort
    ldr     pc, .Ldabort
    ldr     pc, .Lreserved
    ldr     pc, .Lirq
    ldr     pc, .Lfiq
.Lreset:    .word _start
.Lundef:    .word undef_entry
.Lswi:      .word swi_entry
.Lpabort:   .word pabort_entry
.Ldabort:   .word dabort_entry
.Lreserved: .word reserved_entry
.Lirq:      .word irq_entry
.Lfiq:      .word fiq_entry

/* ---- IRQ: the only exception that Myna expects. Save what the C procedure call standard lets a callee destroy, let
   irq_dispatch() (kernel/irq.c) service every pending line, and return to the interrupted instruction. Handlers run
   with IRQ masked and do not nest: they are short (clear the source, post a message) and the work happens in tasks.
   The frame is 6 words, so the IRQ stack stays 8-byte aligned as the procedure call standard wants. ---- */
    .text
irq_entry:
    sub     lr, lr, #4                  /* lr = the instruction to go back to */
    push    {r0-r3, r12, lr}
    bl      irq_dispatch
    ldm     sp!, {r0-r3, r12, pc}^      /* ^ with pc: CPSR = SPSR, back in the interrupted mode */

/* ---- every other exception is a fault: build a register frame on the exception mode's stack and hand it to
   myna_fault() (kernel/fault.c), which prints it and stops. Frame layout (struct fault_frame, words):
     0-12 r0-r12, 13 sp and 14 lr of the interrupted mode, 15 the exception's lr, 16 spsr, 17 kind ---- */
    .macro  fault name, kind
\name:
    sub     sp, sp, #(18 * 4)
    stmia   sp, {r0-r12}
    mov     r0, #\kind
    b       fault_common
    .endm

    fault   undef_entry, 1
    fault   swi_entry, 2
    fault   pabort_entry, 3
    fault   dabort_entry, 4
    fault   reserved_entry, 5
    fault   fiq_entry, 7

fault_common:
    str     r0, [sp, #(17 * 4)]
    str     lr, [sp, #(15 * 4)]
    mrs     r1, spsr
    str     r1, [sp, #(16 * 4)]
    /* the interrupted mode's banked sp and lr: switch to that mode for two instructions (user mode's registers are
       reached through system mode, which shares them and can switch back) */
    mrs     r2, cpsr
    and     r3, r1, #0x1F
    cmp     r3, #0x10
    moveq   r3, #0x1F
    orr     r3, r3, #NO_INT
    msr     cpsr_c, r3
    mov     r4, sp
    mov     r5, lr
    msr     cpsr_c, r2
    str     r4, [sp, #(13 * 4)]
    str     r5, [sp, #(14 * 4)]
    mov     r0, sp
    bl      myna_fault
6:  b       6b                          /* not reached: myna_fault() does not return */
