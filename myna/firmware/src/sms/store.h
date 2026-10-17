/* SPDX-License-Identifier: MIT */
/* The message store: text messages on the user file system.
 *
 *   /sms/index      every message's record (struct sms_record: number, direction, state, times, parts, cause),
 *                   oldest first: read whole at start (one file: about 1 ms for any number of messages), rewritten
 *                   whole at every change, which littlefs makes atomic (the old or the new index, never a mixture)
 *   /sms/m/<id>     the text of one message (UTF-8), written once; its record at creation rides along as a littlefs
 *                   attribute, so a message whose index entry was not written yet (a power cut between the two
 *                   commits) is found again at the next start
 *   /sms/p/<...>    one part of a concatenated message that has not come whole yet: the sender's match key, the
 *                   reference, the count and the number of the part in the name, the part's text and record inside
 *   /sms/d/<key>    the unsent draft of one conversation (the number's match key in the name): its text (UTF-8),
 *                   with the number and the time it was left as an attribute, in one commit
 *
 * The records are kept in RAM as well, so lists, counts and states cost no flash reads; reading a text costs one
 * file lookup. A received message (or part) is on flash before it is acknowledged, so a power cut loses none.
 *
 * At most SMS_STORE_CAP messages are kept: storing one more first deletes the oldest that is not waiting to be
 * sent. When the file system is full (littlefs: no space), storing fails with STORE_FULL: the message service then
 * refuses the message with "memory capacity exceeded", and the network keeps it. */
#ifndef MYNA_SMS_STORE_H
#define MYNA_SMS_STORE_H

#include <stdint.h>

#include "lib/sms_pdu.h"

#define SMS_STORE_CAP   500
#define SMS_NUMBER_MAX  24
#define SMS_TEXT_MAX    2904       /* 6 parts of SMS_PART_TEXT_MAX: the most UTF-8 six received parts can carry */

enum sms_dir { SMS_IN = 0, SMS_OUT = 1 };

enum sms_state {
    SMS_QUEUED = 1,            /* out: waiting to be sent (also while it is being sent) */
    SMS_SENT,                  /* out: the network took every part */
    SMS_FAILED,                /* out: refused; `cause` says why */
    SMS_RECEIVED,              /* in: not read yet */
    SMS_READ,                  /* in: read */
    SMS_DELIVERED,             /* out: a status report said it arrived */
};

/* causes that are not the network's (the network's are RP causes 1-127 of 3GPP TS 24.011 table 8.4, or +CMS
 * ERROR codes 300-511 of 27.005) */
#define SMS_CAUSE_NO_ANSWER  1000  /* the modem never answered */
#define SMS_CAUSE_TOO_LONG   1001
#define SMS_CAUSE_BAD_NUMBER 1002

struct sms_record {
    uint32_t id;
    uint32_t time;             /* the phone's clock (clock_seconds) when it was written or received */
    uint32_t sc_time;          /* received: the centre's time stamp (UTC); sent: the phone's clock when accepted */
    uint8_t dir, state;
    uint8_t parts, parts_done; /* out: parts of the text, parts the network has taken */
    uint16_t cause;
    uint16_t text_len;
    uint8_t ref;               /* out: the concatenation reference */
    uint8_t attempts;          /* out: sends that failed for a passing reason */
    uint8_t flags;
    uint8_t version;
    uint8_t mr[6];             /* out: the message reference the network gave each part */
    uint8_t pad[2];
    char number[SMS_NUMBER_MAX];
};

#define SMS_FLAG_CLASS0  0x01  /* a "flash" message (class 0): to be shown at once */

/* RAM index entry: oldest first (ids grow with time) */
struct store_entry {
    uint32_t id;
    uint32_t time;
    uint32_t key;              /* phonenum_key() of the number: the conversation */
    uint8_t dir, state;
    uint16_t cause;
};

enum { STORE_OK = 0, STORE_FULL = -1, STORE_ERROR = -2, STORE_NOT_FOUND = -3 };

int store_init(void);                          /* mount the folders, read the index; 0 = usable */
int store_ready(void);

/* Store a new message (r->id is given here). 0, STORE_FULL or STORE_ERROR. */
int store_add(struct sms_record *r, const char *text);
/* Write a changed record (state, cause, parts done ...). */
int store_update(const struct sms_record *r);
/* Read a record and its text (text may be 0; max bytes with the 0). */
int store_read(uint32_t id, struct sms_record *r, char *text, unsigned max);
int store_delete(uint32_t id);

const struct store_entry *store_index(unsigned *count);
const struct store_entry *store_find(uint32_t id);
unsigned store_unread(void);

/* ---- parts of an incoming concatenated message ---- */

struct store_part_key {
    uint32_t key;              /* phonenum_key() of the sender */
    uint16_t ref;
    uint8_t total;
};

int store_part_exists(const struct store_part_key *k, unsigned seq);      /* from RAM */
int store_part_put(const struct store_part_key *k, unsigned seq, const struct sms_record *r, const char *text,
                   unsigned len);
/* the part's text into out (max bytes); its record into r (may be 0). Returns the length or < 0. */
int store_part_read(const struct store_part_key *k, unsigned seq, struct sms_record *r, char *out, unsigned max);
void store_part_delete(const struct store_part_key *k, unsigned seq);
unsigned store_parts_waiting(void);

/* ---- drafts: the unsent text of a conversation ---- */

#define STORE_DRAFTS     16        /* drafts kept: one more replaces the oldest */
#define STORE_DRAFT_HEAD 48        /* the start of a draft's text kept in RAM (UTF-8, whole characters) */

struct store_draft {
    uint32_t key;              /* phonenum_key() of the number: the conversation */
    uint32_t time;             /* the phone's clock when it was left */
    char number[SMS_NUMBER_MAX];
    char head[STORE_DRAFT_HEAD];   /* the first characters, for the list */
};

/* Keep the draft of `number` (UTF-8, len bytes); an empty text deletes it. 0 or a STORE_* error. */
int store_draft_put(const char *number, uint32_t time, const char *text, unsigned len);
/* the draft's text into out (max bytes with the 0); its length, or STORE_NOT_FOUND */
int store_draft_get(uint32_t key, char *out, unsigned max);
void store_draft_delete(uint32_t key);
const struct store_draft *store_draft_find(uint32_t key);     /* from RAM; 0 if none */
const struct store_draft *store_drafts(unsigned *count);

/* testing: make every store_add / store_part_put answer STORE_FULL. A build with -DMYNA_TEST_HOOKS=1 switches it
 * from the dialer (src/apps/dialer.c: *#3678*1# on, *#3678*0# off); nothing else calls it. */
void store_simulate_full(int on);
int store_simulating_full(void);

struct store_stats {
    uint32_t init_us, entries;
    uint32_t last_add_us, last_update_us;
    uint32_t adds, updates, deletes, evicted;
};
const struct store_stats *store_stats(void);

#endif
