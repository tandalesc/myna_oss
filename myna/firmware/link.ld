/* SPDX-License-Identifier: MIT */
/* Memory layout of Myna on the application CPU of the DB3210 (myna/README.md, "Memory layout").
 *
 * The image runs where the launcher (and later a boot loader) puts it: in SDRAM, with the MMU off, so every address
 * here is physical. The launcher loads each PT_LOAD segment at its physical address (LMA), so .data needs no copy.
 *
 *   0x00000000 .. 0x00010000   TCM (64 KB): crt0 copies the exception vectors to 0 (SCTLR.V = 0: low vectors)
 *   0x48000000 ..              .text (crt0 first), .rodata, .data, .bss
 *   end of .bss .. 0x4BEEB000  heap (nothing allocates yet)
 *   0x4BEEB000 .. 0x4BF00000   stacks, one per CPU mode (sizes below)
 *   0x4BF00000 .. 0x4C000000   reserved (1 MB): the launcher keeps its boot-ROM stand-ins of the stock firmware at
 *                              0x4BFFE000; Myna leaves the top megabyte alone so the two can never meet
 * Not SDRAM, not ours: 0x28000000 (the window shared with the modem CPU), 0xA0000000 and 0xC0000000 (hardware). */

ENTRY(_start)

MEMORY
{
    SDRAM (rwx) : ORIGIN = 0x48000000, LENGTH = 0x03F00000   /* 64 MB minus the reserved top megabyte */
}

STACK_SVC = 0x10000;     /* main() and everything it calls */
STACK_IRQ = 0x2000;
STACK_FIQ = 0x1000;
STACK_ABT = 0x1000;      /* the abort and undefined handlers only report and stop */
STACK_UND = 0x1000;

SECTIONS
{
    .text : ALIGN(4)
    {
        KEEP(*(.text.start))          /* _start at 0x48000000, the ELF entry */
        __vectors_start = .;
        KEEP(*(.vectors))             /* copied to address 0 by crt0 */
        __vectors_end = .;
        *(.text .text.*)
    } > SDRAM

    .rodata : ALIGN(4)
    {
        *(.rodata .rodata.*)
    } > SDRAM

    .data : ALIGN(4)
    {
        __data_start = .;
        *(.data .data.*)
        . = ALIGN(4);
        __data_end = .;
    } > SDRAM
    __data_load = LOADADDR(.data);

    .bss (NOLOAD) : ALIGN(4)
    {
        __bss_start = .;
        *(.bss .bss.* COMMON)
        . = ALIGN(4);
        __bss_end = .;
    } > SDRAM

    __heap_start = ALIGN(__bss_end, 0x1000);

    /* stacks at the top of Myna's part of SDRAM, each full-descending from its _top */
    __stack_top     = ORIGIN(SDRAM) + LENGTH(SDRAM);
    __stack_svc_top = __stack_top;
    __stack_irq_top = __stack_svc_top - STACK_SVC;
    __stack_fiq_top = __stack_irq_top - STACK_IRQ;
    __stack_abt_top = __stack_fiq_top - STACK_FIQ;
    __stack_und_top = __stack_abt_top - STACK_ABT;
    __stack_bottom  = __stack_und_top - STACK_UND;
    __heap_end      = __stack_bottom;

    ASSERT(__heap_start <= __heap_end, "Myna: the image runs into the stacks")

    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment) }
}
