/* SPDX-License-Identifier: MIT */
/* The board-ID strap (drivers/board.h): GPIO bank 3 pins 1:0, inputs that resistors on the board tie high or low
 * (myna/spec/07-gpio-power.md, section 1.3). 00 is the P2 chin slider (and so is a board without the strap: those
 * pins read 0), 01 the P2 flip; 10 and 11 are not given out and count as the slider. Read once: a strap does not
 * change while the phone runs. */
#include <stdint.h>

#include "drivers/board.h"
#include "hw.h"
#include "lib/print.h"

#define BANK3_DATA_IN   (GPIO_BASE + 3u * 0x30u + 0x04u)
#define STRAP_PINS      3u

static enum board_model model = BOARD_SLIDER;

void board_init(void)
{
    /* pins 0 and 1 are inputs from reset (DIRECTION 00) and nothing makes them outputs: read the levels as they are */
    unsigned id = rd16(BANK3_DATA_IN) & STRAP_PINS;
    model = id == 1 ? BOARD_FLIP : BOARD_SLIDER;
    kprintf("board: id %u, %s\n", id, board_name());
}

enum board_model board_model(void)
{
    return model;
}

const char *board_name(void)
{
    return model == BOARD_FLIP ? "P2 flip" : "P2 slider";
}
