# 06 Keypad

## 1. Hardware

- A matrix of 5 row outputs and 6 column inputs, and 6 direct keys. A direct key pulls its column low whatever the rows do.
- Keypad controller, base 0xC0015000. 16-bit registers (16-bit or 32-bit accesses).
- Two interrupt lines: 30 (a key is down), 31 (all keys are up).
- The slide switch and the lens cover are not keys: they are GPIO pins (`07-gpio-power.md`).

## 2. Registers

| Offset | Name | Width | Access | Reset | Meaning |
|---|---|---|---|---|---|
| +0x00 | CONTROL | 16 | S | 0 | No effect. |
| +0x04 | COLUMNS | 7 | R | 0x7F | Column inputs, active low. Bit c (0-5) = 0 when a pressed key in column c is on a row that is driven, or when a pressed direct key is in column c. Bit 6 is always 1 (no key). |
| +0x08 | ROWS | 5 | RW | 0 | Row outputs, active low: row r (0-4) is driven when bit r = 0. Reset 0 = all rows driven. |
| +0x14 | - | 16 | S | 0 | No effect. |
| +0x18 | IRQ_ENABLE | 2 | RW | 0 | Bit 0 = key-down interrupt enabled. Bit 1 = all-up interrupt enabled. |
| other | | | S | 0 | |

Interrupts (levels):

- Line 30 is high while IRQ_ENABLE bit 0 = 1 and at least one key (matrix or direct) is down.
- Line 31 is high while IRQ_ENABLE bit 1 = 1 and no key is down.
- To stop a line, change IRQ_ENABLE. The usual pattern: enable bit 0 while idle; in the line 30 handler switch to bit 1, then scan the matrix periodically (with the OS timer) until line 31 comes; then switch back to bit 0.

## 3. Scanning [VALIDATED]

1. Write ROWS = 0x1F (no row driven). Read COLUMNS: a 0 in bit c means direct key c is down.
2. For each row r = 0 to 4: write ROWS = 0x1F & ~(1 << r), read COLUMNS. A 0 in bit c means key (r, c) is down, or direct key c is down. Remove the direct keys found in step 1.
3. Key index = r x 6 + c for matrix keys, 30 + c for direct keys.
4. Write ROWS = 0 (all rows driven) before idling, so that any key raises line 30.

Several keys can be down together. There is no ghosting, no bounce and no scan timing in the model [MODEL].

## 4. Key positions

Input names are the names that the viewer and the key control file use (`native/devices/*/skin/skin.json`).

### 4.1 Variant A

| Index | Row | Column | Input name | Physical key |
|---|---|---|---|---|
| 0 | 0 | 0 | `3` | 3 |
| 1 | 0 | 1 | `6` | 6 |
| 2 | 0 | 2 | `1` | 1 |
| 3 | 0 | 3 | `camera_half` | Shutter, half press |
| 4 | 0 | 4 | `operator` | Probably no physical key [UNCONFIRMED] |
| 5 | 0 | 5 | `game_b` | Right key above the screen [UNCONFIRMED] |
| 6 | 1 | 0 | `call` | Call (green) |
| 7 | 1 | 1 | `game_a` | Left key above the screen [UNCONFIRMED] |
| 8 | 1 | 2 | - | No key |
| 9 | 1 | 3 | `clear` | C (clear) |
| 10 | 1 | 4 | `8` | 8 |
| 11 | 1 | 5 | `camera_mode` | Camera mode (photo / video), side |
| 12 | 2 | 0 | `2` | 2 |
| 13 | 2 | 1 | `0` | 0 |
| 14 | 2 | 2 | `soft_left` | Left soft key |
| 15 | 2 | 3 | `5` | 5 |
| 16 | 2 | 4 | `camera_review` | Camera review, side |
| 17 | 2 | 5 | `9` | 9 |
| 18 | 3 | 0 | `activity` | Activity menu |
| 19 | 3 | 1 | `4` | 4 |
| 20 | 3 | 2 | `7` | 7 |
| 21 | 3 | 3 | `camera_full` | Shutter, full press |
| 22 | 3 | 4 | `hash` | # |
| 23 | 3 | 5 | `star` | * |
| 24 | 4 | 0 | `down` | Navigation down |
| 25 | 4 | 1 | `left` | Navigation left |
| 26 | 4 | 2 | `up` | Navigation up |
| 27 | 4 | 3 | `select` | Navigation centre (select) [VALIDATED] |
| 28 | 4 | 4 | `right` | Navigation right |
| 29 | 4 | 5 | `soft_right` | Right soft key |
| 30 | direct | 0 | `end` | End (red) key; also the power key |
| 31 | direct | 1 | `media` | Music key, side [UNCONFIRMED that it exists] |
| 32 | direct | 2 | `camera_onoff` | Camera on/off [UNCONFIRMED] |
| 33 | direct | 3 | `vol_up` | Volume up, side |
| 34 | direct | 4 | `vol_down` | Volume down, side |
| 35 | direct | 5 | `media2` | Media player key, side [UNCONFIRMED that it exists] |

Notes:

- A press of `camera_full` in the viewer also presses `camera_half` first (two-stage shutter); both are down together.
- The viewer's `lens_cover` switch drives a GPIO pin (`07-gpio-power.md`). Only when no GPIO model is attached does it hold `camera_onoff` down while the cover is open.
- The keys `1`-`9`, `0`, `star`, `hash` are on the slide: the viewer offers them only with the slide open. The matrix itself does not depend on the slide.

### 4.2 Variant B

| Index | Row | Column | Input name | Physical key |
|---|---|---|---|---|
| 0 | 0 | 0 | `3` | 3 |
| 1 | 0 | 1 | `6` | 6 |
| 2 | 0 | 2 | `1` | 1 |
| 3 | 0 | 3 | `camera_half` | Shutter, half press |
| 4 | 0 | 4 | `play_stop` | Play / stop, right side |
| 5 | 0 | 5 | `rewind` | Rewind, right side |
| 6 | 1 | 0 | `call` | Call |
| 7 | 1 | 1 | - | No key |
| 8 | 1 | 2 | - | No key |
| 9 | 1 | 3 | `clear` | C (clear) |
| 10 | 1 | 4 | `8` | 8 |
| 11 | 1 | 5 | `music` | Music key, left side [UNCONFIRMED: inferred] |
| 12 | 2 | 0 | `2` | 2 |
| 13 | 2 | 1 | `0` | 0 |
| 14 | 2 | 2 | `soft_left` | Left soft key |
| 15 | 2 | 3 | `5` | 5 |
| 16 | 2 | 4 | `fast_forward` | Fast forward, right side |
| 17 | 2 | 5 | `9` | 9 |
| 18 | 3 | 0 | `activity` | Activity menu |
| 19 | 3 | 1 | `4` | 4 |
| 20 | 3 | 2 | `7` | 7 |
| 21 | 3 | 3 | `camera_full` | Shutter, full press |
| 22 | 3 | 4 | `hash` | # |
| 23 | 3 | 5 | `star` | * |
| 24 | 4 | 0 | `down` | Navigation down |
| 25 | 4 | 1 | `left` | Navigation left |
| 26 | 4 | 2 | `up` | Navigation up |
| 27 | 4 | 3 | `select` | Navigation centre |
| 28 | 4 | 4 | `right` | Navigation right |
| 29 | 4 | 5 | `soft_right` | Right soft key |
| 30 | direct | 0 | `end` | End key; also the power key |
| 31 | direct | 1 | - | No key |
| 32 | direct | 2 | - | No key |
| 33 | direct | 3 | `vol_up` | Volume up, right side |
| 34 | direct | 4 | `vol_down` | Volume down, right side |
| 35 | direct | 5 | - | No key |

Variant B has no lens cover.

## 5. Power key

- The power key is the `end` key (direct key 0, index 30). While the phone runs it is an ordinary key of the keypad.
- Pressing it does not create an event in the power-management chip during operation [MODEL].
- The power-management chip reports "power key" as the power-on cause at every start (`08-i2c-spi-chips.md`).
- To switch the phone off, the firmware switches off the system supply (`07-gpio-power.md`). A phone that is off is switched on by the viewer's power control (a new run).

## 6. Switches of the viewer

| Input name | States | Where it goes |
|---|---|---|
| `slide` | closed, open | GPIO bank 0 pin 4 (`07-gpio-power.md`) |
| `lens_cover` (variant A only) | closed, open | GPIO bank 0 pin 3 |
| `usb` | out, in | Power-management chip status and event (`08-i2c-spi-chips.md`) |
| `charger` | out, in | Power-management chip status and event |
| `headset` | out, in | Recorded only: no hardware effect |
| `orientation` | upright, side, side_other, flat, face_down | Accelerometer readings (`08-i2c-spi-chips.md`) |

The first state is the state at power-on.

## 7. Stock driver notes [STOCK]

- Set-up: CONTROL = (CONTROL & 0xFFF8) | 0, register +0x14 |= 3, IRQ_ENABLE |= 3. All registers are accessed as 16-bit halfwords.
- While no key is down all rows are driven (ROWS = 0), so any key raises line 30.
- The line 30 handler leaves IRQ_ENABLE = (x & ~3) | 2 and signals the input process; the line 31 handler leaves (x & ~3) | 1. The scan itself runs in process context.
- Scan: ROWS takes the values 0x1E, 0x1D, 0x1B, 0x17, 0x0F (rows 0-4), then 0x1F (no row) for the direct keys; COLUMNS is read as (COLUMNS | 0xFF80) & 0xFF, bits 5:0 decoded, bit 6 used only for "any key". The reading with no row driven is the ghost mask for the five row readings and the sixth row (indexes 30-35).
- The result is compared with the last scan; for every changed key the index (row x 6 + column) and the new level go to the user-interface server. While a key is down the scan repeats every 25 ms.
- Slide and lens cover: drivers subscribe to their GPIO pins for both edges and post them as key events (slider open / closed, lens cover open / closed).
- A press of 4 s on the END key at the standby screen starts the shut-down.
