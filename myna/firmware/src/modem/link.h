/* SPDX-License-Identifier: MIT */
/* Link channel 0 to the modem (myna/spec/11-modem-link.md, 14-modem-at.md section 2): one byte stream each way.
 *
 * Receive: interrupt-driven (line 5). The handler empties the 64-byte FIFO into a 4 KB ring and posts MSG_LINK_RX to
 * the owner task once per batch; when the ring is nearly full it stops taking bytes (the FIFO then holds the modem
 * back: the link's only flow control) until the task has read. Transmit: a 4 KB ring sent by DMA, which waits for
 * FIFO space by itself; one transfer per contiguous stretch of the ring, the next one started from the completion
 * interrupt. Nothing polls. */
#ifndef MYNA_MODEM_LINK_H
#define MYNA_MODEM_LINK_H

#include <stdint.h>

struct task;

void link_init(struct task *owner);

/* Queue bytes for the modem. Returns the bytes taken (all of them unless the ring is full). */
unsigned link_write(const void *data, unsigned n);

/* Take received bytes (up to max). Called by the owner task after MSG_LINK_RX until it returns 0. */
unsigned link_read(uint8_t *out, unsigned max);

struct link_stats {
    uint32_t rx_bytes, tx_bytes;
    uint32_t rx_irqs, tx_dmas;
    uint32_t rx_stalls;        /* times the ring was too full to empty the FIFO */
    uint32_t tx_dropped;       /* bytes refused by a full transmit ring */
};
const struct link_stats *link_stats(void);

#endif
