/* SPDX-License-Identifier: MIT */
/* Storage: the NAND chip divided into partitions, and a littlefs file system in each of the two that hold files.
 *
 *   partition  blocks        size     content
 *   boot       0 - 31        4 MB     reserved for a boot loader and the firmware image (not used yet)
 *   system     32 - 63       4 MB     littlefs "system": settings and other state of the phone
 *   user       64 - 2039     247 MB   littlefs "user": the user's files
 *   reserve    2040 - 2047   1 MB     outside the file systems: the NAND self-test's block (2047); later a crash log
 *                                     or a factory area
 *
 * A file system is mounted at start. A partition that has never been written (its first two blocks erased) is
 * formatted first; one that holds something littlefs cannot mount is left alone and reported, never formatted over.
 * littlefs makes every file change atomic: after a power cut a file has its old or its new content. */
#ifndef MYNA_FS_STORAGE_H
#define MYNA_FS_STORAGE_H

#include <stdint.h>

#include "lfs.h"
#include "kernel/ostimer.h"

enum storage_fs { FS_SYSTEM, FS_USER, FS_COUNT };

/* the cache each open file needs (struct lfs_file_config .buffer): one NAND page */
#define STORAGE_FILE_CACHE 2048

struct storage_report {
    uint8_t mounted;           /* the file system can be used */
    uint8_t formatted;         /* it was formatted at this start (a blank partition) */
    uint32_t format_us, mount_us;
    uint32_t blocks;           /* littlefs blocks (erase blocks) */
};

/* Find the chip, mount both file systems (formatting blank ones). 0 = the system file system is usable. */
int storage_init(void);

/* the file system, or 0 when it is not mounted */
lfs_t *storage_fs(enum storage_fs which);
const struct storage_report *storage_report(enum storage_fs which);

/* Master reset: both file systems formatted again (everything on them is gone) and mounted empty. The services' RAM
 * state is not told: the caller switches the phone off at once. 0 = both done. */
int storage_erase_all(void);

/* Kernel time of the last program or erase of the chip, 0 if none since start. The simulator keeps the chip between
 * runs only from a moment at which the chip has been quiet for 1.5 s (spec 10 4): power off waits for that. */
ktime_t storage_last_write(void);

#endif
