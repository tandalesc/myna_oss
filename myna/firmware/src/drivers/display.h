/* SPDX-License-Identifier: MIT */
/* The display: a 240 x 320 RGB565 framebuffer in SDRAM, sent to the panel a changed rectangle at a time. */
#ifndef MYNA_DRIVERS_DISPLAY_H
#define MYNA_DRIVERS_DISPLAY_H

#include <stdint.h>

#include "gfx/gfx.h"
#include "kernel/ostimer.h"

#define DISPLAY_W 240
#define DISPLAY_H 320

struct task;

/* Start the display: framebuffer, controller, panel wake-up. Returns the framebuffer surface, or 0 if there is no
 * display controller. Needs the kernel's timers (the panel's wake-up time runs on one). */
const struct surface *display_init(void);
struct task *display_task(void);       /* the driver's own task (panel power sequence), for task_add() */

/* Mark a rectangle of the framebuffer as changed. */
void display_invalidate(const struct rect *r);
/* Send what changed to the panel. Returns at once; the updates run on the controller's interrupt. While the panel is
 * still waking up, the changes wait and go out with the first frame. */
void display_flush(void);

/* Dark (1): the panel's display off once the updates on their way have arrived, and nothing sent to it until light
 * (0) switches it on again; the framebuffer and the marks are kept. The caller draws what the panel shows meanwhile
 * (the simulator shows every update, dark or not: spec 05 5.1) and draws everything again after light. At start,
 * before the panel is on, dark keeps it from being switched on after its first frame. The flip's lid (ui/ui.c). */
void display_dark(int dark);

/* figures for reports */
struct display_stats {
    uint32_t updates;          /* updates sent to the panel */
    uint32_t pixels;           /* pixels in those updates */
    ktime_t first_frame;       /* kernel time of the first full-screen update, 0 before it */
};
const struct display_stats *display_stats(void);

#endif
