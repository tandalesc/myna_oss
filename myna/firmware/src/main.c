/* SPDX-License-Identifier: MIT */
/* Myna's start: bring up the kernel and the drivers in dependency order, register the tasks, and hand over to the
 * event loop. Everything after this file runs as tasks reacting to messages. */
#include <stdint.h>

#include "apps/clock.h"
#include "cpu.h"
#include "drivers/backlight.h"
#include "drivers/board.h"
#include "drivers/clock.h"
#include "drivers/display.h"
#include "drivers/keypad.h"
#include "drivers/nand.h"
#include "drivers/pmic.h"
#include "drivers/slide.h"
#include "fs/storage.h"
#include "kernel/irq.h"
#include "kernel/ostimer.h"
#include "kernel/task.h"
#include "lib/print.h"
#include "modem/modem.h"
#include "services/network.h"
#include "services/settings.h"
#include "sms/sms.h"
#include "ui/bench.h"
#include "ui/theme.h"
#include "ui/ui.h"
#include "version.h"

/* the CPSR at _start, before crt0 changed mode and mask (stored by crt0) */
uint32_t myna_entry_cpsr;

/* battery percentage from the voltage: a plain line from 3.40 V (empty) to 4.15 V (full). A placeholder: a real
 * gauge needs the cell's discharge curve and the load, which come with the power work. */
static int battery_percent(int mv)
{
    if (mv < 0)
        return -1;
    int p = (mv - 3400) * 100 / (4150 - 3400);
    return p < 0 ? 0 : p > 100 ? 100 : p;
}

int main(void)
{
    kprintf("Myna %s booting (cpu %08x, entry cpsr %08x)\n", MYNA_VERSION, cpu_id(), myna_entry_cpsr);
#ifdef MYNA_FAULT_TEST
    /* recognisable values in r0-r3, then an instruction that is permanently undefined: the fault report must show both */
    __asm__ volatile("ldr r0, =0x11111111\n\tldr r1, =0x22222222\n\tldr r2, =0x33333333\n\tldr r3, =0x44444444\n\t"
                     ".word 0xe7f000f0" ::: "r0", "r1", "r2", "r3");
#endif

    /* kernel: interrupt controllers quiet first, then the timer that every later wait depends on */
    irq_init();
    ostimer_init();
    board_init();              /* which board (slider or flip): the slide switch, the keypad and the UI ask */

    /* drivers. The display goes first among them: its panel needs 120 ms to wake, and everything else is done
       within that time. */
    const struct surface *fb = display_init();
    pmic_init();
    clock_init();
    int mv = pmic_battery_mv();
    kprintf("battery: %d mV\n", mv);
    backlight_on();

    /* storage and settings, before anything that shows them: the file systems are mounted (a blank chip is
       formatted) while the panel wakes */
    storage_init();
#ifdef MYNA_NAND_TEST
    nand_self_test();
#endif
    settings_init();
    clock_set_offset(settings_get(SET_CLOCK_OFFSET));
    theme_select(settings_get(SET_THEME));
    backlight_set_level(settings_get(SET_BRIGHTNESS));
    modem_init();              /* link channel 0 and the AT engine; the modem is quiet until the bring-up starts */

    /* tasks, most urgent first: drivers before the services and the screen that use them */
    task_add(keypad_task());
    task_add(display_task());
    task_add(modem_task());
    task_add(settings_task());
    task_add(sms_task());
    task_add(ui_task());
    task_add(clock_task());
    slide_init(ui_task());
    keypad_init(ui_task());
    settings_subscribe(ui_task());
    settings_subscribe(clock_task());   /* the alarm follows the clock offset */
    if (fb) {
        network_subscribe(ui_task());      /* without a display the UI is not set up */
        sms_subscribe(ui_task());
    }
    network_subscribe(sms_task());
    task_post(modem_task(), MSG_START, 0, 0);
    task_post(sms_task(), MSG_START, 0, 0);
    if (fb) {
        ui_init(fb, battery_percent(mv));
        task_post(ui_task(), MSG_START, 0, 0);
        task_post(clock_task(), MSG_START, 0, 0);     /* the alarm (apps/clock.h): after the UI is up */
    }
#ifdef MYNA_BENCH
    if (fb)
        bench_start();
#endif
    ktime_t t = ktime_now();
    kprintf("kernel: started at %u us\n", ktime_to_us(t));
    kernel_run();
}
