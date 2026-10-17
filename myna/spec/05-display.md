# 05 Display

## 1. Overview

- Panel: 240 x 320 pixels, portrait, colour. The real part is a Samsung S6D14A0 with a command set like MIPI DCS.
- Display controller ("XGAM"), base 0xD0000000, 2 MB window. Sub-blocks:

  | Offset | Sub-block | Use |
  |---|---|---|
  | +0x0000-+0x07FF | Bus and memory controller | Version register, GRAM bank registers, cache control |
  | +0x0800-+0x0BFF | Camera data interface | `12-video-camera-other.md` |
  | +0x0C00-+0x0FFF | Camera interface controller | `12-video-camera-other.md` |
  | +0x1000-+0x13FF | Panel bus engine | Commands and register reads to the panel |
  | +0x1400-+0x17FF | Refresh controller | Sends a rectangle of a RAM surface to the panel |
  | +0x1800-+0x1BFF | 2D accelerator | Not executed by the model |
  | +0x1C00-+0x1CFF | Motion-compensation / inverse-DCT block | `12-video-camera-other.md` |
  | +0x100000-+0x10FFFF | GRAM bank 0: 64 KB of internal RAM (CPU address 0xD0100000) | |

- There is no fixed framebuffer. The refresh controller reads pixels from RAM through "GRAM offsets". A GRAM offset is (bank << 20) | (offset within a 1 MB block). Bank 0 is the internal RAM. Banks 1 to 15 are 1 MB blocks of SDRAM that the firmware chooses with the bank registers.
- A picture reaches the viewer only when the firmware starts an update of the refresh controller. There is no periodic refresh, no vertical-blank and no tearing signal.

## 2. End-to-end: framebuffer to screen

Validated sequence for a 240 x 320 RGB565 framebuffer at physical 0x4A000000 [VALIDATED]:

1. Write the pixels into RAM at 0x4A000000: 240 pixels per line, 2 bytes per pixel, little-endian RGB565 (red bits 15:11, green 10:5, blue 4:0), lines top to bottom.
2. XGAM +0x404 (bank 1) = 0x4A0 (physical address >> 20).
3. +0x1440 = 240 | (320 << 16) (panel size).
4. +0x1458 = 16 (source bits per pixel). +0x1444 = 0x10 (output depth).
5. +0x1450 = 0x00100000 (GRAM offset of the surface: bank 1, offset 0). +0x1454 = 240 (source line length in pixels).
6. +0x1460 = 0 (upright).
7. +0x1448 = 0 (update origin x | y << 16). +0x144C = 240 | (320 << 16) (update size).
8. +0x1418 = 1 (update-done interrupt enable) and enable line 18 in VIC0.
9. +0x1404 = 2 (start). The model builds the picture at this write and sends it to the viewer. +0x1420 bit 0 becomes 1 and line 18 goes high.
10. In the line 18 handler: +0x1424 = 1.

For a partial update, set +0x1448 and +0x144C to the rectangle. The rest of the screen keeps the previous picture. Repeat steps 7, 9, 10 for every update.

## 3. Bus and memory controller

| Offset | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| +0x000 | VERSION | R | 0x00004101 | Bits 15:8 = 0x41 identify the controller; bits 7:0 = revision 1. |
| +0x004 | CONTROL | S | 0 | |
| +0x008 | MASK | S | 0 | |
| +0x010-+0x018 | - | S | 0 | |
| +0x01C | STATUS | W1C | 0 | No model sets a bit. Line 13 is never raised. |
| +0x404-+0x43C | BANK1-BANK15 | RW | 0 | Bank i (register +0x400 + 4 x i): bits 11:0 = physical address >> 20 of the 1 MB block. |
| +0x444-+0x450 | CACHE_CONTROL 0-3 | RW | 0 | Writing a value with bit 2 set (flush request) completes at once: bits 4:2 then read 0 [MODEL]. Bit 3 = dirty, bit 4 = busy: never set. |

- GRAM offset to physical address: bank 0: 0xD0100000 + (offset & 0xFFFFF); bank i >= 1: (BANKi & 0xFFF) << 20 | (offset & 0xFFFFF).
- A surface may cross from one bank into the next bank number. It must lie where the bank registers point.
- The internal RAM (bank 0) is read and written by the CPU at 0xD0100000 like normal memory.

## 4. Refresh controller (+0x1400)

| Offset | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| +0x1404 | COMMAND | RW | 0 | Writing 2 or 3 starts an update (section 4.1). Other values: stored. |
| +0x1408 | STATUS | R | 0 | Bit 0 = busy: always reads 0 (an update completes at once) [MODEL]. Other bits: last value written. |
| +0x1410 | CONTROL | RW | 0 | Bits 9:8 = 3: video plane on (section 4.3). Other bits stored. |
| +0x1418 | IRQ_ENABLE | RW | 0 | Bit 0 = update-done interrupt (line 18) enabled. |
| +0x141C | - | RW | 0 | Stored. A write re-evaluates line 18. |
| +0x1420 | IRQ_STATUS | R | 0 | Bit 0 = update done. Set by every update. |
| +0x1424 | IRQ_CLEAR | W1C (of IRQ_STATUS) | - | Write 1 to clear bit 0. |
| +0x1440 | PANEL_SIZE | RW | 0 | Width bits 10:0, height bits 26:16. 0 = 240 x 320. |
| +0x1444 | OUTPUT_DEPTH | RW | 0 | 0x10 = 16 bits per pixel to the panel, 0x12 = 18 bits. No visible effect in the model (section 4.2). Also used as source depth when +0x1458 is 0. |
| +0x1448 | UPDATE_ORIGIN | RW | 0 | x bits 10:0, y bits 26:16 on the panel. |
| +0x144C | UPDATE_SIZE | RW | 0 | Width bits 10:0, height bits 26:16 of the update. If width or height is 0, the whole panel is updated. |
| +0x1450 | SOURCE_ADDRESS | RW | 0 | GRAM offset of the source surface (its first line, first pixel). |
| +0x1454 | SOURCE_WIDTH | RW | 0 | Source line length in pixels. 0 = panel width (upright) or panel height (turned). |
| +0x1458 | SOURCE_BPP | RW | 0 | Source bits per pixel: 16, 24 or 32. 0 = use OUTPUT_DEPTH, and if that is 0 too, 16. Always set it: with OUTPUT_DEPTH 0x12 and SOURCE_BPP 0 the model takes 4 bytes per pixel. |
| +0x145C | TURN_START | RW | 0 | Turned mode only: x bits 10:0, y bits 26:16 of the source pixel that the first panel pixel of the update shows. |
| +0x1460 | ORIENTATION | RW | 0 | 0 = upright. 5 = turned (section 4.1). Other values: upright. |
| +0x1470, +0x1474 | - | S | 0 | Blend settings: not modelled. |
| +0x1478, +0x147C, +0x1480 | VIDEO_Y, VIDEO_U, VIDEO_V | RW | 0 | GRAM offsets of the planes of the video plane |
| +0x1490 | VIDEO_Y_PITCH | RW | 0 | Bytes per line of the Y plane (bits 11:0) |
| +0x1494 | VIDEO_C_PITCH | RW | 0 | Bytes per line of the U and V planes (bits 11:0) |
| +0x149C | VIDEO_SIZE | RW | 0 | Width bits 10:0, height bits 26:16 of the video picture |
| +0x14A0 | VIDEO_POSITION | RW | 0 | Two signed 16-bit numbers: px (bits 15:0), py (bits 31:16) |
| +0x14A4 | VIDEO_SCALE | RW | 0 | sx (bits 15:0), sy (bits 31:16), 8.8 fixed point; 0 = 0x100 = 1:1 |
| +0x14E4-+0x14F8 | DATA_LINE_MAP | S | 0 | Mapping of colour bits to panel data lines. No effect. |
| +0x14FC-+0x1528 | OVERLAY | S | 0 | Overlay set-up. Not modelled. |
| other | | S | 0 | |

Line 18 is high while IRQ_STATUS bit 0 = 1 and IRQ_ENABLE bit 0 = 1.

### 4.1 One update

At the write of 2 or 3 to COMMAND the model:

1. Reads the update rectangle (origin, size), clipped to the panel.
2. For each panel pixel (X, Y) in the rectangle, with i = X - origin x and j = Y - origin y:
   - upright (ORIENTATION 0): source pixel (column origin x + i, line origin y + j) of the surface;
   - turned (ORIENTATION 5): source pixel (column sx + j, line sy - i), with sx = TURN_START bits 10:0, sy = TURN_START bits 26:16. For a whole panel showing a 320 x 240 landscape surface: SOURCE_WIDTH = 320, TURN_START = 0x00EF0000 (sx 0, sy 239); panel (X, Y) shows surface (Y, 239 - X). The update is cut where the surface ends.
3. Converts each source pixel (section 4.2) and writes it into the panel picture. Pixels outside the rectangle keep their previous value.
4. Puts the video plane over it, if on (section 4.3).
5. Sends the whole 240 x 320 picture to the viewer, sets IRQ_STATUS bit 0 and updates line 18.

Source byte address of pixel (column c, line l) = SOURCE_ADDRESS + l x SOURCE_WIDTH x bytes_per_pixel + c x bytes_per_pixel.

### 4.2 Pixel formats

| SOURCE_BPP | Bytes | Layout in memory | Shown as |
|---|---|---|---|
| 16 | 2 | Little-endian 16-bit RGB565: red 15:11, green 10:5, blue 4:0 | 8 bits per colour by repeating the top bits [VALIDATED] |
| 24 | 3 | Byte 0 blue, byte 1 green, byte 2 red | 8 bits per colour [MODEL: a real panel gets 16 or 18 bits] |
| 32 | 4 | Byte 0 blue, byte 1 green, byte 2 red, byte 3 not used | as 24 |

### 4.3 Video plane

When CONTROL bits 9:8 = 3 and VIDEO_SIZE, VIDEO_Y_PITCH (>= width) and VIDEO_C_PITCH are not 0:

- The plane is a planar YUV 4:2:0 picture: a Y plane and U and V planes of half width and half height, at the GRAM offsets VIDEO_Y, VIDEO_U, VIDEO_V.
- Panel pixel (X, Y) shows plane sample ((X x sx >> 8) + px, (Y x sy >> 8) + py) when that sample lies inside the plane. Nearest sample [MODEL].
- Conversion: ITU-R BT.601, limited range (Y 16-235) [UNCONFIRMED: inferred].
- [MOCK] The plane is shown only where the RGB picture is black (0, 0, 0). The real blend rule is not known.

## 5. Panel bus engine (+0x1000)

The panel is connected through a programmable bus engine. On a real phone the engine runs a small program from its memory at +0x1000; the instruction set is not known. The model does not run the program [MODEL]: it acts on the command and parameter bytes as described here.

| Offset | Name | Access | Meaning |
|---|---|---|---|
| +0x1000-+0x10FF | ENGINE_MEMORY | RW | Program memory (ignored by the model). Its top bytes are the data area: the bytes to send end at +0x10FF. |
| +0x100C bits 31:16 | SEND_COUNT | RW | Number n of bytes to send, 1 to 32. |
| +0x111C | BYTE_KIND | RW | One bit per byte of the data area: bit 31 for the byte at +0x10FF, bit 30 for +0x10FE, and so on. 1 = parameter or data byte (D/C high), 0 = command byte (D/C low). |
| +0x11DC | RUN | RW | Write 2: send the n bytes at +0x1100 - n to +0x10FF, in ascending address order. Write 3: send the command byte at +0x10FF and read one byte back. Completes at once. |
| +0x11F4 | READ_RESULT | RW | After RUN = 3: bits 15:8 = the byte that the panel returned. |
| +0x10FC, +0x1100, +0x1120, +0x11E0-+0x11FC | - | S | Bus timing and pad settings: no effect. |

Write the data area with 32-bit stores: the byte at address a is in bits ((a & 3) x 8) of the word at a & ~3.

Line 17 (engine) is never raised.

### 5.1 Panel commands acted on by the model

| Command | Parameters | Effect in the model |
|---|---|---|
| 0x01 | - | Software reset: sleep in, display off |
| 0x10 | - | Sleep in |
| 0x11 | - | Sleep out |
| 0x28 | - | Display off |
| 0x29 | - | Display on |
| 0x2A | 4 (start high, start low, end high, end low) | Column window |
| 0x2B | 4 | Row window |
| 0x2C | pixel data | Memory write. Pixel bytes sent through the engine are not shown [MODEL]: the picture comes only from the refresh controller. |
| 0x36 | 1 | Memory access control. Bit 3 = BGR order. |
| 0x3A | 1 | Pixel format: 5 = 16 bits, 6 = 18 bits per pixel |
| 0x0A (read, RUN = 3) | - | Power mode: 0x88, plus 0x10 when out of sleep, plus 0x04 when the display is on. |

Any other command is accepted and has no effect. Any other register read returns 0 [MOCK].

The panel starts in sleep, display off. [MODEL] The model shows every update whatever the panel state: an update with the panel asleep or off is still visible. A firmware for a real phone must wake the panel (0x11, wait 120 ms as DCS panels need, 0x3A, 0x36, 0x29). The vendor-specific set-up commands of the real panel are not specified here.

## 6. 2D accelerator (+0x1800)

| Offset | Name | Access | Meaning |
|---|---|---|---|
| +0x1804 | COMMAND_FIFO | W | Command words are recorded. No operation is executed [MODEL]. |
| +0x1808 | STATUS | R | Always 0 (never busy, never full). |

Line 19 is never raised. Do not use the accelerator: draw with the CPU.

## 7. Backlight

There is no backlight model: the viewer always shows the screen lit. See `07-gpio-power.md`.

## 8. Stock driver notes [STOCK]

- Start: the driver reads VERSION and requires bits 15:8 = 0x41; otherwise it reports a wrong version, asks whether the clocks are on, and retries for 30 s.
- GRAM: at start the graphics process reserves one 15 MB block of SDRAM and writes the 15 megabyte addresses into BANK1-BANK15. Surfaces are allocated in that block and are addressed by GRAM offset. A surface outside it cannot be shown.
- Panel: a text file in the stock file system describes the panel (size, colour depth, the command sequences for initialisation and standby, and small programs for the panel bus engine as hex bytes). The driver loads the programs into ENGINE_MEMORY, puts the command and parameter bytes at the end of that memory, marks the parameter bytes in BYTE_KIND, writes the byte count into the write program (the model reads it from +0x100C bits 31:16), and writes RUN = 2. A register read uses RUN = 3 and takes the answer from READ_RESULT bits 15:8.
- The initialisation sequence starts with sleep out (0x11), sets memory access control 0x36 = 0x18 (BGR order) and pixel format 0x3A = 0x05 (16 bits), sends vendor-specific settings, opens the full window (0x2A / 0x2B) and ends with display on (0x29). 0x3A = 0x06 (18 bits) is used with OUTPUT_DEPTH 0x12.
- Every 2 s a watch process reads panel register 0x0A and checks the display-on bit (mask 0x04 of the value as read); if it is missing, it initialises the panel again.
- Updates: one process composes the screen in a surface with the CPU and sends one update for the changed rectangle per step (typical: the full screen 240 x 320, the area between status bar and soft keys 240 x 266, the soft-key bar 240 x 30). For each update it writes UPDATE_ORIGIN, UPDATE_SIZE, SOURCE_ADDRESS and then COMMAND = 2, and waits for line 18. It does not wait for the panel's vertical blank and does not use the 2D accelerator for the standby screen.
- Landscape surfaces (media, picture viewer, video) are shown with ORIENTATION = 5.
- Video playback uses the video plane (CONTROL bits 9:8 = 3) with the planes in GRAM that the camera interface fills, 25 updates per second; the RGB surface is 0 (black) where the video is to be seen.
- A second display description (TV output, 640 x 480) exists; its driver is installed as not active.
