# 10 Storage: NAND flash and memory card

## 1. NAND chip

| Item | Value |
|---|---|
| Type | 2 Gbit (256 MB) NAND flash, 8-bit bus, large pages. The model's default identity is the Samsung K9K2G08R0A (1.8 V). |
| Page | 2048 data bytes + 64 spare bytes = 2112 (0x840) bytes |
| Block | 64 pages (128 KB of data) |
| Size | 2048 blocks, 131,072 pages |
| ID bytes (command 0x90) | 0xEC, 0xAA, 0x10, 0x15, 0x44, then 0x00 [VALIDATED: first four] |
| Address cycles | 2 column cycles (column bits 11:0 used) + 3 row cycles (page number, low byte first) |
| Bad blocks | None [MODEL]. A real chip has factory bad blocks marked in the spare area. |
| Write protection | None |
| Program and erase failure | Never [MODEL] |

### 1.1 Content at power-on

- Every page that was never programmed reads 0xFF (data and spare).
- Today the simulator starts from a stock flash image. A clean firmware needs a blank chip or its own image: `90-gaps.md`, G2.
- Changes are kept between runs in the flash state (section 4).

## 2. Bus windows

| Address | Name | Access | Meaning |
|---|---|---|---|
| 0x80000000-0x8000FFFF | DATA | R/W, 8, 16 or 32 bit | Data port. The address inside the window has no meaning: every access takes or gives the next 1, 2 or 4 bytes of the data stream, in little-endian order. |
| 0x80010000-0x8001FFFF | COMMAND | W, 8 bit | A write sends the low byte as a command. Reads give 0. |
| 0x80020000-0x8002FFFF | ADDRESS | W, 8 bit | A write sends the low byte as an address cycle. Reads give 0. |

### 2.1 Commands

| Sequence | Function | Model behaviour |
|---|---|---|
| FFh | Reset | Data output = status. Busy for 3 ready polls. |
| 90h, 00h, read n bytes | Read ID | Returns the ID bytes (section 1). The address cycle is not checked. |
| 00h, 5 address cycles, 30h | Read page | Loads the page into the page register; data output starts at the column. Busy for 3 polls. Then read the data port. Bytes past the end of the 2112-byte register read 0xFF. A row beyond the chip gives an all-0xFF page. |
| 05h, 2 column cycles, E0h | Random data output | Moves the data output to a new column of the page register. |
| 00h without address cycles (after a read, for example after 70h) | Back to data output | Data output continues from the page register at the current position. |
| 35h with 5 address cycles (00h, address, 35h) | Copy-back read | Loads the page into the page register, no data output. Busy for 3 polls. |
| 80h, 5 address cycles, data, 10h | Program page | 80h fills the page register with 0xFF. Data bytes are stored from the column on. 10h programs: new content = old content AND page register (bits go from 1 to 0 only). Busy for 3 polls. |
| 80h ..., 85h, 2 column cycles, data | Random data input | Moves the data input to a new column within the open program. |
| 35h ..., 85h, 5 address cycles, [data], 10h | Copy-back program | Programs the page register (as read by 35h, with any new data) into the new row. |
| 15h | Cache program | Same as 10h. |
| 60h, 3 row cycles, D0h | Block erase | Sets the 64 pages of the block that holds the row to 0xFF. Busy for 3 polls. |
| 70h, read | Read status | Every data byte read gives the status. |
| any other | - | Ignored. |

Status byte: 0xC0 normally: bit 7 = 1 (not write-protected), bit 6 = 1 (ready), bit 0 = 0 (pass) [VALIDATED]. Bit 0 = 1 after a failed program or erase (never happens in the model).

Data output in other states: in ID mode the ID bytes, in status mode the status byte, otherwise 0xFF.

## 3. NAND controller, base 0x9F800000

| Offset | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| +0x40 | CONTROL | RW | 0 | Bit 6 = ECC engine on. A change of bit 6 from 0 to 1 clears the ECC accumulator. Write 0, then 0x40, to start a new code. Other bits stored. |
| +0x44 | STATUS | R | 0x40 | Always 0x40 (bit 6 = ECC / FIFO done) [MODEL]. |
| +0x48, +0x4C | TIMING0, TIMING1 | RW | 0 | Bus timing. No effect. |
| +0x54 | ECC | R | 0xFFFFFF | ECC result, 24 bits (section 3.1). |
| +0xC8 | READY | R | 0x2 | Bit 1 = chip ready (R/B line). |
| other | | S | 0 | |

Ready line: after the commands that make the chip busy (reset, 30h, 35h, 10h/15h, D0h) the next 3 reads of READY give 0, then it gives 2 [MODEL: no time passes; the chip is busy for a number of polls]. A firmware must poll READY (or read status) after each such command. Line 45 is never raised.

### 3.1 ECC engine

While CONTROL bit 6 = 1, every byte that passes through the data port (read or written) is fed to the engine. The engine computes a 24-bit Hamming code (the usual "3 bytes per 512 bytes" NAND code):

- Let i be the position of a byte in the stream (counted from the clear) modulo 512, and b its value.
- For k = 0 to 8: P[2k] = parity (XOR of all bits) of the bytes with bit k of i = 0; P[2k+1] = parity of the bytes with bit k of i = 1.
- For k = 0 to 2: P[18+2k] = parity, over all bytes, of the bit positions j (0-7) with bit k of j = 0; P[19+2k] = with bit k of j = 1.
- ECC register bit n = NOT P[n], for n = 0 to 23 (so an all-0xFF or all-0x00 sector gives 0xFFFFFF).

Notes:

- The accumulator does not restart at a 512-byte boundary: clear it (CONTROL bit 6 to 0 and back to 1) before each 512-byte sector, and read the register after exactly 512 bytes.
- To check a read: compute the code while reading the sector, compare it with the code stored when it was written. XOR of the two (as P bits): all 0 = no error; exactly 12 bits set, one in each pair = one bit error, at byte position given by the odd row bits and bit position given by the odd column bits; anything else = uncorrectable or an error in the stored code.
- Where the code is stored (spare area layout) is the firmware's choice.

## 4. Flash state between runs

- The chip content is a base image plus the changes. The viewer saves the changed blocks in the flash state file and loads them at the next start.
- The viewer saves only at a quiet moment: no program or erase in progress and none in the last 1.5 s of emulated time. It tries every 10 s of emulated time, at the stop of the simulator, and at power off.
- REQUIRED: let the flash be quiet for at least 1.5 s of emulated time from time to time, and before power off. Writes made after the last quiet moment can be lost when the simulator is stopped.
- A flash state belongs to one base image; another base image refuses it.

## 5. Memory card

### 5.1 MMC / SD host, base 0xC0001000

An MMC/SD host with the layout of the ARM PrimeCell PL180 [UNCONFIRMED: inferred]. [MODEL] No card is ever present.

| Offset | Name | Access | Meaning |
|---|---|---|---|
| +0x08 | ARGUMENT | S | Command argument |
| +0x0C | COMMAND | RW | Bit 10 = send, bit 6 = response expected. A write with bit 10 set completes at once: with bit 6 set, STATUS bit 2 (response timeout) is set; without, STATUS bit 7 (command sent) is set. |
| +0x34 | STATUS | R | Bit 2 = response timeout, bit 7 = command sent |
| +0x38 | CLEAR | W1C (of STATUS) | |
| other | S | | Storage |

Every command that expects a response times out. Lines 40 and 41 are never raised.

### 5.2 Memory Stick detect

GPIO bank 1 pin 4 reads 1 (no card). See `07-gpio-power.md`.

## 6. Stock driver notes [STOCK]

- The first-stage loader tries three storage back ends in a fixed order: NOR (window 0x60000000, reads 0: no chip), NAND, and the memory-card host ("SSD": commands time out). Only NAND answers.
- The stock loader of variant A reads two ID bytes and takes the size from the device byte; that of variant B reads five and computes page, block and spare size from the 4th byte and the size from the 5th (planes in bits 3:2, plane size in bits 6:4). With a 5th byte of 0 it gets a 64 KB device: the 5th byte matters.
- The data port is read with 32-bit loads in a tight loop (three instructions make 99.9 % of all reads).
- After a reset or a page command the driver polls READY bit 1; after a read it sends 00h without address cycles to go back to data output.
- ECC: the driver clears CONTROL bits 7:6 and then sets bit 6 before each 512-byte sector, reads the ECC register after the sector, reorders the 24 bits (with a fixed table of its own) and stores four codes per page in the spare area. On a read it compares and corrects a single wrong bit. A page is 4 sectors of 512 bytes.
- The copy-back program 35h / 85h is used with partial replacement of the data (85h with a column and data after a row).
- Flash layout of the stock software: the first 1 MB holds what runs before its loader (not in the firmware files); a main segment of 63 MB from flash address 0x00100000 holds the boot volume; a file-system segment of 192 MB from 0x04000000 holds five FAT volumes. Between FAT and pages is a flash translation layer with 4 KB chunks. None of this is required by the hardware.
