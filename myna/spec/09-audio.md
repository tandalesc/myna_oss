# 09 Audio

## 1. Summary

- The only sound output is I2S1: 44,100 Hz, stereo, signed 16-bit little-endian samples, fed by the DMA controller.
- The firmware mixes and converts all sound itself. Nothing in the simulator decodes compressed sound or synthesises instruments for a clean firmware.
- There is no microphone input, no volume control in hardware and no audio codec chip model.

## 2. I2S blocks

| Block | Base | Line | Use |
|---|---|---|---|
| I2S0 | 0xC0002000 | 10 (never raised) | Same model as I2S1. Its output is recorded but the viewer does not play it. |
| I2S1 | 0xC0003000 | 12 (never raised) | Sound output: the viewer plays it. |

### 2.1 Registers (each block)

| Offset | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| +0x00 | CONTROL | S | 0 | Enable and mode bits. No effect. |
| +0x04 | - | S | 0 | |
| +0x08 | FIFO_STATUS | R (bits 4:0 live) | 0 | Bits 4:0 = transmit FIFO level in 32-bit words: words accepted and not yet played, at most 8. 0 with no transfer running = under-run. Other bits: last value written. |
| +0x14 | TX_DATA | DMA port | - | Transmit data. Only DMA writes are played. A CPU write here is stored and NOT played [MODEL]. |
| +0x18 | VERSION_CONTROL | RW | 0 | Bits 31:28 = hardware version, read as 0 (8-word FIFO). Other bits stored. |
| +0x1C, +0x20, +0x24 | CLOCK_DIVIDERS | S | 0 | No effect: the rate is fixed (section 2.2). |
| +0x28, +0x2C, +0x30 | - | S | 0 | Interrupt mask and clear (presumed). No effect. |
| other | | S | 0 | |

### 2.2 Playing sound [VALIDATED]

1. Put samples in RAM: stereo frames of 4 bytes (left 16-bit, right 16-bit, little-endian).
2. Program a DMA channel (`13-dma.md`): source = the buffer (physical address), destination = 0xC0003014, count = bytes (a multiple of 4, at most 4095 per item; use descriptor chains for longer or circular buffers), type 1 (memory to peripheral).
3. Start the channel. Wait for its terminal count (line 2), then queue the next buffer.

Pacing:

- The port takes 44,100 x 4 = 176,400 bytes per second of emulated time. The rate does not depend on any register [MOCK: 44,100 Hz is the rate the model uses; option `EMU_I2S_RATE`].
- [MOCK] The port first takes up to 8 ms of sound (1,408 bytes) at once, then follows the rate. Example: 1,920 bytes (10.9 ms) end 2.9 ms after the start [VALIDATED].
- The port takes whole frames only (multiples of 4 bytes).
- An idle firmware is woken for the DMA completion (it is a scheduled event).
- Keep at least two buffers queued (or a circular descriptor chain) to avoid gaps. A gap is silence in the viewer.

## 3. Sound-synthesis block, 0xC0038000-0xC003AFFF

A hardware voice engine with its own waveform memory.

| Address | Content |
|---|---|
| 0xC0038000-0xC0039FFF | Work memory (8 KB) |
| 0xC003A000 | Command port (DMA destination) |
| 0xC003A000-0xC003AFFF | Registers |
| 0xC003A7FC | Result port (DMA source) |

Line 21 is never raised. The waveforms of the real block (in a ROM of the chip) are not available; the model plays substitute tones. Section 7 gives the command format for information. Do not use it for a clean firmware; synthesise in software and play through I2S1.

## 4. Signal-processing block ("AVE"), 0xC0040000-0xC0047FFF

| Offset | Access | Meaning |
|---|---|---|
| +0x0000-+0x2FFF | RW | Storage (RAM of the block) |
| +0x3020 | RW | Control: bit 0 = start. |
| +0x3028, +0x306C | S | Configuration |
| +0x3078 | R | Version: reads 0 [MOCK] |
| +0x307C | RW | Status: bits 15, 13, 12 (0xB000) read as 1 while +0x3020 bit 0 = 1. Other bits: last value written. |
| other | S | Logged as unmodelled. |

The block does nothing else in the model: no job runs, no interrupt. Its purpose is not known. A clean firmware does not need it.

## 5. What is not modelled

| Function | Status |
|---|---|
| Microphone, I2S receive | Not modelled. A receive DMA from I2S gets no data (the channel waits). |
| Audio codec (digital-to-analogue converter, amplifiers, volume, routing to speaker or headset) | Not modelled. Apply volume in software. |
| Headset detection | Not modelled (the viewer's `headset` switch has no effect). |
| Compressed audio decoding | No hardware decoder is available to a clean firmware. Decode in software. |
| Key tones, ringer, vibration | Only through I2S1 sound. |

## 6. Stock driver notes [STOCK]

- I2S set-up: +0x00, +0x04, +0x2C, +0x30 = 0 and +0x28 = 0xFFFFFFFF; around each transmit start +0x00 = 0x27 and +0x2C / +0x28 = 0x20. The clock dividers are written for 8000 Hz and stay so during playback: the bit clock comes from the audio converter, and the output device is set to 44,100 Hz.
- It reads VERSION_CONTROL bits 31:28 once: 3 or more selects a 16-word FIFO, else 8 words.
- Output: one mixer process mixes all sources, applies the volume and converts to 44,100 Hz stereo 16-bit; DMA channel 23 moves 3 buffers of 1920 bytes (10.9 ms each) in a chain to 0xC0003014. When FIFO_STATUS bits 4:0 read 0 with the chain idle it reports an under-run and restarts the chain.
- I2S0 uses DMA channels 21 (transmit) and 22 (receive); I2S1 23 and 24. No run of the stock software used the receive side.
- Compressed sound (AAC, MP3 and others) is not decoded on the application CPU: the stock software sends each frame over the link to the other processor and gets PCM back.
- MIDI (ringtones, start-up melody) is synthesised in software with the sound-synthesis block as voice engine (section 7).
- Signal-processing block: at start the stock software clears +0x0000-+0x2FFF, writes +0x307C = 0x40 then 0, +0x306C = 0, +0x3028 = 0x2044, +0x3020 = 0x140C1001, polls +0x307C until bits 12, 13 and 15 are all set (no time-out), writes +0x307C = 0x40 then 0, and reads +0x3078 once (printed as the version). Nothing else in a normal start. Its purpose is not known.

## 7. Sound-synthesis block: format of the voice commands [STOCK, MODEL]

For information. Every 2 ms the stock synthesiser computes one 48-byte command (12 little-endian words) per sounding voice; the block plays the voice's waveform and mixes all voices into buffers in its work memory: 64 samples per voice and tick at 32,000 Hz. The waveforms are 8-bit samples in a ROM of the real block (about 100 KB); they are not available, and the model plays substitute tones. Without the stock instrument table (a profile without one) the substitutes do not follow any instrument.

Transport (all by DMA):

| What | DMA |
|---|---|
| Voice commands, then one closing command | memory -> 0xC003A000 (the stock software uses channel 20) |
| Loads of the work memory and of registers +0x2034 (8 bytes), +0x2030 (4 bytes), +0x203C (8 bytes, written last: bit 0 = start) | memory to memory (channel 36) |
| Results: 2 bytes per voice command (total rounded up to 4), filler, then 0x480 bytes of work memory if read back | 0xC003A7FC -> memory (channel 19); its terminal count is the only completion signal |

Voice command words (as the model reads them):

| Word | Bits | Meaning |
|---|---|---|
| w0 | 30 | 1 = voice command |
| w0 | 25:19 | Voice number |
| w0 | 18:12 | Samples (0 = 64) |
| w0 | 2, 1, 0 | Filter on; note start; looped |
| w1 | | Phase step: w1 / 2^21 waveform samples per output sample |
| w2 | 31:16, 15:0 | First sample index; last index (one-shot end) |
| w3 | 31:16, 15:0 | Loop start; loop end |
| w4 | | Waveform address inside the block |
| w5 | 15:0 | Voice gain, signed Q15 |
| w6 | 15:0 | Filter b (Q15); bits 25:22 = "first writer" flags of the four destination buffers (overwrite instead of add) |
| w7 | 31:16, 15:0 | Filter c1, c2 (Q15): y = 4 b x - 2 c1 y1 - 2 c2 y2 |
| w8 | 23:12, 11:0 | Word addresses of mix buffers 1 and 2 in the work memory |
| w9 | 23:12, 11:0 | Word addresses of effect buffers 1 and 2 |
| w10 | 31:16, 15:0 | Gains (Q15) for mix buffers 1, 2 |
| w11 | 31:16, 15:0 | Gains for effect buffers 1, 2 |

Status word per voice command: bits 6:0 = voice number; bits 14:7 non-zero while the voice sounds; 0 when a one-shot waveform has ended.

A clean firmware gains nothing from this block in the simulator: synthesise in software and play through I2S1.
