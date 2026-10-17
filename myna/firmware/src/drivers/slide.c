/* SPDX-License-Identifier: MIT */
/* The slide switch (drivers/slide.h): GPIO bank 0 pin 4, an input, 1 = closed and 0 = open on hardware
 * variant A (myna/spec/07-gpio-power.md, sections 1.2 and 1.3; variant B has the opposite levels).
 *
 * The pin interrupts on one edge, chosen by its polarity bit, so the driver catches both edges by always waiting for
 * the level the pin does not have: after each interrupt it reads the level and sets the polarity to the other one.
 * A switch that bounced back before the handler ran is caught by comparing the level with the state last reported.
 * On the flip (drivers/board.h) the same pin, with the same levels, is the lid's switch: closed = the lid is shut. */
#include <stdint.h>

#include "drivers/board.h"
#include "drivers/slide.h"
#include "hw.h"
#include "kernel/irq.h"
#include "kernel/task.h"
#include "lib/print.h"

#define BANK0          GPIO_BASE
#define GPIO_DATA_IN   (BANK0 + 0x04u)
#define GPIO_DIRECTION (BANK0 + 0x0Cu)
#define GPIO_IRQ_STAT  (BANK0 + 0x14u)    /* W1C */
#define GPIO_IRQ_EN    (BANK0 + 0x18u)
#define GPIO_IRQ_POL   (BANK0 + 0x20u)    /* 1 = interrupt when the pin becomes high */
#define IRQ_GPIO0      32

#define PIN            4u
#define BIT            (1u << PIN)
#define LEVEL_CLOSED   1u                 /* variant A */

static struct task *subscriber;
static volatile int open;

int slide_is_open(void)
{
    return open;
}

/* wait for the level the pin does not have now; returns the level */
static unsigned arm(void)
{
    unsigned level = (rd16(GPIO_DATA_IN) >> PIN) & 1u, again;
    for (;;) {
        uint16_t pol = rd16(GPIO_IRQ_POL);
        wr16(GPIO_IRQ_POL, (uint16_t)(level ? pol & ~BIT : pol | BIT));
        /* a change between the read and the write made no edge for the new polarity: look once more */
        again = (rd16(GPIO_DATA_IN) >> PIN) & 1u;
        if (again == level)
            return level;
        level = again;
    }
}

static void slide_irq(void *arg)
{
    (void)arg;
    wr16(GPIO_IRQ_STAT, BIT);             /* clears line 32 (only this pin is enabled in bank 0) */
    unsigned level = arm();
    int now_open = level != LEVEL_CLOSED;
    if (now_open != open) {
        open = now_open;
        task_post(subscriber, MSG_SLIDE, (uint16_t)now_open, 0);
    }
}

void slide_init(struct task *sub)
{
    subscriber = sub;
    wr16(GPIO_DIRECTION, (uint16_t)(rd16(GPIO_DIRECTION) & ~(3u << (2 * PIN))));    /* input */
    open = arm() != LEVEL_CLOSED;
    wr16(GPIO_IRQ_STAT, BIT);
    wr16(GPIO_IRQ_EN, (uint16_t)(rd16(GPIO_IRQ_EN) | BIT));
    irq_attach(IRQ_GPIO0, slide_irq, 0);
    kprintf("%s: %s\n", board_is_flip() ? "lid" : "slide", open ? "open" : "closed");
}
