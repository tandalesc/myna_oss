/* SPDX-License-Identifier: MIT */
/* NAND flash: the 2 Gbit large-page chip behind the NAND controller (myna/spec/10-storage-nand.md).
 *
 * The driver speaks in pages (2048 data bytes + 64 spare bytes), sectors (512 data bytes: the unit of the controller's
 * ECC engine, four per page) and erase blocks (64 pages, 128 KB). Every sector is written with its 24-bit Hamming code
 * in the page's spare area and checked on every read: one wrong bit in a sector is corrected, more are reported.
 *
 * Spare area of a page (64 bytes), Myna's layout:
 *   byte 0          bad-block marker: 0xFF on a good block (pages 0 and 1 of a block are looked at). Never written
 *                   by Myna except to mark a block bad (0x00).
 *   byte 1          reserved (0xFF)
 *   bytes 40-51     ECC of sectors 0-3, three bytes each (sector s at 40 + 3s), the ECC register's 24 bits,
 *                   least significant byte first
 *   other bytes     free (0xFF)
 * A sector that was never programmed reads 0xFF with an ECC of 0xFFFFFF, which is also the code of 512 bytes of 0xFF:
 * an erased sector reads as valid. Sectors of one page may be programmed separately (one program each per erase). */
#ifndef MYNA_DRIVERS_NAND_H
#define MYNA_DRIVERS_NAND_H

#include <stdint.h>

#define NAND_SECTOR           512u
#define NAND_PAGE             2048u
#define NAND_SPARE            64u
#define NAND_SECTORS_PER_PAGE 4u
#define NAND_PAGES_PER_BLOCK  64u
#define NAND_BLOCK            (NAND_PAGE * NAND_PAGES_PER_BLOCK)    /* 128 KB */
#define NAND_BLOCKS           2048u

#define NAND_SPARE_BADMARK    0u
#define NAND_SPARE_ECC        40u

enum nand_result {
    NAND_OK = 0,
    NAND_ERR_ECC = -1,         /* a sector has more wrong bits than the code can correct */
    NAND_ERR_FAIL = -2,        /* the chip reported a failed program or erase */
    NAND_ERR_TIMEOUT = -3,     /* the chip stayed busy */
    NAND_ERR_BAD = -4,         /* the block is marked bad: not erased, not programmed */
    NAND_ERR_ARG = -5,         /* outside the chip, or not whole sectors */
    NAND_ERR_NOCHIP = -6,      /* no chip answered at start */
};

struct nand_stats {
    uint32_t sectors_read, sectors_programmed, blocks_erased;
    uint32_t bits_corrected;   /* single-bit errors repaired on read */
    uint32_t ecc_failures;     /* sectors that could not be repaired */
    uint32_t bad_blocks;       /* blocks found marked bad, or marked by Myna */
};

/* Reset the chip and check its identity. 0 = a chip of the expected geometry answers. */
int nand_init(void);

/* Read `count` whole sectors of one page, starting at sector `sector` (0-3), into `buf`, each checked against its
 * code. Returns the number of bits corrected (>= 0), or NAND_ERR_ECC (the data is in buf, as read) or another error. */
int nand_read(uint32_t page, unsigned sector, unsigned count, void *buf);

/* Program `count` whole sectors of one page with their codes. The sectors must be erased (not programmed since the
 * block's last erase). NAND_ERR_FAIL: the chip refused; the caller should move the data and mark the block bad. */
int nand_program(uint32_t page, unsigned sector, unsigned count, const void *buf);

/* Erase a block (64 pages to 0xFF). NAND_ERR_BAD without touching a block that is marked bad. */
int nand_erase(uint32_t block);

/* Bad blocks. A block is bad when byte 0 of the spare area of its page 0 or page 1 is not 0xFF (the factory's mark,
 * and Myna's). The answer is kept, so each block is read once per start. */
int nand_block_is_bad(uint32_t block);
/* Mark a block bad: the mark is programmed into pages 0 and 1 (over whatever they hold). */
int nand_mark_bad(uint32_t block);

/* Raw access without codes, for tests and tools: `len` bytes from `column` (0 - 2111) of a page. */
int nand_read_raw(uint32_t page, unsigned column, void *buf, unsigned len);
int nand_program_raw(uint32_t page, unsigned column, const void *buf, unsigned len);
int nand_erase_raw(uint32_t block);

const struct nand_stats *nand_stats(void);

/* The code the ECC engine computes for 512 bytes, done in software (spec 10 3.1): for tests. */
uint32_t nand_ecc_soft(const uint8_t *data);

#ifdef MYNA_NAND_TEST
void nand_self_test(void);
#endif

#endif
