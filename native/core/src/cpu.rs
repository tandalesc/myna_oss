// The CPU: an ARMv5TEJ interpreter (ARM and Thumb state, the E instructions) for the ARM926EJ-S, with exceptions taken inside
// the core, level-sensitive IRQ / FIQ inputs sampled at every instruction boundary, instruction counting, entry hooks and the
// event log. One decode per instruction, no cache.
// SPDX-License-Identifier: MIT

use crate::mem::Mem;
use crate::mmu::{Tlb, NO_ENTRY, SETS, TLB_N};
use std::collections::HashMap;

/// Unicorn's ARM target page is 1K: a Thumb BL pair that starts in its last two bytes counts as two instructions.
const BL_PAGE: u32 = 0x3FF;

// `stop`: why the instruction being executed did not complete in the ordinary way (0 = it did).
pub const S_DABT: u32 = 1;
pub const S_PABT: u32 = 2;
pub const S_SWI: u32 = 3;
pub const S_UND: u32 = 4;
pub const S_WFI: u32 = 5;      // completed; the CPU halts
pub const S_HOOK: u32 = 6;     // an entry hook at this address
pub const S_UNH: u32 = 7;      // an instruction the core does not model (BKPT)
pub const S_NOMEM: u32 = 8;    // fetch from unmapped memory

// Stop reasons of a run, as the interface names them.
pub const R_BUDGET: u32 = 0;
pub const R_WFI: u32 = 1;
pub const R_REQUEST: u32 = 2;
pub const R_HOOK: u32 = 3;
pub const R_FETCH: u32 = 4;
pub const R_UNHANDLED: u32 = 5;

/// Exceptions in a row, with no instruction completed between them, after which the run ends (reason 5): the state repeats.
const EXC_STREAK: u32 = 16;
/// The event log keeps this many entries; later ones are dropped until it is cleared.
const EVENTS_MAX: usize = 1 << 20;

#[derive(Clone, Copy)]
pub struct Event { pub icount: u64, pub kind: u32, pub pc: u32, pub far: u32, pub fsr: u32 }

#[cfg(not(target_arch = "wasm32"))]
pub type ExtRead = unsafe extern "C" fn(user: *mut core::ffi::c_void, dev: u32, off: u32, size: u32) -> u32;
#[cfg(not(target_arch = "wasm32"))]
pub type ExtWrite = unsafe extern "C" fn(user: *mut core::ffi::c_void, dev: u32, off: u32, size: u32, value: u32);
#[cfg(target_arch = "wasm32")]
#[link(wasm_import_module = "env")]
extern "C" {
    fn dbc_ext_read(dev: u32, off: u32, size: u32) -> u32;
    fn dbc_ext_write(dev: u32, off: u32, size: u32, value: u32);
}
/// The host can reach the core from inside a callback through its own pointer. Publishing the address here before each call
/// tells the compiler that the callee may read and write the core.
static ESCAPE: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

/// The two things the run loop tests after every instruction, side by side so that one 64-bit load sees both.
/// `stop`: why the instruction did not complete in the ordinary way (0 = it did). `attn`: non-zero when an interrupt input or
/// the stop request has to be looked at.
#[repr(C, align(8))]
pub struct Flags { pub stop: u32, pub attn: u32 }
impl Flags { #[inline(always)] fn any(&self) -> bool { unsafe { *(self as *const Flags as *const u64) != 0 } } }

pub struct Cpu {
    pub(crate) r: [u32; 16],               // r15: address of the next instruction between instructions; inside one, that of the following instruction
    pub(crate) n: u32, pub(crate) z: u32, pub(crate) c: u32, pub(crate) v: u32, pub(crate) q: u32,
    pub(crate) rest: u32,                  // CPSR without the flags and T (I, F, mode, the unused bits)
    pub(crate) thumb: bool,
    bank: [[u32; 2]; 6], spsr: [u32; 6], fiq8: [u32; 5], usr8: [u32; 5],      // sp, lr per mode (usr, fiq, irq, svc, abt, und); r8-r12 of the other side
    pub(crate) sctlr: u32, pub(crate) ttbr: u32, pub(crate) dacr: u32, pub(crate) fcse: u32, pub(crate) fsr: [u32; 2], pub(crate) far: u32,
    pub(crate) f: Flags, pub(crate) stop_addr: u32, pub(crate) ffsr: u32,
    // interrupt inputs and the stop request
    irq: u32, fiq: u32, stop_req: u32,
    /// The host was called since this was cleared (run_slices). A page read of the NAND store does not count.
    pub(crate) touched: bool, pub(crate) slice_pc: u32,
    halted: bool, pub(crate) reason: u32, pub(crate) icount: u64,
    exc_last: u64, exc_n: u32,
    pub(crate) hooks: Vec<u32>, pub(crate) hook_skip: bool, hook_at: Option<u32>,
    pub(crate) tlb_r: Vec<Tlb>, pub(crate) tlb_w: Vec<Tlb>, pub(crate) tlb_x: Vec<Tlb>,
    // The 1K piece of code the last fetch through the TLB came from: `cva` its virtual address, `coff` its arena offset,
    // `c16` / `c32` the number of start addresses in it of a 16-bit / 32-bit fetch that lies in it whole (0: none, no
    // piece is held). It is a copy of an entry of `tlb_x` that is valid now, dropped with every change of `tb`, `ep` or `tlb_x`.
    pub(crate) cva: u32, pub(crate) c16: u32, pub(crate) c32: u32, pub(crate) coff: u32,
    pub(crate) tb: usize, pub(crate) ep: u32, pub(crate) set: usize, pub(crate) set_dacr: [u32; SETS], pub(crate) set_ep: [u32; SETS], pub(crate) set_next: usize,
    pub(crate) mem: Mem, pub(crate) fpa: u32, pub(crate) fext: bool,
    pub walks: u64,
    pub(crate) events: Vec<Event>, pub(crate) cpmap: HashMap<u32, u32>,
    #[cfg(not(target_arch = "wasm32"))] pub(crate) ext: (Option<ExtRead>, Option<ExtWrite>, *mut core::ffi::c_void),
    /// The compiled devices, the clock and the interrupt lines (boxed: the layout of the CPU state stays as it is).
    pub(crate) dev: Box<crate::dev::Devs>,
}

fn mode_idx(m: u32) -> usize { match m & 0x1f { 0x11 => 1, 0x12 => 2, 0x13 => 3, 0x17 => 4, 0x1b => 5, _ => 0 } }

impl Cpu {
    pub fn new() -> Box<Cpu> {
        Box::new(Cpu { r: [0; 16], n: 0, z: 0, c: 0, v: 0, q: 0, rest: 0xd3, thumb: false, bank: [[0; 2]; 6], spsr: [0; 6], fiq8: [0; 5], usr8: [0; 5],
            sctlr: 0, ttbr: 0, dacr: 0, fcse: 0, fsr: [0; 2], far: 0, f: Flags { stop: 0, attn: 0 }, stop_addr: 0, ffsr: 0,
            irq: 0, fiq: 0, stop_req: 0, touched: false, slice_pc: 0, halted: false, reason: 0, icount: 0, exc_last: u64::MAX, exc_n: 0,
            hooks: Vec::new(), hook_skip: false, hook_at: None,
            tlb_r: vec![NO_ENTRY; SETS * 2 * TLB_N], tlb_w: vec![NO_ENTRY; SETS * 2 * TLB_N], tlb_x: vec![NO_ENTRY; SETS * 2 * TLB_N],
            cva: 0, c16: 0, c32: 0, coff: 0, tb: TLB_N, ep: 0, set: 0, set_dacr: [0; SETS], set_ep: [0; SETS], set_next: 1,
            mem: Mem::new(), fpa: 0, fext: false, walks: 0, events: Vec::new(), cpmap: HashMap::new(),
            #[cfg(not(target_arch = "wasm32"))] ext: (None, None, core::ptr::null_mut()),
            dev: Box::new(crate::dev::Devs::new()) })
    }

    // ---- host calls ------------------------------------------------------------------------------
    /// None: no callback installed (the window then behaves as memory).
    #[inline(never)]
    pub(crate) fn host_read(&mut self, dev: u32, off: u32, size: u32) -> Option<u32> {
        if dev != crate::dev::nand::STORE_READ { self.touched = true; }
        ESCAPE.store(self as *mut Cpu as usize, std::sync::atomic::Ordering::Relaxed);
        #[cfg(not(target_arch = "wasm32"))]
        { let (f, user) = (self.ext.0?, self.ext.2); Some(unsafe { f(user, dev, off, size) }) }
        #[cfg(target_arch = "wasm32")]
        { Some(unsafe { dbc_ext_read(dev, off, size) }) }
    }
    #[inline(never)]
    pub(crate) fn host_write(&mut self, dev: u32, off: u32, size: u32, value: u32) {
        self.touched = true;
        ESCAPE.store(self as *mut Cpu as usize, std::sync::atomic::Ordering::Relaxed);
        #[cfg(not(target_arch = "wasm32"))]
        { if let Some(f) = self.ext.1 { let user = self.ext.2; unsafe { f(user, dev, off, size, value) } } }
        #[cfg(target_arch = "wasm32")]
        { unsafe { dbc_ext_write(dev, off, size, value) } }
    }

    /// The host has a callback for reads (writes) of the external windows.
    #[inline(always)]
    pub(crate) fn has_host(&self, write: bool) -> bool {
        #[cfg(not(target_arch = "wasm32"))]
        { if write { self.ext.1.is_some() } else { self.ext.0.is_some() } }
        #[cfg(target_arch = "wasm32")]
        { let _ = write; true }
    }

    // ---- state -----------------------------------------------------------------------------------
    pub fn cpsr(&self) -> u32 { self.n << 31 | self.z << 30 | self.c << 29 | self.v << 28 | self.q << 27 | self.rest | if self.thumb { 0x20 } else { 0 } }
    pub(crate) fn priv_(&self) -> bool { self.rest & 0x1f != 0x10 }
    fn set_mode(&mut self, new: u32) {
        let (o, nn) = (mode_idx(self.rest), mode_idx(new));
        if o != nn {
            self.bank[o] = [self.r[13], self.r[14]];
            if o == 1 { for i in 0..5 { self.fiq8[i] = self.r[8 + i]; self.r[8 + i] = self.usr8[i]; } }
            if nn == 1 { for i in 0..5 { self.usr8[i] = self.r[8 + i]; self.r[8 + i] = self.fiq8[i]; } }
            self.r[13] = self.bank[nn][0]; self.r[14] = self.bank[nn][1];
        }
        self.tb = self.set * 2 * TLB_N + if new & 0x1f == 0x10 { 0 } else { TLB_N }; self.no_code();
        self.rest = (self.rest & !0x1f) | (new & 0x1f);
    }
    /// MSR and the exception returns. In user mode only the flags can be written.
    fn set_cpsr(&mut self, val: u32, mask: u32, exc_ret: bool) {
        if mask & 0xff00_0000 != 0 { self.n = val >> 31; self.z = val >> 30 & 1; self.c = val >> 29 & 1; self.v = val >> 28 & 1; self.q = val >> 27 & 1; }
        if mask & 0x00ff_ffff != 0 && self.rest & 0x1f != 0x10 {
            if mask & 0xff != 0 { self.set_mode(val); }
            let keep = if exc_ret { 0x07ff_ffc0 } else { mask & 0x00ff_ffc0 }; self.rest = (self.rest & !keep) | (val & keep);
            if exc_ret { self.thumb = val & 0x20 != 0; }
            self.attention();
        }
    }
    /// Recompute `attn` after an input, the stop request or the CPSR masks changed.
    #[inline(always)]
    fn attention(&mut self) {
        self.f.attn = (self.stop_req != 0 || (self.irq != 0 && self.rest & 0x80 == 0) || (self.fiq != 0 && self.rest & 0x40 == 0)) as u32;
    }
    pub fn set_irq(&mut self, level: bool) { self.irq = level as u32; self.attention(); }
    pub fn set_fiq(&mut self, level: bool) { self.fiq = level as u32; self.attention(); }
    pub fn request_stop(&mut self) { self.stop_req = 1; self.f.attn = 1; }
    pub fn icount(&self) -> u64 { self.icount }
    pub fn stop_reason(&self) -> u32 { self.reason }
    pub fn events(&self) -> &[Event] { &self.events }
    pub fn clear_events(&mut self) { self.events.clear(); }
    pub fn mem(&mut self) -> &mut Mem { &mut self.mem }
    pub fn map_ram(&mut self, addr: u32, size: u32) -> i32 { let r = self.mem.map_ram(addr, size); self.flush(); r }
    pub fn map_ext(&mut self, addr: u32, size: u32, dev: u32) -> i32 { let r = self.mem.map_ext(addr, size, dev); self.flush(); r }
    /// Entry hook at a virtual address (bit 0 ignored). False when it was there already.
    pub fn add_hook(&mut self, vaddr: u32) -> bool {
        let a = vaddr & !1;
        match self.hooks.binary_search(&a) { Ok(_) => false, Err(i) => { self.hooks.insert(i, a); self.flush(); true } }
    }
    pub fn del_hook(&mut self, vaddr: u32) {
        if let Ok(i) = self.hooks.binary_search(&(vaddr & !1)) { self.hooks.remove(i); self.flush(); }
    }

    /// Register by the interface's id (see the README). Unknown ids read as zero.
    pub fn reg(&self, id: u32) -> u32 {
        let cur = mode_idx(self.rest);
        match id {
            0..=15 => self.r[id as usize],
            16 => self.cpsr(),
            17 => self.spsr[cur],
            18..=35 => { let (m, k) = (((id - 18) / 3) as usize, (id - 18) % 3); if k == 2 { self.spsr[m] } else if m == cur { self.r[13 + k as usize] } else { self.bank[m][k as usize] } }
            36..=40 => { let i = (id - 36) as usize; if cur == 1 { self.r[8 + i] } else { self.fiq8[i] } }
            41..=45 => { let i = (id - 41) as usize; if cur == 1 { self.usr8[i] } else { self.r[8 + i] } }
            46 => self.sctlr, 47 => self.ttbr, 48 => self.dacr, 49 => self.fcse, 50 => self.fsr[0], 51 => self.fsr[1], 52 => self.far,
            _ => 0,
        }
    }
    pub fn set_reg(&mut self, id: u32, x: u32) {
        let cur = mode_idx(self.rest);
        match id {
            0..=14 => self.r[id as usize] = x,
            15 => { self.r[15] = x; self.halted = false; }
            16 => {
                self.set_mode(x);
                self.n = x >> 31; self.z = x >> 30 & 1; self.c = x >> 29 & 1; self.v = x >> 28 & 1; self.q = x >> 27 & 1;
                self.rest = x & 0x07ff_ffdf; self.thumb = x & 0x20 != 0;
                self.attention();
            }
            17 => self.spsr[cur] = x,
            18..=35 => { let (m, k) = (((id - 18) / 3) as usize, (id - 18) % 3); if k == 2 { self.spsr[m] = x } else if m == cur { self.r[13 + k as usize] = x } else { self.bank[m][k as usize] = x } }
            36..=40 => { let i = (id - 36) as usize; if cur == 1 { self.r[8 + i] = x } else { self.fiq8[i] = x } }
            41..=45 => { let i = (id - 41) as usize; if cur == 1 { self.usr8[i] = x } else { self.r[8 + i] = x } }
            46 => { self.sctlr = x; self.flush(); } 47 => self.ttbr = x, 48 => self.set_dacr(x), 49 => { self.fcse = x; self.flush(); }
            50 => self.fsr[0] = x, 51 => self.fsr[1] = x, 52 => self.far = x,
            _ => {}
        }
    }

    /// Load a snapshot: memory is zeroed and filled from it (mappings, windows, hooks and the inputs stay), registers and the
    /// four cp15 words are set, the instruction count and the event log start again.
    pub fn load(&mut self, s: &[u8]) -> bool {
        let snap = match crate::mem::parse_snapshot(s) { Some(x) => x, None => return false };
        let w = &snap.words;
        if w.len() < 50 { return false; }
        self.mem.zero();
        for (a, d) in &snap.runs { if !self.mem.write(*a, d) { return false; } }
        // words: r0..r15, cpsr, spsr, 6 x (sp, lr, spsr) for usr fiq irq svc abt und, fiq r8-12, usr r8-12, sctlr ttbr dacr fcse
        for m in 0..6 { self.bank[m] = [w[18 + 3 * m], w[19 + 3 * m]]; self.spsr[m] = w[20 + 3 * m]; }
        for i in 0..5 { self.fiq8[i] = w[36 + i]; self.usr8[i] = w[41 + i]; }
        self.sctlr = w[46]; self.ttbr = w[47]; self.dacr = w[48]; self.fcse = w[49];
        self.fsr = [0; 2]; self.far = 0;
        let cpsr = w[16];
        self.r.copy_from_slice(&w[0..16]);
        self.n = cpsr >> 31; self.z = cpsr >> 30 & 1; self.c = cpsr >> 29 & 1; self.v = cpsr >> 28 & 1; self.q = cpsr >> 27 & 1;
        self.rest = cpsr & 0x07ff_ffdf; self.thumb = cpsr & 0x20 != 0;
        self.spsr[mode_idx(cpsr)] = w[17];
        self.reset_tlb();
        self.f.stop = 0; self.reason = 0; self.halted = false; self.icount = 0; self.exc_last = u64::MAX; self.exc_n = 0;
        self.hook_at = None; self.hook_skip = false; self.stop_req = 0;
        self.events.clear(); self.cpmap.clear();
        self.attention();
        true
    }

    // ---- state save / load ---------------------------------------------------------------------
    pub(crate) fn save_cpu(&self, w: &mut crate::state::Wr) {
        w.words(&self.r); w.words(&[self.n, self.z, self.c, self.v, self.q, self.rest, self.thumb as u32]);
        for b in &self.bank { w.words(b); }
        w.words(&self.spsr); w.words(&self.fiq8); w.words(&self.usr8);
        w.words(&[self.irq, self.fiq, self.halted as u32, self.reason, self.exc_n]);
        w.u64(self.icount); w.u64(self.exc_last);
        w.u32(self.hook_at.is_some() as u32); w.u32(self.hook_at.unwrap_or(0));
    }
    pub(crate) fn load_cpu(&mut self, r: &mut crate::state::Rd) -> Option<()> {
        r.words(&mut self.r)?;
        let mut f = [0u32; 7]; r.words(&mut f)?;
        self.n = f[0] & 1; self.z = f[1] & 1; self.c = f[2] & 1; self.v = f[3] & 1; self.q = f[4] & 1; self.rest = f[5] & 0x07ff_ffdf; self.thumb = f[6] != 0;
        for b in self.bank.iter_mut() { r.words(b)?; }
        r.words(&mut self.spsr)?; r.words(&mut self.fiq8)?; r.words(&mut self.usr8)?;
        let mut g = [0u32; 5]; r.words(&mut g)?;
        self.irq = (g[0] != 0) as u32; self.fiq = (g[1] != 0) as u32; self.halted = g[2] != 0; self.reason = g[3]; self.exc_n = g[4];
        self.icount = r.u64()?; self.exc_last = r.u64()?;
        let (some, at) = (r.u32()?, r.u32()?);
        self.hook_at = if some != 0 { Some(at) } else { None };
        Some(())
    }
    pub(crate) fn save_cp15(&self, w: &mut crate::state::Wr) {
        w.words(&[self.sctlr, self.ttbr, self.dacr, self.fcse, self.fsr[0], self.fsr[1], self.far]);
        let mut keys: Vec<u32> = self.cpmap.keys().copied().collect(); keys.sort_unstable();
        w.u32(keys.len() as u32);
        for k in keys { w.u32(k); w.u32(self.cpmap[&k]); }
    }
    pub(crate) fn load_cp15(&mut self, r: &mut crate::state::Rd) -> Option<()> {
        let mut f = [0u32; 7]; r.words(&mut f)?;
        self.sctlr = f[0]; self.ttbr = f[1]; self.dacr = f[2]; self.fcse = f[3]; self.fsr = [f[4], f[5]]; self.far = f[6];
        self.cpmap.clear();
        for _ in 0..r.u32()? { let k = r.u32()?; let v = r.u32()?; self.cpmap.insert(k, v); }
        Some(())
    }
    /// After the sections of a container are in: nothing translated is kept, no stop is pending.
    pub(crate) fn after_load(&mut self) {
        self.reset_tlb();
        self.f.stop = 0; self.stop_req = 0; self.hook_skip = false;
        self.attention();
    }

    // ---- exceptions ------------------------------------------------------------------------------
    /// Exception entry. kind: 1 data abort, 2 prefetch abort, 3 SWI, 4 undefined (r15 = the instruction), 5 IRQ, 6 FIQ
    /// (r15 = the next instruction to run). `count`: instructions completed before it, for the log.
    #[inline(never)]
    fn exception(&mut self, kind: u32, count: u64) {
        let pc = self.r[15]; let cpsr = self.cpsr(); let step = if self.thumb { 2 } else { 4 };
        let (far, fsr) = if kind <= 2 { (self.stop_addr, self.ffsr) } else { (0, 0) };
        if self.events.len() < EVENTS_MAX { self.events.push(Event { icount: count, kind, pc, far, fsr }); }
        let (mode, vec, lr) = match kind {
            1 => { self.fsr[0] = fsr; self.far = far; (0x17, 0x10, pc.wrapping_add(8)) }
            2 => { self.fsr[1] = fsr; self.fsr[0] = fsr; (0x17, 0x0c, pc.wrapping_add(4)) }
            3 => (0x13, 0x08, pc.wrapping_add(step)),
            4 => (0x1b, 0x04, pc.wrapping_add(step)),
            5 => (0x12, 0x18, pc.wrapping_add(4)),
            _ => (0x11, 0x1c, pc.wrapping_add(4)),
        };
        self.set_mode(mode); self.rest |= if kind == 6 { 0xc0 } else { 0x80 }; self.thumb = false;
        self.spsr[mode_idx(mode)] = cpsr; self.r[14] = lr;
        self.r[15] = (if self.sctlr & 0x2000 != 0 { 0xffff_0000 } else { 0 }) + vec;
        self.f.stop = 0;
        self.attention();
    }
    /// The run loop found `attn` set, at an instruction boundary. True: the run ends here.
    #[inline(never)]
    fn attend(&mut self, count: u64) -> bool {
        if self.stop_req != 0 { self.stop_req = 0; self.reason = R_REQUEST; self.attention(); return true; }
        if self.fiq != 0 && self.rest & 0x40 == 0 { self.exception(6, count); }
        else if self.irq != 0 && self.rest & 0x80 == 0 { self.exception(5, count); }
        else { self.attention(); }
        false
    }
    /// The instruction set `stop`. 0: an exception was entered, the instruction does not count; 1: the run ends, the
    /// instruction does not count (r15 at it); 2: the run ends, the instruction counts.
    #[inline(never)]
    fn stopped(&mut self, count: u64) -> u32 {
        let s = self.f.stop; self.f.stop = 0;
        match s {
            S_DABT | S_PABT | S_SWI | S_UND => {
                if count == self.exc_last { self.exc_n += 1; if self.exc_n >= EXC_STREAK { self.exc_n = 0; self.reason = R_UNHANDLED; return 1; } }
                else { self.exc_last = count; self.exc_n = 0; }
                self.exception(s, count); 0
            }
            S_WFI => { self.halted = true; self.reason = R_WFI; 2 }
            S_HOOK => { self.hook_at = Some(self.r[15]); self.reason = R_HOOK; 1 }
            S_NOMEM => { self.reason = R_FETCH; 1 }
            _ => { self.reason = R_UNHANDLED; 1 }
        }
    }

    /// Run at most `n` instructions; returns the number completed. `stop_reason()` says why it returned.
    pub fn run(&mut self, n: u64) -> u64 {
        self.reason = R_BUDGET; self.f.stop = 0; self.stop_req = 0; self.attention();
        if n == 0 { return 0; }
        if self.halted {
            if self.irq | self.fiq == 0 { self.reason = R_WFI; return 0; }
            self.halted = false;                           // woken; with the input masked the CPU goes on at the next instruction
        }
        let mut done = 0;
        if self.hook_at.take() == Some(self.r[15]) {      // the last run stopped at a hook here: this arrival was reported
            self.hook_skip = true; done = self.run_loop(1); self.hook_skip = false;
        }
        if self.reason == R_BUDGET && done < n { done += self.run_loop(n - done); }
        if self.reason == R_BUDGET && self.stop_req != 0 { self.reason = R_REQUEST; }
        self.stop_req = 0; self.attention();
        done
    }
    /// Slices of `quantum` instructions (less than 2^32), with what a host does between two slices done here after each
    /// slice that used its whole budget: the instructions are added to the clock's count and the timer's due event fires.
    /// The next slice follows unless the host was called during the slice (a page read of the NAND store aside), or the
    /// clock has reached `due_ns` or is past `until_ns`, or `max` slices are done, or the slice ended at the pc the slice
    /// before it ended at (`last_pc` for the first). A slice that ends in any other way than by its budget ends the call
    /// with nothing done for it: it is the host's, as after a run().
    /// Returns whole slices << 33 | (the last one ended at the pc of the one before) << 32 | instructions of the slice that
    /// is left to the host (stop_reason() says how it ended; 0 when there is none).
    pub fn run_slices(&mut self, quantum: u64, max: u32, due_ns: u64, until_ns: u64, last_pc: u32) -> u64 {
        let (mut k, mut last) = (0u64, last_pc);
        if quantum == 0 || quantum >> 32 != 0 { self.reason = R_BUDGET; return 0; }
        loop {
            self.touched = false;
            let done = self.run(quantum);
            if self.reason != R_BUDGET || done != quantum { return k << 33 | done; }
            k += 1;
            self.dev.clock.insns += done;
            self.dev_advance(crate::dev::K_TIMER);
            let pc = self.r[15]; let same = pc == last; last = pc; self.slice_pc = pc;
            let now = self.dev.clock.now_ns();
            if same || self.touched || now >= due_ns || now > until_ns || k >= max as u64 { return k << 33 | (same as u64) << 32; }
        }
    }
    fn run_loop(&mut self, n: u64) -> u64 {
        let base = self.icount;
        let mut left = n;
        // The inputs are looked at here, at the boundary before the first instruction, and after every instruction that is
        // followed by another one in this run. The loop itself has one test for "anything unusual" per instruction.
        if self.f.attn != 0 && self.attend(base) { return 0; }
        while left > 0 {
            if self.thumb { self.thumb_step() } else { self.arm() }
            if self.f.any() {
                match self.unusual(base + (n - left), left > 1) { 0 => continue, 1 => break, 2 => { left -= 1; break; } _ => {} }
            }
            left -= 1;
        }
        self.icount = base + (n - left);
        n - left
    }
    /// After an instruction that set `stop`, or with `attn` set. `count`: instructions completed before it; `more`: the
    /// budget allows another instruction after it. Returns 0: go on, the instruction does not count (an exception was
    /// entered); 1: the run ends, it does not count; 2: the run ends, it counts; 3: go on, it counts.
    #[inline(never)]
    fn unusual(&mut self, count: u64, more: bool) -> u32 {
        let mut counted = 1;
        if self.f.stop != 0 { match self.stopped(count) { 0 => counted = 0, x => return x } }
        if self.f.attn != 0 && (more || counted == 0) && self.attend(count + counted) { return 1 + counted as u32; }
        if counted != 0 { 3 } else { 0 }
    }

    // ---- helpers ---------------------------------------------------------------------------------
    #[inline(always)] fn cond(&self, c: u32) -> bool {
        match c { 0 => self.z != 0, 1 => self.z == 0, 2 => self.c != 0, 3 => self.c == 0, 4 => self.n != 0, 5 => self.n == 0, 6 => self.v != 0, 7 => self.v == 0,
            8 => self.c != 0 && self.z == 0, 9 => self.c == 0 || self.z != 0, 10 => self.n == self.v, 11 => self.n != self.v,
            12 => self.z == 0 && self.n == self.v, 13 => self.z != 0 || self.n != self.v, _ => true }
    }
    #[inline(always)] fn nz(&mut self, x: u32) { self.n = x >> 31; self.z = (x == 0) as u32; }
    #[inline(always)] fn add(&mut self, a: u32, b: u32, cin: u32, s: bool) -> u32 {
        let t = a as u64 + b as u64 + cin as u64; let x = t as u32;
        if s { self.nz(x); self.c = (t >> 32) as u32; self.v = ((a ^ x) & (b ^ x)) >> 31; }
        x
    }
    #[inline(always)] fn sub(&mut self, a: u32, b: u32, cin: u32, s: bool) -> u32 { self.add(a, !b, cin, s) }
    #[inline(always)] fn bx(&mut self, a: u32) { self.thumb = a & 1 != 0; self.r[15] = if self.thumb { a & !1 } else { a & !3 }; }
    #[inline(always)] fn shift(&mut self, typ: u32, x: u32, amt: u32, imm: bool) -> (u32, u32) {   // (value, carry out)
        let c = self.c;
        if imm {
            match typ {
                0 => if amt == 0 { (x, c) } else { (x << amt, x >> (32 - amt) & 1) },
                1 => if amt == 0 { (0, x >> 31) } else { (x >> amt, x >> (amt - 1) & 1) },
                2 => if amt == 0 { ((x as i32 >> 31) as u32, x >> 31) } else { ((x as i32 >> amt) as u32, x >> (amt - 1) & 1) },
                _ => if amt == 0 { (c << 31 | x >> 1, x & 1) } else { (x.rotate_right(amt), x >> (amt - 1) & 1) },
            }
        } else {
            let amt = amt & 0xff;
            if amt == 0 { return (x, c); }
            match typ {
                0 => if amt < 32 { (x << amt, x >> (32 - amt) & 1) } else if amt == 32 { (0, x & 1) } else { (0, 0) },
                1 => if amt < 32 { (x >> amt, x >> (amt - 1) & 1) } else if amt == 32 { (0, x >> 31) } else { (0, 0) },
                2 => if amt < 32 { ((x as i32 >> amt) as u32, x >> (amt - 1) & 1) } else { ((x as i32 >> 31) as u32, x >> 31) },
                _ => { let a = amt & 31; if a == 0 { (x, x >> 31) } else { (x.rotate_right(a), x >> (a - 1) & 1) } }
            }
        }
    }
    fn sat(&mut self, x: i64) -> u32 { if x > 0x7fff_ffff { self.q = 1; 0x7fff_ffff } else if x < -0x8000_0000 { self.q = 1; 0x8000_0000 } else { x as u32 } }

    // ---- ARM -------------------------------------------------------------------------------------
    // An instruction that faults sets `stop` and puts r15 back at itself. A single transfer changes no other register; a
    // multiple one (LDM, STM, PUSH, POP, LDRD, STRD) keeps the words before the fault and does not write the base back.
    // Its words go through rd32_blk / wr32_blk with the words still to come, so that no device is reached by an
    // instruction that is going to abort (see mmu.rs).
    #[inline(always)] pub(crate) fn rg(&self, i: u32) -> u32 { let x = unsafe { *self.r.get_unchecked(i as usize) }; if i == 15 { x.wrapping_add(4) } else { x } }   // r15 already holds pc+4
    #[inline(always)]
    fn arm(&mut self) {
        let pc = self.r[15];
        let op = self.fetch32(pc);
        if op >> 32 != 0 { return; }
        let op = op as u32;
        self.r[15] = pc.wrapping_add(4);
        let cc = op >> 28;
        if cc != 14 {
            if cc == 15 {
                if op & 0xfe00_0000 == 0xfa00_0000 {            // BLX imm
                    self.r[14] = pc.wrapping_add(4);
                    let off = (((op & 0xff_ffff) << 8) as i32 >> 6) as u32 | (op >> 23 & 2);
                    self.r[15] = pc.wrapping_add(8).wrapping_add(off); self.thumb = true; return;
                }
                if op & 0xfd70_f000 == 0xf550_f000 { return; }   // PLD
                self.f.stop = S_UND; self.r[15] = pc; return;
            }
            if !self.cond(cc) { return; }
        }
        match op >> 25 & 7 {
            0 | 1 => self.arm_dp(op, pc),
            2 | 3 => {
                if op & 0x0200_0010 == 0x0200_0010 { self.f.stop = S_UND; self.r[15] = pc; return; }
                let (rn, rd) = (op >> 16 & 15, op >> 12 & 15);
                let off = if op & 0x0200_0000 == 0 { op & 0xfff } else { let x = self.rg(op & 15); self.shift(op >> 5 & 3, x, op >> 7 & 31, true).0 };
                let base = self.rg(rn);
                let ao = if op & 0x0080_0000 != 0 { base.wrapping_add(off) } else { base.wrapping_sub(off) };
                let a = if op & 0x0100_0000 != 0 { ao } else { base };
                let wb = op & 0x0100_0000 == 0 || op & 0x0020_0000 != 0;
                if op & 0x0010_0000 != 0 {
                    let x = if op & 0x0040_0000 != 0 { self.rd8(a) } else { self.rd32(a) };
                    if self.f.stop != 0 { self.r[15] = pc; return; }
                    if wb { self.r[rn as usize] = ao; }
                    if rd == 15 { self.bx(x); } else { self.r[rd as usize] = x; }
                } else {
                    let x = self.rg(rd);
                    if op & 0x0040_0000 != 0 { self.wr8(a, x) } else { self.wr32(a, x) }
                    if self.f.stop != 0 { self.r[15] = pc; return; }
                    if wb { self.r[rn as usize] = ao; }
                }
            }
            4 => self.arm_ldm(op, pc),
            5 => {
                if op & 0x0100_0000 != 0 { self.r[14] = pc.wrapping_add(4); }
                self.r[15] = pc.wrapping_add(8).wrapping_add((((op & 0xff_ffff) << 8) as i32 >> 6) as u32);
            }
            6 => { self.f.stop = S_UND; self.r[15] = pc; }           // LDC / STC: no such coprocessor
            _ => {
                if op & 0x0100_0000 != 0 { self.f.stop = S_SWI; self.r[15] = pc; return; }
                if op & 0x10 == 0 || op >> 8 & 15 != 15 { self.f.stop = S_UND; self.r[15] = pc; return; }     // CDP, or not p15
                self.cp15(op);
            }
        }
    }
    #[inline(always)]
    fn arm_dp(&mut self, op: u32, pc: u32) {
        let (rn, rd) = (op >> 16 & 15, op >> 12 & 15);
        let s = op & 0x0010_0000 != 0;
        let (b, sc);
        if op & 0x0200_0000 != 0 {
            if op & 0x0190_0000 == 0x0100_0000 {              // MSR imm
                if op & 0x0020_0000 == 0 { self.f.stop = S_UND; self.r[15] = pc; return; }
                let x = (op & 0xff).rotate_right((op >> 8 & 15) * 2); self.msr(op, x); return;
            }
            let rot = (op >> 8 & 15) * 2; b = (op & 0xff).rotate_right(rot); sc = if rot == 0 { self.c } else { b >> 31 };
        } else {
            if op & 0x90 == 0x90 { self.arm_misc90(op, pc); return; }
            if op & 0x0190_0000 == 0x0100_0000 { self.arm_misc(op, pc); return; }
            let x = self.rg(op & 15);
            let r = if op & 0x10 != 0 {
                let amt = self.rg(op >> 8 & 15); self.shift(op >> 5 & 3, x, amt, false)
            } else { self.shift(op >> 5 & 3, x, op >> 7 & 31, true) };
            b = r.0; sc = r.1;
        }
        let a = self.rg(rn);
        let sf = s && rd != 15;
        let c = self.c;
        let x = match op >> 21 & 15 {
            0 => { let x = a & b; if sf { self.nz(x); self.c = sc; } x }
            1 => { let x = a ^ b; if sf { self.nz(x); self.c = sc; } x }
            2 => self.sub(a, b, 1, sf), 3 => self.sub(b, a, 1, sf), 4 => self.add(a, b, 0, sf), 5 => self.add(a, b, c, sf), 6 => self.sub(a, b, c, sf), 7 => self.sub(b, a, c, sf),
            8 => { let x = a & b; self.nz(x); self.c = sc; return; }
            9 => { let x = a ^ b; self.nz(x); self.c = sc; return; }
            10 => { self.sub(a, b, 1, true); return; }
            11 => { self.add(a, b, 0, true); return; }
            12 => { let x = a | b; if sf { self.nz(x); self.c = sc; } x }
            13 => { if sf { self.nz(b); self.c = sc; } b }
            14 => { let x = a & !b; if sf { self.nz(x); self.c = sc; } x }
            _ => { let x = !b; if sf { self.nz(x); self.c = sc; } x }
        };
        if rd == 15 {
            if s { let sp = self.spsr[mode_idx(self.rest)]; self.set_cpsr(sp, 0xffff_ffff, true); self.r[15] = if self.thumb { x & !1 } else { x & !3 }; }
            else { self.r[15] = x & !3; }
        } else { self.r[rd as usize] = x; }
    }
    fn msr(&mut self, op: u32, x: u32) {
        let mut mask = 0u32;
        if op & 0x1_0000 != 0 { mask |= 0xff; } if op & 0x2_0000 != 0 { mask |= 0xff00; } if op & 0x4_0000 != 0 { mask |= 0xff_0000; } if op & 0x8_0000 != 0 { mask |= 0xff00_0000; }
        if op & 0x0040_0000 != 0 { let m = mode_idx(self.rest); self.spsr[m] = (self.spsr[m] & !mask) | (x & mask); }
        else { self.set_cpsr(x, mask, false); }
    }
    #[inline(never)]
    fn arm_misc(&mut self, op: u32, pc: u32) {          // 0001 0xx0 without the S bit, register form
        let (rd, rm) = (op >> 12 & 15, op & 15);
        match op >> 4 & 15 {
            0 => { if op & 0x0020_0000 != 0 { let x = self.rg(rm); self.msr(op, x); }
                   else { self.r[rd as usize] = if op & 0x0040_0000 != 0 { self.spsr[mode_idx(self.rest)] } else { self.cpsr() }; } }
            1 => { if op & 0x0060_0000 == 0x0020_0000 { let x = self.rg(rm); self.bx(x); } else if op & 0x0060_0000 == 0x0060_0000 { self.r[rd as usize] = self.rg(rm).leading_zeros(); } else { self.f.stop = S_UND; self.r[15] = pc; } }
            2 => { if op & 0x0060_0000 == 0x0020_0000 { let x = self.rg(rm); self.bx(x); } else { self.f.stop = S_UND; self.r[15] = pc; } }      // BXJ: as BX (no Jazelle state)
            3 => { if op & 0x0060_0000 == 0x0020_0000 { let x = self.rg(rm); self.r[14] = pc.wrapping_add(4); self.bx(x); } else { self.f.stop = S_UND; self.r[15] = pc; } }
            5 => { let (a, b) = (self.rg(rm) as i32 as i64, self.rg(op >> 16 & 15) as i32 as i64);
                   let x = match op >> 21 & 3 { 0 => self.sat(a + b), 1 => self.sat(a - b), 2 => { let d = self.sat(2 * b) as i32 as i64; self.sat(a + d) } _ => { let d = self.sat(2 * b) as i32 as i64; self.sat(a - d) } };
                   self.r[rd as usize] = x; }
            7 => { self.f.stop = S_UNH; self.r[15] = pc; }       // BKPT
            8 | 10 | 12 | 14 => {
                let (rdd, rn, rs) = (op >> 16 & 15, op >> 12 & 15, op >> 8 & 15);
                let ys = self.rg(rs); let y = if op & 0x40 != 0 { ys as i32 >> 16 } else { ys as i16 as i32 } as i64;
                let xm = self.rg(rm); let xh = if op & 0x20 != 0 { xm as i32 >> 16 } else { xm as i16 as i32 } as i64;
                match op >> 21 & 3 {
                    0 => { let p = (xh * y) as i32; let acc = self.rg(rn) as i32; let (x, o) = p.overflowing_add(acc); if o { self.q = 1; } self.r[rdd as usize] = x as u32; }
                    1 => { let p = ((xm as i32 as i64 * y) >> 16) as i32;
                           if op & 0x20 != 0 { self.r[rdd as usize] = p as u32; } else { let (x, o) = p.overflowing_add(self.rg(rn) as i32); if o { self.q = 1; } self.r[rdd as usize] = x as u32; } }
                    2 => { let acc = ((self.rg(rdd) as u64) << 32 | self.rg(rn) as u64) as i64; let x = acc.wrapping_add(xh * y); self.r[rn as usize] = x as u32; self.r[rdd as usize] = (x >> 32) as u32; }
                    _ => { self.r[rdd as usize] = (xh * y) as u32; }
                }
            }
            _ => { self.f.stop = S_UND; self.r[15] = pc; }
        }
    }
    #[inline(never)]
    fn arm_misc90(&mut self, op: u32, pc: u32) {        // bits 7 and 4 set: multiplies, swap, halfword / signed / doubleword transfers
        let (rn, rd, rm) = (op >> 16 & 15, op >> 12 & 15, op & 15);
        let s = op & 0x0010_0000 != 0;
        if op & 0x60 == 0 {
            if op & 0x0fc0_0000 == 0 {                   // MUL / MLA: rd = rn field, accumulate = rd field
                let mut x = self.rg(rm).wrapping_mul(self.rg(op >> 8 & 15));
                if op & 0x0020_0000 != 0 { x = x.wrapping_add(self.rg(rd)); }
                self.r[rn as usize] = x; if s { self.nz(x); }
            } else if op & 0x0f80_0000 == 0x0080_0000 {
                let (a, b) = (self.rg(rm), self.rg(op >> 8 & 15));
                let mut x = if op & 0x0040_0000 != 0 { (a as i32 as i64 * b as i32 as i64) as u64 } else { a as u64 * b as u64 };
                if op & 0x0020_0000 != 0 { x = x.wrapping_add((self.rg(rn) as u64) << 32 | self.rg(rd) as u64); }
                self.r[rd as usize] = x as u32; self.r[rn as usize] = (x >> 32) as u32;
                if s { self.n = (x >> 63) as u32; self.z = (x == 0) as u32; }
            } else if op & 0x0fb0_0000 == 0x0100_0000 {  // SWP / SWPB: the word must be writable before it is read
                let a = self.rg(rn); let b = op & 0x0040_0000 != 0;
                self.touch(a, true); if !b && self.f.stop == 0 { self.touch(a.wrapping_add(3), true); }
                if self.f.stop != 0 { self.r[15] = pc; return; }
                let x = if b { self.rd8(a) } else { self.rd32(a) };
                if self.f.stop != 0 { self.r[15] = pc; return; }
                let y = self.rg(rm); if b { self.wr8(a, y) } else { self.wr32(a, y) }
                if self.f.stop != 0 { self.r[15] = pc; return; }
                self.r[rd as usize] = x;
            } else { self.f.stop = S_UND; self.r[15] = pc; }
            return;
        }
        let off = if op & 0x0040_0000 != 0 { (op >> 4 & 0xf0) | (op & 15) } else { self.rg(rm) };
        let base = self.rg(rn);
        let ao = if op & 0x0080_0000 != 0 { base.wrapping_add(off) } else { base.wrapping_sub(off) };
        let a = if op & 0x0100_0000 != 0 { ao } else { base };
        let wb = op & 0x0100_0000 == 0 || op & 0x0020_0000 != 0;
        let sh = op >> 5 & 3;
        if s {
            let x = match sh { 1 => self.rd16(a), 2 => self.rd8(a) as i8 as i32 as u32, _ => self.rd16(a) as i16 as i32 as u32 };
            if self.f.stop != 0 { self.r[15] = pc; return; }
            if wb { self.r[rn as usize] = ao; }
            self.r[rd as usize] = x;
        } else if sh == 1 {
            let x = self.rg(rd); self.wr16(a, x);
            if self.f.stop != 0 { self.r[15] = pc; return; }
            if wb { self.r[rn as usize] = ao; }
        } else if sh == 2 {                              // LDRD: word by word; a fault on the second leaves the first loaded
            let x = self.rd32_blk(a, 1);
            if self.f.stop != 0 { self.r[15] = pc; return; }
            if rd != rn { self.r[rd as usize] = x; }     // a first register that is the base waits for the second word
            let y = self.rd32(a.wrapping_add(4));
            if self.f.stop != 0 { self.r[15] = pc; return; }
            if rd == rn { self.r[rd as usize] = x; }
            if wb { self.r[rn as usize] = ao; }
            self.r[(rd + 1) as usize & 15] = y;
        } else {                                         // STRD: word by word; a fault on the second leaves the first stored
            let (x, y) = (self.rg(rd), self.rg(rd + 1 & 15));
            self.wr32_blk(a, x, 1);
            if self.f.stop != 0 { self.r[15] = pc; return; }
            self.wr32(a.wrapping_add(4), y);
            if self.f.stop != 0 { self.r[15] = pc; return; }
            if wb { self.r[rn as usize] = ao; }
        }
    }
    #[inline(always)]
    fn arm_ldm(&mut self, op: u32, pc: u32) {
        let rn = op >> 16 & 15; let list = op & 0xffff; let n = list.count_ones();
        let base = self.rg(rn);
        let (p, u, sbit, w, l) = (op & 0x0100_0000 != 0, op & 0x0080_0000 != 0, op & 0x0040_0000 != 0, op & 0x0020_0000 != 0, op & 0x0010_0000 != 0);
        let mut a = if u { if p { base.wrapping_add(4) } else { base } } else if p { base.wrapping_sub(4 * n) } else { base.wrapping_sub(4 * n).wrapping_add(4) };
        let end = if u { base.wrapping_add(4 * n) } else { base.wrapping_sub(4 * n) };
        // Word by word in ascending address order. A fault in the middle leaves the words before it transferred; the base is
        // written back (and a loaded base takes its value) only when every word went through.
        if sbit && !(l && list & 0x8000 != 0) {
            let keep = self.r[rn as usize];                   // a base that is in the list and not banked
            if !self.ldm_user(list, a, l) { self.r[rn as usize] = keep; self.r[15] = pc; return; }
            if w { self.r[rn as usize] = end; }
            return;
        }
        if l {
            let mut lb = 0; let mut m = list;                 // bit 15 stays in `m`: the word of the pc is still to come
            while m & 0x7fff != 0 {
                let i = m.trailing_zeros(); m &= m - 1;
                let x = self.rd32_blk(a, m);
                if self.f.stop != 0 { self.r[15] = pc; return; }
                if i == rn { lb = x; } else { unsafe { *self.r.get_unchecked_mut(i as usize) = x; } }
                a = a.wrapping_add(4);
            }
            if list & 0x8000 != 0 {
                let x = self.rd32(a);
                if self.f.stop != 0 { self.r[15] = pc; return; }
                if w { self.r[rn as usize] = end; }
                if list & 1 << rn != 0 { self.r[rn as usize] = lb; }
                if sbit { let sp = self.spsr[mode_idx(self.rest)]; self.set_cpsr(sp, 0xffff_ffff, true); self.r[15] = if self.thumb { x & !1 } else { x & !3 }; } else { self.bx(x); }
            } else {
                if w { self.r[rn as usize] = end; }
                if list & 1 << rn != 0 { self.r[rn as usize] = lb; }
            }
        } else {
            let mut m = list;
            while m != 0 {
                let i = m.trailing_zeros(); m &= m - 1;
                let x = self.rg(i); self.wr32_blk(a, x, m);
                if self.f.stop != 0 { self.r[15] = pc; return; }
                a = a.wrapping_add(4);
            }
            if w { self.r[rn as usize] = end; }
        }
    }
    /// LDM / STM of the user-mode registers. False: a word faulted (the ones before it are transferred).
    #[inline(never)]
    fn ldm_user(&mut self, list: u32, mut a: u32, l: bool) -> bool {
        let cur = mode_idx(self.rest);
        for i in 0..16u32 {
            if list & 1 << i == 0 { continue; }
            let banked = cur != 0 && (i == 13 || i == 14); let fiq = cur == 1 && (8..13).contains(&i);
            let rest = list >> i >> 1;
            if l { let x = self.rd32_blk(a, rest); if self.f.stop != 0 { return false; }
                if banked { self.bank[0][(i - 13) as usize] = x; } else if fiq { self.usr8[(i - 8) as usize] = x; } else { self.r[i as usize] = x; } }
            else { let x = if banked { self.bank[0][(i - 13) as usize] } else if fiq { self.usr8[(i - 8) as usize] } else { self.rg(i) }; self.wr32_blk(a, x, rest); if self.f.stop != 0 { return false; } }
            a = a.wrapping_add(4);
        }
        true
    }

    // ---- Thumb -----------------------------------------------------------------------------------
    #[inline(always)]
    fn thumb_step(&mut self) {
        let pc = self.r[15];
        let op = self.fetch16(pc);
        if op >> 32 != 0 { return; }
        let op = op as u32;
        self.r[15] = pc.wrapping_add(2);
        let (rd, rs) = ((op & 7) as usize, (op >> 3 & 7) as usize);
        match op >> 11 {
            0 | 1 | 2 => { let x = self.r[rs]; let (v, c) = self.shift(op >> 11, x, op >> 6 & 31, true); self.r[rd] = v; self.nz(v); self.c = c; }
            3 => { let b = if op & 0x400 != 0 { op >> 6 & 7 } else { self.r[(op >> 6 & 7) as usize] }; let a = self.r[rs];
                   self.r[rd] = if op & 0x200 != 0 { self.sub(a, b, 1, true) } else { self.add(a, b, 0, true) }; }
            4 => { let x = op & 0xff; self.r[(op >> 8 & 7) as usize] = x; self.nz(x); }
            5 => { let a = self.r[(op >> 8 & 7) as usize]; self.sub(a, op & 0xff, 1, true); }
            6 => { let i = (op >> 8 & 7) as usize; let a = self.r[i]; self.r[i] = self.add(a, op & 0xff, 0, true); }
            7 => { let i = (op >> 8 & 7) as usize; let a = self.r[i]; self.r[i] = self.sub(a, op & 0xff, 1, true); }
            8 => {
                if op & 0x400 == 0 {
                    let (a, b) = (self.r[rd], self.r[rs]); let c = self.c;
                    match op >> 6 & 15 {
                        0 => { let x = a & b; self.r[rd] = x; self.nz(x); } 1 => { let x = a ^ b; self.r[rd] = x; self.nz(x); }
                        2 | 3 | 4 | 7 => { let t = match op >> 6 & 15 { 2 => 0, 3 => 1, 4 => 2, _ => 3 }; let (v, co) = self.shift(t, a, b, false); self.r[rd] = v; self.nz(v); self.c = co; }
                        5 => self.r[rd] = self.add(a, b, c, true), 6 => self.r[rd] = self.sub(a, b, c, true),
                        8 => { let x = a & b; self.nz(x); } 9 => self.r[rd] = self.sub(0, b, 1, true), 10 => { self.sub(a, b, 1, true); } 11 => { self.add(a, b, 0, true); }
                        12 => { let x = a | b; self.r[rd] = x; self.nz(x); } 13 => { let x = a.wrapping_mul(b); self.r[rd] = x; self.nz(x); }
                        14 => { let x = a & !b; self.r[rd] = x; self.nz(x); } _ => { let x = !b; self.r[rd] = x; self.nz(x); }
                    }
                } else {
                    let d = (op & 7 | op >> 4 & 8) as usize; let m = op >> 3 & 15;
                    let b = if m == 15 { pc.wrapping_add(4) } else { self.r[m as usize] };
                    match op >> 8 & 3 {
                        0 => { let a = if d == 15 { pc.wrapping_add(4) } else { self.r[d] }; let x = a.wrapping_add(b); if d == 15 { self.r[15] = x & !1; } else { self.r[d] = x; } }
                        1 => { let a = if d == 15 { pc.wrapping_add(4) } else { self.r[d] }; self.sub(a, b, 1, true); }
                        2 => { if d == 15 { self.r[15] = b & !1; } else { self.r[d] = b; } }
                        _ => { if op & 0x80 != 0 { self.r[14] = pc.wrapping_add(2) | 1; } self.bx(b); }
                    }
                }
            }
            9 => { let a = (pc.wrapping_add(4) & !3).wrapping_add((op & 0xff) << 2); let x = self.rd32(a); if self.f.stop != 0 { self.r[15] = pc; return; } self.r[(op >> 8 & 7) as usize] = x; }
            10 | 11 => {
                let a = self.r[rs].wrapping_add(self.r[(op >> 6 & 7) as usize]);
                match op >> 9 & 7 {
                    0 => { let x = self.r[rd]; self.wr32(a, x) } 1 => { let x = self.r[rd]; self.wr16(a, x) } 2 => { let x = self.r[rd]; self.wr8(a, x) }
                    3 => { let x = self.rd8(a) as i8 as i32 as u32; if self.f.stop == 0 { self.r[rd] = x; } }
                    4 => { let x = self.rd32(a); if self.f.stop == 0 { self.r[rd] = x; } } 5 => { let x = self.rd16(a); if self.f.stop == 0 { self.r[rd] = x; } }
                    6 => { let x = self.rd8(a); if self.f.stop == 0 { self.r[rd] = x; } } _ => { let x = self.rd16(a) as i16 as i32 as u32; if self.f.stop == 0 { self.r[rd] = x; } }
                }
                if self.f.stop != 0 { self.r[15] = pc; }
            }
            12 => { let a = self.r[rs].wrapping_add((op >> 6 & 31) << 2); let x = self.r[rd]; self.wr32(a, x); if self.f.stop != 0 { self.r[15] = pc; } }
            13 => { let a = self.r[rs].wrapping_add((op >> 6 & 31) << 2); let x = self.rd32(a); if self.f.stop != 0 { self.r[15] = pc; } else { self.r[rd] = x; } }
            14 => { let a = self.r[rs].wrapping_add(op >> 6 & 31); let x = self.r[rd]; self.wr8(a, x); if self.f.stop != 0 { self.r[15] = pc; } }
            15 => { let a = self.r[rs].wrapping_add(op >> 6 & 31); let x = self.rd8(a); if self.f.stop != 0 { self.r[15] = pc; } else { self.r[rd] = x; } }
            16 => { let a = self.r[rs].wrapping_add((op >> 6 & 31) << 1); let x = self.r[rd]; self.wr16(a, x); if self.f.stop != 0 { self.r[15] = pc; } }
            17 => { let a = self.r[rs].wrapping_add((op >> 6 & 31) << 1); let x = self.rd16(a); if self.f.stop != 0 { self.r[15] = pc; } else { self.r[rd] = x; } }
            18 => { let a = self.r[13].wrapping_add((op & 0xff) << 2); let x = self.r[(op >> 8 & 7) as usize]; self.wr32(a, x); if self.f.stop != 0 { self.r[15] = pc; } }
            19 => { let a = self.r[13].wrapping_add((op & 0xff) << 2); let x = self.rd32(a); if self.f.stop != 0 { self.r[15] = pc; } else { self.r[(op >> 8 & 7) as usize] = x; } }
            20 => self.r[(op >> 8 & 7) as usize] = (pc.wrapping_add(4) & !3).wrapping_add((op & 0xff) << 2),
            21 => self.r[(op >> 8 & 7) as usize] = self.r[13].wrapping_add((op & 0xff) << 2),
            22 | 23 => self.thumb_misc(op, pc),
            24 | 25 => {
                let rb = (op >> 8 & 7) as usize; let list = op & 0xff; let n = list.count_ones(); let mut a = self.r[rb];
                if op & 0x800 != 0 {                             // word by word, as the ARM LDM / STM
                    let end = a.wrapping_add(4 * n); let mut lb = 0;
                    let mut m = list; while m != 0 { let i = m.trailing_zeros(); m &= m - 1; let x = self.rd32_blk(a, m); if self.f.stop != 0 { self.r[15] = pc; return; }
                        if i as usize == rb { lb = x; } else { self.r[i as usize] = x; } a = a.wrapping_add(4); }
                    self.r[rb] = if list & 1 << rb == 0 { end } else { lb };
                } else {
                    let mut m = list; while m != 0 { let i = m.trailing_zeros(); m &= m - 1; let x = self.r[i as usize]; self.wr32_blk(a, x, m); if self.f.stop != 0 { self.r[15] = pc; return; } a = a.wrapping_add(4); }
                    self.r[rb] = a;
                }
            }
            26 | 27 => {
                let cc = op >> 8 & 15;
                if cc == 15 { self.f.stop = S_SWI; self.r[15] = pc; } else if cc == 14 { self.f.stop = S_UND; self.r[15] = pc; }
                else if self.cond(cc) { self.r[15] = pc.wrapping_add(4).wrapping_add(((op & 0xff) as i8 as i32 as u32) << 1); }
            }
            28 => self.r[15] = pc.wrapping_add(4).wrapping_add((((op & 0x7ff) << 21) as i32 >> 20) as u32),
            30 => {
                if pc & BL_PAGE < BL_PAGE - 2 {                // the pair is one instruction (as Unicorn counts it)
                    let op2 = self.fetch16_more(pc.wrapping_add(2));
                    if self.f.stop != 0 { self.r[15] = pc; return; }
                    self.r[14] = pc.wrapping_add(4).wrapping_add((((op & 0x7ff) << 21) as i32 >> 9) as u32);
                    if op2 >> 11 == 31 || op2 >> 11 == 29 { self.r[15] = pc.wrapping_add(4); self.bl_suffix(op2, pc.wrapping_add(2)); }
                } else {
                    self.r[14] = pc.wrapping_add(4).wrapping_add((((op & 0x7ff) << 21) as i32 >> 9) as u32);
                }
            }
            29 | 31 => self.bl_suffix(op, pc),
            _ => { self.f.stop = S_UND; self.r[15] = pc; }
        }
    }
    #[inline(always)] fn bl_suffix(&mut self, op: u32, pc: u32) {
        let t = self.r[14].wrapping_add((op & 0x7ff) << 1);
        self.r[14] = pc.wrapping_add(2) | 1;
        if op >> 11 == 29 { self.r[15] = t & !3; self.thumb = false; } else { self.r[15] = t & !1; }
    }
    #[inline(never)]
    fn thumb_misc(&mut self, op: u32, pc: u32) {
        match op >> 8 & 15 {
            0 => { let x = (op & 0x7f) << 2; self.r[13] = if op & 0x80 != 0 { self.r[13].wrapping_sub(x) } else { self.r[13].wrapping_add(x) }; }
            4 | 5 => {
                let lr = op & 0x100 != 0; let list = op & 0xff; let n = list.count_ones() + lr as u32;
                let mut a = self.r[13].wrapping_sub(4 * n); let start = a;
                let mut m = op & 0x1ff;                       // bit 8 stays in `m`: the word of lr is still to come
                while m & 0xff != 0 { let i = m.trailing_zeros(); m &= m - 1; let x = self.r[i as usize]; self.wr32_blk(a, x, m); if self.f.stop != 0 { self.r[15] = pc; return; } a = a.wrapping_add(4); }
                if lr { let x = self.r[14]; self.wr32(a, x); if self.f.stop != 0 { self.r[15] = pc; return; } }
                self.r[13] = start;
            }
            12 | 13 => {
                let pcb = op & 0x100 != 0;
                let mut a = self.r[13];
                let mut m = op & 0x1ff;                       // bit 8 stays in `m`: the word of the pc is still to come
                while m & 0xff != 0 { let i = m.trailing_zeros(); m &= m - 1; let x = self.rd32_blk(a, m); if self.f.stop != 0 { self.r[15] = pc; return; } self.r[i as usize] = x; a = a.wrapping_add(4); }
                if pcb { let x = self.rd32(a); if self.f.stop != 0 { self.r[15] = pc; return; } a = a.wrapping_add(4); self.bx(x); }
                self.r[13] = a;
            }
            14 => { self.f.stop = S_UNH; self.r[15] = pc; }      // BKPT
            _ => { self.f.stop = S_UND; self.r[15] = pc; }
        }
    }
}
