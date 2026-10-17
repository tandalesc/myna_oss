/* SPDX-License-Identifier: MIT */
/* Start-up memory: big buffers (the framebuffer) taken once from the heap area of link.ld and never given back.
 * A general allocator comes when something needs to free. */
#ifndef MYNA_KERNEL_HEAP_H
#define MYNA_KERNEL_HEAP_H

#include <stddef.h>

/* `align` a power of two; returns zeroed memory, or 0 when the heap is exhausted */
void *heap_take(size_t size, size_t align);

#endif
