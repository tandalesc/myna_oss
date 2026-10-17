/* SPDX-License-Identifier: MIT */
/* Fault report: an exception that Myna does not handle (anything but IRQ) prints the whole register state on the
 * debug console and stops the CPU. There is no recovery: a fault is a bug, and the report is what finds it. */
#include <stdint.h>

#include "cpu.h"
#include "lib/print.h"

/* built by crt0.S (fault_common) on the stack of the exception mode */
struct fault_frame {
    uint32_t r[13];
    uint32_t sp, lr;           /* banked registers of the interrupted mode */
    uint32_t exc_lr;           /* lr of the exception mode: the return address the core computed */
    uint32_t spsr;             /* CPSR of the interrupted code */
    uint32_t kind;             /* vector number */
};

static const char *const kinds[] = {
    "reset", "undefined instruction", "software interrupt", "prefetch abort", "data abort", "reserved vector",
    "interrupt (IRQ)", "fast interrupt (FIQ)",
};

static const char *mode_name(uint32_t psr)
{
    switch (psr & PSR_MODE_MASK) {
    case 0x10: return "usr";
    case 0x11: return "fiq";
    case 0x12: return "irq";
    case 0x13: return "svc";
    case 0x17: return "abt";
    case 0x1B: return "und";
    case 0x1F: return "sys";
    default:   return "???";
    }
}

/* the address of the instruction that caused the exception, from the return address the core left in lr
 * (ARM926EJ-S TRM / ARM ARM: the offset depends on the exception and, for the undefined one, on the state) */
static uint32_t fault_pc(const struct fault_frame *f)
{
    int thumb = (f->spsr & PSR_THUMB) != 0;
    switch (f->kind) {
    case 1: return f->exc_lr - (thumb ? 2 : 4);
    case 2: return f->exc_lr - (thumb ? 2 : 4);
    case 4: return f->exc_lr - 8;
    default: return f->exc_lr - 4;
    }
}

__attribute__((noreturn)) void myna_fault(const struct fault_frame *f)
{
    uint32_t pc = fault_pc(f);
    kprintf("\n*** Myna fault: %s at pc %08x (from %s mode)\n", f->kind < 8 ? kinds[f->kind] : "exception", pc,
            mode_name(f->spsr));
    for (int i = 0; i < 13; i += 4) {
        for (int j = i; j < i + 4 && j < 13; j++)
            kprintf("%sr%d%s %08x", j == i ? "    " : "  ", j, j < 10 ? " " : "", f->r[j]);
        kprintf("\n");
    }
    kprintf("    sp  %08x  lr  %08x  pc  %08x  psr %08x (%s%s%s)\n", f->sp, f->lr, pc, f->spsr, mode_name(f->spsr),
            f->spsr & PSR_IRQ_MASKED ? ", irq masked" : "", f->spsr & PSR_THUMB ? ", thumb" : "");
    if (f->kind == 4)
        kprintf("    fault status %08x, fault address %08x\n", cpu_fault_status(), cpu_fault_address());
    if (f->kind == 1 && !(f->spsr & PSR_THUMB))
        kprintf("    instruction %08x\n", *(const uint32_t *)pc);
    kprintf("*** stopped\n");
    for (;;)
        cpu_wait_for_interrupt();       /* IRQ stays masked in the exception mode: this never resumes */
}
