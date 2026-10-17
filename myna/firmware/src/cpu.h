/* SPDX-License-Identifier: MIT */
/* The ARM926EJ-S as Myna sees it: the system control coprocessor (CP15) and the program status register. */
#ifndef MYNA_CPU_H
#define MYNA_CPU_H

#include <stdint.h>

/* CP15 c0: main ID (implementer, variant, architecture, part number, revision). 0x41069265 = ARM, ARM926EJ-S r0p5 */
static inline uint32_t cpu_id(void)
{
    uint32_t v;
    __asm__ volatile("mrc p15, 0, %0, c0, c0, 0" : "=r"(v));
    return v;
}

/* CP15 c0, opcode2 1: cache type (sizes and kinds of the instruction and data caches) */
static inline uint32_t cpu_cache_type(void)
{
    uint32_t v;
    __asm__ volatile("mrc p15, 0, %0, c0, c0, 1" : "=r"(v));
    return v;
}

/* CP15 c1: control register. Bit 0 MMU, bit 2 data cache, bit 12 instruction cache, bit 13 high vectors (0xFFFF0000) */
#define CTRL_MMU     (1u << 0)
#define CTRL_DCACHE  (1u << 2)
#define CTRL_ICACHE  (1u << 12)
#define CTRL_HIGHVEC (1u << 13)

static inline uint32_t cpu_control(void)
{
    uint32_t v;
    __asm__ volatile("mrc p15, 0, %0, c1, c0, 0" : "=r"(v));
    return v;
}

/* CP15 c5 / c6: why and where the last data abort happened */
static inline uint32_t cpu_fault_status(void)
{
    uint32_t v;
    __asm__ volatile("mrc p15, 0, %0, c5, c0, 0" : "=r"(v));
    return v;
}

static inline uint32_t cpu_fault_address(void)
{
    uint32_t v;
    __asm__ volatile("mrc p15, 0, %0, c6, c0, 0" : "=r"(v));
    return v;
}

#define PSR_MODE_MASK 0x1Fu
#define PSR_FIQ_MASKED (1u << 6)
#define PSR_IRQ_MASKED (1u << 7)
#define PSR_THUMB      (1u << 5)

static inline uint32_t cpu_cpsr(void)
{
    uint32_t v;
    __asm__ volatile("mrs %0, cpsr" : "=r"(v));
    return v;
}

/* IRQ masking. One CPU and no preemption between tasks: masking IRQ is the whole of Myna's locking. FIQ is never used
 * (the platform does not deliver it), so only the I bit is touched. Each returns or takes the whole CPSR so that a
 * nested save/restore pair puts back exactly what it found. */
static inline uint32_t cpu_irq_save(void)
{
    uint32_t old, masked;
    __asm__ volatile("mrs %0, cpsr\n\t"
                     "orr %1, %0, #0x80\n\t"
                     "msr cpsr_c, %1"
                     : "=r"(old), "=r"(masked)
                     :
                     : "memory");
    return old;
}

static inline void cpu_irq_restore(uint32_t old)
{
    __asm__ volatile("msr cpsr_c, %0" : : "r"(old) : "memory");
}

static inline void cpu_irq_enable(void)
{
    uint32_t v;
    __asm__ volatile("mrs %0, cpsr\n\t"
                     "bic %0, %0, #0x80\n\t"
                     "msr cpsr_c, %0"
                     : "=r"(v)
                     :
                     : "memory");
}

/* Wait for interrupt: the ARM926 form (CP15 c7, c0, 4; ARMv5 has no WFI instruction). The core stops until an interrupt
 * line is raised, even a masked one, which costs the simulator nothing: it skips the emulated time to the next event.
 * Myna idles only this way, never by polling. With IRQ masked the core wakes without taking the interrupt and goes on
 * at the next instruction: the kernel's idle relies on that to check for work and sleep without a lost wake-up. */
static inline void cpu_wait_for_interrupt(void)
{
    __asm__ volatile("mcr p15, 0, %0, c7, c0, 4" : : "r"(0) : "memory");
}

#endif
