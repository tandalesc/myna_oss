// Physical memory: 4K pages in one growing arena, a page table from physical page number to arena page, windows (pages
// whose accesses go to the host, or to a compiled device first; the arena page behind them is the shadow that keeps the
// last value that crossed the bus), and the snapshot reader. A page of a window gets its shadow at the first access:
// until then the page table holds only the number of its window, and the page reads as zeros.
// SPDX-License-Identifier: MIT

pub const PAGE: usize = 4096;
/// Flag in a page-table entry: the page belongs to an external window.
pub const EXT: u32 = 0x8000_0000;
/// Flag beside EXT: the page has no shadow yet; the low 16 bits are the index of its window.
const BARE: u32 = 0x4000_0000;
/// The arena page of a page-table entry, if it has one.
#[inline(always)] fn arena_page(e: u32) -> Option<u32> { let x = (e & !EXT).wrapping_sub(1); if x < BARE - 1 { Some(x) } else { None } }

/// A window. `dev`: the host's device number. `kind`: 0 = every access goes to the host; else the compiled device that
/// is asked first (dev::K_*). `hoff`: offset of `addr` in the host's window, for the accesses passed on to the host.
#[derive(Clone, Copy)]
pub struct Win { pub addr: u32, pub size: u32, pub dev: u32, pub kind: u32, pub hoff: u32 }

pub struct Mem {
    /// Per physical 4K page: 0 = not mapped, else (arena page number + 1), with EXT set for a page of an external window;
    /// or EXT | BARE | window index for a page of a window that was not accessed yet.
    pub pmap: Vec<u32>,
    pub arena: Vec<u8>,
    /// Per arena page: index into `wins` (meaningful for external pages only).
    pwin: Vec<u16>,
    wins: Vec<Win>,
}

impl Mem {
    pub fn new() -> Mem { Mem { pmap: vec![0u32; 1 << 20], arena: Vec::new(), pwin: Vec::new(), wins: Vec::new() } }

    /// Arena offset of a new zeroed page for physical page `pn`, which has none: it is not mapped (the page becomes
    /// RAM), or it is a page of a window without its shadow (it stays a page of that window).
    #[inline(never)]
    pub fn alloc(&mut self, pn: u32) -> u32 {
        let k = (self.arena.len() >> 12) as u32;
        if self.arena.capacity() - self.arena.len() < PAGE { self.arena.reserve(16 << 20); }
        self.arena.resize(self.arena.len() + PAGE, 0);
        let e = self.pmap[pn as usize];
        self.pwin.push(if e & BARE != 0 { e as u16 } else { 0 });
        self.pmap[pn as usize] = (k + 1) | (e & EXT);
        k << 12
    }
    /// Arena offset of physical page `pn`; `alloc`: give it a zeroed page when it has none (see `alloc`).
    #[inline(always)]
    pub fn page(&mut self, pn: u32, alloc: bool) -> Option<u32> {
        if let Some(k) = arena_page(self.pmap[pn as usize]) { return Some(k << 12); }
        if !alloc { return None; }
        Some(self.alloc(pn))
    }
    #[inline(always)] pub fn is_ext(&self, pa: u32) -> bool { self.pmap[(pa >> 12) as usize] & EXT != 0 }
    /// The window of an external page.
    pub fn window(&self, pa: u32) -> Win {
        let e = self.pmap[(pa >> 12) as usize];
        self.wins[match arena_page(e) { Some(k) => self.pwin[k as usize], None => e as u16 } as usize]
    }
    /// Make physical page `pn` a page of window `wi`: memory that is there becomes the shadow, else there is none yet.
    fn set_window(&mut self, pn: u32, wi: usize) {
        match arena_page(self.pmap[pn as usize]) {
            Some(k) => { self.pwin[k as usize] = wi as u16; self.pmap[pn as usize] |= EXT; }
            None => self.pmap[pn as usize] = EXT | BARE | wi as u32,
        }
    }
    fn span_ok(addr: u32, size: u32) -> bool { addr & 0xfff == 0 && size & 0xfff == 0 && size != 0 && addr as u64 + size as u64 <= 1 << 32 }

    pub fn map_ram(&mut self, addr: u32, size: u32) -> i32 {
        if !Self::span_ok(addr, size) { return -1; }
        for pn in (addr >> 12)..(addr >> 12) + (size >> 12) {
            match arena_page(self.pmap[pn as usize]) { Some(_) => self.pmap[pn as usize] &= !EXT, None => { self.pmap[pn as usize] = 0; self.alloc(pn); } }
        }
        0
    }
    pub fn map_ext(&mut self, addr: u32, size: u32, dev: u32) -> i32 {
        if !Self::span_ok(addr, size) || self.wins.len() >= 0xffff { return -1; }
        let wi = match self.wins.iter().position(|w| w.addr == addr && w.size == size) {
            Some(i) => { self.wins[i] = Win { addr, size, dev, kind: 0, hoff: 0 }; i }
            None => { self.wins.push(Win { addr, size, dev, kind: 0, hoff: 0 }); self.wins.len() - 1 }
        };
        for pn in (addr >> 12)..(addr >> 12) + (size >> 12) { self.set_window(pn, wi); }
        0
    }

    /// Give a span that lies in one external window to compiled device `kind` (0: back to the host alone). What the device
    /// declines goes to the host with the device number and offsets of the window the span was part of.
    pub fn map_dev(&mut self, addr: u32, size: u32, kind: u32) -> i32 {
        if !Self::span_ok(addr, size) || self.wins.len() >= 0xffff { return -1; }
        let mut host: Option<(u32, u32)> = None;                   // (device, offset of `addr` in the host's window)
        for pn in (addr >> 12)..(addr >> 12) + (size >> 12) {
            if self.pmap[pn as usize] & EXT == 0 { return -1; }
            let w = self.window(pn << 12);
            let h = (w.dev, w.hoff.wrapping_add(addr.wrapping_sub(w.addr)));
            if *host.get_or_insert(h) != h { return -1; }
        }
        let (dev, hoff) = host.unwrap();
        let wi = match self.wins.iter().position(|w| w.addr == addr && w.size == size) {
            Some(i) => { self.wins[i] = Win { addr, size, dev, kind, hoff }; i }
            None => { self.wins.push(Win { addr, size, dev, kind, hoff }); self.wins.len() - 1 }
        };
        for pn in (addr >> 12)..(addr >> 12) + (size >> 12) { self.set_window(pn, wi); }
        0
    }

    /// Runs of window pages without a shadow: (first page, pages, window index).
    fn bare_runs(&self) -> Vec<(u32, u32, u32)> {
        let mut runs: Vec<(u32, u32, u32)> = Vec::new();
        for (pn, &e) in self.pmap.iter().enumerate() {
            if e & BARE == 0 || e & EXT == 0 { continue; }
            let wi = e & 0xffff;
            match runs.last_mut() { Some(r) if r.0 + r.1 == pn as u32 && r.2 == wi => r.1 += 1, _ => runs.push((pn as u32, 1, wi)) }
        }
        runs
    }

    pub const VERSION: u32 = 2;
    /// The windows; the runs of window pages that have no shadow yet (first page, pages, window index); then every page
    /// with contents: page number, flags (bit 0 external, bit 1 bytes follow; a page of zeros has none), window index,
    /// bytes.
    pub fn save(&self, w: &mut crate::state::Wr) {
        w.u32(self.wins.len() as u32);
        for x in &self.wins { w.words(&[x.addr, x.size, x.dev, x.kind, x.hoff]); }
        let runs = self.bare_runs();
        w.u32(runs.len() as u32);
        for r in &runs { w.words(&[r.0, r.1, r.2]); }
        w.u32(self.pmap.iter().filter(|&&e| arena_page(e).is_some()).count() as u32);
        for (pn, &e) in self.pmap.iter().enumerate() {
            let k = match arena_page(e) { Some(k) => k as usize, None => continue };
            let page = &self.arena[k << 12..(k + 1) << 12];
            let data = page.iter().any(|&b| b != 0);
            w.u32(pn as u32); w.u32((e & EXT != 0) as u32 | (data as u32) << 1); w.u32(self.pwin[k] as u32);
            if data { w.bytes(page); }
        }
    }
    /// Replaces the whole memory: mapping, windows and contents.
    pub fn load(&mut self, r: &mut crate::state::Rd) -> Option<()> {
        let nw = r.u32()? as usize;
        if nw > 0xffff { return None; }
        let mut wins = Vec::with_capacity(nw);
        for _ in 0..nw { let mut f = [0u32; 5]; r.words(&mut f)?; wins.push(Win { addr: f[0], size: f[1], dev: f[2], kind: f[3], hoff: f[4] }); }
        let nr = r.u32()? as usize;
        if nr > 1 << 20 { return None; }
        let mut runs = Vec::with_capacity(nr);
        for _ in 0..nr {
            let (pn, n, wi) = (r.u32()?, r.u32()?, r.u32()?);
            if pn as u64 + n as u64 > 1 << 20 || wi as usize >= wins.len() { return None; }
            runs.push((pn, n, wi));
        }
        let np = r.u32()? as usize;
        if np > 1 << 20 { return None; }
        self.pmap.fill(0); self.arena.clear(); self.pwin.clear(); self.wins = wins;
        for (pn, n, wi) in runs { for p in pn..pn + n { if self.pmap[p as usize] != 0 { return None; } self.pmap[p as usize] = EXT | BARE | wi; } }
        for _ in 0..np {
            let (pn, flags, wi) = (r.u32()?, r.u32()?, r.u32()?);
            if pn >= 1 << 20 || self.pmap[pn as usize] != 0 || (flags & 1 != 0 && wi as usize >= self.wins.len()) { return None; }
            let off = self.alloc(pn) as usize;
            if flags & 2 != 0 { self.arena[off..off + PAGE].copy_from_slice(r.bytes(PAGE)?); }
            if flags & 1 != 0 { self.pmap[pn as usize] |= EXT; self.pwin[off >> 12] = wi as u16; }
        }
        Some(())
    }

    /// Word read for the table walk: unmapped memory reads as zero and stays unmapped.
    #[inline(always)]
    pub fn rd32(&self, pa: u32) -> u32 {
        let k = match arena_page(self.pmap[(pa >> 12) as usize]) { Some(k) => k, None => return 0 };
        let o = ((k << 12) + (pa & 0xffc)) as usize;
        unsafe { (self.arena.as_ptr().add(o) as *const u32).read_unaligned() }
    }
    /// Copy out (shadow for external pages; zeros for unmapped pages and for window pages that were never accessed,
    /// which stay as they are). False when the span leaves the address space.
    pub fn read(&self, addr: u32, buf: &mut [u8]) -> bool {
        if addr as u64 + buf.len() as u64 > 1 << 32 { return false; }
        let (mut a, mut d) = (addr as usize, 0usize);
        while d < buf.len() {
            let n = (PAGE - (a & 0xfff)).min(buf.len() - d);
            match arena_page(self.pmap[a >> 12]) {
                None => buf[d..d + n].fill(0),
                Some(k) => { let o = ((k as usize) << 12) + (a & 0xfff); buf[d..d + n].copy_from_slice(&self.arena[o..o + n]); }
            }
            a += n; d += n;
        }
        true
    }
    /// Copy in (into the shadow for external pages; unmapped pages become RAM). False when the span leaves the address space.
    pub fn write(&mut self, addr: u32, buf: &[u8]) -> bool {
        if addr as u64 + buf.len() as u64 > 1 << 32 { return false; }
        let (mut a, mut d) = (addr as usize, 0usize);
        while d < buf.len() {
            let n = (PAGE - (a & 0xfff)).min(buf.len() - d);
            let o = self.page((a >> 12) as u32, true).unwrap() as usize + (a & 0xfff);
            self.arena[o..o + n].copy_from_slice(&buf[d..d + n]);
            a += n; d += n;
        }
        true
    }
    /// Zero every mapped page (the mapping and the windows stay).
    pub fn zero(&mut self) { self.arena.fill(0); }
}

/// A parsed snapshot: 'SNAP1\0\0\0', u32 nwords, the words, u32 nruns, then per run (u32 addr, u32 len, bytes).
pub struct Snapshot<'a> { pub words: Vec<u32>, pub runs: Vec<(u32, &'a [u8])> }

pub fn parse_snapshot(s: &[u8]) -> Option<Snapshot<'_>> {
    if s.len() < 16 || &s[0..8] != b"SNAP1\0\0\0" { return None; }
    let u = |o: usize| -> Option<u32> { let b = s.get(o..o.checked_add(4)?)?; Some(u32::from_le_bytes([b[0], b[1], b[2], b[3]])) };
    let nw = u(8)? as usize;
    if nw > 4096 { return None; }
    let mut words = Vec::with_capacity(nw);
    for i in 0..nw { words.push(u(12 + 4 * i)?); }
    let mut o = 12 + 4 * nw;
    let nr = u(o)?; o += 4;
    let mut runs = Vec::new();
    for _ in 0..nr {
        let a = u(o)?; let len = u(o + 4)? as usize; o += 8;
        if a as u64 + len as u64 > 1 << 32 { return None; }
        runs.push((a, s.get(o..o.checked_add(len)?)?));
        o += len;
    }
    Some(Snapshot { words, runs })
}
