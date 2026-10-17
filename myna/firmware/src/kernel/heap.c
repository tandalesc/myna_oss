/* SPDX-License-Identifier: MIT */
/* Start-up memory (kernel/heap.h): a pointer that only moves up through [__heap_start, __heap_end). */
#include <stdint.h>

#include "kernel/heap.h"
#include "lib/mem.h"

extern char __heap_start[], __heap_end[];

static uintptr_t next;

void *heap_take(size_t size, size_t align)
{
    if (!next)
        next = (uintptr_t)__heap_start;
    uintptr_t p = (next + align - 1) & ~(uintptr_t)(align - 1);
    if (p + size > (uintptr_t)__heap_end || p + size < p)
        return 0;
    next = p + size;
    /* the launcher's SDRAM starts zeroed, a boot loader's need not: callers get the same either way */
    memset((void *)p, 0, size);
    return (void *)p;
}
