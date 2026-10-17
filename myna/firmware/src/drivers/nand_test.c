/* SPDX-License-Identifier: MIT */
/* A self-test of the NAND driver on the chip's last block, outside the file systems (make clean all
 * DEFS=-DMYNA_NAND_TEST=1): the engine's code against the specification's formula, read-back, partial programs, a
 * corrected bit, an uncorrectable sector, the bad-block mark, and the cost of each operation. The block is erased
 * again at the end. */
#ifdef MYNA_NAND_TEST
#include <stdint.h>

#include "drivers/nand.h"
#include "kernel/ostimer.h"
#include "lib/mem.h"
#include "lib/print.h"

#define TEST_BLOCK (NAND_BLOCKS - 1u)

static uint32_t page_buf[NAND_PAGE / 4], back[NAND_PAGE / 4];
static int failures;

static void expect(int ok, const char *what)
{
    kprintf("nand test: %s: %s\n", what, ok ? "ok" : "FAILED");
    if (!ok)
        failures++;
}

static void fill(uint32_t seed)
{
    uint32_t x = seed;
    for (unsigned i = 0; i < NAND_PAGE / 4; i++) {
        x = x * 1664525u + 1013904223u;          /* any pattern with every bit value in every position */
        page_buf[i] = x;
    }
}

void nand_self_test(void)
{
    uint32_t first = TEST_BLOCK * NAND_PAGES_PER_BLOCK;
    uint8_t *pb = (uint8_t *)page_buf, *bb = (uint8_t *)back;
    ktime_t t0, t1;

    expect(nand_erase_raw(TEST_BLOCK) == NAND_OK, "erase");
    memset(back, 0, sizeof back);
    expect(nand_read(first, 0, 4, back) == 0, "erased page reads clean");
    int all_ff = 1;
    for (unsigned i = 0; i < NAND_PAGE / 4; i++)
        all_ff &= back[i] == 0xFFFFFFFFu;
    expect(all_ff, "erased page is 0xFF");

    /* a whole page, timed */
    fill(1);
    t0 = ktime_now();
    int r = nand_program(first, 0, 4, page_buf);
    t1 = ktime_now();
    expect(r == NAND_OK, "program page");
    kprintf("nand test: program of a page: %u us\n", ktime_to_us(t1 - t0));
    t0 = ktime_now();
    r = nand_read(first, 0, 4, back);
    t1 = ktime_now();
    expect(r == 0 && memcmp(page_buf, back, NAND_PAGE) == 0, "read page back");
    kprintf("nand test: read of a page: %u us\n", ktime_to_us(t1 - t0));

    /* the engine's code against the formula of spec 10 3.1 */
    uint8_t spare[NAND_SPARE];
    nand_read_raw(first, NAND_PAGE, spare, NAND_SPARE);
    int same = 1;
    for (unsigned s = 0; s < 4; s++) {
        uint32_t stored = spare[NAND_SPARE_ECC + 3 * s] | (uint32_t)spare[NAND_SPARE_ECC + 3 * s + 1] << 8 |
                          (uint32_t)spare[NAND_SPARE_ECC + 3 * s + 2] << 16;
        uint32_t soft = nand_ecc_soft(pb + s * NAND_SECTOR);
        if (stored != soft) {
            kprintf("nand test: sector %u: engine %06x, formula %06x\n", s, stored, soft);
            same = 0;
        }
    }
    expect(same, "engine code = formula");
    expect(spare[0] == 0xFF && spare[1] == 0xFF, "bad-block mark untouched");

    /* sectors programmed one at a time, out of order */
    fill(2);
    expect(nand_program(first + 1, 2, 1, pb + 2 * NAND_SECTOR) == NAND_OK, "program sector 2 alone");
    expect(nand_program(first + 1, 0, 2, pb) == NAND_OK, "program sectors 0-1");
    expect(nand_program(first + 1, 3, 1, pb + 3 * NAND_SECTOR) == NAND_OK, "program sector 3");
    expect(nand_read(first + 1, 0, 4, back) == 0 && memcmp(page_buf, back, NAND_PAGE) == 0, "partial programs read");
    expect(nand_read(first + 1, 1, 2, back) == 0 && memcmp(pb + NAND_SECTOR, back, 2 * NAND_SECTOR) == 0,
           "read sectors 1-2");
    expect(nand_read(first + 1, 3, 1, bb + 1) == 0 && memcmp(pb + 3 * NAND_SECTOR, bb + 1, NAND_SECTOR) == 0,
           "read into an unaligned buffer");

    /* one bit flipped in the chip (a program can only clear bits): corrected */
    fill(1);
    unsigned pos = 0;
    while (!(pb[pos + 700] & 0x10))
        pos++;
    pos += 700;                                   /* a byte of sector 1 with bit 4 set */
    uint8_t flip = (uint8_t)(pb[pos] & ~0x10);
    nand_program_raw(first, pos, &flip, 1);
    r = nand_read(first, 0, 4, back);
    expect(r == 1 && memcmp(page_buf, back, NAND_PAGE) == 0, "one wrong bit corrected");
    /* a second wrong bit in the same sector: reported */
    unsigned pos2 = pos + 1;
    while (!(pb[pos2] & 0x01))
        pos2++;
    flip = (uint8_t)(pb[pos2] & ~0x01);
    nand_program_raw(first, pos2, &flip, 1);
    expect(nand_read(first, 1, 1, back) == NAND_ERR_ECC, "two wrong bits reported");
    /* a wrong bit in a stored code: the data stands */
    uint8_t code0;
    nand_read_raw(first, NAND_PAGE + NAND_SPARE_ECC, &code0, 1);
    unsigned b = 0;
    while (b < 8 && !(code0 & (1u << b)))
        b++;
    if (b < 8) {
        code0 = (uint8_t)(code0 & ~(1u << b));
        nand_program_raw(first, NAND_PAGE + NAND_SPARE_ECC, &code0, 1);
        expect(nand_read(first, 0, 1, back) == 1 && memcmp(page_buf, back, NAND_SECTOR) == 0,
               "wrong bit in the code tolerated");
    }

    /* bad-block mark: set, seen, refused; an erase without the check removes it */
    expect(!nand_block_is_bad(TEST_BLOCK), "block good");
    nand_mark_bad(TEST_BLOCK);
    expect(nand_block_is_bad(TEST_BLOCK), "block marked bad");
    expect(nand_erase(TEST_BLOCK) == NAND_ERR_BAD && nand_program(first + 5, 0, 1, pb) == NAND_ERR_BAD,
           "bad block refused");
    t0 = ktime_now();
    r = nand_erase_raw(TEST_BLOCK);
    t1 = ktime_now();
    expect(r == NAND_OK && !nand_block_is_bad(TEST_BLOCK), "erased: good again");
    kprintf("nand test: erase of a block: %u us\n", ktime_to_us(t1 - t0));

    const struct nand_stats *st = nand_stats();
    kprintf("nand test: %s (%d failures); %u sectors read, %u programmed, %u erases, %u bits corrected, "
            "%u uncorrectable\n", failures ? "FAILED" : "passed", failures, st->sectors_read,
            st->sectors_programmed, st->blocks_erased, st->bits_corrected, st->ecc_failures);
}
#endif
