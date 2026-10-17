# Third-party content

Myna, the simulator's part that it runs on, the compiled core, the phone page and the relay have the MIT licence,
copyright (c) 2026 Shishir Tandale. The text is in `LICENSE`. This document lists the content in this tree that comes
from other sources, and the software that the tree uses but does not include. For each item it gives the licence, where
the licence text is, and how the licence was found.

## 1. Content in the tree

| Item | Location | Licence | Licence text | Source |
|---|---|---|---|---|
| stb_truetype 1.26 (Sean Barrett) | `myna/third_party/stb/stb_truetype.h` | MIT or public domain (Unlicense), the user's choice. Copyright (c) 2017 Sean Barrett. | `myna/third_party/stb/LICENSE`; the same text is at the end of the header file | Both files copied unchanged from `https://raw.githubusercontent.com/nothings/stb/2c980bb59875b0d32144a71867fbdebb2f77cd20/` (SHA-256 of the header `ecd30b05e0dd4fea3a13c26810dd9e1992dc379049482c393d5a19e6b5090aab`). Used only by the build-host tool `myna/tools/mkfont.c`; no part of it is in the firmware image. |
| Nunito 3.601, the static Light, SemiBold, Bold and ExtraBold fonts | `myna/assets/fonts/Nunito-Light.ttf`, `Nunito-SemiBold.ttf`, `Nunito-Bold.ttf`, `Nunito-ExtraBold.ttf` | SIL Open Font License 1.1. Copyright 2014 The Nunito Project Authors. No Reserved Font Name. | `myna/assets/fonts/Nunito-OFL.txt` | The Nunito project, `https://github.com/googlefonts/nunito`: `fonts/TTF/Nunito-<weight>.ttf` copied unchanged from commit `ed889dda6d742a0495c1963898e1b3567ab61a15` (SHA-256 Light `b91b65047974abea9f5190de9aa4284dbd76bdf31f72f17da8e322d1345fddd9`, SemiBold `b993b443935abd1e26e290c20ba3febf1c2bb752eeabbb88cfb399c877f947af`, Bold `f922b74ed5cca7c8675d352fd5ed197e0f38b3ac4a427c15b7a3db039dc6294c`, ExtraBold `2d0979711b8cdf8be91827776b493e5483e639985d79acd937d752e1c13ce6c6`). The build renders glyph bitmaps from them into `myna/firmware/build/gen/fonts_*.c`, which carry the same licence; a firmware binary contains those bitmaps, so it must come with the licence text. |
| littlefs 2.11.3 | `myna/third_party/littlefs/`: `lfs.c`, `lfs.h`, `lfs_util.c`, `lfs_util.h`, `README.md` | BSD 3-Clause. Copyright (c) 2022, The littlefs authors; Copyright (c) 2017, Arm Limited. | `myna/third_party/littlefs/LICENSE.md` | `https://github.com/littlefs-project/littlefs`, release tag `v2.11.3`, files copied unchanged from the release archive (SHA-256 `15521be8aaed133c453e7337714e029a9f62480ab41f59c4ba5d18297a076207`). `lfs.c` is compiled into the firmware image; `lfs_util.h` is replaced at build time by Myna's `myna/firmware/src/fs/lfs_port.h` (MIT) through `LFS_CONFIG`; `lfs_util.c` is not compiled. A binary of the firmware must carry the littlefs copyright notice and licence. |
| Drawings of the phone and of Myna's design | `native/devices/myna/skin/`, `native/devices/myna_flip/skin/`, `myna/assets/design/`, `myna/web/icons/` | MIT, as the project | `LICENSE` | Made for this project by the scripts next to them (`draw.py`, the design's `*.py`, `icons/make.sh`). No photograph is included or traced. |

The tree contains no photograph of a phone and no firmware of any phone maker.

## 2. Software that the tree uses and does not include

| Item | Use | Licence |
|---|---|---|
| Pyodide (tested: 314.0.7) | The phone page runs the simulator's Python under it. Downloaded by whoever serves the page; `myna/web/serve.py --pyodide DIR` | Mozilla Public License 2.0 (Pyodide), with the licences of the Python standard library and the packages it carries |
| Rust (`rustc`, `cargo`, `rust-lld`, `rust-objcopy`) | Builds the compiled core, links Myna | MIT or Apache 2.0 |
| clang | Compiles Myna | Apache 2.0 with LLVM exceptions |
| Python 3.10 or later | The simulator, the build tools of Myna, the page's server | Python Software Foundation License |
| Node.js, `wrangler`, `typescript`, `@cloudflare/workers-types` (installed by `npm install` in `myna/relay`, `package-lock.json`) | The relay: local runs, tests, deploy | MIT (Node.js), MIT or Apache 2.0 (wrangler, workers-types), Apache 2.0 (TypeScript) |
| Chrome or Chromium | The page's tests (`myna/web/test/`) and the icons (`myna/web/icons/make.sh`) | BSD-style (Chromium) |
| Unicorn | Not needed. The launcher can use it instead of the compiled core where it is installed | GNU GPL 2 |

## 3. Facts about the hardware

Myna was written against a specification of the hardware (`myna/spec/`). The simulator's device models in `native/`
describe the hardware's registers, bits and timings, which were learnt by observing how the phone's original software uses
the hardware, for interoperability. The release carries no code, data tables, calibration, images, sounds, fonts or text of
that software: the values of the phone's board that the models need (the battery thermistor, the converter ranges) are
Myna's own, stated in its device profile (`native/devices/myna/__init__.py`, `PMIC_ANALOG`) and in `myna/spec/`.
