/* SPDX-License-Identifier: MIT */
/* Display backlight (drivers/backlight.h).
 *
 * The backlight and key lights hang on an illumination driver chip on the external I2C bus at 0x4A, which takes
 * one-byte commands (myna/spec/07-gpio-power.md section 3, 08 section 7). Which command sets the display's light is
 * not known (spec gap G11; question in myna/spec/QUESTIONS.md), and the simulator always shows the screen lit. Until
 * it is known, Myna only checks that the chip answers and sends it nothing: a guessed command could switch on the
 * wrong light, or a light at a current the hardware does not like. */
#include <stdint.h>

#include "drivers/backlight.h"
#include "drivers/i2c.h"
#include "lib/print.h"

#define ILLUMINATION 0x4A

int backlight_on(void)
{
    int r = i2c_write(I2C_EXTERNAL, ILLUMINATION, 0, 0);     /* address only: is the chip there? */
    kprintf("backlight: illumination driver %s; its commands are not known yet, nothing sent\n",
            r == I2C_OK ? "answers" : "does not answer");
    return r;
}

static int level = 4;

void backlight_set_level(int l)
{
    level = l;                 /* the command for it is not known (QUESTIONS.md Q4): nothing goes to the chip */
}

int backlight_level(void)
{
    return level;
}
