# 11 Link to the modem processor

## 1. Overview

The link block joins the application CPU and the modem CPU. Each side has the same block at 0xC0022000 (8 KB window). It has 8 transmit and 8 receive channels. Bytes written into transmit channel c of one side appear in receive channel c of the other side. The channels are byte FIFOs that the CPU or the DMA controller can fill and empty. A transmit channel can mark the end of a message.

In the simulator the modem side is played by a modem stand-in. With the stock profiles (variants A and B) it speaks the link protocol of the stock firmware on channels 0 and 2; that protocol is not part of this specification. With the `myna` profile it is the AT modem: standard protocols on channel 0, described in `14-modem-at.md`.

This file describes the block at the hardware level only.

## 2. Registers (application side, base 0xC0022000)

Transmit channel c (0-7) at 0xC0022000 + 0x40 x c. Receive channel c at 0xC0022200 + 0x40 x c.

### 2.1 Transmit channel registers

| Offset | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| +0x00 | TX_CONTROL | RW | 0 | Bit 0 = enable. Bit 1 = DMA requests enabled. Bit 2 stored. Bits 13:8 threshold, bits 23:16 depth - 1: stored, no effect. Channel 7 only: writing bit 0 = 1 sends a wake-up signal to the other side (section 4). |
| +0x04 | TX_STATUS | R, bit 6 W1C | 0x0C | Bit 2 = FIFO empty. Bit 3 = space in the FIFO. Bit 4 = FIFO full. Bit 6 = done: a message ended with TX_COMMAND has left the FIFO completely. Write 1 to bit 6 to clear it. |
| +0x08 | TX_LEVEL | R | 0 | Bytes in the FIFO |
| +0x0C | TX_IRQ_ENABLE | RW | 0 | Bit 3 = interrupt while there is space in the FIFO. Bit 6 = interrupt while "done" is set. |
| +0x10 | TX_COMMAND | W; R = message pending | 0 | Write bit 0 = 1: end of message after the bytes written so far. Reads 1 while an ended message has not completely left the FIFO. |
| +0x20 | TX_DATA | W | - | Write 1, 2 or 4 bytes (little-endian) into the FIFO. Ignored when the channel is not enabled. Bytes that do not fit are lost. |

### 2.2 Receive channel registers

| Offset | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| +0x00 | RX_CONTROL | RW | 0 | Bit 0 = enable: bytes from the other side enter only while it is 1. Bit 1 = DMA requests enabled. |
| +0x04 | RX_STATUS | R, bit 6 W1C | 0x04 | Bit 2 = FIFO empty. Bit 3 = data available. Bit 6 = end of message: the oldest message that the other side ended has been read completely. Write 1 to bit 6 to acknowledge it (the next message boundary then applies). |
| +0x08 | RX_LEVEL | R | 0 | Bytes in the FIFO (at most 0x7F) |
| +0x0C | RX_IRQ_ENABLE | RW | 0 | Bit 3 = interrupt while data is available. Bit 6 = interrupt while end of message is set. |
| +0x10 | RX_COMMAND | S | 0 | |
| +0x20 | RX_DATA | R | - | Read 1, 2 or 4 bytes (little-endian). Missing bytes read as 0. |

### 2.3 Common registers

| Address | Name | Access | Reset | Meaning |
|---|---|---|---|---|
| 0xC0022400 | MODE | S | 0 | |
| 0xC0022404 | SLEEP | RW | 0 | Bit 0 = the link is asleep: then data arriving on receive channel 0 also raises the wake line. |
| 0xC0022408, 0xC0022410 | - | S | 0 | |
| 0xC0022500 | CHANNEL_IRQ_ENABLE | W1S; read = current | 0 | Bit c = transmit channel c, bit 8 + c = receive channel c may interrupt. Only channels 0-6 can be enabled (mask 0x7F7F). |
| 0xC0022504 | CHANNEL_IRQ_DISABLE | W1C (of 0xC0022500) | - | Writing bit 8 also clears a pending wake-up signal. |

Wake-up kick: TX_CONTROL of transmit channel 7 is 0xC00221C0.

## 3. Data movement

- FIFO depth: 64 bytes per channel and direction [MOCK: inferred].
- Bytes move from a transmit FIFO to the other side's receive FIFO at once, while the receive channel is enabled and has space [MODEL: no transfer time]. A full receive FIFO holds the bytes back in the transmit FIFO: that is the only flow control.
- A message boundary set with TX_COMMAND travels with the bytes. On the receive side, RX_STATUS bit 6 becomes 1 when all bytes of the oldest ended message have been read.
- An empty message (TX_COMMAND with no bytes) also produces a boundary.

## 4. Interrupt lines (application side)

| Line | Name | High while |
|---|---|---|
| 5 | RECEIVE | Any receive channel c enabled in CHANNEL_IRQ_ENABLE (bit 8 + c) has (RX_IRQ_ENABLE bit 3 and data) or (RX_IRQ_ENABLE bit 6 and end of message). |
| 6 | TRANSMIT | Any transmit channel c enabled in CHANNEL_IRQ_ENABLE (bit c) has (TX_IRQ_ENABLE bit 3 and FIFO not full) or (TX_IRQ_ENABLE bit 6 and done). |
| 8 | WAKE | The other side has sent a wake-up kick and it is still pending, or SLEEP bit 0 = 1 and receive channel 0 holds data. |

A pending wake-up kick is cleared when receive channel 0 is read empty, or by writing bit 8 to CHANNEL_IRQ_DISABLE.

## 5. DMA

- The data registers are DMA ports (`13-dma.md`): transmit channel c at 0xC0022020 + 0x40 x c, receive channel c at 0xC0022220 + 0x40 x c.
- A transmit port accepts DMA data while TX_CONTROL bits 0 and 1 are both 1. A receive port gives DMA data while RX_CONTROL bits 0 and 1 are both 1.
- A DMA item to a transmit port whose control word has bits 24 and 25 both set ends a message when its count reaches 0 (as a write of TX_COMMAND bit 0).

## 6. A clean firmware and the modem stand-in

- With a stock device profile, the stock modem stand-in is connected to the modem side and writes into the application's receive channels 0 and 2 and may send wake-up kicks.
- With the `myna` profile, the AT modem is connected (`14-modem-at.md`). It uses channel 0 only, sends no wake-up kicks, and sends nothing before the firmware has sent a byte on channel 0.
- Bytes reach the application only while its receive channel is enabled. A firmware that does not use the link: leave all channels disabled (RX_CONTROL bit 0 = 0) and keep lines 5, 6 and 8 disabled in VIC0.
- Without a modem stand-in (no peer), nothing arrives and transmitted bytes stay in the transmit FIFO.

## 7. Stock driver notes [STOCK]

Register-level use only; the content of the bytes is not described.

- Both processors run the same driver for the block. Channel 0 is used without DMA, with an interrupt for every byte received. Channel 2 is used with DMA: the stock software transmits with DMA channel 2 and receives with DMA channel 9 on each processor; the last transmit item of a message has control bits 24 and 25 set.
- The wake-up kick (transmit channel 7 control bit 0) is sent before transmitting after the link has been idle; SLEEP bit 0 is set while the link is considered asleep.
- Channels 1 and 3-6 are meant for sound between the processors; no run used them.
- Bytes written before the other side has started stay in the FIFO until it reads them.
