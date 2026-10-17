# Words of predictive text

- `en.txt`: 32,000 English words, one a line, the most frequent first. Made once by `myna/tools/importwords.py` from
  12dicts 6.0.2 by Alan Beale (`Lemmatized/2+2+3frq.txt`: lemmas in frequency bands from the BYU Corpus of
  Contemporary American English; `Lemmatized/2+2+3lem.txt`: their inflections), plus `extra.txt`.
  Source: http://wordlist.aspell.net/12dicts/, archive http://downloads.sourceforge.net/wordlist/12dicts-6.0.2.zip
  (SHA-256 `64ac1d35acb66b550c7ebc56e080b62e0bad8f5984d72059dc2e05ac48780e52`). Licence: public domain, with the
  permissive notice of AGID, on which the lemmatised lists depend: `LICENSE-12dicts.txt`.
- `extra.txt`: the project's own short list (MIT): common contractions (don't, I'm ...) and "ok", "okay", which the
  source does not have.

The firmware's build indexes `en.txt` by key sequence (`myna/tools/mkdict.py`, read by `src/lib/dict.c`).
