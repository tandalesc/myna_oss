/* SPDX-License-Identifier: MIT */
/* littlefs on Myna: the system part of littlefs, in place of its lfs_util.h (the build defines
 * LFS_CONFIG=fs/lfs_port.h, so littlefs includes this file and nothing of a C library).
 *
 * It gives littlefs Myna's memory and string routines (lib/mem.h), its console for errors and warnings, a stop with a
 * report for a failed assertion, the bit helpers on the compiler's built-ins, and the CRC-32 of fs/lfs_port.c. littlefs
 * never allocates here: every buffer is given in its configuration (fs/storage.c), so lfs_malloc returns 0. */
#ifndef MYNA_FS_LFS_PORT_H
#define MYNA_FS_LFS_PORT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "lib/mem.h"
#include "lib/print.h"

/* printf formats of the fixed-width types (no <inttypes.h> in a freestanding build): int is 32 bits, and the 8 and
 * 16-bit types are promoted to int */
#define PRId32 "d"
#define PRIu32 "u"
#define PRIx32 "x"
#define PRIu16 "u"
#define PRIx16 "x"
#define PRIu8  "u"

/* messages: errors and warnings on the console; debug and trace off */
#define LFS_TRACE(...)
#define LFS_DEBUG(...)
#define LFS_WARN_(fmt, ...)  kprintf("lfs: warning: " fmt "%s\n", __VA_ARGS__)
#define LFS_WARN(...)        LFS_WARN_(__VA_ARGS__, "")
#define LFS_ERROR_(fmt, ...) kprintf("lfs: error: " fmt "%s\n", __VA_ARGS__)
#define LFS_ERROR(...)       LFS_ERROR_(__VA_ARGS__, "")

__attribute__((noreturn)) void lfs_port_assert(const char *file, int line);
#define LFS_ASSERT(test) ((test) ? (void)0 : lfs_port_assert(__FILE__, __LINE__))

static inline uint32_t lfs_max(uint32_t a, uint32_t b)
{
    return a > b ? a : b;
}

static inline uint32_t lfs_min(uint32_t a, uint32_t b)
{
    return a < b ? a : b;
}

static inline uint32_t lfs_aligndown(uint32_t a, uint32_t alignment)
{
    return a - a % alignment;
}

static inline uint32_t lfs_alignup(uint32_t a, uint32_t alignment)
{
    return lfs_aligndown(a + alignment - 1, alignment);
}

/* log2 of the smallest power of two >= a */
static inline uint32_t lfs_npw2(uint32_t a)
{
    return 32 - __builtin_clz(a - 1);
}

/* trailing zero bits (a != 0): the lowest set bit isolated, then its position by CLZ (ARMv5 has CLZ, not CTZ) */
static inline uint32_t lfs_ctz(uint32_t a)
{
    return 31 - __builtin_clz(a & -a);
}

static inline uint32_t lfs_popc(uint32_t a)
{
    return (uint32_t)__builtin_popcount(a);
}

/* distance between two sequence numbers, ignoring overflow */
static inline int lfs_scmp(uint32_t a, uint32_t b)
{
    return (int)(unsigned)(a - b);
}

/* the ARM926 runs little-endian, littlefs's order on disk */
static inline uint32_t lfs_fromle32(uint32_t a)
{
    return a;
}

static inline uint32_t lfs_tole32(uint32_t a)
{
    return a;
}

static inline uint32_t lfs_frombe32(uint32_t a)
{
    return __builtin_bswap32(a);
}

static inline uint32_t lfs_tobe32(uint32_t a)
{
    return __builtin_bswap32(a);
}

/* CRC-32, polynomial 0x04C11DB7 bit-reversed (0xEDB88320), no final inversion: fs/lfs_port.c */
uint32_t lfs_crc(uint32_t crc, const void *buffer, size_t size);

static inline void *lfs_malloc(size_t size)
{
    (void)size;
    return 0;
}

static inline void lfs_free(void *p)
{
    (void)p;
}

#endif
