/* SPDX-License-Identifier: MIT */
/* Interrupt lines: one handler per line of the two interrupt controllers (myna/spec/03-interrupts.md). */
#ifndef MYNA_KERNEL_IRQ_H
#define MYNA_KERNEL_IRQ_H

#include <stdint.h>

#define IRQ_LINES 64

/* line numbers that Myna uses */
#define IRQ_XGAM_UPDATE  18     /* display refresh controller: update done */
#define IRQ_OSTIMER      28     /* OS timer event 0 */
#define IRQ_KEY_DOWN     30
#define IRQ_KEYS_UP      31

/* A handler runs in IRQ mode with IRQ masked. It must remove the cause of its line before it returns: lines are
 * levels, and a line still high is taken again at once on one CPU engine and 200 us later on the other (spec 00 5.4). */
typedef void (*irq_handler)(void *arg);

void irq_init(void);
void irq_attach(unsigned line, irq_handler fn, void *arg);   /* and enable the line */
void irq_line_enable(unsigned line);
void irq_line_disable(unsigned line);
uint32_t irq_count(unsigned line);                           /* interrupts taken on a line since start */

#endif
