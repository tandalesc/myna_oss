/* SPDX-License-Identifier: MIT */
/* The DMA controller (myna/spec/13-dma.md): single-item transfers between memory and a peripheral port, with a
 * completion callback. Any channel serves any port; each user owns the channel numbers it passes. */
#ifndef MYNA_DRIVERS_DMA_H
#define MYNA_DRIVERS_DMA_H

#include <stdint.h>

#define DMA_MAX_ITEM 4095u     /* bytes per item: the count field has 12 bits */

enum dma_type { DMA_MEM_TO_MEM = 0, DMA_MEM_TO_PERIPH = 1, DMA_PERIPH_TO_MEM = 2 };

/* Called from the interrupt handler (IRQ mode) when a channel's transfer has ended: only post messages there. */
typedef void (*dma_done_fn)(void *arg);

/* Start a transfer of `bytes` (1 - DMA_MAX_ITEM) on channel `ch` (0-63). Addresses are physical (the MMU is off).
 * The channel must be idle. */
void dma_start(unsigned ch, enum dma_type type, uint32_t src, uint32_t dst, unsigned bytes, dma_done_fn done,
               void *arg);
int dma_busy(unsigned ch);
void dma_stop(unsigned ch);

#endif
