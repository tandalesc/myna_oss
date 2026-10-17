/* SPDX-License-Identifier: MIT */
/* The memory routines of lib/string.c (a freestanding build has no <string.h>). */
#ifndef MYNA_LIB_MEM_H
#define MYNA_LIB_MEM_H

#include <stddef.h>

void *memcpy(void *dst, const void *src, size_t n);
void *memmove(void *dst, const void *src, size_t n);
void *memset(void *dst, int c, size_t n);
int memcmp(const void *a, const void *b, size_t n);
size_t strlen(const char *s);
int strcmp(const char *a, const char *b);
char *strcpy(char *dst, const char *src);
char *strchr(const char *s, int c);
size_t strspn(const char *s, const char *accept);
size_t strcspn(const char *s, const char *reject);

#endif
