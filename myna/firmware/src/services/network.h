/* SPDX-License-Identifier: MIT */
/* The network service: what the modem says about the card, the registration, the operator, the signal, the phone's
 * own number and the network's time (3GPP TS 27.007 +CPIN, +CREG, +COPS, +CIND / +CIEV, +CNUM, +CCLK).
 *
 * The state is kept from unsolicited result codes (+CREG, +CIEV) and from queries when they change: no polling.
 * Subscribed tasks get MSG_NETWORK_CHANGED when something that can be shown changes. With the setting SET_NET_TIME
 * the clock follows the network's time once at each registration (the clock offset is set when it differs by more
 * than 2 s). Everything runs in the modem task. */
#ifndef MYNA_SERVICES_NETWORK_H
#define MYNA_SERVICES_NETWORK_H

#include <stdint.h>

struct task;

/* +CREG <stat> (27.007 7.2) */
enum net_reg {
    NET_NOT_SEARCHING = 0, NET_HOME = 1, NET_SEARCHING = 2, NET_DENIED = 3, NET_UNKNOWN = 4, NET_ROAMING = 5,
};

enum net_sim { SIM_UNKNOWN, SIM_READY, SIM_ABSENT, SIM_NOT_READY };

struct net_status {
    uint8_t sim;               /* enum net_sim */
    int8_t reg;                /* enum net_reg, -1 before the first answer */
    uint8_t bars;              /* 0-5 */
    uint8_t service;           /* the "service" indicator */
    char operator_name[32];
    char own_number[24];       /* +CNUM, "" when the card knows none */
    char lac[8], cell[12];     /* location area and cell (+CREG=2) */
    uint32_t changes;          /* how many MSG_NETWORK_CHANGED were sent */
};

void network_init(void);                       /* register the URC handlers (before the modem starts) */
void network_subscribe(struct task *t);        /* MSG_NETWORK_CHANGED to this task from now on */

/* the bring-up commands of the service, queued by the modem in its order (myna/spec/14-modem-at.md 6) */
void network_bringup_card(void);               /* +CPIN?, +CFUN=1 */
void network_bringup_reg(void);                /* +CREG=2, +CIND=?, +CMER=3,0,0,1, +CIND? */
void network_bringup_identity(void);           /* +CNUM, +COPS=3,0, +COPS?, +CREG? (then +CCLK? when registered) */
void network_modem_lost(void);                 /* the modem channel restarts: nothing is known */

const struct net_status *network_status(void);
int network_registered(void);
/* what the status bar shows: the operator, "Searching", "No network", "No SIM" */
const char *network_label(void);

#endif
