/* SPDX-License-Identifier: MIT */
/* Interrupt dispatch through the two PL190 interrupt controllers (myna/spec/03-interrupts.md).
 *
 * The controllers' vectored mode is left off: every slot stays disabled, so the priority logic never holds a line
 * back, and the dispatcher reads the two IRQ status words and calls the handler of each pending line, lowest number
 * first. Priorities between handlers do not matter while handlers only clear their source and post a message; the
 * order in which work is done is the tasks' business (kernel/task.c). */
#include <stddef.h>
#include <stdint.h>

#include "hw.h"
#include "kernel/irq.h"
#include "lib/print.h"

#define VIC_IRQSTATUS    0x000u
#define VIC_INTSELECT    0x00Cu
#define VIC_INTENABLE    0x010u
#define VIC_INTENCLEAR   0x014u
#define VIC_SOFTINTCLEAR 0x01Cu

static struct {
    irq_handler fn;
    void *arg;
    uint32_t count;
} lines[IRQ_LINES];

static uint32_t spurious;

static uint32_t vic(unsigned line)
{
    return line < 32 ? VIC0_BASE : VIC1_BASE;
}

void irq_init(void)
{
    for (uint32_t base = VIC0_BASE; base <= VIC1_BASE; base += VIC1_BASE - VIC0_BASE) {
        wr32(base + VIC_INTENCLEAR, 0xFFFFFFFFu);
        wr32(base + VIC_SOFTINTCLEAR, 0xFFFFFFFFu);
        wr32(base + VIC_INTSELECT, 0);        /* all IRQ: a line selected as FIQ would never be delivered */
    }
}

void irq_attach(unsigned line, irq_handler fn, void *arg)
{
    if (line >= IRQ_LINES)
        return;
    lines[line].fn = fn;
    lines[line].arg = arg;
    irq_line_enable(line);
}

void irq_line_enable(unsigned line)
{
    wr32(vic(line) + VIC_INTENABLE, 1u << (line & 31));
}

void irq_line_disable(unsigned line)
{
    wr32(vic(line) + VIC_INTENCLEAR, 1u << (line & 31));
}

uint32_t irq_count(unsigned line)
{
    return line < IRQ_LINES ? lines[line].count : 0;
}

/* service every line that is set in `pending` (lines base .. base + 31) */
static void service(uint32_t pending, unsigned base)
{
    while (pending) {
        unsigned bit = 31 - __builtin_clz(pending & -pending);     /* lowest set bit; ARMv5 has CLZ, not CTZ */
        unsigned line = base + bit;
        pending &= pending - 1;
        if (lines[line].fn) {
            lines[line].count++;
            lines[line].fn(lines[line].arg);
        } else {
            /* nobody asked for this line: switch it off so it cannot hold the CPU in interrupts */
            irq_line_disable(line);
            kprintf("irq: line %u had no handler, disabled\n", line);
        }
    }
}

/* called by crt0.S irq_entry */
void irq_dispatch(void)
{
    /* a handler may make another line pending (a display update done at once in the model, say): look again
       until both controllers are quiet, so the CPU does not leave and come straight back */
    for (int round = 0; round < 8; round++) {
        uint32_t s0 = rd32(VIC0_BASE + VIC_IRQSTATUS);
        uint32_t s1 = rd32(VIC1_BASE + VIC_IRQSTATUS);
        if (!(s0 | s1)) {
            if (round == 0)
                spurious++;
            return;
        }
        service(s0, 0);
        service(s1, 32);
    }
}
