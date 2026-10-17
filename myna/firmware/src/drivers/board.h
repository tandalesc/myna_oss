/* SPDX-License-Identifier: MIT */
/* The board: which phone this firmware runs in, read once at start from the board-ID strap (myna/spec/07-gpio-power.md,
 * section 1.3: GPIO bank 3, pins 1:0, tied high or low by resistors on the board). One firmware for every Myna board. */
#ifndef MYNA_DRIVERS_BOARD_H
#define MYNA_DRIVERS_BOARD_H

enum board_model {
    BOARD_SLIDER = 0,          /* P2 chin slider: the switch is the slide; the number keys hide under the face */
    BOARD_FLIP = 1,            /* P2 flip: the switch is the lid; closed, the display is dark and only side keys reach */
};

void board_init(void);         /* read the strap: before the drivers that depend on it (slide, keypad) */
enum board_model board_model(void);
const char *board_name(void);

static inline int board_is_flip(void)
{
    return board_model() == BOARD_FLIP;
}

#endif
