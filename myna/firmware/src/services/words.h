/* SPDX-License-Identifier: MIT */
/* Predictive text: the words that fit a key sequence, from the built-in English word list (lib/dict.h) and the
 * user's own words ("My words").
 *
 * A key sequence is the digits pressed, one per letter: 2 abc, 3 def, 4 ghi, 5 jkl, 6 mno, 7 pqrs, 8 tuv, 9 wxyz, and
 * 1 for an apostrophe inside a word ("I'm" is 4-1-6). Candidates come in this order: the user's words with exactly
 * that sequence (the most recently used first), the word list's (the most frequent first), and, when no word has
 * that sequence, the beginnings of longer words (so a word being typed shows letters that lead somewhere).
 *
 * My words: a word spelled letter by letter, or a word chosen over the first candidate, goes to the front of the
 * user's list, so it comes first the next time. The list (at most WORDS_USER_MAX, the least recently used dropped)
 * is the file /words on the user file system, one word per line, the most recent first; it is read at the first use
 * and written whole (atomically) when it changes. All of this runs in the UI task. */
#ifndef MYNA_SERVICES_WORDS_H
#define MYNA_SERVICES_WORDS_H

#include <stdint.h>

#define WORD_MAX        32     /* a word with its 0 */
#define WORDS_CANDIDATES 12    /* candidates offered for one sequence, at most */
#define WORDS_USER_MAX  200

/* the key of a character: '2'-'9' for a letter (lib/keyseq.h: accented letters on their base letter's key,
   Cyrillic on the Russian layout), '1' for an apostrophe, 0 for anything else */
char words_key(uint32_t c);
/* the key sequence of a word (UTF-8) into keys (max bytes with the 0); returns its length, or -1 if a character has no
   key */
int words_keys_of(const char *word, char *keys, unsigned max);

/* the candidates for keys into out[0..WORDS_CANDIDATES), each a word; returns how many. *exact gets 1 if they are
   whole words, 0 if they are beginnings of longer ones */
int words_candidates(const char *keys, char out[][WORD_MAX], int *exact);
/* a longer word worth offering after `shown` (the candidate on the screen for keys): the whole word into out
   (WORD_MAX); returns its length, or 0 */
int words_complete(const char *keys, const char *shown, char *out);
/* a word was used: spelled, or chosen when it was not the first candidate. It goes to the front of My words. */
void words_learn(const char *word);

/* My words, the most recent first: the word at i, or 0 past the end; and forgetting one */
const char *words_user(unsigned i);
void words_forget(unsigned i);

#endif
