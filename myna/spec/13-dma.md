# 13 DMA controller

Base 0xC0020000. 64 channels. Line 2. The register layout is the platform's own (not an ARM PL080).

## 1. Registers

| Offset | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| +0x000 | - | S | 0 | |
| +0x008 | TC_STATUS_LOW | R | 0 | Bit n = channel n (0-31) has finished its whole descriptor chain |
| +0x00C | TC_STATUS_HIGH | R | 0 | Bit n = channel 32 + n |
| +0x010 | TC_CLEAR_LOW | W1C (of TC_STATUS_LOW) | - | |
| +0x014 | TC_CLEAR_HIGH | W1C (of TC_STATUS_HIGH) | - | |
| +0x028 | ERROR_CLEAR_LOW | W1C | - | |
| +0x02C | ERROR_CLEAR_HIGH | W1C | - | |
| +0x030 | ERROR_STATUS_LOW | R | 0 | Never set by the model |
| +0x034 | ERROR_STATUS_HIGH | R | 0 | Never set by the model |
| +0x100 + 4n | CHANNEL_CONFIG n | RW | 0 | Bit 0 = enable / start. Bits 2:1 = type: 0 memory to memory, 1 memory to peripheral, 2 peripheral to memory, 3 peripheral to peripheral. Other bits stored. |
| +0x200 + 4n | CHANNEL_STATUS n | R | 0 | Bit 0 = busy |
| +0x400 + 16n | CONTROL n | RW | 0 | Current item: control word (section 2) |
| +0x404 + 16n | SOURCE n | RW | 0 | Current item: source address |
| +0x408 + 16n | DESTINATION n | RW | 0 | Current item: destination address |
| +0x40C + 16n | NEXT n | RW | 0 | Address of the next descriptor, 0 = last item |

Line 2 is high while any TC_STATUS bit or any ERROR_STATUS bit is 1.

## 2. Items and descriptors

Control word:

| Bits | Meaning |
|---|---|
| 11:0 | Byte count of the item, 0 to 4095. The model counts it down as bytes move. |
| 24, 25 | Both 1: end a message when the item ends (only for a link transmit port, `11-modem-link.md`). |
| 26 | Address increment (presumed). Ignored by the model: see below. |
| other | Stored. |

A descriptor in memory is 4 words, 16 bytes, at a 4-byte-aligned physical address: control, source, destination, next.

## 3. Operation

1. Write CONTROL, SOURCE, DESTINATION, NEXT of channel n (the first item).
2. Write CHANNEL_CONFIG n with bit 0 = 1 and the type. The change of bit 0 from 0 to 1 starts the channel: TC bit cleared, busy set.
3. The channel moves the item. When the count reaches 0 and NEXT is not 0, it loads the next descriptor from memory into CONTROL, SOURCE, DESTINATION, NEXT and goes on. When the count reaches 0 and NEXT is 0, the chain ends: busy cleared, CHANNEL_CONFIG bit 0 cleared, TC bit set, line 2 high.
4. Clear the TC bit with TC_CLEAR before the next use; line 2 stays high until all TC bits are clear.
5. Writing CHANNEL_CONFIG bit 0 = 0 stops the channel (busy cleared, no TC).

Addresses:

- All addresses are physical.
- A peripheral is identified by its exact data-register address (the "ports" below). The peripheral address stays fixed; the memory address goes up by the bytes moved. Bit 26 does not change this.
- Memory to memory: the bytes are copied at once; both addresses go up. Addresses inside the sound-synthesis block (0xC0038000-0xC003AFFF) are reachable. An address with no memory reads as zeros and writes are dropped.

Timing [MODEL]:

- There is no transfer time. A transfer runs during the register write that starts it, or whenever its peripheral can take or give data (for the link and the sound output this is paced as described in their files).
- Peripheral transfers move multiples of 4 bytes when 4 or more bytes can move.
- A peripheral channel whose port address is not one of the ports below never moves data and stays busy.
- A circular descriptor chain to a port that never fills (for example the SPI port) is cut after 4096 items per run of the engine and continues at the next opportunity.

Channel numbers: any channel can be used for any port. There is no request-line mapping.

## 4. Ports

| Port address | Peripheral | Direction | Accepts / gives data while |
|---|---|---|---|
| 0xC0022020 + 0x40c | Link transmit channel c | memory to port | TX_CONTROL bits 0 and 1 = 1, FIFO space |
| 0xC0022220 + 0x40c | Link receive channel c | port to memory | RX_CONTROL bits 0 and 1 = 1, data present |
| 0xC0002014 | I2S0 transmit | memory to port | Paced at 176,400 bytes/s (`09-audio.md`) |
| 0xC0003014 | I2S1 transmit (sound output) | memory to port | Paced at 176,400 bytes/s |
| 0xC0006008 | SPI data | both | Transmit: SSE = 1 and SPI DMACR bit 1 = 1. Receive: frames received while SPI DMACR bit 0 = 1. (`08-i2c-spi-chips.md`) |
| 0xC0006014 | SPI interrupt mask | memory to port | Always (an item of 2 or more bytes sets the SPI IMSC) |
| 0xC003A000 | Sound-synthesis command port | memory to port | Always (not specified, `09-audio.md`) |
| 0xC003A7FC | Sound-synthesis result port | port to memory | Not specified |

Do not use I2S addresses as a DMA source.

## 5. Stock driver notes [STOCK]

Channel numbers that the stock software uses (any channel works in the model): link transmit 2, link receive 9; I2S0 21 / 22; I2S1 transmit 23, receive 24; sound-synthesis block 19 (results), 20 (commands), 36 (memory-to-memory loads); SPI: any free channel for the multimedia chip's messages. One item moves at most 2048 bytes in the stock software.
