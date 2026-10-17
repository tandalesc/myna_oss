/* SPDX-License-Identifier: MIT */
/* Keypad: key presses and releases as messages (MSG_KEY_DOWN / MSG_KEY_UP, a = key index) to one subscriber task. */
#ifndef MYNA_DRIVERS_KEYPAD_H
#define MYNA_DRIVERS_KEYPAD_H

#include <stdint.h>

struct task;

/* key index = row x 6 + column for the matrix (0-29), 30 + column for the six direct keys (myna/spec/06-keypad.md) */
#define KEY_COUNT 36

enum key {
    KEY_3 = 0, KEY_6 = 1, KEY_1 = 2, KEY_CAMERA_HALF = 3, KEY_OPERATOR = 4, KEY_GAME_B = 5,
    KEY_CALL = 6, KEY_GAME_A = 7, KEY_CLEAR = 9, KEY_8 = 10, KEY_CAMERA_MODE = 11,
    KEY_2 = 12, KEY_0 = 13, KEY_SOFT_LEFT = 14, KEY_5 = 15, KEY_CAMERA_REVIEW = 16, KEY_9 = 17,
    KEY_ACTIVITY = 18, KEY_4 = 19, KEY_7 = 20, KEY_CAMERA_FULL = 21, KEY_HASH = 22, KEY_STAR = 23,
    KEY_DOWN = 24, KEY_LEFT = 25, KEY_UP = 26, KEY_SELECT = 27, KEY_RIGHT = 28, KEY_SOFT_RIGHT = 29,
    KEY_END = 30, KEY_MEDIA = 31, KEY_CAMERA_ONOFF = 32, KEY_VOL_UP = 33, KEY_VOL_DOWN = 34, KEY_MEDIA2 = 35,
};

void keypad_init(struct task *subscriber);
struct task *keypad_task(void);                /* the driver's own task, for task_add() */

/* the key's name: the viewer's input name (spec 06 4.1, variant A), so a log and a key script use the same words */
const char *key_name(unsigned key);

#endif
