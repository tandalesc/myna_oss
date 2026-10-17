/* SPDX-License-Identifier: MIT */
/* The panel's command bus: DCS-style commands sent through the display controller's panel bus engine. */
#ifndef MYNA_DRIVERS_PANEL_H
#define MYNA_DRIVERS_PANEL_H

#include <stdint.h>

/* MIPI DCS command numbers that Myna uses (myna/spec/05-display.md, section 5.1) */
#define DCS_SLEEP_OUT      0x11
#define DCS_DISPLAY_OFF    0x28
#define DCS_DISPLAY_ON     0x29
#define DCS_COLUMN_WINDOW  0x2A
#define DCS_ROW_WINDOW     0x2B
#define DCS_ACCESS_CONTROL 0x36
#define DCS_PIXEL_FORMAT   0x3A
#define DCS_POWER_MODE     0x0A    /* read */

#define POWER_MODE_AWAKE   0x10
#define POWER_MODE_ON      0x04

void panel_command(uint8_t cmd, const uint8_t *params, unsigned n);   /* n <= 31 */
uint8_t panel_read(uint8_t cmd);                                      /* a one-byte register read */

#endif
