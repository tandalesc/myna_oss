/* SPDX-License-Identifier: MIT */
/* NAND flash driver (drivers/nand.h): commands through the controller's latches, data through its data port, codes
 * from its ECC engine (myna/spec/10-storage-nand.md, sections 2 and 3).
 *
 * Every operation is synchronous. The chip has no completion interrupt (line 45 is never raised, spec 10 3), so after
 * each command that makes the chip busy the driver polls the controller's READY bit: in the simulator the chip is busy
 * for three polls; on a phone a page read takes some 25 us, a program 200 us, an erase 2 ms. (If that ever matters,
 * the storage work moves into a task of its own that yields between pages.) There is no DMA path: the DMA controller
 * has no port for the NAND data register (spec 13 4), so data moves with LDM/STM loops of eight words
 * (drivers/nand_arm.S), every word one access to the data port, in order. */
#include <stdint.h>

#include "drivers/nand.h"
#include "hw.h"
#include "lib/mem.h"
#include "lib/print.h"

#define NAND_DATA     0x80000000u
#define NAND_CMD      0x80010000u
#define NAND_ADDR     0x80020000u
#define NFC_CONTROL   (NANDC_BASE + 0x40u)   /* bit 6: ECC engine on; 0 -> 1 clears the code */
#define NFC_ECC       (NANDC_BASE + 0x54u)   /* the code of the bytes since the clear, 24 bits */
#define NFC_READY     (NANDC_BASE + 0xC8u)   /* bit 1: the chip's ready line */

#define ECC_ON        0x40u
#define READY_POLLS   100000u                /* about 2 ms of polling on a phone: longer than any erase */

/* chip commands (spec 10 2.1) */
enum {
    C_READ = 0x00, C_READ_GO = 0x30, C_RANDOM_OUT = 0x05, C_RANDOM_OUT_GO = 0xE0,
    C_PROGRAM = 0x80, C_RANDOM_IN = 0x85, C_PROGRAM_GO = 0x10,
    C_ERASE = 0x60, C_ERASE_GO = 0xD0, C_STATUS = 0x70, C_READ_ID = 0x90, C_RESET = 0xFF,
};
#define STATUS_FAIL   0x01u

#define PAGES         (NAND_BLOCKS * NAND_PAGES_PER_BLOCK)
#define WORDS_PER_SECTOR (NAND_SECTOR / 4u)

/* drivers/nand_arm.S: n a multiple of 8, buffers word-aligned */
void nand_read_words(uint32_t *dst, uint32_t n);
void nand_write_words(const uint32_t *src, uint32_t n);

static struct nand_stats stats;
static uint32_t block_checked[NAND_BLOCKS / 32], block_bad[NAND_BLOCKS / 32];
static int present;
/* for callers whose buffer is not word-aligned (littlefs passes the caller's buffer through on large reads) */
static uint32_t bounce[WORDS_PER_SECTOR];

static inline void cmd(uint8_t c)
{
    *(volatile uint8_t *)NAND_CMD = c;
}

static inline void addr(uint8_t a)
{
    *(volatile uint8_t *)NAND_ADDR = a;
}

static inline uint8_t data8(void)
{
    return *(volatile uint8_t *)NAND_DATA;
}

static inline void put8(uint8_t v)
{
    *(volatile uint8_t *)NAND_DATA = v;
}

/* column (2 cycles) and row (3 cycles), low byte first */
static void address(unsigned column, uint32_t row)
{
    addr((uint8_t)column);
    addr((uint8_t)(column >> 8));
    addr((uint8_t)row);
    addr((uint8_t)(row >> 8));
    addr((uint8_t)(row >> 16));
}

static int wait_ready(void)
{
    for (uint32_t i = 0; i < READY_POLLS; i++)
        if (rd32(NFC_READY) & 2u)
            return NAND_OK;
    return NAND_ERR_TIMEOUT;
}

/* after a program or an erase: the chip's pass / fail bit */
static int status(void)
{
    int r = wait_ready();
    if (r)
        return r;
    cmd(C_STATUS);
    return data8() & STATUS_FAIL ? NAND_ERR_FAIL : NAND_OK;
}

static inline void ecc_start(void)
{
    wr32(NFC_CONTROL, 0);
    wr32(NFC_CONTROL, ECC_ON);
}

static inline uint32_t ecc_take(void)
{
    uint32_t e = rd32(NFC_ECC) & 0xFFFFFFu;
    wr32(NFC_CONTROL, 0);
    return e;
}

/* ---- the code ---- */

uint32_t nand_ecc_soft(const uint8_t *data)
{
    /* P[2k+1] (k = 0..8) is the parity of the bytes whose index has bit k set: the XOR of the indexes of the bytes of
       odd parity, bit k. P[2k] is the rest of those bytes: the overall parity XOR P[2k+1]. The column parities come
       from the XOR of all bytes. The register holds NOT P. */
    uint32_t idx = 0, all = 0;
    for (uint32_t i = 0; i < NAND_SECTOR; i++) {
        uint32_t b = data[i];
        all ^= b;
        if (__builtin_popcount(b) & 1)
            idx ^= i;
    }
    uint32_t odd = __builtin_popcount(all) & 1, p = 0;
    for (unsigned k = 0; k < 9; k++) {
        uint32_t hi = (idx >> k) & 1;
        p |= (hi ^ odd) << (2 * k) | hi << (2 * k + 1);
    }
    static const uint8_t lo_mask[3] = { 0x55, 0x33, 0x0F };
    for (unsigned k = 0; k < 3; k++) {
        uint32_t lo = __builtin_popcount(all & lo_mask[k]) & 1;
        uint32_t hi = __builtin_popcount(all & (uint8_t)~lo_mask[k]) & 1;
        p |= lo << (18 + 2 * k) | hi << (19 + 2 * k);
    }
    return ~p & 0xFFFFFFu;
}

/* Compare the code computed while reading with the stored one; repair one wrong bit. 0 = clean, 1 = one bit
 * repaired (in the data or in the stored code), NAND_ERR_ECC = more. */
static int ecc_fix(uint8_t *data, uint32_t computed, uint32_t stored)
{
    uint32_t syn = (computed ^ stored) & 0xFFFFFFu;
    if (!syn)
        return 0;
    if (__builtin_popcount(syn) == 1)
        return 1;                                  /* the stored code took the hit: the data is right */
    if (((syn ^ (syn >> 1)) & 0x555555u) == 0x555555u) {
        /* one of each pair: the odd bits spell the byte's index (9 bits) and the bit's position (3 bits) */
        uint32_t byte = 0, bit = 0;
        for (unsigned k = 0; k < 9; k++)
            byte |= ((syn >> (2 * k + 1)) & 1u) << k;
        for (unsigned k = 0; k < 3; k++)
            bit |= ((syn >> (19 + 2 * k)) & 1u) << k;
        data[byte] ^= (uint8_t)(1u << bit);
        return 1;
    }
    return NAND_ERR_ECC;
}

/* ---- start ---- */

int nand_init(void)
{
    cmd(C_RESET);
    if (wait_ready())
        return NAND_ERR_TIMEOUT;
    cmd(C_READ_ID);
    addr(0);
    uint8_t id[5];
    for (unsigned i = 0; i < 5; i++)
        id[i] = data8();
    /* byte 4: page size (bits 1:0, 1 KB << n), block size (bits 5:4, 64 KB << n), spare per 512 bytes (bit 2) */
    unsigned page = 1024u << (id[3] & 3u), block = (64u * 1024u) << ((id[3] >> 4) & 3u);
    kprintf("nand: id %02x %02x %02x %02x %02x, page %u, block %u\n", id[0], id[1], id[2], id[3], id[4], page, block);
    if (id[0] == 0x00 || id[0] == 0xFF || page != NAND_PAGE || block != NAND_BLOCK) {
        kprintf("nand: no chip of the expected geometry\n");
        return NAND_ERR_NOCHIP;
    }
    present = 1;
    return NAND_OK;
}

const struct nand_stats *nand_stats(void)
{
    return &stats;
}

/* ---- sectors with codes ---- */

static int check(uint32_t page, unsigned sector, unsigned count)
{
    if (!present)
        return NAND_ERR_NOCHIP;
    if (page >= PAGES || sector >= NAND_SECTORS_PER_PAGE || count == 0 || sector + count > NAND_SECTORS_PER_PAGE)
        return NAND_ERR_ARG;
    return NAND_OK;
}

int nand_read(uint32_t page, unsigned sector, unsigned count, void *buf)
{
    int r = check(page, sector, count);
    if (r)
        return r;
    cmd(C_READ);
    address(sector * NAND_SECTOR, page);
    cmd(C_READ_GO);
    if ((r = wait_ready()))
        return r;

    uint32_t computed[NAND_SECTORS_PER_PAGE];
    uint8_t *out = buf;
    int aligned = ((uintptr_t)buf & 3u) == 0;
    for (unsigned i = 0; i < count; i++) {
        uint32_t *dst = aligned ? (uint32_t *)(out + i * NAND_SECTOR) : bounce;
        ecc_start();
        nand_read_words(dst, WORDS_PER_SECTOR);
        computed[i] = ecc_take();
        if (!aligned)
            memcpy(out + i * NAND_SECTOR, bounce, NAND_SECTOR);
    }

    /* the stored codes: move the data output to the spare area */
    uint8_t code[3 * NAND_SECTORS_PER_PAGE];
    cmd(C_RANDOM_OUT);
    addr((uint8_t)(NAND_PAGE + NAND_SPARE_ECC + 3 * sector));
    addr((uint8_t)((NAND_PAGE + NAND_SPARE_ECC + 3 * sector) >> 8));
    cmd(C_RANDOM_OUT_GO);
    for (unsigned i = 0; i < 3 * count; i++)
        code[i] = data8();

    int fixed = 0;
    for (unsigned i = 0; i < count; i++) {
        uint32_t stored = code[3 * i] | (uint32_t)code[3 * i + 1] << 8 | (uint32_t)code[3 * i + 2] << 16;
        int f = ecc_fix(out + i * NAND_SECTOR, computed[i], stored);
        if (f < 0) {
            stats.ecc_failures++;
            kprintf("nand: page %u sector %u: uncorrectable (code %06x, read %06x)\n", page, sector + i, stored,
                    computed[i]);
            fixed = NAND_ERR_ECC;
        } else if (f && fixed >= 0) {
            stats.bits_corrected++;
            kprintf("nand: page %u sector %u: one bit corrected\n", page, sector + i);
            fixed++;
        }
    }
    stats.sectors_read += count;
    return fixed;
}

int nand_program(uint32_t page, unsigned sector, unsigned count, const void *buf)
{
    int r = check(page, sector, count);
    if (r)
        return r;
    if (nand_block_is_bad(page / NAND_PAGES_PER_BLOCK))
        return NAND_ERR_BAD;
    cmd(C_PROGRAM);
    address(sector * NAND_SECTOR, page);
    uint8_t code[3 * NAND_SECTORS_PER_PAGE];
    const uint8_t *in = buf;
    int aligned = ((uintptr_t)buf & 3u) == 0;
    for (unsigned i = 0; i < count; i++) {
        const uint32_t *src = (const uint32_t *)(in + i * NAND_SECTOR);
        if (!aligned) {
            memcpy(bounce, in + i * NAND_SECTOR, NAND_SECTOR);
            src = bounce;
        }
        ecc_start();
        nand_write_words(src, WORDS_PER_SECTOR);
        uint32_t e = ecc_take();
        code[3 * i] = (uint8_t)e;
        code[3 * i + 1] = (uint8_t)(e >> 8);
        code[3 * i + 2] = (uint8_t)(e >> 16);
    }
    /* the codes into the spare area, in the same program operation */
    cmd(C_RANDOM_IN);
    addr((uint8_t)(NAND_PAGE + NAND_SPARE_ECC + 3 * sector));
    addr((uint8_t)((NAND_PAGE + NAND_SPARE_ECC + 3 * sector) >> 8));
    for (unsigned i = 0; i < 3 * count; i++)
        put8(code[i]);
    cmd(C_PROGRAM_GO);
    r = status();
    if (r == NAND_ERR_FAIL)
        kprintf("nand: program of page %u failed\n", page);
    stats.sectors_programmed += count;
    return r;
}

/* ---- blocks ---- */

static int erase(uint32_t block)
{
    uint32_t row = block * NAND_PAGES_PER_BLOCK;
    cmd(C_ERASE);
    addr((uint8_t)row);
    addr((uint8_t)(row >> 8));
    addr((uint8_t)(row >> 16));
    cmd(C_ERASE_GO);
    int r = status();
    if (r == NAND_ERR_FAIL)
        kprintf("nand: erase of block %u failed\n", block);
    stats.blocks_erased++;
    return r;
}

int nand_erase(uint32_t block)
{
    if (!present)
        return NAND_ERR_NOCHIP;
    if (block >= NAND_BLOCKS)
        return NAND_ERR_ARG;
    if (nand_block_is_bad(block))
        return NAND_ERR_BAD;
    return erase(block);
}

int nand_erase_raw(uint32_t block)
{
    if (!present)
        return NAND_ERR_NOCHIP;
    if (block >= NAND_BLOCKS)
        return NAND_ERR_ARG;
    block_checked[block / 32] &= ~(1u << (block % 32));
    return erase(block);
}

int nand_block_is_bad(uint32_t block)
{
    if (!present || block >= NAND_BLOCKS)
        return 1;
    uint32_t bit = 1u << (block % 32);
    if (!(block_checked[block / 32] & bit)) {
        uint8_t m0 = 0, m1 = 0;
        uint32_t page = block * NAND_PAGES_PER_BLOCK;
        int bad = nand_read_raw(page, NAND_PAGE + NAND_SPARE_BADMARK, &m0, 1) != NAND_OK ||
                  nand_read_raw(page + 1, NAND_PAGE + NAND_SPARE_BADMARK, &m1, 1) != NAND_OK ||
                  m0 != 0xFF || m1 != 0xFF;
        block_checked[block / 32] |= bit;
        if (bad) {
            block_bad[block / 32] |= bit;
            stats.bad_blocks++;
            kprintf("nand: block %u is marked bad\n", block);
        } else {
            block_bad[block / 32] &= ~bit;
        }
    }
    return (block_bad[block / 32] & bit) != 0;
}

int nand_mark_bad(uint32_t block)
{
    if (!present || block >= NAND_BLOCKS)
        return NAND_ERR_ARG;
    static const uint8_t mark = 0x00;
    uint32_t page = block * NAND_PAGES_PER_BLOCK;
    nand_program_raw(page, NAND_PAGE + NAND_SPARE_BADMARK, &mark, 1);
    nand_program_raw(page + 1, NAND_PAGE + NAND_SPARE_BADMARK, &mark, 1);
    uint32_t bit = 1u << (block % 32);
    if (!(block_bad[block / 32] & bit))
        stats.bad_blocks++;
    block_checked[block / 32] |= bit;
    block_bad[block / 32] |= bit;
    kprintf("nand: block %u marked bad\n", block);
    return NAND_OK;
}

/* ---- raw bytes ---- */

int nand_read_raw(uint32_t page, unsigned column, void *buf, unsigned len)
{
    if (!present)
        return NAND_ERR_NOCHIP;
    if (page >= PAGES || column + len > NAND_PAGE + NAND_SPARE)
        return NAND_ERR_ARG;
    cmd(C_READ);
    address(column, page);
    cmd(C_READ_GO);
    int r = wait_ready();
    if (r)
        return r;
    uint8_t *out = buf;
    for (unsigned i = 0; i < len; i++)
        out[i] = data8();
    return NAND_OK;
}

int nand_program_raw(uint32_t page, unsigned column, const void *buf, unsigned len)
{
    if (!present)
        return NAND_ERR_NOCHIP;
    if (page >= PAGES || column + len > NAND_PAGE + NAND_SPARE)
        return NAND_ERR_ARG;
    cmd(C_PROGRAM);
    address(column, page);
    const uint8_t *in = buf;
    for (unsigned i = 0; i < len; i++)
        put8(in[i]);
    cmd(C_PROGRAM_GO);
    return status();
}
