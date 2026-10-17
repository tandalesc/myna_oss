// The two PL190-style vectored interrupt controllers of the DB3210: lines 0-31 on the first, 32-63 on the second, which is
// daisy-chained behind the first: when the first has no active vectored interrupt, a read of its VectAddr gives the vector
// of the second's highest-priority active vectored interrupt, else the first's default vector. A VectAddr read puts the
// slot in service (lower priorities are held off), a VectAddr write ends the service of the innermost one.
// The interrupt output of the pair is the OR of the two controllers.
// SPDX-License-Identifier: MIT

use crate::state::{Rd, Wr};

const IRQSTATUS: u32 = 0x00;
const FIQSTATUS: u32 = 0x04;
const RAWINTR: u32 = 0x08;
const INTSELECT: u32 = 0x0C;
const INTENABLE: u32 = 0x10;
const INTENCLEAR: u32 = 0x14;
const SOFTINT: u32 = 0x18;
const SOFTINTCLEAR: u32 = 0x1C;
const PROTECTION: u32 = 0x20;
const VECTADDR: u32 = 0x30;
const DEFVECTADDR: u32 = 0x34;
const VECTADDR0: u32 = 0x100;
const VECTCNTL0: u32 = 0x200;
const IDS: [u32; 8] = [0x90, 0x11, 0x04, 0x00, 0x0D, 0xF0, 0x05, 0xB1];       // PeriphID0-3, PCellID0-3

pub struct Vic {
    /// Level inputs from the devices.
    pub lines: u32,
    pub soft: u32,
    pub enable: u32,
    /// 1 = the line is a FIQ.
    pub select: u32,
    pub protection: u32,
    pub defvect: u32,
    pub vectaddr: [u32; 16],
    pub vectcntl: [u32; 16],
    /// Slots whose vector was read and not yet acknowledged, innermost last.
    pub prio: [u8; 16],
    pub nprio: u32,
    pub reads_vect: u64,
    pub writes_vect: u64,
}

impl Vic {
    fn new() -> Vic {
        Vic { lines: 0, soft: 0, enable: 0, select: 0, protection: 0, defvect: 0, vectaddr: [0; 16], vectcntl: [0; 16], prio: [0; 16], nprio: 0, reads_vect: 0, writes_vect: 0 }
    }
    fn raw(&self) -> u32 { self.lines | self.soft }
    fn irq_status(&self) -> u32 { self.raw() & self.enable & !self.select }
    fn fiq_status(&self) -> u32 { self.raw() & self.enable & self.select }
    /// Lowest enabled slot whose source is active as IRQ and that the slot in service does not hold off.
    fn active_slot(&self) -> Option<usize> {
        let st = self.irq_status();
        let limit = if self.nprio != 0 { (self.prio[self.nprio as usize - 1] as usize).min(16) } else { 16 };
        (0..limit).find(|&i| { let c = self.vectcntl[i]; c & 0x20 != 0 && st >> (c & 0x1F) & 1 != 0 })
    }
    /// A non-vectored interrupt is held off while a vectored one is in service.
    fn irq_asserted(&self) -> bool { self.irq_status() != 0 && (self.nprio == 0 || self.active_slot().is_some()) }
    fn fiq_asserted(&self) -> bool { self.fiq_status() != 0 }
    fn push(&mut self, slot: usize) { if (self.nprio as usize) < self.prio.len() { self.prio[self.nprio as usize] = slot as u8; self.nprio += 1; } }

    fn save(&self, w: &mut Wr) {
        w.words(&[self.lines, self.soft, self.enable, self.select, self.protection, self.defvect]);
        w.words(&self.vectaddr); w.words(&self.vectcntl); w.bytes(&self.prio); w.u32(self.nprio);
        w.u64(self.reads_vect); w.u64(self.writes_vect);
    }
    fn load(&mut self, r: &mut Rd) -> Option<()> {
        let mut f = [0u32; 6]; r.words(&mut f)?;
        self.lines = f[0]; self.soft = f[1]; self.enable = f[2]; self.select = f[3]; self.protection = f[4]; self.defvect = f[5];
        r.words(&mut self.vectaddr)?; r.words(&mut self.vectcntl)?;
        self.prio.copy_from_slice(r.bytes(16)?); self.nprio = r.u32()?.min(16);
        self.reads_vect = r.u64()?; self.writes_vect = r.u64()?;
        Some(())
    }
}

pub struct VicPair {
    pub v: [Vic; 2],
    pub irq_out: bool,
    pub fiq_out: bool,
    /// Rising edges of the interrupt output.
    pub irq_edges: u64,
}

impl VicPair {
    pub fn new() -> VicPair { VicPair { v: [Vic::new(), Vic::new()], irq_out: false, fiq_out: false, irq_edges: 0 } }

    /// Recompute the outputs. Some(level): the interrupt output changed to it.
    pub fn update(&mut self) -> Option<bool> {
        let irq = self.v[0].irq_asserted() || self.v[1].irq_asserted();
        self.fiq_out = self.v[0].fiq_asserted() || self.v[1].fiq_asserted();
        if irq == self.irq_out { return None; }
        self.irq_out = irq; self.irq_edges += irq as u64;
        Some(irq)
    }
    pub fn set_line(&mut self, n: u32, level: bool) {
        let (v, bit) = (&mut self.v[(n >> 5 & 1) as usize], 1u32 << (n & 31));
        if level { v.lines |= bit } else { v.lines &= !bit }
    }
    pub fn line(&self, n: u32) -> bool { self.v[(n >> 5 & 1) as usize].lines >> (n & 31) & 1 != 0 }

    /// A VectAddr read of controller `k`. The bool says the state changed (the outputs have to be recomputed).
    fn read_vect(&mut self, k: usize) -> (u32, bool) {
        self.v[k].reads_vect += 1;
        if let Some(i) = self.v[k].active_slot() { self.v[k].push(i); return (self.v[k].vectaddr[i], true); }
        if k == 0 && self.v[1].active_slot().is_some() { return self.read_vect(1); }
        (self.v[k].defvect, false)
    }
    /// Read of controller `k` (0 or 1). The bool: the outputs have to be recomputed (update()).
    pub fn read(&mut self, k: usize, off: u32) -> (u32, bool) {
        let v = &self.v[k];
        let x = match off {
            IRQSTATUS => v.irq_status(), FIQSTATUS => v.fiq_status(), RAWINTR => v.raw(), INTSELECT => v.select, INTENABLE => v.enable,
            SOFTINT => v.soft, PROTECTION => v.protection, DEFVECTADDR => v.defvect,
            VECTADDR => return self.read_vect(k),
            _ if (VECTADDR0..VECTADDR0 + 64).contains(&off) => v.vectaddr[((off - VECTADDR0) >> 2) as usize],
            _ if (VECTCNTL0..VECTCNTL0 + 64).contains(&off) => v.vectcntl[((off - VECTCNTL0) >> 2) as usize],
            _ if (0xFE0..0x1000).contains(&off) => IDS[((off - 0xFE0) >> 2) as usize],
            _ => 0,
        };
        (x, false)
    }
    /// Write to controller `k`. The outputs have to be recomputed afterwards (update()).
    pub fn write(&mut self, k: usize, off: u32, value: u32) {
        let v = &mut self.v[k];
        match off {
            INTSELECT => v.select = value,
            INTENABLE => v.enable |= value,
            INTENCLEAR => v.enable &= !value,
            SOFTINT => v.soft |= value,
            SOFTINTCLEAR => v.soft &= !value,
            PROTECTION => v.protection = value & 1,
            VECTADDR => {
                v.writes_vect += 1;
                if v.nprio != 0 { v.nprio -= 1; }
                else if k == 0 && self.v[1].nprio != 0 { self.v[1].nprio -= 1; }
            }
            DEFVECTADDR => v.defvect = value,
            _ if (VECTADDR0..VECTADDR0 + 64).contains(&off) => v.vectaddr[((off - VECTADDR0) >> 2) as usize] = value,
            _ if (VECTCNTL0..VECTCNTL0 + 64).contains(&off) => v.vectcntl[((off - VECTCNTL0) >> 2) as usize] = value & 0x3F,
            _ => {}
        }
    }

    pub const VERSION: u32 = 1;
    pub fn save(&self, w: &mut Wr) {
        self.v[0].save(w); self.v[1].save(w);
        w.u32(self.irq_out as u32); w.u32(self.fiq_out as u32); w.u64(self.irq_edges);
    }
    pub fn load(&mut self, r: &mut Rd) -> Option<()> {
        self.v[0].load(r)?; self.v[1].load(r)?;
        self.irq_out = r.u32()? != 0; self.fiq_out = r.u32()? != 0; self.irq_edges = r.u64()?;
        Some(())
    }
}
