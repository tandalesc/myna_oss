# 12 Video, camera, and parts that are not modelled

## 1. Camera interface of the display controller

The display controller has a camera input (a parallel picture port). On the phone the multimedia chip (`08-i2c-spi-chips.md`) drives it with decoded video. There is no camera sensor model: a clean firmware receives no pictures here.

### 1.1 Camera interface controller (XGAM +0x0C00)

| Offset | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| +0x0C04 | CONTROL | RW | 0 | Bit 4 = capture enabled, bit 6 = start. |
| +0x0C08 | STATE | RW | 0 | Bit 2 = transfer in progress; cleared when a frame is stored. |
| +0x0C0C | IRQ_ENABLE | RW | 0 | Bits 7:0 |
| +0x0C10 | IRQ_STATUS | R | 0 | Bit 2 = frame stored, bit 4 = error (never set). |
| +0x0C14 | IRQ_ACK | W1C (of IRQ_STATUS) | - | |
| +0x0C20 | - | RW | 0 | Cleared when a frame is stored. |
| +0x0C24 | BUFFER | RW | 0 | GRAM offset of the capture buffer |
| +0x0C48 | LINE_PIXELS | RW | 0 | Pixels per line (bits 10:0) |
| +0x0C4C | LINES | RW | 0 | Lines (bits 10:0) |

Line 15 is high while (IRQ_STATUS & IRQ_ENABLE & 0xFF) is not 0.

### 1.2 Camera data interface (XGAM +0x0800)

| Offset | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| +0x0804 | CONTROL | RW | 0 | Bit 0 = enabled |
| +0x0808 | FRAME_BYTES | RW | 0 | Bytes expected per frame |
| +0x080C | RECEIVED_BYTES | R | 0 | Bytes of the last frame |
| +0x0824 | IRQ_STATUS | R | 0 | Never set by the model |
| +0x0828 | IRQ_ENABLE | RW | 0 | |
| +0x082C | IRQ_ACK | W1C (of IRQ_STATUS) | - | |

Line 14 is high while (IRQ_STATUS & IRQ_ENABLE & 0xFF) is not 0.

### 1.3 A frame

The capture is armed while +0x0C04 bit 4 = 1 and +0x0804 bit 0 = 1. A frame that arrives then is stored at BUFFER (at most FRAME_BYTES bytes), RECEIVED_BYTES is set, IRQ_STATUS bit 2 is set. The frame from the multimedia chip is planar YUV 4:2:0. It arrives at once [MODEL]. The refresh controller can show such a buffer as its video plane (`05-display.md`, 4.3).

## 2. Motion-compensation and inverse-DCT block (profile of variant B only)

A block of the display controller that builds video pictures from 8 x 8 blocks: prediction from a reference picture plus an inverse DCT of coefficients. It is attached in the profile of variant B only. In the profile of variant A its registers are plain storage.

Registers at XGAM +0x1C00 (offsets below are from +0x1C00). Line 20.

| Offset | Name | Access | Meaning |
|---|---|---|---|
| +0x00 | ID | R | 0x4900 (bits 15:8 = 0x49 identify the block; low byte 0 [MOCK]) |
| +0x04 | CONTROL | S | Writing 0x100 resets the engine (presumed); stored |
| +0x08 | CHANNEL0_RUN | RW | Write 2 = run the command buffer of channel 0. Bit 1 reads back as "started". Write 0 after it has finished. |
| +0x0C | CHANNEL1_RUN | RW | Same for channel 1 |
| +0x20 | STATUS | R | Bit k = channel k has finished its buffer |
| +0x24 | IRQ_ENABLE | RW | Same bits |
| +0x28 | CLEAR | W1C (of STATUS) | |
| +0x40, +0x44 | CH0_START, CH0_END | RW | GRAM offsets of the command buffer of channel 0 |
| +0x48, +0x4C | CH1_START, CH1_END | RW | Same for channel 1 |
| +0x50, +0x54, +0x58 | DEST_Y, DEST_U, DEST_V | RW | GRAM offsets of the destination planes |
| +0x5C, +0x60, +0x64 | REF_Y, REF_U, REF_V | RW | GRAM offsets of the reference planes |
| +0x68, +0x6C, +0x70 | PITCH_Y, PITCH_U, PITCH_V | RW | Bytes per line of each plane |
| +0x74 | SIZE | RW | Width bits 15:0, height bits 31:16 |

The line is high while (STATUS & IRQ_ENABLE) is not 0. A buffer takes no time: the status bit is set by the write that starts it [MODEL].

Command buffer: 32-bit words from START to END (GRAM offsets):

| Word | Meaning |
|---|---|
| 0x10000000 | End of the buffer |
| Block word | Bits 7:0 block column, bits 15:8 block row (units of 8 samples of its plane), bits 17:16 plane (0 Y, 1 U, 2 V), bit 18 intra block with coefficients, bit 19 predicted block with coefficients, bit 20 predicted block, bit 21 rounding control of half-sample prediction, bits 23:22 B-picture prediction kinds (not modelled: forward prediction) |
| Motion vector (follows a block word with bit 20 = 1 and bit 18 = 0) | x bits 12:0, y bits 28:16, signed, in half samples of that plane |
| Coefficients (follow when bit 18 or 19 is set) | 16-bit entries: bits 11:0 value (signed, after inverse quantisation), bits 15:12 n = distance to the next coefficient place; n = 0 ends the block. Then padding to a 32-bit boundary. Places count down the columns: place i = row (i & 7), column (i >> 3). |

Limits of the model: width and height even, 16 to 2048; a command buffer of at most 1 MB; a pitch of 0 means width (Y) or width / 2 (U, V). A block word with none of bits 18-20 set, a block of plane 3, and a block outside its plane are skipped.

Result: prediction = reference plane at (8 x column + x / 2, 8 x row + y / 2), half positions as the mean of 2 or 4 samples with rounding ((sum + 1 - r) >> 1, (sum + 2 - r) >> 2, r = rounding bit); positions outside the picture take the nearest edge sample. Destination = clip(prediction + IDCT) or clip(IDCT) for an intra block. IDCT: the exact inverse DCT of ISO/IEC 14496-2 Annex A, rounded to the nearest integer.

## 3. Not modelled

| Function | Status |
|---|---|
| Camera sensor | Not modelled. |
| Video encoder (lines 3, 4) | Not modelled. |
| Hardware video decoding for a clean firmware | Not available: the multimedia chip only answers the stock protocol (`90-gaps.md`, G16). |
| 2D accelerator | Commands recorded, not executed (`05-display.md`). |
| TV output | Not modelled. |
| Bluetooth, WLAN, GPS, cellular radio | No hardware for them is reachable from the application CPU in the simulator. |
| USB | Only the cable detection in the power-management chip (`08-i2c-spi-chips.md`). No USB controller. |
| Memory card | No card (`10-storage-nand.md`). |
| Vibrator, LEDs, backlight | No visible effect (`07-gpio-power.md`). |
| Watchdog | Not modelled. |
| SIM card | Read by the modem processor only. Not available to a clean firmware. |

## 4. Stock driver notes [STOCK]

- Camera interface: the stock software arms the capture with CDICON +0x0C04 bit 4 and CDI +0x0804 bit 0, the buffer in +0x0C24, the raster in +0x0C48 / +0x0C4C and the frame size in +0x0808. Its interrupt handler reads +0x0C10 and writes the value back to +0x0C14; the CDI handler reads +0x0824 and writes +0x082C. The multimedia chip turns a 320 x 240 picture into a 240 x 320 raster for the upright panel.
- Motion-compensation / IDCT block (variant B's stock software): requires ID bits 15:8 = 0x49, else reports the block as missing. Writes CONTROL = 0x100 before every set-up, then the planes, pitches (240, 120, 120 for 240 x 320), size, the buffer start and end, and CHANNELk_RUN = 2; it reads bit 1 back as "started", waits for the status bit (interrupt line 20) and writes CHANNELk_RUN = 0. The stock MPEG-4 and H.264 software decoders parse the stream on the CPU and give every 8 x 8 block to the block.
