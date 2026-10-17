/* SPDX-License-Identifier: MIT */
/* DMA controller (drivers/dma.h), myna/spec/13-dma.md. Line 2 is high while any channel's "finished" bit is set;
 * the handler clears each bit and calls that channel's callback. */
#include <stdint.h>

#include "drivers/dma.h"
#include "hw.h"
#include "kernel/irq.h"

#define DMA_BASE         0xC0020000u
#define TC_STATUS_LOW    0x008u
#define TC_STATUS_HIGH   0x00Cu
#define TC_CLEAR_LOW     0x010u
#define TC_CLEAR_HIGH    0x014u
#define CHANNEL_CONFIG   0x100u    /* + 4 n: bit 0 enable / start, bits 2:1 type */
#define CHANNEL_STATUS   0x200u    /* + 4 n: bit 0 busy */
#define CONTROL          0x400u    /* + 16 n: count (bits 11:0), ... */
#define SOURCE           0x404u
#define DESTINATION      0x408u
#define NEXT             0x40Cu

#define CTRL_INCREMENT   (1u << 26)

#define IRQ_DMA 2

static struct {
    dma_done_fn fn;
    void *arg;
} chans[64];
static int attached;

static void dma_irq(void *unused)
{
    (void)unused;
    for (unsigned half = 0; half < 2; half++) {
        uint32_t s = rd32(DMA_BASE + (half ? TC_STATUS_HIGH : TC_STATUS_LOW));
        if (!s)
            continue;
        wr32(DMA_BASE + (half ? TC_CLEAR_HIGH : TC_CLEAR_LOW), s);
        while (s) {
            unsigned bit = 31 - __builtin_clz(s & -s);
            s &= s - 1;
            unsigned ch = half * 32 + bit;
            if (chans[ch].fn)
                chans[ch].fn(chans[ch].arg);
        }
    }
}

void dma_start(unsigned ch, enum dma_type type, uint32_t src, uint32_t dst, unsigned bytes, dma_done_fn done,
               void *arg)
{
    if (!attached) {
        irq_attach(IRQ_DMA, dma_irq, 0);
        attached = 1;
    }
    chans[ch].fn = done;
    chans[ch].arg = arg;
    uint32_t c = DMA_BASE + 16u * ch;
    wr32(c + CONTROL, (bytes & 0xFFFu) | CTRL_INCREMENT);
    wr32(c + SOURCE, src);
    wr32(c + DESTINATION, dst);
    wr32(c + NEXT, 0);
    /* the 0 -> 1 change of bit 0 starts it; in the model a transfer can run during this very write */
    wr32(DMA_BASE + CHANNEL_CONFIG + 4u * ch, 1u | (uint32_t)type << 1);
}

int dma_busy(unsigned ch)
{
    return rd32(DMA_BASE + CHANNEL_STATUS + 4u * ch) & 1u;
}

void dma_stop(unsigned ch)
{
    wr32(DMA_BASE + CHANNEL_CONFIG + 4u * ch, 0);
}
