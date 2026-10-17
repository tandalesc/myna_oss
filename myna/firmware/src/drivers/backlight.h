/* SPDX-License-Identifier: MIT */
/* Display backlight. */
#ifndef MYNA_DRIVERS_BACKLIGHT_H
#define MYNA_DRIVERS_BACKLIGHT_H

int backlight_on(void);        /* 0 = the light's driver chip is there */
/* Brightness 1 (dim) to 5 (full): the setting SET_BRIGHTNESS. Kept until the chip's commands are known; none sent. */
void backlight_set_level(int level);
int backlight_level(void);

#endif
