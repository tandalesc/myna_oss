# SPDX-License-Identifier: MIT
# Build of the Myna firmware with tools that are already on a Mac with Xcode's command-line tools and Rust (rustup):
#   compiler  clang (Apple's, or any clang with the ARM target)
#   linker    rust-lld in GNU mode (`rust-lld -flavor gnu`), and rust-objcopy: both come with every Rust toolchain
#   host      cc, for the font tool (myna/tools/mkfont.c) that turns the TrueType font into glyph atlases at build time,
#             and python3 (standard library only) for the image tool (myna/tools/mkassets.py)
#
#   make                       -> build/myna.elf (what the simulator loads), build/myna.bin, build/myna.map
#   make BENCH=1               the same, with drawing benchmarks and the cost of a minute printed on the console
#   make DEFS=-DMYNA_FAULT_TEST=1   a build that runs into an undefined instruction at start (the fault report)
#   make DEFS=-DMYNA_NAND_TEST=1    a build that tests the NAND driver on the chip's last block at start
#                              (after a change of BENCH or DEFS: make clean first)
#   make clean
#   make LLD=/path/ld.lld OBJCOPY=/path/llvm-objcopy CC=/path/clang HOSTCC=cc PYTHON=python3   other tools
#
# The rust tools are looked for: on the PATH, then in the sysroot of `rustc`, then in any toolchain under ~/.rustup.

ifeq ($(origin CC),default)
CC := clang
endif
HOSTCC ?= cc

RUST_BIN := $(shell rustc --print sysroot 2>/dev/null)/lib/rustlib/$(shell rustc -vV 2>/dev/null | sed -n 's/^host: //p')/bin
find_tool = $(firstword $(shell command -v $(1) 2>/dev/null) $(wildcard $(RUST_BIN)/$(1)) \
                        $(wildcard $(HOME)/.rustup/toolchains/*/lib/rustlib/*/bin/$(1)))
LLD ?= $(call find_tool,rust-lld)
OBJCOPY ?= $(call find_tool,rust-objcopy)
ifeq ($(LLD),)
$(error rust-lld not found: install a Rust toolchain with rustup, or give LLD=/path/to/ld.lld)
endif
ifeq ($(OBJCOPY),)
$(error rust-objcopy not found: give OBJCOPY=/path/to/llvm-objcopy)
endif

LFS_DIR := ../third_party/littlefs

# ARMv5TE, the ARM926EJ-S; ARM state (not Thumb): the simulator charges per instruction, and ARM code is the simpler
# one to read in a trace. Soft float: the DB3210's application CPU has no floating-point unit.
ARCH   := --target=armv5te-none-eabi -mcpu=arm926ej-s -marm -mfloat-abi=soft
CFLAGS := $(ARCH) -std=c11 -O2 -g -Wall -Wextra -Werror -ffreestanding -nostdlib -fno-common \
          -ffunction-sections -fdata-sections -Isrc -Ibuild/gen -I$(LFS_DIR) -DLFS_CONFIG=fs/lfs_port.h
ifeq ($(BENCH),1)
CFLAGS += -DMYNA_BENCH=1
endif
CFLAGS += $(DEFS)              # make DEFS=-DMYNA_FAULT_TEST=1: other build switches (make clean first)
ASFLAGS := $(ARCH) -g -Isrc
LDFLAGS := -flavor gnu -T link.ld --gc-sections -nostdlib -static -Map build/myna.map

# littlefs (myna/third_party/littlefs, unchanged): compiled with its own warnings relaxed; its system header is ours
LFS_CFLAGS := $(filter-out -Werror -Wextra,$(CFLAGS)) -Wno-unused-function

# glyph atlases: per weight of Nunito its file, its name in C, mkfont's options and its sizes with their character sets
# (mkfont.c says how). The sizes are the type scale of the themes (src/ui/theme.c); a size no theme uses is wasted
# space. Text sizes have three phases (glyphs placed at a third of a pixel) and a coverage gamma that brings the weight
# close to a browser's rendering of the design; the clock's digits sit in whole-pixel cells. Cyrillic is in the sizes
# that show what people write (message text and headers, list rows and their values, titles, the status bar's
# network name); the others draw '?' for it. Nunito has no Greek.
FONT_GAMMA            ?= 0.75
FONT_TEXT_OPTS        := phases=3 gamma=$(FONT_GAMMA)
FONT_WEIGHTS          := light semibold bold extrabold
FONT_FILE_light       := ../assets/fonts/Nunito-Light.ttf
FONT_OPTS_light       := gamma=$(FONT_GAMMA)
FONT_SIZES_light      := '60:0123456789: ' '30:0123456789+*\# '
FONT_OPTS_semibold    := $(FONT_TEXT_OPTS)
FONT_OPTS_bold        := $(FONT_TEXT_OPTS)
FONT_OPTS_extrabold   := $(FONT_TEXT_OPTS)
FONT_FILE_semibold    := ../assets/fonts/Nunito-SemiBold.ttf
FONT_SIZES_semibold   := 11 12:text+cyrillic 13:text+cyrillic 14:text+cyrillic
FONT_FILE_bold        := ../assets/fonts/Nunito-Bold.ttf
FONT_SIZES_bold       := 11:text+cyrillic 13 14
FONT_FILE_extrabold   := ../assets/fonts/Nunito-ExtraBold.ttf
FONT_SIZES_extrabold  := 11 12 13 14:text+cyrillic 15:text+cyrillic

# images (icons, wallpapers, the selection tile, status signs) rendered from the design's drawings by a stdlib Python
# tool; no browser and no image library is needed
PYTHON      ?= python3
ASSET_SRCS  := $(wildcard ../assets/design/*.py) ../tools/mkassets.py ../tools/svgraster.py ../tools/png.py
# the dictionary of predictive text: the ranked word list (12dicts) indexed by key sequence (myna/tools/mkdict.py)
DICT_SRCS   := ../assets/words/en.txt ../tools/mkdict.py

SRC_C := $(wildcard src/*.c src/*/*.c)
SRC_S := $(wildcard src/*.S src/*/*.S)
HDRS  := $(wildcard src/*.h src/*/*.h)
OBJS  := $(patsubst src/%.c,build/obj/%.o,$(SRC_C)) $(patsubst src/%.S,build/obj/%.S.o,$(SRC_S)) \
         $(patsubst %,build/obj/gen/fonts_%.o,$(FONT_WEIGHTS)) build/obj/gen/assets.o build/obj/lfs/lfs.o \
         build/obj/gen/dict_data.o

all: build/myna.elf build/myna.bin

build/obj/%.o: src/%.c $(HDRS) build/gen/fonts.h build/gen/assets.h build/gen/dict_data.h
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

build/obj/%.S.o: src/%.S
	@mkdir -p $(dir $@)
	$(CC) $(ASFLAGS) -c $< -o $@

# the font pipeline: a host tool (stb_truetype) renders the TrueType file into C arrays, compiled like any source
build/host/mkfont: ../tools/mkfont.c ../third_party/stb/stb_truetype.h
	@mkdir -p $(dir $@)
	$(HOSTCC) -O2 -w -I../third_party/stb -o $@ $< -lm

.PRECIOUS: build/gen/fonts_%.c             # keep the generated atlases (they are worth reading)
.SECONDEXPANSION:
build/gen/fonts_%.c: build/host/mkfont $$(FONT_FILE_$$*) Makefile
	@mkdir -p $(dir $@)
	build/host/mkfont $@ $(FONT_FILE_$*) nunito_$* $(FONT_OPTS_$*) $(FONT_SIZES_$*)

build/gen/fonts.h: Makefile
	@mkdir -p $(dir $@)
	@printf '/* Generated by the Makefile: the glyph atlases of build/gen/fonts_*.c */\n#include "gfx/font.h"\n' > $@
	@$(foreach w,$(FONT_WEIGHTS),for s in $(FONT_SIZES_$(w)); do \
	    printf 'extern const struct font font_nunito_$(w)_%s;\n' $${s%%:*} >> $@; done;)

# the images: build/gen/assets.c and assets.h (and build/gen/preview/*.png to look at)
build/gen/assets.c: $(ASSET_SRCS)
	@mkdir -p $(dir $@)
	$(PYTHON) -I -B ../tools/mkassets.py build/gen
build/gen/assets.h: build/gen/assets.c

# the dictionary: build/gen/dict_data.c and dict_data.h
build/gen/dict_data.c: $(DICT_SRCS)
	@mkdir -p $(dir $@)
	$(PYTHON) -I -B ../tools/mkdict.py ../assets/words/en.txt build/gen
build/gen/dict_data.h: build/gen/dict_data.c

build/obj/gen/%.o: build/gen/%.c src/gfx/font.h src/gfx/image.h
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

build/obj/lfs/lfs.o: $(LFS_DIR)/lfs.c $(LFS_DIR)/lfs.h $(LFS_DIR)/lfs_util.h src/fs/lfs_port.h
	@mkdir -p $(dir $@)
	$(CC) $(LFS_CFLAGS) -c $< -o $@

build/myna.elf: $(OBJS) link.ld
	$(LLD) $(LDFLAGS) $(OBJS) -o $@

build/myna.bin: build/myna.elf
	$(OBJCOPY) -O binary $< $@

# host tests of the codecs (text message PDUs, GSM 7-bit alphabet, vCard, phone numbers) and of the dictionary:
# built with the host cc
HOST_TEST_SRC := test/test_codecs.c src/lib/gsm7.c src/lib/sms_pdu.c src/lib/vcard.c src/lib/phonenum.c \
                 src/lib/keyseq.c
HOST_DICT_SRC := test/test_dict.c src/lib/dict.c build/gen/dict_data.c

host-test: build/host/test_codecs build/host/test_dict
	build/host/test_codecs
	build/host/test_dict

build/host/test_codecs: $(HOST_TEST_SRC) $(HDRS)
	@mkdir -p $(dir $@)
	$(HOSTCC) -std=c11 -O1 -g -Wall -Wextra -Werror -Isrc -fsanitize=address,undefined -o $@ $(HOST_TEST_SRC)

build/host/test_dict: $(HOST_DICT_SRC) src/lib/dict.h build/gen/dict_data.h
	@mkdir -p $(dir $@)
	$(HOSTCC) -std=c11 -O1 -g -Wall -Wextra -Werror -Isrc -Ibuild/gen -DMYNA_DICT_STATS=1 \
	    -fsanitize=address,undefined -o $@ $(HOST_DICT_SRC)

clean:
	rm -rf build

.PHONY: all clean host-test
