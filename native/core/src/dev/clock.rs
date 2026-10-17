// Emulated time: instructions charged so far times the length of one instruction, plus the time skipped while the CPU
// slept. The scheduler sets the instruction count between slices, so every device sees the time of the slice start.
// SPDX-License-Identifier: MIT

use crate::state::{Rd, Wr};

pub struct Clock {
    /// Instructions charged, as the scheduler last set it.
    pub insns: u64,
    /// Time skipped in wait-for-interrupt, ns.
    pub skipped_ns: u64,
    pub ns_per_insn: f64,
}

impl Clock {
    pub fn new() -> Clock { Clock { insns: 0, skipped_ns: 0, ns_per_insn: 10.0 } }
    pub fn now_ns(&self) -> u64 { ((self.insns as f64 * self.ns_per_insn) as u64).wrapping_add(self.skipped_ns) }
    /// Ticks of a clock of `hz` since power-on.
    pub fn cycles(&self, hz: u64) -> u64 { (self.now_ns() as u128 * hz as u128 / 1_000_000_000) as u64 }
    /// Earliest time (ns) at which cycles(hz) >= cycle.
    pub fn ns_of_cycle(&self, cycle: u64, hz: u64) -> u64 { ((cycle as u128 * 1_000_000_000 + hz as u128 - 1) / hz as u128) as u64 }

    pub const VERSION: u32 = 1;
    pub fn save(&self, w: &mut Wr) { w.u64(self.insns); w.u64(self.skipped_ns); w.u64(self.ns_per_insn.to_bits()); }
    pub fn load(&mut self, r: &mut Rd) -> Option<()> {
        self.insns = r.u64()?; self.skipped_ns = r.u64()?; self.ns_per_insn = f64::from_bits(r.u64()?);
        Some(())
    }
}
