/* SPDX-License-Identifier: MIT */
/* Panel command bus (drivers/panel.h), through the display controller's panel bus engine (myna/spec/05-display.md,
 * section 5).
 *
 * The engine sends the bytes that end its memory at +0x10FF, a count given in +0x100C bits 31:16, each byte marked
 * as command or parameter by a bit of +0x111C (bit 31 for the last byte, downwards). On a real phone the engine also
 * needs a small program at the start of its memory, whose instruction set is not known (spec 90, G10): the simulator
 * does not run it, so Myna loads none. That is the first thing to solve before this driver can run on hardware. */
#include <stdint.h>

#include "drivers/panel.h"
#include "hw.h"

#define ENGINE_COUNT  (XGAM_BASE + 0x100Cu)   /* bits 31:16: bytes to send */
#define ENGINE_END    (XGAM_BASE + 0x1100u)   /* the data area ends just below */
#define ENGINE_KIND   (XGAM_BASE + 0x111Cu)   /* 1 = parameter byte, 0 = command byte */
#define ENGINE_RUN    (XGAM_BASE + 0x11DCu)   /* 2 = send, 3 = send one command and read one byte */
#define ENGINE_RESULT (XGAM_BASE + 0x11F4u)   /* bits 15:8: the byte read */

/* put `n` bytes so that the last one is at ENGINE_END - 1, with whole-word stores; returns the KIND mask */
static uint32_t load(const uint8_t *bytes, unsigned n)
{
    uint32_t first = ENGINE_END - n;
    uint32_t kind = 0;
    for (uint32_t word = first & ~3u; word < ENGINE_END; word += 4) {
        /* bytes of the word below the first one belong to the engine's program memory: keep them */
        uint32_t v = word < first ? rd32(word) : 0;
        for (uint32_t a = word; a < word + 4; a++) {
            if (a < first)
                continue;
            v &= ~(0xFFu << ((a & 3) * 8));
            v |= (uint32_t)bytes[a - first] << ((a & 3) * 8);
        }
        wr32(word, v);
    }
    for (unsigned i = 1; i < n; i++)
        kind |= 1u << (32 - n + i);            /* every byte but the first (the command) is a parameter */
    return kind;
}

static void run(unsigned n, uint32_t kind, uint32_t how)
{
    wr32(ENGINE_COUNT, (rd32(ENGINE_COUNT) & 0xFFFFu) | (uint32_t)n << 16);
    wr32(ENGINE_KIND, kind);
    wr32(ENGINE_RUN, how);                     /* completes at once in the model; hardware: see the file comment */
}

void panel_command(uint8_t cmd, const uint8_t *params, unsigned n)
{
    uint8_t bytes[32];
    if (n > 31)
        n = 31;
    bytes[0] = cmd;
    for (unsigned i = 0; i < n; i++)
        bytes[i + 1] = params[i];
    run(n + 1, load(bytes, n + 1), 2);
}

uint8_t panel_read(uint8_t cmd)
{
    run(1, load(&cmd, 1), 3);
    return (uint8_t)(rd32(ENGINE_RESULT) >> 8);
}
