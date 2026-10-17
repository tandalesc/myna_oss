/* SPDX-License-Identifier: MIT */
/* The built-in dictionary of predictive text: about 32,000 English words ranked by frequency (12dicts, public domain
 * with the AGID notice: myna/assets/words), indexed by key sequence at build time (myna/tools/mkdict.py).
 *
 * A key sequence is the keys that type a word once each: 2 abc, 3 def, 4 ghi, 5 jkl, 6 mno, 7 pqrs, 8 tuv, 9 wxyz,
 * and 1 for an apostrophe ("4663" is good, home, gone, hood ...; "416" is I'm). Words keep their case ("I",
 * "Monday"). The index is in .rodata; nothing is allocated, nothing is kept between calls.
 *
 * Out: a word is copied into out and terminated; a word longer than max - 1 bytes is cut to fit. */
#ifndef MYNA_LIB_DICT_H
#define MYNA_LIB_DICT_H

/* candidate n (0 = the most frequent) whose key sequence is exactly `keys` ("4663"); the word into out (terminated,
   at most max bytes); returns its length, or 0 if there is no such candidate */
int dict_exact(const char *keys, unsigned n, char *out, unsigned max);

/* candidate n among the distinct beginnings (as long as keys) of longer words whose sequence starts with keys,
   ordered by the frequency of the best word with that beginning (beginnings that differ only in case are one, with
   the case of the best word); for a key sequence that is not (yet) a word: "23288" gives "beaut" (beautiful) */
int dict_prefix(const char *keys, unsigned n, char *out, unsigned max);

/* The most frequent longer word whose first letters are the letters `shown` (as long as keys; compared without
   regard to case) and whose key sequence starts with keys, when it is worth offering: it is among the 8,000 most
   frequent words, it adds at least two letters, and it is more frequent than `shown` itself if that is a word. The
   whole word into out, its beginning as `shown` has it ("Beau" -> "Beautiful"); returns its length, or 0. Needs at
   least two keys. */
int dict_complete(const char *keys, const char *shown, char *out, unsigned max);

unsigned dict_words(void);     /* words in the index */

#ifdef MYNA_DICT_STATS
/* entries read by the last call (for measurements) */
extern unsigned dict_stat_entries;
#endif

#endif
