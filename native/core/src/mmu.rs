// ARMv5 MMU: the table walk (sections, coarse and fine tables, large, small and tiny pages, domains, S / R, FCSE), a software
// TLB with 1K entries, the guest's view of memory through it (with the external windows), and cp15.
// SPDX-License-Identifier: MIT

use crate::cpu::{Cpu, S_DABT, S_NOMEM, S_PABT, S_HOOK, S_UND, S_WFI};

/// Entries per TLB half. An entry covers 1K: the firmware maps memory with fine tables and tiny pages.
pub const TLB_N: usize = 16384;
/// TLB sets, one per recent DACR value: the firmware switches domains about once per 800 instructions, and a flush each time
/// would cost about 150 walks. Each set has two halves, user and privileged, so a mode change needs no flush either.
pub const SETS: usize = 4;

#[derive(Clone, Copy)]
pub struct Tlb { pub tag: u32, pub off: u32 }
pub const NO_ENTRY: Tlb = Tlb { tag: 0xFFFF_FFFF, off: 0 };

impl Cpu {
    /// Flush every set. An epoch in the top bits of the tags makes this free; the tables are cleared only when it wraps.
    pub(crate) fn flush(&mut self) {
        for i in 0..SETS { self.bump(i); }
        self.ep = self.set_ep[self.set]; self.no_code();
    }
    /// Drop the piece of code held for the fetch (see `cva`).
    #[inline(always)] pub(crate) fn no_code(&mut self) { self.c16 = 0; self.c32 = 0; }
    /// Next epoch of one set. The last value is never used: with it a tag could equal the empty entry's.
    fn bump(&mut self, i: usize) {
        self.set_ep[i] = self.set_ep[i].wrapping_add(1 << 22);
        if self.set_ep[i] >= 0xffc0_0000 { self.set_ep[i] = 0; self.clear_set(i); }
    }
    fn clear_set(&mut self, set: usize) {
        let (a, b) = (set * 2 * TLB_N, (set + 1) * 2 * TLB_N);
        self.tlb_r[a..b].fill(NO_ENTRY); self.tlb_w[a..b].fill(NO_ENTRY); self.tlb_x[a..b].fill(NO_ENTRY); self.no_code();
    }
    /// A DACR write selects the set that belongs to the value (or recycles the oldest one) instead of flushing.
    pub(crate) fn set_dacr(&mut self, x: u32) {
        self.dacr = x;
        let i = match (0..SETS).find(|&i| self.set_dacr[i] == x) { Some(i) => i, None => {
            let i = self.set_next; self.set_next = (i + 1) % SETS; self.set_dacr[i] = x;
            self.bump(i);
            i } };
        self.tb = self.tb % (2 * TLB_N) + i * 2 * TLB_N; self.set = i; self.ep = self.set_ep[i]; self.no_code();
    }
    /// Back to one set holding the current DACR value, everything flushed (snapshot load).
    pub(crate) fn reset_tlb(&mut self) {
        self.set = 0; self.set_next = 1; self.set_dacr = [self.dacr; SETS];
        self.tb = if self.rest & 0x1f == 0x10 { 0 } else { TLB_N };
        self.flush();
    }

    fn ap_ok(&self, ap: u32, write: bool) -> bool {
        let (s, r, p) = (self.sctlr & 0x100 != 0, self.sctlr & 0x200 != 0, self.priv_());
        match ap { 0 => { if s && !r { p && !write } else if r && !s { !write } else { false } } 1 => p, 2 => p || !write, _ => true }
    }
    /// Virtual to physical; None with the fault status in `ffsr`.
    pub(crate) fn translate(&mut self, va0: u32, write: bool) -> Option<u32> {
        if self.sctlr & 1 == 0 { return Some(va0); }
        self.walks += 1;
        let va = if va0 < 0x0200_0000 { va0.wrapping_add(self.fcse & 0xfe00_0000) } else { va0 };
        let d1 = self.mem.rd32((self.ttbr & 0xffff_c000) | ((va >> 20) << 2));
        let t = d1 & 3; if t == 0 { self.ffsr = 5; return None; }
        let dom = (d1 >> 5 & 15) << 4;
        let dm = self.dacr >> ((d1 >> 5 & 15) * 2) & 3;
        if dm == 0 || dm == 2 { self.ffsr = (if t == 2 { 9 } else { 11 }) | dom; return None; }
        if t == 2 { if dm == 1 && !self.ap_ok(d1 >> 10 & 3, write) { self.ffsr = 13 | dom; return None; } return Some((d1 & 0xfff0_0000) | (va & 0xf_ffff)); }
        let l2 = if t == 1 { (d1 & 0xffff_fc00) | ((va >> 12 & 0xff) << 2) } else { (d1 & 0xffff_f000) | ((va >> 10 & 0x3ff) << 2) };
        let d2 = self.mem.rd32(l2);
        let (pa, ap) = match d2 & 3 { 0 => { self.ffsr = 7 | dom; return None; }
            1 => ((d2 & 0xffff_0000) | (va & 0xffff), d2 >> (4 + 2 * (va >> 14 & 3)) & 3),
            2 => ((d2 & 0xffff_f000) | (va & 0xfff), d2 >> (4 + 2 * (va >> 10 & 3)) & 3),
            _ => ((d2 & 0xffff_fc00) | (va & 0x3ff), d2 >> 4 & 3) };
        if dm == 1 && !self.ap_ok(ap, write) { self.ffsr = 15 | dom; return None; }
        Some(pa)
    }

    /// Translate `va` for `kind` (0 read, 1 write, 2 execute) and enter it into the TLB. Returns the arena offset of the 1K
    /// piece; `fpa` is the physical address, `fext` says the page belongs to an external window. On a fault `stop` is set.
    /// Data accesses to external pages are never cached (every one has to reach the host), nor are fetches from a 1K piece
    /// that holds an entry hook (every one has to be checked).
    #[inline(never)]
    pub(crate) fn fill(&mut self, va: u32, kind: u32) -> Option<u32> {
        let pa = match self.translate(va, kind == 1) { Some(p) => p, None => { self.f.stop = if kind == 2 { S_PABT } else { S_DABT }; self.stop_addr = va; return None; } };
        // a data access maps memory that is not there; a window page gets its shadow at the first access of any kind
        let off = match self.mem.page(pa >> 12, kind != 2 || self.mem.is_ext(pa)) { Some(o) => o, None => { self.f.stop = S_NOMEM; self.stop_addr = va; return None; } };
        let off = off + (pa & 0xc00);
        self.fpa = pa; self.fext = self.mem.is_ext(pa);
        let e = Tlb { tag: va >> 10 | self.ep, off };
        let i = self.tb + ((va >> 10) as usize & (TLB_N - 1));
        match kind {
            0 => if !self.fext { self.tlb_r[i] = e },
            1 => if !self.fext { self.tlb_w[i] = e },
            _ => { self.no_code(); if self.hooks.is_empty() || !self.hook_piece(va) { self.tlb_x[i] = e } }
        }
        Some(off)
    }
    fn hook_piece(&self, va: u32) -> bool {
        let lo = va & !0x3ff; let i = self.hooks.partition_point(|&h| h < lo);
        i < self.hooks.len() && self.hooks[i] - lo < 0x400
    }

    // ---- data access, slow paths ---------------------------------------------------------------
    #[inline(never)]
    pub(crate) fn rd_slow(&mut self, va: u32, n: u32) -> u32 {
        if (va & 0x3ff) + n > 0x400 {                       // crosses a 1K piece: both ends must translate before anything is read
            if self.fill(va, 0).is_none() || self.fill(va.wrapping_add(n - 1), 0).is_none() { return 0; }
            let mut x = 0; for i in 0..n { x |= self.rd_slow(va.wrapping_add(i), 1) << (8 * i); } return x;
        }
        let o = match self.fill(va, 0) { Some(o) => o as usize + (va & 0x3ff) as usize, None => return 0 };
        if self.fext { let pa = self.fpa; return self.ext_read(pa, n); }
        let a = &self.mem.arena;
        match n { 1 => a[o] as u32, 2 => u16::from_le_bytes([a[o], a[o + 1]]) as u32, _ => u32::from_le_bytes([a[o], a[o + 1], a[o + 2], a[o + 3]]) }
    }
    #[inline(never)]
    pub(crate) fn wr_slow(&mut self, va: u32, n: u32, x: u32) {
        if (va & 0x3ff) + n > 0x400 {                       // no partial store
            if self.fill(va, 1).is_none() || self.fill(va.wrapping_add(n - 1), 1).is_none() { return; }
            for i in 0..n { self.wr_slow(va.wrapping_add(i), 1, x >> (8 * i) & 0xff); } return;
        }
        let o = match self.fill(va, 1) { Some(o) => o as usize + (va & 0x3ff) as usize, None => return };
        if self.fext { let pa = self.fpa; self.ext_write(pa, n, x); return; }
        let a = &mut self.mem.arena;
        match n { 1 => a[o] = x as u8, 2 => a[o..o + 2].copy_from_slice(&(x as u16).to_le_bytes()), _ => a[o..o + 4].copy_from_slice(&x.to_le_bytes()) }
    }
    // ---- block transfers ---------------------------------------------------------------------------
    // A word of LDM, STM, PUSH, POP, LDRD or STRD. `rest`: one bit per word of the instruction that follows this one. The
    // fast paths are those of a single word. On the slow path, before a word that goes to a device, the words that
    // follow are checked: if one of them is going to fault, its abort is taken now and the device is not touched, so
    // that the restarted instruction does not reach the device a second time.
    #[inline(always)] pub(crate) fn rd32_blk(&mut self, va: u32, rest: u32) -> u32 {
        let e = Self::ent(&self.tlb_r, self.slot(va));
        if e.tag == (va >> 10 | self.ep) && va & 0x3ff <= 0x3fc { unsafe { (self.mem.arena.as_ptr().add((e.off + (va & 0x3ff)) as usize) as *const u32).read_unaligned() } } else { self.rd_blk_slow(va, rest) }
    }
    #[inline(always)] pub(crate) fn wr32_blk(&mut self, va: u32, x: u32, rest: u32) {
        let e = Self::ent(&self.tlb_w, self.slot(va));
        if e.tag == (va >> 10 | self.ep) && va & 0x3ff <= 0x3fc { unsafe { (self.mem.arena.as_mut_ptr().add((e.off + (va & 0x3ff)) as usize) as *mut u32).write_unaligned(x) } } else { self.wr_blk_slow(va, x, rest) }
    }
    #[inline(never)]
    fn rd_blk_slow(&mut self, va: u32, rest: u32) -> u32 {
        let k = rest.count_ones();
        // words that follow in the same 1K piece as this one translate as this one does
        if k != 0 && (va ^ va.wrapping_add(4 * k + 3)) >> 10 != 0 && !self.blk_rest(va, k, false) { return 0; }
        self.rd_slow(va, 4)
    }
    #[inline(never)]
    fn wr_blk_slow(&mut self, va: u32, x: u32, rest: u32) {
        let k = rest.count_ones();
        if k != 0 && (va ^ va.wrapping_add(4 * k + 3)) >> 10 != 0 && !self.blk_rest(va, k, true) { return; }
        self.wr_slow(va, 4, x)
    }
    /// The word at `va` of a block transfer, with `k` words after it. When the word goes to a device, the words after it
    /// are translated (nothing else is done to them). False: one of them faults; `stop` and the fault address and status
    /// are set as the transfer would have set them on arriving there. A word that faults itself is left to the access.
    fn blk_rest(&mut self, va: u32, k: u32, write: bool) -> bool {
        let last = va.wrapping_add(3);
        let mut dev = false;
        for a in [va, last] {
            match self.translate(a, write) { Some(pa) => dev |= self.to_device(pa, write), None => return true }
            if last >> 10 == va >> 10 { break; }
        }
        if !dev { return true; }
        let mut piece = last >> 10;                         // the last 1K piece known to translate
        for j in 1..=k {
            let a = va.wrapping_add(4 * j);
            for b in [a, a.wrapping_add(3)] {
                if b >> 10 == piece { continue; }
                if self.translate(b, write).is_none() { self.f.stop = S_DABT; self.stop_addr = b; return false; }
                piece = b >> 10;
            }
        }
        true
    }
    /// An access to `pa` reaches a compiled device or a callback of the host (a window without them is memory).
    fn to_device(&self, pa: u32, write: bool) -> bool {
        self.mem.is_ext(pa) && (self.mem.window(pa).kind != 0 || self.has_host(write))
    }

    /// An access to a window: the compiled device of the window is asked first, if it has one; what it declines, and every
    /// access to a window without one, goes to the host. Then the value goes into the shadow page. The host may call back
    /// into the core (interrupt inputs, memory, stop request), so nothing computed before the call is used after it.
    #[inline(never)]
    fn ext_read(&mut self, pa: u32, n: u32) -> u32 {
        let w = self.mem.window(pa); let off = pa.wrapping_sub(w.addr);
        let mask = 0xffff_ffffu32 >> (32 - 8 * n);
        if w.kind != 0 { if let Some(x) = self.dev_read(w.kind, off, n) { return self.shadow(pa, n, Some(x & mask)); } }
        let x = match self.host_read(w.dev, off.wrapping_add(w.hoff), n) { Some(x) => x & mask, None => return self.shadow(pa, n, None) };
        self.shadow(pa, n, Some(x))
    }
    #[inline(never)]
    fn ext_write(&mut self, pa: u32, n: u32, x: u32) {
        let x = x & (0xffff_ffffu32 >> (32 - 8 * n));
        let w = self.mem.window(pa); let off = pa.wrapping_sub(w.addr);
        if w.kind == 0 || !self.dev_write(w.kind, off, n, x) { self.host_write(w.dev, off.wrapping_add(w.hoff), n, x); }
        self.shadow(pa, n, Some(x));
    }
    /// Store into (Some) or read from (None) the shadow of an external page.
    fn shadow(&mut self, pa: u32, n: u32, x: Option<u32>) -> u32 {
        let o = self.mem.page(pa >> 12, true).unwrap() as usize + (pa & 0xfff) as usize;
        let a = &mut self.mem.arena[o..o + n as usize];
        match x {
            Some(x) => { a.copy_from_slice(&x.to_le_bytes()[..n as usize]); x }
            None => { let mut b = [0u8; 4]; b[..n as usize].copy_from_slice(a); u32::from_le_bytes(b) }
        }
    }

    // ---- data access, fast paths ---------------------------------------------------------------
    #[inline(always)] fn ent(t: &[Tlb], i: usize) -> Tlb { unsafe { *t.as_ptr().add(i) } }
    #[inline(always)] fn slot(&self, va: u32) -> usize { self.tb + ((va >> 10) as usize & (TLB_N - 1)) }
    #[inline(always)] pub(crate) fn rd32(&mut self, va: u32) -> u32 {
        let e = Self::ent(&self.tlb_r, self.slot(va));
        if e.tag == (va >> 10 | self.ep) && va & 0x3ff <= 0x3fc { unsafe { (self.mem.arena.as_ptr().add((e.off + (va & 0x3ff)) as usize) as *const u32).read_unaligned() } } else { self.rd_slow(va, 4) }
    }
    #[inline(always)] pub(crate) fn rd16(&mut self, va: u32) -> u32 {
        let e = Self::ent(&self.tlb_r, self.slot(va));
        if e.tag == (va >> 10 | self.ep) && va & 0x3ff <= 0x3fe { unsafe { (self.mem.arena.as_ptr().add((e.off + (va & 0x3ff)) as usize) as *const u16).read_unaligned() as u32 } } else { self.rd_slow(va, 2) }
    }
    #[inline(always)] pub(crate) fn rd8(&mut self, va: u32) -> u32 {
        let e = Self::ent(&self.tlb_r, self.slot(va));
        if e.tag == (va >> 10 | self.ep) { unsafe { *self.mem.arena.as_ptr().add((e.off + (va & 0x3ff)) as usize) as u32 } } else { self.rd_slow(va, 1) }
    }
    #[inline(always)] pub(crate) fn wr32(&mut self, va: u32, x: u32) {
        let e = Self::ent(&self.tlb_w, self.slot(va));
        if e.tag == (va >> 10 | self.ep) && va & 0x3ff <= 0x3fc { unsafe { (self.mem.arena.as_mut_ptr().add((e.off + (va & 0x3ff)) as usize) as *mut u32).write_unaligned(x) } } else { self.wr_slow(va, 4, x) }
    }
    #[inline(always)] pub(crate) fn wr16(&mut self, va: u32, x: u32) {
        let e = Self::ent(&self.tlb_w, self.slot(va));
        if e.tag == (va >> 10 | self.ep) && va & 0x3ff <= 0x3fe { unsafe { (self.mem.arena.as_mut_ptr().add((e.off + (va & 0x3ff)) as usize) as *mut u16).write_unaligned(x as u16) } } else { self.wr_slow(va, 2, x) }
    }
    #[inline(always)] pub(crate) fn wr8(&mut self, va: u32, x: u32) {
        let e = Self::ent(&self.tlb_w, self.slot(va));
        if e.tag == (va >> 10 | self.ep) { unsafe { *self.mem.arena.as_mut_ptr().add((e.off + (va & 0x3ff)) as usize) = x as u8 } } else { self.wr_slow(va, 1, x) }
    }
    /// Make sure the byte at `va` can be read / written, without touching it (sets `stop` on a fault).
    #[inline(always)] pub(crate) fn touch(&mut self, va: u32, w: bool) {
        let e = Self::ent(if w { &self.tlb_w } else { &self.tlb_r }, self.slot(va));
        if e.tag != (va >> 10 | self.ep) { self.fill(va, w as u32); }
    }

    // ---- instruction fetch -----------------------------------------------------------------------
    // First the piece of code held from the last fetch (no look-up); else the TLB, and a hit there is held for the next
    // fetch. The value is in the low half; the high half is not zero when the fetch set `stop`.
    #[inline(always)] pub(crate) fn fetch32(&mut self, va: u32) -> u64 {
        let d = va.wrapping_sub(self.cva);
        if d < self.c32 { return unsafe { (self.mem.arena.as_ptr().add((self.coff + d) as usize) as *const u32).read_unaligned() } as u64; }
        self.fetch_miss(va, 4)
    }
    #[inline(always)] pub(crate) fn fetch16(&mut self, va: u32) -> u64 {
        let d = va.wrapping_sub(self.cva);
        if d < self.c16 { return unsafe { (self.mem.arena.as_ptr().add((self.coff + d) as usize) as *const u16).read_unaligned() } as u64; }
        self.fetch_miss(va, 2)
    }
    #[inline(never)] fn fetch_miss(&mut self, va: u32, n: u32) -> u64 {
        let e = Self::ent(&self.tlb_x, self.slot(va));
        let x = if e.tag == (va >> 10 | self.ep) && (va & 0x3ff) + n <= 0x400 {
            self.cva = va & !0x3ff; self.coff = e.off; self.c16 = 0x3ff; self.c32 = 0x3fd;
            let p = unsafe { self.mem.arena.as_ptr().add((e.off + (va & 0x3ff)) as usize) };
            if n == 4 { unsafe { (p as *const u32).read_unaligned() } } else { unsafe { (p as *const u16).read_unaligned() as u32 } }
        } else { self.fetch_slow(va, n, true) };
        (self.f.stop as u64) << 32 | x as u64
    }
    /// The second half of a Thumb BL pair: part of the same instruction, so no hook is looked up.
    #[inline(always)] pub(crate) fn fetch16_more(&mut self, va: u32) -> u32 {
        let e = Self::ent(&self.tlb_x, self.slot(va));
        if e.tag == (va >> 10 | self.ep) && va & 0x3ff <= 0x3fe { unsafe { (self.mem.arena.as_ptr().add((e.off + (va & 0x3ff)) as usize) as *const u16).read_unaligned() as u32 } } else { self.fetch_slow(va, 2, false) }
    }
    #[inline(never)] fn fetch_slow(&mut self, va: u32, n: u32, first: bool) -> u32 {
        if first && !self.hooks.is_empty() {
            if self.hook_skip { self.hook_skip = false; }
            else if self.hooks.binary_search(&va).is_ok() { self.f.stop = S_HOOK; return 0; }
        }
        let mut x = 0;
        for i in 0..n { let a = va.wrapping_add(i); match self.fill(a, 2) { Some(o) => x |= (self.mem.arena[o as usize + (a & 0x3ff) as usize] as u32) << (8 * i), None => return 0 } }
        x
    }

    // ---- cp15 --------------------------------------------------------------------------------------
    /// MRC / MCR p15. ID and cache type as the ARM926EJ-S; c1, c2, c3, c5, c6, c13 modelled; c7 cache operations do nothing
    /// (test-and-clean reads as clean, c7,c0,4 is wait-for-interrupt); c8 flushes; c15 (test and debug) reads zero and
    /// ignores writes; every other word is a stored value. In user mode the instruction is undefined, as on the CPU.
    #[inline(never)]
    pub(crate) fn cp15(&mut self, op: u32) {
        let (crn, crm, op2, rd) = (op >> 16 & 15, op & 15, op >> 5 & 7, op >> 12 & 15);
        if !self.priv_() { self.f.stop = S_UND; self.r[15] = self.r[15].wrapping_sub(4); return; }
        if op & 0x0010_0000 != 0 {
            let x = match crn { 0 if op2 == 0 => 0x4106_9265, 0 if op2 == 1 => 0x01dd_20d2, 1 if crm == 0 && op2 == 0 => self.sctlr, 2 => self.ttbr, 3 => self.dacr,
                5 => self.fsr[(op2 & 1) as usize], 6 => self.far, 13 if op2 == 0 => self.fcse, 7 => 0x4000_0000, 15 => 0,
                _ => *self.cpmap.get(&(op & 0x00ef_00ef)).unwrap_or(&0) };
            if rd != 15 { self.r[rd as usize] = x; } else { self.n = x >> 31; self.z = x >> 30 & 1; self.c = x >> 29 & 1; self.v = x >> 28 & 1; }
        } else {
            let x = self.rg(rd);
            match crn { 1 if crm == 0 && op2 == 0 => { self.sctlr = x; self.flush(); } 2 => { self.ttbr = x; } 3 => self.set_dacr(x),
                5 => self.fsr[(op2 & 1) as usize] = x, 6 => self.far = x,
                7 => { if crm == 0 && op2 == 4 { self.f.stop = S_WFI; } }
                8 => self.flush(), 13 if op2 == 0 => { self.fcse = x; self.flush(); } 15 => {}
                _ => { self.cpmap.insert(op & 0x00ef_00ef, x); } }
        }
    }
}
