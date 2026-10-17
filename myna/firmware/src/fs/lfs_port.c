/* SPDX-License-Identifier: MIT */
/* The run-time part of fs/lfs_port.h: CRC-32 and the assertion stop. */
#include <stddef.h>
#include <stdint.h>

#include "cpu.h"
#include "fs/lfs_port.h"

/* CRC-32 a byte at a time from a 256-entry table, made at the first call (1 KB of RAM; littlefs checks every
 * metadata commit it reads, so this runs over kilobytes at each mount) */
uint32_t lfs_crc(uint32_t crc, const void *buffer, size_t size)
{
    static uint32_t table[256];
    if (!table[1]) {
        for (uint32_t i = 0; i < 256; i++) {
            uint32_t c = i;
            for (int k = 0; k < 8; k++)
                c = c & 1 ? (c >> 1) ^ 0xEDB88320u : c >> 1;
            table[i] = c;
        }
    }
    const uint8_t *p = buffer;
    while (size--)
        crc = (crc >> 8) ^ table[(crc ^ *p++) & 0xFFu];
    return crc;
}

void lfs_port_assert(const char *file, int line)
{
    kprintf("lfs: assertion failed at %s:%d; stopped\n", file, line);
    cpu_irq_save();
    for (;;)
        cpu_wait_for_interrupt();
}
