/* SPDX-License-Identifier: MIT */
/* Storage (fs/storage.h): littlefs on the NAND driver.
 *
 * littlefs geometry: a littlefs block is one erase block (64 pages, 128 KB); reads and programs are in whole 512-byte
 * sectors (the unit of the NAND codes, and a partial-page program the chip allows), and the caches hold one page, so a
 * cache fill is one page read. Metadata logs are kept to 8 KB of their block (metadata_max), so that a mount and a
 * directory lookup read at most 16 sectors per log instead of 128 KB. Small files (up to 1 KB: every settings file)
 * live inside their directory's metadata.
 *
 * Bad blocks: littlefs is told a block is bad by LFS_ERR_CORRUPT from erase or program, and moves the data elsewhere.
 * The driver refuses blocks that carry a bad mark (factory or Myna's), and a block whose program or erase fails is
 * marked here. littlefs's own first two blocks (its superblock) cannot move: a partition starts at its first pair of
 * good blocks, which is the same at every start because a good block only becomes bad by failing a write.
 *
 * RAM: per file system a read and a program cache of 2 KB and a lookahead bitmap (one bit per block); each open file
 * needs a 2 KB cache of its own (the opener gives it). */
#include <stdint.h>

#include "drivers/nand.h"
#include "fs/storage.h"
#include "lib/mem.h"
#include "lib/print.h"

#define SECTOR NAND_SECTOR
#define CACHE  NAND_PAGE

_Static_assert(STORAGE_FILE_CACHE == CACHE, "a file's cache is the file system's cache size");

struct partition {
    const char *name;
    uint32_t start, end;       /* erase blocks [start, end) of the chip */
    uint32_t first;            /* littlefs block 0: the first block of the first good pair */
    lfs_t lfs;
    struct lfs_config cfg;
    struct storage_report report;
};

static uint8_t system_read[CACHE], system_prog[CACHE], system_look[16];      /* 32 blocks: 4 bytes would do */
static uint8_t user_read[CACHE], user_prog[CACHE], user_look[256];           /* 1976 blocks */

static struct partition parts[FS_COUNT] = {
    [FS_SYSTEM] = { .name = "system", .start = 32, .end = 64 },
    [FS_USER] = { .name = "user", .start = 64, .end = NAND_BLOCKS - 8 },     /* the last 8 blocks: reserve */
};

static ktime_t last_write;

ktime_t storage_last_write(void)
{
    return last_write;
}

static uint32_t physical(const struct lfs_config *c, lfs_block_t block)
{
    const struct partition *p = c->context;
    return p->first + block;
}

/* littlefs gives whole sectors at sector-aligned offsets; a request may cross a page boundary */
static int bd_read(const struct lfs_config *c, lfs_block_t block, lfs_off_t off, void *buffer, lfs_size_t size)
{
    uint32_t page = physical(c, block) * NAND_PAGES_PER_BLOCK + off / NAND_PAGE;
    unsigned sector = off % NAND_PAGE / SECTOR;
    uint8_t *out = buffer;
    while (size) {
        unsigned n = NAND_SECTORS_PER_PAGE - sector;
        if (n > size / SECTOR)
            n = size / SECTOR;
        int r = nand_read(page, sector, n, out);
        if (r < 0)
            return r == NAND_ERR_ECC ? LFS_ERR_CORRUPT : LFS_ERR_IO;
        out += n * SECTOR;
        size -= n * SECTOR;
        page++;
        sector = 0;
    }
    return 0;
}

static int bd_prog(const struct lfs_config *c, lfs_block_t block, lfs_off_t off, const void *buffer,
                   lfs_size_t size)
{
    uint32_t phys = physical(c, block);
    uint32_t page = phys * NAND_PAGES_PER_BLOCK + off / NAND_PAGE;
    unsigned sector = off % NAND_PAGE / SECTOR;
    const uint8_t *in = buffer;
    last_write = ktime_now();
    while (size) {
        unsigned n = NAND_SECTORS_PER_PAGE - sector;
        if (n > size / SECTOR)
            n = size / SECTOR;
        int r = nand_program(page, sector, n, in);
        if (r == NAND_ERR_FAIL)
            nand_mark_bad(phys);
        if (r == NAND_ERR_FAIL || r == NAND_ERR_BAD)
            return LFS_ERR_CORRUPT;
        if (r)
            return LFS_ERR_IO;
        in += n * SECTOR;
        size -= n * SECTOR;
        page++;
        sector = 0;
    }
    last_write = ktime_now();
    return 0;
}

static int bd_erase(const struct lfs_config *c, lfs_block_t block)
{
    uint32_t phys = physical(c, block);
    last_write = ktime_now();
    int r = nand_erase(phys);
    last_write = ktime_now();
    if (r == NAND_ERR_FAIL)
        nand_mark_bad(phys);
    if (r == NAND_ERR_FAIL || r == NAND_ERR_BAD)
        return LFS_ERR_CORRUPT;
    return r ? LFS_ERR_IO : 0;
}

static int bd_sync(const struct lfs_config *c)
{
    (void)c;
    return 0;                  /* every program is complete when nand_program returns */
}

/* the first two blocks of littlefs never wrote anything: no superblock there */
static int blank(const struct partition *p)
{
    for (uint32_t b = p->first; b < p->first + 2; b++) {
        uint32_t head[4];
        if (nand_read_raw(b * NAND_PAGES_PER_BLOCK, 0, head, sizeof head))
            return 0;
        for (unsigned i = 0; i < 4; i++)
            if (head[i] != 0xFFFFFFFFu)
                return 0;
    }
    return 1;
}

static void setup(struct partition *p, uint8_t *read, uint8_t *prog, uint8_t *look, uint32_t look_size)
{
    p->first = p->start;
    while (p->first + 2 < p->end && (nand_block_is_bad(p->first) || nand_block_is_bad(p->first + 1)))
        p->first++;
    p->report.blocks = p->end - p->first;
    p->cfg = (struct lfs_config){
        .context = p,
        .read = bd_read,
        .prog = bd_prog,
        .erase = bd_erase,
        .sync = bd_sync,
        .read_size = SECTOR,
        .prog_size = SECTOR,
        .block_size = NAND_BLOCK,
        .block_count = p->report.blocks,
        .block_cycles = 500,
        .cache_size = CACHE,
        .lookahead_size = look_size,
        .read_buffer = read,
        .prog_buffer = prog,
        .lookahead_buffer = look,
        .name_max = 64,
        .metadata_max = 8192,
    };
}

static void bring_up(struct partition *p)
{
    struct storage_report *rep = &p->report;
    int r;
    if (blank(p)) {
        kprintf("storage: %s: blank, formatting %u blocks\n", p->name, rep->blocks);
        ktime_t t0 = ktime_now();
        r = lfs_format(&p->lfs, &p->cfg);
        rep->format_us = ktime_to_us(ktime_now() - t0);
        rep->formatted = 1;
        if (r) {
            kprintf("storage: %s: format failed (%d)\n", p->name, r);
            return;
        }
    }
    ktime_t t0 = ktime_now();
    r = lfs_mount(&p->lfs, &p->cfg);
    rep->mount_us = ktime_to_us(ktime_now() - t0);
    if (r) {
        kprintf("storage: %s: cannot mount (%d); left alone\n", p->name, r);
        return;
    }
    rep->mounted = 1;
    lfs_ssize_t used = lfs_fs_size(&p->lfs);
    if (rep->formatted)
        kprintf("storage: %s: %u blocks from block %u, %d in use; format %u us, mount %u us\n", p->name,
                rep->blocks, p->first, (int)used, rep->format_us, rep->mount_us);
    else
        kprintf("storage: %s: %u blocks from block %u, %d in use; mount %u us\n", p->name, rep->blocks, p->first,
                (int)used, rep->mount_us);
}

int storage_init(void)
{
    if (nand_init())
        return -1;
    setup(&parts[FS_SYSTEM], system_read, system_prog, system_look, sizeof system_look);
    setup(&parts[FS_USER], user_read, user_prog, user_look, sizeof user_look);
    for (unsigned i = 0; i < FS_COUNT; i++)
        bring_up(&parts[i]);
    return parts[FS_SYSTEM].report.mounted ? 0 : -1;
}

lfs_t *storage_fs(enum storage_fs which)
{
    return which < FS_COUNT && parts[which].report.mounted ? &parts[which].lfs : 0;
}

const struct storage_report *storage_report(enum storage_fs which)
{
    return &parts[which].report;
}

int storage_erase_all(void)
{
    int result = 0;
    for (unsigned i = 0; i < FS_COUNT; i++) {
        struct partition *p = &parts[i];
        if (p->report.mounted)
            lfs_unmount(&p->lfs);
        p->report.mounted = 0;
        int r = lfs_format(&p->lfs, &p->cfg);
        if (!r)
            r = lfs_mount(&p->lfs, &p->cfg);
        kprintf("storage: %s: erased (%d)\n", p->name, r);
        if (r)
            result = -1;
        else
            p->report.mounted = 1;
    }
    return result;
}
