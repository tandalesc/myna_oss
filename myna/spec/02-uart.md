# 02 Console UART

Base 0xC0013000. Transmit only.

| Offset | Name | Width | Access | Reset | Meaning |
|---|---|---|---|---|---|
| +0x00 | TXDATA | 8 (any size accepted) | W | - | A write sends the low 8 bits as one character. A read gives 0. |
| +0x18 | STATUS | 32 | R | 0x80 | Always 0x80: bit 7 = transmitter idle, ready for the next character; bit 5 (busy) = 0. |
| other | - | - | - | 0 | Reads give 0, writes are ignored. |

Behaviour:

- A character is sent at once. There is no FIFO, no baud rate, no delay.
- The simulator collects the characters into lines. A line feed (0x0A) ends a line. A carriage return (0x0D) is dropped. Each line appears in the run log as `APP uart| <text>` and in the file `app-uart.log` of the run directory. Bytes outside 0x20-0x7E are kept as they are (Latin-1).
- There is no receive path: nothing can be typed into the firmware.
- The UART interrupt (line 22) is never raised.
- Good practice: wait for STATUS bit 7 = 1 before each write. In the simulator it is always 1.
