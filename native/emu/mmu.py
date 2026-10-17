"""Software ARMv5 (ARM926) MMU walk, used to work out the fault address/status of a Unicorn MMU abort.
No Unicorn import: pass read32(physical_address) -> int."""

# fault status (FSR[3:0]); domain goes in FSR[7:4]
FS_ALIGN, FS_SEC_TRANS, FS_PAGE_TRANS = 0x1, 0x5, 0x7
FS_SEC_DOMAIN, FS_PAGE_DOMAIN, FS_SEC_PERM, FS_PAGE_PERM = 0x9, 0xB, 0xD, 0xF


def _ap_ok(ap, write, priv, s, r):
    if ap == 0:
        if s and not r: return priv and not write          # priv read-only
        if r and not s: return not write                   # read-only for all
        return False
    if ap == 1: return priv
    if ap == 2: return priv or not write
    return True


def translate(va, write, priv, ttb, dacr, sr, read32):
    """Returns (True, pa) or (False, fsr). sr = (S, R) bits of SCTLR."""
    s, r = sr
    d1 = read32((ttb & 0xFFFFC000) | ((va >> 20) << 2))
    t = d1 & 3
    if t == 0:
        return False, FS_SEC_TRANS
    dom = (d1 >> 5) & 0xF
    dm = (dacr >> (dom * 2)) & 3
    sec = t == 2
    if dm in (0, 2):
        return False, (FS_SEC_DOMAIN if sec else FS_PAGE_DOMAIN) | (dom << 4)
    if sec:
        if dm == 1 and not _ap_ok((d1 >> 10) & 3, write, priv, s, r):
            return False, FS_SEC_PERM | (dom << 4)
        return True, (d1 & 0xFFF00000) | (va & 0xFFFFF)
    if t == 1:
        l2a = (d1 & 0xFFFFFC00) | (((va >> 12) & 0xFF) << 2)
    else:
        l2a = (d1 & 0xFFFFF000) | (((va >> 10) & 0x3FF) << 2)
    d2 = read32(l2a)
    t2 = d2 & 3
    if t2 == 0:
        return False, FS_PAGE_TRANS | (dom << 4)
    if t2 == 1:
        pa = (d2 & 0xFFFF0000) | (va & 0xFFFF); ap = (d2 >> (4 + 2 * ((va >> 14) & 3))) & 3
    elif t2 == 2:
        pa = (d2 & 0xFFFFF000) | (va & 0xFFF); ap = (d2 >> (4 + 2 * ((va >> 10) & 3))) & 3
    else:
        pa = (d2 & 0xFFFFFC00) | (va & 0x3FF); ap = (d2 >> 4) & 3
    if dm == 1 and not _ap_ok(ap, write, priv, s, r):
        return False, FS_PAGE_PERM | (dom << 4)
    return True, pa
