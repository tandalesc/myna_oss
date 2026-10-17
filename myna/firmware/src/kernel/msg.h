/* SPDX-License-Identifier: MIT */
/* Message types: one list for the whole firmware, so a number means one thing everywhere and a log shows it plainly. */
#ifndef MYNA_KERNEL_MSG_H
#define MYNA_KERNEL_MSG_H

enum msg_type {
    MSG_NONE = 0,
    MSG_START,                 /* first message of every task, posted by main() */
    MSG_TIMER,                 /* a software timer expired; a = the timer's id (kernel/timer.h) */

    /* keypad driver -> its subscriber: a = key index (drivers/keypad.h) */
    MSG_KEY_DOWN,
    MSG_KEY_UP,
    MSG_KEYPAD_SCAN,           /* keypad interrupt -> keypad task: look at the matrix */

    /* display driver */
    MSG_DISPLAY_DONE,          /* refresh controller: every queued update has gone to the panel */

    /* slide switch -> its subscriber: a = 1 open, 0 closed */
    MSG_SLIDE,

    /* settings service -> subscribers: a = the setting (services/settings.h), b = its new value */
    MSG_SETTING_CHANGED,

    /* user interface */
    MSG_PAINT,                 /* redraw what changed (posted by a task to itself, once per batch of changes) */

    /* modem (src/modem/) */
    MSG_LINK_RX,               /* link channel 0 -> modem task: bytes from the modem are waiting */
    /* network service -> subscribers: card, registration, operator, signal or own number changed */
    MSG_NETWORK_CHANGED,

    /* text message service (src/sms/) */
    MSG_SMS_EVENT,             /* -> subscribers: a = enum sms_event, b = the message id */
    MSG_SMS_KICK,              /* the service to itself: look at the send queue */
    MSG_SMS_SENT,              /* +CMGS answered: a = enum at_status + 8, b = the +CMS ERROR code */
    MSG_SMS_INCOMING,          /* a +CMT or +CDS PDU waits in slot a */
};

#endif
