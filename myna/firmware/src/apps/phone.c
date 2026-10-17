/* SPDX-License-Identifier: MIT */
/* The services' news in the UI task (apps/phone.h): app_event() of ui/apps.h.
 *
 * The status bar is set only through its setters (ui_status_*). The network service counts the signal in bars 0-5
 * (+CIND "signal", spec 14); the design's sign has four (STYLE.md section 2), so five bars show as four. */
#include <stdint.h>

#include "apps/phone.h"
#include "kernel/msg.h"
#include "kernel/task.h"
#include "services/network.h"
#include "ui/apps.h"
#include "ui/ui.h"

static void network_show(void)
{
#ifndef MYNA_UI_DEMO          /* with it, the status bar stays as the mock-ups show it (ui/ui.c) */
    const struct net_status *n = network_status();
    int bars = n->bars > 4 ? 4 : n->bars;
    ui_status_signal(network_registered() ? bars : -1);
    ui_status_operator(network_label());
#endif
}

void app_event(const struct msg *m)
{
    switch (m->type) {
    case MSG_START:
        network_show();
        messages_start();
        break;
    case MSG_NETWORK_CHANGED:
        network_show();
        messages_network();
        break;
    case MSG_SMS_EVENT:
        messages_sms_event(m->a, m->b);
        break;
    }
}

void app_power_off(void)
{
    messages_power_off();
}
