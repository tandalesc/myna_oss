/* SPDX-License-Identifier: MIT */
/* Link channel 0 (modem/link.h). */
#include <stdint.h>

#include "cpu.h"
#include "drivers/dma.h"
#include "hw.h"
#include "kernel/irq.h"
#include "kernel/task.h"
#include "lib/mem.h"
#include "modem/link.h"

#define LINK_BASE           0xC0022000u
#define TX0                 (LINK_BASE + 0x000u)    /* transmit channel 0 */
#define RX0                 (LINK_BASE + 0x200u)    /* receive channel 0 */
#define CH_CONTROL          0x00u                   /* bit 0 enable, bit 1 DMA requests */
#define CH_LEVEL            0x08u
#define CH_IRQ_ENABLE       0x0Cu                   /* bit 3: data available (receive) */
#define CH_DATA             0x20u
#define CHANNEL_IRQ_ENABLE  (LINK_BASE + 0x500u)
#define RX_DATA_AVAILABLE   (1u << 3)

#define IRQ_LINK_RECEIVE    5
#define TX_DMA_CHANNEL      2       /* any channel serves any port (spec 13 3) */

#define RING 4096u                  /* both rings; a power of two */

static struct task *owner;
static uint8_t rx_ring[RING], tx_ring[RING];
static volatile uint32_t rx_head;   /* written by the interrupt handler */
static uint32_t rx_tail;            /* by the task */
static volatile uint8_t rx_posted, rx_stalled;
static volatile uint32_t tx_head, tx_tail, tx_inflight;
static struct link_stats stats;

const struct link_stats *link_stats(void)
{
    return &stats;
}

static void rx_irq(void *unused)
{
    (void)unused;
    stats.rx_irqs++;
    uint32_t head = rx_head;
    for (;;) {
        uint32_t level = rd32(RX0 + CH_LEVEL);
        if (!level)
            break;
        if (RING - (head - rx_tail) < level) {
            /* no room: leave the bytes in the FIFO, which holds the modem back, until the task has read */
            wr32(RX0 + CH_IRQ_ENABLE, 0);
            rx_stalled = 1;
            stats.rx_stalls++;
            break;
        }
        stats.rx_bytes += level;
        for (; level >= 4; level -= 4) {
            uint32_t w = rd32(RX0 + CH_DATA);
            rx_ring[head++ & (RING - 1)] = (uint8_t)w;
            rx_ring[head++ & (RING - 1)] = (uint8_t)(w >> 8);
            rx_ring[head++ & (RING - 1)] = (uint8_t)(w >> 16);
            rx_ring[head++ & (RING - 1)] = (uint8_t)(w >> 24);
        }
        for (; level; level--)
            rx_ring[head++ & (RING - 1)] = *(volatile uint8_t *)(RX0 + CH_DATA);
    }
    rx_head = head;
    if (!rx_posted && head != rx_tail) {
        rx_posted = 1;
        task_post(owner, MSG_LINK_RX, 0, 0);
    }
}

unsigned link_read(uint8_t *out, unsigned max)
{
    uint32_t head = rx_head, n = head - rx_tail;
    if (n > max)
        n = max;
    for (uint32_t i = 0; i < n; i++)
        out[i] = rx_ring[(rx_tail + i) & (RING - 1)];
    rx_tail += n;
    uint32_t psr = cpu_irq_save();
    if (rx_head == rx_tail)
        rx_posted = 0;             /* the next byte posts again */
    if (rx_stalled && RING - (rx_head - rx_tail) >= 64) {
        rx_stalled = 0;
        wr32(RX0 + CH_IRQ_ENABLE, RX_DATA_AVAILABLE);
    }
    cpu_irq_restore(psr);
    return n;
}

static void tx_kick(void);

static void tx_done(void *unused)
{
    (void)unused;
    tx_tail += tx_inflight;
    tx_inflight = 0;
    tx_kick();
}

/* start the next stretch of the ring, if any (IRQ masked, or from the DMA interrupt) */
static void tx_kick(void)
{
    if (tx_inflight)
        return;
    uint32_t n = tx_head - tx_tail, at = tx_tail & (RING - 1);
    if (!n)
        return;
    if (n > RING - at)
        n = RING - at;
    if (n > DMA_MAX_ITEM)
        n = DMA_MAX_ITEM;
    tx_inflight = n;
    stats.tx_dmas++;
    dma_start(TX_DMA_CHANNEL, DMA_MEM_TO_PERIPH, (uint32_t)&tx_ring[at], TX0 + CH_DATA, n, tx_done, 0);
}

unsigned link_write(const void *data, unsigned n)
{
    const uint8_t *p = data;
    uint32_t psr = cpu_irq_save();
    uint32_t space = RING - (tx_head - tx_tail);
    if (n > space) {
        stats.tx_dropped += n - space;
        n = space;
    }
    uint32_t head = tx_head;
    for (unsigned i = 0; i < n; i++)
        tx_ring[(head + i) & (RING - 1)] = p[i];
    tx_head = head + n;
    stats.tx_bytes += n;
    tx_kick();
    cpu_irq_restore(psr);
    return n;
}

void link_init(struct task *t)
{
    owner = t;
    wr32(TX0 + CH_CONTROL, 3);                 /* enabled, DMA requests on */
    wr32(RX0 + CH_CONTROL, 1);                 /* enabled; bytes enter only from now on */
    wr32(RX0 + CH_IRQ_ENABLE, RX_DATA_AVAILABLE);
    wr32(CHANNEL_IRQ_ENABLE, 1u << (8 + 0));   /* receive channel 0 may interrupt */
    irq_attach(IRQ_LINK_RECEIVE, rx_irq, 0);
}
