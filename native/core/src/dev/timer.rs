// The sleep / OS timer block (window 0xC001A000). Time base: a counter of 4,094,000 counts per second, read as a coarse
// counter (+0x04, one step per 0x3ff8 counts = 4 ms) and a fine counter (+0x08, counting down from 0x3ff7). Until the
// first write to the block the pair reads as stopped. +0x18 is a free-running counter that also advances by `read_step`
// at every read. +0x10 (low 16 bits, in coarse steps; 0 = at every coarse step) arms event 0 while +0x2C bit 0 is set;
// +0x28 is the event status (write 1 to clear). Event 0 drives interrupt line `line0`, event 1 (never raised here) `line1`.
// Every other offset stores what is written. Time is the clock's: the value of the slice start; events fire in advance().
// SPDX-License-Identifier: MIT

use super::clock::Clock;
use crate::state::{Rd, Wr};

pub const TIMER_HZ: u64 = 4_094_000;
const FINE_TOP: u64 = 0x3FF7;
const UNIT: u64 = FINE_TOP + 1;
/// "No event armed" in `deadline0`.
pub const NONE: u64 = u64::MAX;
const WINDOW: usize = 0x1000;

pub struct Timer {
    /// What was written, by offset (every byte offset of the window is a register of its own).
    pub regs: Vec<u32>,
    /// Sum of the read advances of +0x18.
    pub extra: u64,
    pub written: bool,
    /// Reads of the counter pair answered as stopped.
    pub held_reads: u64,
    pub status: u32,
    /// Count of the time base at which event 0 fires, or NONE.
    pub deadline0: u64,
    pub fired: u64,
    /// Times event 0 was armed by a write to +0x10.
    pub arms: u64,
    pub line0: u32,
    pub line1: u32,
    pub read_step: u32,
}

impl Timer {
    pub fn new() -> Timer {
        Timer { regs: vec![0; WINDOW], extra: 0, written: false, held_reads: 0, status: 0, deadline0: NONE, fired: 0, arms: 0, line0: 28, line1: 29, read_step: 100 }
    }
    #[inline] fn reg(&self, off: u32) -> u32 { self.regs[off as usize & (WINDOW - 1)] }
    fn next_boundary(c: &Clock) -> u64 { (c.cycles(TIMER_HZ) / UNIT + 1) * UNIT }

    /// Fire the event whose deadline has passed. The caller then drives the two lines from `status`.
    pub fn advance(&mut self, c: &Clock) {
        if self.deadline0 != NONE && c.cycles(TIMER_HZ) >= self.deadline0 {
            self.deadline0 = NONE;
            if self.reg(0x2C) & 1 != 0 {
                self.status |= 1; self.fired += 1;
                if self.reg(0x10) & 0xFFFF == 0 { self.deadline0 = Self::next_boundary(c); }      // periodic: every coarse step
            }
        }
    }
    /// Time of the next event, ns, or NONE.
    pub fn next_event_ns(&self, c: &Clock) -> u64 {
        if self.deadline0 == NONE || self.reg(0x2C) & 1 == 0 { NONE } else { c.ns_of_cycle(self.deadline0, TIMER_HZ) }
    }

    pub fn read(&mut self, c: &Clock, off: u32) -> u32 {
        let cyc = c.cycles(TIMER_HZ);
        if !self.written && (off == 0x04 || off == 0x08) {
            self.held_reads += 1;
            return if off == 0x04 { 0 } else { FINE_TOP as u32 };
        }
        match off {
            0x04 => (cyc / UNIT) as u32,
            0x08 => (FINE_TOP - cyc % UNIT) as u32,
            0x18 => { self.extra = self.extra.wrapping_add(self.read_step as u64); cyc.wrapping_add(self.extra) as u32 }
            0x28 => self.status,
            _ => self.reg(off),
        }
    }
    /// True: the caller has to drive the two lines from `status`.
    pub fn write(&mut self, c: &Clock, off: u32, value: u32) -> bool {
        self.written = true;
        if off == 0x28 { self.status &= !value & 3; return true; }
        self.regs[off as usize & (WINDOW - 1)] = value;
        if off == 0x10 && self.reg(0x2C) & 1 != 0 {
            let n = (value & 0xFFFF) as u64;
            self.deadline0 = if n != 0 { c.cycles(TIMER_HZ) + n * UNIT } else { Self::next_boundary(c) };
            self.arms += 1;
        } else if off == 0x2C {
            if value & 1 == 0 { self.deadline0 = NONE; }
            else if self.deadline0 == NONE && self.reg(0x10) & 0xFFFF == 0 { self.deadline0 = Self::next_boundary(c); }
        }
        false
    }

    pub const VERSION: u32 = 1;
    /// The scalars, then the registers that are not zero as (offset, value).
    pub fn save(&self, w: &mut Wr) {
        w.u64(self.extra); w.u64(self.held_reads); w.u64(self.deadline0); w.u64(self.fired); w.u64(self.arms);
        w.words(&[self.written as u32, self.status, self.line0, self.line1, self.read_step]);
        w.u32(self.regs.iter().filter(|&&x| x != 0).count() as u32);
        for (i, &x) in self.regs.iter().enumerate() { if x != 0 { w.u32(i as u32); w.u32(x); } }
    }
    pub fn load(&mut self, r: &mut Rd) -> Option<()> {
        self.extra = r.u64()?; self.held_reads = r.u64()?; self.deadline0 = r.u64()?; self.fired = r.u64()?; self.arms = r.u64()?;
        let mut f = [0u32; 5]; r.words(&mut f)?;
        self.written = f[0] != 0; self.status = f[1]; self.line0 = f[2]; self.line1 = f[3]; self.read_step = f[4];
        self.regs.fill(0);
        for _ in 0..r.u32()? { let i = r.u32()? as usize; let x = r.u32()?; if i >= WINDOW { return None; } self.regs[i] = x; }
        Some(())
    }
}
