/* SPDX-License-Identifier: MIT */
/* The network service (services/network.h). */
#include <stdint.h>

#include "drivers/clock.h"
#include "kernel/task.h"
#include "lib/mem.h"
#include "lib/print.h"
#include "lib/sms_pdu.h"          /* sms_days_from_civil */
#include "modem/at.h"
#include "services/network.h"
#include "services/settings.h"

#define SUBSCRIBERS 4

static struct net_status st = { .reg = -1 };
static struct task *subscribers[SUBSCRIBERS];
static int signal_index, service_index;        /* 1-based +CIND positions, 0 = unknown */
static uint8_t use_csq;                        /* no +CIND: ask +CSQ at each registration change */
static uint8_t clock_taken;                    /* the network's time was taken since this registration */

const struct net_status *network_status(void)
{
    return &st;
}

int network_registered(void)
{
    return st.reg == NET_HOME || st.reg == NET_ROAMING;
}

const char *network_label(void)
{
    if (st.sim == SIM_ABSENT)
        return "No SIM";
    if (network_registered())
        return st.operator_name[0] ? st.operator_name : "Network";
    if (st.reg == NET_SEARCHING || st.reg < 0)
        return st.reg < 0 && st.sim != SIM_READY ? "No network" : "Searching";
    return "No network";
}

void network_subscribe(struct task *t)
{
    for (unsigned i = 0; i < SUBSCRIBERS; i++)
        if (!subscribers[i] || subscribers[i] == t) {
            subscribers[i] = t;
            return;
        }
}

static void changed(void)
{
    st.changes++;
    for (unsigned i = 0; i < SUBSCRIBERS && subscribers[i]; i++)
        task_post(subscribers[i], MSG_NETWORK_CHANGED, 0, 0);
}

/* ---- the network's time (+CCLK) ---- */

/* "yy/MM/dd,hh:mm:ss±zz": the time is local time, zz its offset from UTC in quarters of an hour (27.007 8.15) */
static void cclk_line(void *ctx, const char *line)
{
    (void)ctx;
    char t[32];
    if (at_field_str(line, 0, t, sizeof t) || strlen(t) < 17)
        return;
    unsigned v[6];
    for (int i = 0; i < 6; i++) {
        const char *p = t + 3 * i;
        if (p[0] < '0' || p[0] > '9' || p[1] < '0' || p[1] > '9')
            return;
        v[i] = (unsigned)(p[0] - '0') * 10 + (unsigned)(p[1] - '0');
    }
    if (v[1] < 1 || v[1] > 12 || v[2] < 1 || v[2] > 31 || v[3] > 23 || v[4] > 59 || v[5] > 59)
        return;
    uint32_t local = (uint32_t)sms_days_from_civil(2000 + (int)v[0], v[1], v[2]) * 86400u + v[3] * 3600u +
                     v[4] * 60u + v[5];
    clock_taken = 1;
    if (!settings_get(SET_NET_TIME))
        return;
    int32_t offset = (int32_t)(local - clock_chip_seconds());
    int32_t now = settings_get(SET_CLOCK_OFFSET), diff = offset - now;
    if (diff >= -2 && diff <= 2) {
        kprintf("network: time %s, clock agrees\n", t);
        return;
    }
    kprintf("network: time %s, clock moved by %d s\n", t, diff);
    settings_set(SET_CLOCK_OFFSET, offset);
}

static void ask_time(void)
{
    struct at_cmd c = { .text = "AT+CCLK?", .prefix = "+CCLK:", .line = cclk_line };
    at_send(&c);
}

/* ---- operator, signal ---- */

static void cops_line(void *ctx, const char *line)
{
    (void)ctx;
    char name[sizeof st.operator_name];
    if (at_field_str(line, 2, name, sizeof name))
        name[0] = 0;               /* "+COPS: 0": not registered */
    if (strcmp(name, st.operator_name)) {
        strcpy(st.operator_name, name);
        changed();
    }
}

static void ask_operator(void)
{
    struct at_cmd c = { .text = "AT+COPS?", .prefix = "+COPS:", .line = cops_line };
    at_send(&c);
}

static void set_bars(int bars)
{
    if (bars < 0)
        bars = 0;
    if (bars > 5)
        bars = 5;
    if (st.bars != bars) {
        st.bars = (uint8_t)bars;
        changed();
    }
}

/* +CSQ <rssi> 0-31 (-113 to -51 dBm), 99 unknown: to five bars */
static void csq_line(void *ctx, const char *line)
{
    (void)ctx;
    int rssi;
    if (at_field_int(line, 0, &rssi))
        return;
    set_bars(rssi == 99 || rssi < 2 ? 0 : rssi < 8 ? 1 : rssi < 13 ? 2 : rssi < 18 ? 3 : rssi < 23 ? 4 : 5);
}

static void ask_signal(void)
{
    struct at_cmd c = { .text = "AT+CSQ", .prefix = "+CSQ:", .line = csq_line };
    at_send(&c);
}

/* ---- registration ---- */

static void set_reg(int reg, const char *line, unsigned lac_field)
{
    if (line) {
        at_field_str(line, lac_field, st.lac, sizeof st.lac);
        at_field_str(line, lac_field + 1, st.cell, sizeof st.cell);
    }
    if (reg == st.reg)
        return;
    int was = network_registered();
    st.reg = (int8_t)reg;
    kprintf("network: registration %d (%s)\n", reg, reg == NET_HOME ? "home" : reg == NET_ROAMING ? "roaming"
                                                   : reg == NET_SEARCHING ? "searching" : "not registered");
    if (network_registered() && !was) {
        if (!st.operator_name[0])
            ask_operator();
        clock_taken = 0;
        ask_time();
    } else if (!network_registered() && was) {
        st.operator_name[0] = 0;
        st.lac[0] = st.cell[0] = 0;
    }
    if (use_csq)
        ask_signal();
    changed();
}

/* URC "+CREG: <stat>[,<lac>,<ci>[,<AcT>]]" */
static void creg_urc(const char *line, const char *next)
{
    (void)next;
    int stat;
    if (!at_field_int(line, 0, &stat))
        set_reg(stat, line, 1);
}

/* answer to AT+CREG?: "+CREG: <n>,<stat>[,<lac>,<ci>[,<AcT>]]" */
static void creg_line(void *ctx, const char *line)
{
    (void)ctx;
    int stat;
    if (!at_field_int(line, 1, &stat))
        set_reg(stat, line, 2);
}

/* URC "+CIEV: <index>,<value>" */
static void ciev_urc(const char *line, const char *next)
{
    (void)next;
    int index, value;
    if (at_field_int(line, 0, &index) || at_field_int(line, 1, &value))
        return;
    if (index == signal_index)
        set_bars(value);
    else if (index == service_index && st.service != value) {
        st.service = (uint8_t)value;
        changed();
    }
}

/* "+CIND: ("signal",(0-5)),("service",(0,1)),...": the position of each indicator */
static void cind_test_line(void *ctx, const char *line)
{
    (void)ctx;
    unsigned index = 0;
    for (const char *p = strchr(line, '"'); p; p = strchr(p + 1, '"')) {
        const char *name = p + 1, *end = strchr(name, '"');
        if (!end)
            break;
        index++;
        unsigned n = (unsigned)(end - name);
        if (n == 6 && !memcmp(name, "signal", 6))
            signal_index = (int)index;
        else if (n == 7 && !memcmp(name, "service", 7))
            service_index = (int)index;
        p = end;
    }
}

static void cind_test_done(void *ctx, const struct at_result *r)
{
    (void)ctx;
    if (r->status != AT_OK || !signal_index) {
        kprintf("network: no signal indicator (+CIND), using +CSQ\n");
        use_csq = 1;
    }
}

/* "+CIND: 5,1,0": the values in that order */
static void cind_line(void *ctx, const char *line)
{
    (void)ctx;
    int v;
    if (signal_index && !at_field_int(line, (unsigned)signal_index - 1, &v))
        set_bars(v);
    if (service_index && !at_field_int(line, (unsigned)service_index - 1, &v))
        st.service = (uint8_t)v;
}

/* ---- card, own number ---- */

static void cpin_line(void *ctx, const char *line)
{
    (void)ctx;
    char s[24];
    at_field_str(line, 0, s, sizeof s);
    st.sim = strcmp(s, "READY") ? SIM_NOT_READY : SIM_READY;
    if (st.sim != SIM_READY)
        kprintf("network: card not ready (%s)\n", s);     /* PIN entry is not Myna's business here (closed area) */
}

static void cpin_done(void *ctx, const struct at_result *r)
{
    (void)ctx;
    if (r->status == AT_CME && r->code == 10)
        st.sim = SIM_ABSENT;
    else if (r->status != AT_OK)
        st.sim = SIM_NOT_READY;
    kprintf("network: card %s\n", st.sim == SIM_READY ? "ready" : st.sim == SIM_ABSENT ? "absent" : "not ready");
    changed();
}

static void cnum_line(void *ctx, const char *line)
{
    (void)ctx;
    char n[sizeof st.own_number];
    if (!at_field_str(line, 1, n, sizeof n) && n[0] && strcmp(n, st.own_number)) {
        strcpy(st.own_number, n);
        kprintf("network: own number %s\n", n);
        changed();
    }
}

/* ---- bring-up ---- */

void network_init(void)
{
    at_urc("+CREG:", 0, creg_urc);
    at_urc("+CIEV:", 0, ciev_urc);
}

void network_modem_lost(void)
{
    st.reg = -1;
    st.bars = 0;
    st.operator_name[0] = 0;
    changed();
}

void network_bringup_card(void)
{
    struct at_cmd c = { .text = "AT+CPIN?", .prefix = "+CPIN:", .line = cpin_line, .done = cpin_done };
    at_send(&c);
    at_simple("AT+CFUN=1", 0, 0);
}

void network_bringup_reg(void)
{
    at_simple("AT+CREG=2", 0, 0);
    struct at_cmd test = { .text = "AT+CIND=?", .prefix = "+CIND:", .line = cind_test_line, .done = cind_test_done };
    at_send(&test);
    at_simple("AT+CMER=3,0,0,1", 0, 0);
    struct at_cmd read = { .text = "AT+CIND?", .prefix = "+CIND:", .line = cind_line };
    at_send(&read);
}

void network_bringup_identity(void)
{
    struct at_cmd cnum = { .text = "AT+CNUM", .prefix = "+CNUM:", .line = cnum_line };
    at_send(&cnum);
    at_simple("AT+COPS=3,0", 0, 0);
    ask_operator();
    struct at_cmd creg = { .text = "AT+CREG?", .prefix = "+CREG:", .line = creg_line };
    at_send(&creg);
}
