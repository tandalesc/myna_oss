// State save / load. One container: 'DBCSTATE', u32 format version, u32 section count, then per section an 8-byte name
// (ASCII, zero padded), u32 version, u32 length and the bytes. All numbers little-endian. Sections: cpu, cp15, mem, clock,
// lines, and one per compiled device (nand, timer, vic, sysctl, clkprof). Loading: a section whose name the core does not know is skipped; a
// known section with a version the core does not know fails the load before anything is changed; a part of the core that
// has no section in the container keeps the state it has. Not saved: the TLB (it is flushed), the event log, the entry
// hooks and the callbacks of the host.
// SPDX-License-Identifier: MIT

use crate::cpu::Cpu;
use crate::dev::{clock::Clock, nand::Nand, sysctl::{ClkProf, SysCtl}, timer::Timer, vic::VicPair};

pub const MAGIC: &[u8; 8] = b"DBCSTATE";
pub const FORMAT: u32 = 1;

/// Byte sink that either stores or only counts.
pub struct Wr { buf: Option<Vec<u8>>, n: usize }
impl Wr {
    pub fn counting() -> Wr { Wr { buf: None, n: 0 } }
    pub fn storing(cap: usize) -> Wr { Wr { buf: Some(Vec::with_capacity(cap)), n: 0 } }
    pub fn len(&self) -> usize { self.n }
    pub fn into_bytes(self) -> Vec<u8> { self.buf.unwrap_or_default() }
    pub fn bytes(&mut self, b: &[u8]) { self.n += b.len(); if let Some(v) = &mut self.buf { v.extend_from_slice(b); } }
    pub fn u8(&mut self, x: u8) { self.bytes(&[x]); }
    pub fn u32(&mut self, x: u32) { self.bytes(&x.to_le_bytes()); }
    pub fn u64(&mut self, x: u64) { self.bytes(&x.to_le_bytes()); }
    pub fn words(&mut self, a: &[u32]) { for x in a { self.u32(*x); } }
    /// Fill in a u32 written earlier at `at` (the length of a section).
    fn patch(&mut self, at: usize, x: u32) { if let Some(v) = &mut self.buf { v[at..at + 4].copy_from_slice(&x.to_le_bytes()); } }
    fn section(&mut self, name: &str, version: u32, body: impl FnOnce(&mut Wr)) {
        let mut nm = [0u8; 8]; nm[..name.len()].copy_from_slice(name.as_bytes());
        self.bytes(&nm); self.u32(version);
        let at = self.n; self.u32(0);
        body(self);
        let len = self.n - at - 4; self.patch(at, len as u32);
    }
}

/// Reader over a byte slice; every call gives None past the end.
pub struct Rd<'a> { s: &'a [u8], o: usize }
impl<'a> Rd<'a> {
    pub fn new(s: &'a [u8]) -> Rd<'a> { Rd { s, o: 0 } }
    pub fn left(&self) -> usize { self.s.len() - self.o }
    pub fn bytes(&mut self, n: usize) -> Option<&'a [u8]> { let b = self.s.get(self.o..self.o.checked_add(n)?)?; self.o += n; Some(b) }
    pub fn u8(&mut self) -> Option<u8> { Some(self.bytes(1)?[0]) }
    pub fn u32(&mut self) -> Option<u32> { let b = self.bytes(4)?; Some(u32::from_le_bytes([b[0], b[1], b[2], b[3]])) }
    pub fn u64(&mut self) -> Option<u64> { let b = self.bytes(8)?; let mut a = [0u8; 8]; a.copy_from_slice(b); Some(u64::from_le_bytes(a)) }
    pub fn words(&mut self, a: &mut [u32]) -> Option<()> { for x in a.iter_mut() { *x = self.u32()?; } Some(()) }
}

const CPU_V: u32 = 1;
const CP15_V: u32 = 1;
const LINES_V: u32 = 1;

/// Version the core knows for a section name; None for a name it does not know.
fn known(name: &[u8]) -> Option<u32> {
    let n = name.iter().position(|&b| b == 0).unwrap_or(name.len());
    Some(match &name[..n] {
        b"cpu" => CPU_V, b"cp15" => CP15_V, b"mem" => crate::mem::Mem::VERSION, b"clock" => Clock::VERSION, b"lines" => LINES_V,
        b"nand" => Nand::VERSION, b"timer" => Timer::VERSION, b"vic" => VicPair::VERSION,
        b"sysctl" => SysCtl::VERSION, b"clkprof" => ClkProf::VERSION,
        _ => return None,
    })
}

impl Cpu {
    fn write_state(&self, w: &mut Wr) {
        w.bytes(MAGIC); w.u32(FORMAT); w.u32(10);
        w.section("cpu", CPU_V, |w| self.save_cpu(w));
        w.section("cp15", CP15_V, |w| self.save_cp15(w));
        w.section("mem", crate::mem::Mem::VERSION, |w| self.mem.save(w));
        w.section("clock", Clock::VERSION, |w| self.dev.clock.save(w));
        w.section("lines", LINES_V, |w| { w.u64(self.dev.ext_lines); w.u32(self.dev.vic_on as u32); });
        w.section("nand", Nand::VERSION, |w| self.dev.nand.save(w));
        w.section("timer", Timer::VERSION, |w| self.dev.timer.save(w));
        w.section("vic", VicPair::VERSION, |w| self.dev.vic.save(w));
        w.section("sysctl", SysCtl::VERSION, |w| self.dev.sysctl.save(w));
        w.section("clkprof", ClkProf::VERSION, |w| self.dev.clkprof.save(w));
    }
    /// Bytes save_state would produce now.
    pub fn state_size(&self) -> usize { let mut w = Wr::counting(); self.write_state(&mut w); w.len() }
    pub fn save_state(&self) -> Vec<u8> { let mut w = Wr::storing(self.state_size()); self.write_state(&mut w); w.into_bytes() }

    /// 0 = loaded, -1 = not a container or cut short, -2 = a section in a version the core does not know. On -1 found while
    /// a section is being read the core holds a mixture; -2 and a bad frame are found before anything is changed.
    pub fn load_state(&mut self, s: &[u8]) -> i32 {
        let mut r = Rd::new(s);
        if r.bytes(8) != Some(&MAGIC[..]) || r.u32() != Some(FORMAT) { return -1; }
        let count = match r.u32() { Some(n) => n, None => return -1 };
        let mut secs: Vec<(&[u8], &[u8])> = Vec::new();
        for _ in 0..count {
            let name = match r.bytes(8) { Some(n) => n, None => return -1 };
            let (ver, len) = match (r.u32(), r.u32()) { (Some(v), Some(l)) => (v, l), _ => return -1 };
            let body = match r.bytes(len as usize) { Some(b) => b, None => return -1 };
            match known(name) { None => continue, Some(v) if v != ver => return -2, _ => {} }
            secs.push((name, body));
        }
        for (name, body) in secs {
            let n = name.iter().position(|&b| b == 0).unwrap_or(name.len());
            let mut r = Rd::new(body);
            let ok = match &name[..n] {
                b"cpu" => self.load_cpu(&mut r),
                b"cp15" => self.load_cp15(&mut r),
                b"mem" => self.mem.load(&mut r),
                b"clock" => self.dev.clock.load(&mut r),
                b"lines" => (|| { self.dev.ext_lines = r.u64()?; self.dev.vic_on = r.u32()? != 0; Some(()) })(),
                b"nand" => self.dev.nand.load(&mut r),
                b"timer" => self.dev.timer.load(&mut r),
                b"vic" => self.dev.vic.load(&mut r),
                b"sysctl" => self.dev.sysctl.load(&mut r),
                b"clkprof" => self.dev.clkprof.load(&mut r),
                _ => Some(()),
            };
            if ok.is_none() { return -1; }
        }
        self.after_load();
        0
    }
}
