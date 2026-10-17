/* SPDX-License-Identifier: MIT */
/* The slide switch: open and closed as messages (MSG_SLIDE, a = 1 open, 0 closed) to one subscriber task. On the flip
 * (drivers/board.h) the same switch tells the lid open or closed. */
#ifndef MYNA_DRIVERS_SLIDE_H
#define MYNA_DRIVERS_SLIDE_H

struct task;

void slide_init(struct task *subscriber);
int slide_is_open(void);

#endif
