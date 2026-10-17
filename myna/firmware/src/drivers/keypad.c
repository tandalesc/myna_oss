/* SPDX-License-Identifier: MIT */
/* Keypad (drivers/keypad.h): the 5 x 6 matrix and six direct keys at 0xC0015000 (myna/spec/06-keypad.md).
 *
 * The controller tells only "some key is down" (line 30) and "no key is down" (line 31), so the driver works in two
 * states. Idle: all rows driven, only line 30 enabled; nothing runs until a key goes down. Active: line 31 enabled
 * instead, and the matrix is scanned every 25 ms (a timer) to see further presses and releases, until line 31 says
 * every key is up. Each interrupt handler switches the enable bits (which is what clears its line) and leaves the
 * scan to the keypad task.
 *
 * The digit keys, * and # are on the slide's hidden part. The matrix reports them whatever the slide does (spec 06 4.1:
 * it does not depend on the slide), so while the slide is closed their presses are not passed on; a key that was
 * reported down is still reported up. On the flip (drivers/board.h) the same switch is the lid, and a closed lid
 * covers every key of the face: only the keys on the phone's sides are passed on then. */
#include <stdint.h>

#include "drivers/board.h"
#include "drivers/keypad.h"
#include "drivers/slide.h"
#include "hw.h"
#include "kernel/irq.h"
#include "kernel/task.h"
#include "kernel/timer.h"

#define KP_COLUMNS    (KEYPAD_BASE + 0x04u)   /* column inputs, active low, bits 5:0 */
#define KP_ROWS       (KEYPAD_BASE + 0x08u)   /* row outputs, active low, bits 4:0 */
#define KP_IRQ_ENABLE (KEYPAD_BASE + 0x18u)   /* bit 0 key down (line 30), bit 1 all up (line 31) */

#define EN_DOWN 1u
#define EN_UP   2u
#define SCAN_MS 25

static const char *const names[KEY_COUNT] = {
    "3", "6", "1", "camera_half", "operator", "game_b",
    "call", "game_a", "unmapped_8", "clear", "8", "camera_mode",
    "2", "0", "soft_left", "5", "camera_review", "9",
    "activity", "4", "7", "camera_full", "hash", "star",
    "down", "left", "up", "select", "right", "soft_right",
    "end", "media", "camera_onoff", "vol_up", "vol_down", "media2",
};

static void keypad_handle(struct task *self, const struct msg *m);

static struct task task = { .name = "keypad", .handle = keypad_handle };
static struct task *subscriber;
static struct timer scan_timer;
static uint64_t reported;          /* bit per key index: the keys reported down to the subscriber */

/* the keys under the slide: 0-9, * and # */
#define SLIDE_KEYS ((1ull << KEY_0) | (1ull << KEY_1) | (1ull << KEY_2) | (1ull << KEY_3) | (1ull << KEY_4) | \
                    (1ull << KEY_5) | (1ull << KEY_6) | (1ull << KEY_7) | (1ull << KEY_8) | (1ull << KEY_9) | \
                    (1ull << KEY_STAR) | (1ull << KEY_HASH))
/* the flip: the keys on the sides, which a closed lid does not cover */
#define SIDE_KEYS ((1ull << KEY_VOL_UP) | (1ull << KEY_VOL_DOWN) | (1ull << KEY_CAMERA_HALF) | \
                   (1ull << KEY_CAMERA_FULL) | (1ull << KEY_CAMERA_MODE) | (1ull << KEY_CAMERA_REVIEW) | \
                   (1ull << KEY_CAMERA_ONOFF) | (1ull << KEY_MEDIA) | (1ull << KEY_MEDIA2))
static int scanning;

const char *key_name(unsigned key)
{
    return key < KEY_COUNT ? names[key] : "?";
}

struct task *keypad_task(void)
{
    return &task;
}

static uint32_t columns_low(void)
{
    return ~(uint32_t)rd16(KP_COLUMNS) & 0x3Fu;
}

/* one pass over the matrix: a bit per key index */
static uint64_t scan(void)
{
    wr16(KP_ROWS, 0x1F);                       /* no row driven: what is low now is a direct key */
    uint32_t direct = columns_low();
    uint64_t keys = (uint64_t)direct << 30;
    for (unsigned r = 0; r < 5; r++) {
        wr16(KP_ROWS, (uint16_t)(0x1Fu & ~(1u << r)));
        uint32_t cols = columns_low() & ~direct;   /* a direct key pulls its column on every row: not a matrix key */
        keys |= (uint64_t)cols << (r * 6);
    }
    wr16(KP_ROWS, 0);                          /* all rows driven again, so that any key raises line 30 */
    return keys;
}

static void key_down_irq(void *arg)
{
    (void)arg;
    wr16(KP_IRQ_ENABLE, EN_UP);                /* line 30 off (it stays high while a key is down), wait for all up */
    task_post(&task, MSG_KEYPAD_SCAN, 0, 0);
}

static void keys_up_irq(void *arg)
{
    (void)arg;
    wr16(KP_IRQ_ENABLE, EN_DOWN);
    task_post(&task, MSG_KEYPAD_SCAN, 0, 0);   /* the last scan reports the releases */
}

static void keypad_handle(struct task *self, const struct msg *m)
{
    (void)self;
    if (m->type != MSG_KEYPAD_SCAN && m->type != MSG_TIMER)
        return;
    uint64_t now = scan();
    uint64_t pass = slide_is_open() ? now : board_is_flip() ? now & SIDE_KEYS : now & ~SLIDE_KEYS;
    uint64_t changed = (pass | (now & reported)) ^ reported;
    for (unsigned k = 0; changed; k++, changed >>= 1)
        if (changed & 1)
            task_post(subscriber, (now >> k) & 1 ? MSG_KEY_DOWN : MSG_KEY_UP, (uint16_t)k, 0);
    reported = pass | (now & reported);

    /* scan again in 25 ms while anything is down; stop when nothing is (line 31 may come before or after) */
    if (now && !scanning) {
        timer_start(&scan_timer, KTIME_MS(SCAN_MS), KTIME_MS(SCAN_MS));
        scanning = 1;
    } else if (!now && scanning) {
        timer_stop(&scan_timer);
        scanning = 0;
    }
}

void keypad_init(struct task *sub)
{
    subscriber = sub;
    timer_init(&scan_timer, &task, 0);
    wr16(KP_ROWS, 0);
    irq_attach(IRQ_KEY_DOWN, key_down_irq, 0);
    irq_attach(IRQ_KEYS_UP, keys_up_irq, 0);
    wr16(KP_IRQ_ENABLE, EN_DOWN);
}
