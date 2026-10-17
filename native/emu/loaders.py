"""Firmware image loaders: ELF (a firmware of our own) and the stock firmware's two container forms. Return (load_address,
bytes) pairs; no Unicorn dependency."""
import struct

PAGE = 0x1000
PCORE_MAGIC = 0x0016dadf


def load_cxc(path):
    """Plain CXC: header fields 0x44 (header size), 0x48 (body size), 0x4C (load address). path: a file name, or the bytes of the file."""
    d = path if isinstance(path, (bytes, bytearray)) else open(path, 'rb').read()
    hdr, size, addr = struct.unpack_from('<III', d, 0x44)
    return addr, d[hdr:hdr + size]


def load_elf(path):
    """A 32-bit little-endian ARM ELF executable (a firmware of our own, not the stock one): (entry, [(address, bytes)]), one pair
    per PT_LOAD segment at its physical address, zero-filled up to its size in memory (.bss). path: a file name or the bytes."""
    d = path if isinstance(path, (bytes, bytearray)) else open(path, 'rb').read()
    if d[:4] != b'\x7fELF' or d[4] != 1 or d[5] != 1 or struct.unpack_from('<H', d, 18)[0] != 40:
        raise ValueError('not a 32-bit little-endian ARM ELF file')
    entry, phoff = struct.unpack_from('<II', d, 24)
    phentsize, phnum = struct.unpack_from('<HH', d, 42)
    segs = []
    for i in range(phnum):
        p_type, off, _vaddr, paddr, filesz, memsz = struct.unpack_from('<6I', d, phoff + i * phentsize)
        if p_type == 1 and memsz:                            # PT_LOAD
            segs.append((paddr, d[off:off + filesz] + bytes(memsz - filesz)))
    return entry, segs


def load_pcore(path):
    """The paged container of the stock boot loader: body = pages of 0x20-byte header + payload; payload n lands at
    base+(n-1)*0xfe0."""
    _, body = load_cxc(path)
    mem = bytearray()
    base = None
    for off in range(0, len(body), PAGE):
        magic, _, _, _, la, sz = struct.unpack_from('<6I', body, off)
        assert magic == PCORE_MAGIC, f'bad pCore page magic at body+{off:#x}'
        if base is None:
            base = la
        assert la == base + len(mem), f'pCore page at body+{off:#x} not contiguous'
        mem += body[off + 0x20:off + 0x20 + sz]
    return base, bytes(mem)
