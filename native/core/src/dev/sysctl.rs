// Two register blocks of the application CPU that store what is written and have a rule or two for reads.
//
// System control (window 0xC0011000): every byte offset of the window is a register of its own, as in the model this was
// moved from (a word written at +0x28 is not seen by a read of +0x29). +0x004 reads with bit 1 set (PLL locked) unless
// the clock select, bits 2:0 of +0x000, is 4 (PLL off). The four offsets of +0x4d0 read with bit 3 set. The chip-id word
// at +0x400 is a stored value like the rest; whoever sets the device up puts it there. While `wr_out` is set the block
// declines every write, which then reaches the host (that is how a host watches the writes for a while); the host's
// model stores it through dev_set.
//
// Clock profile (window 0xA0004000): one register per word, whatever the access size and the low two bits of the
// offset. The word at +0x04 reads with bit 0 clear and with bit 2 as it is in the word at +0x20 (the request is
// acknowledged at once).
//
// Neither sees time, drives a line or does anything outside itself.
// SPDX-License-Identifier: MIT

use crate::state::{Rd, Wr};

const WINDOW: usize = 0x1000;

pub struct SysCtl {
    /// What was written, by byte offset.
    pub regs: Vec<u32>,
    /// Writes are declined (they go to the host).
    pub wr_out: bool,
}

impl SysCtl {
    pub fn new() -> SysCtl { SysCtl { regs: vec![0; WINDOW], wr_out: false } }

    pub fn read(&self, off: u32) -> u32 {
        let off = off as usize & (WINDOW - 1);
        let mut v = self.regs[off];
        if off == 0x004 && self.regs[0] & 7 != 4 { v |= 2; }
        if off & !3 == 0x4d0 { v |= 8; }
        v
    }
    /// False: declined.
    pub fn write(&mut self, off: u32, value: u32) -> bool {
        if self.wr_out { return false; }
        self.regs[off as usize & (WINDOW - 1)] = value;
        true
    }

    pub const VERSION: u32 = 1;
    /// `wr_out`, then the registers that are not zero as (offset, value).
    pub fn save(&self, w: &mut Wr) { w.u32(self.wr_out as u32); save_regs(&self.regs, w); }
    pub fn load(&mut self, r: &mut Rd) -> Option<()> { self.wr_out = r.u32()? != 0; load_regs(&mut self.regs, r) }
}

pub struct ClkProf {
    /// What was written, by word (offset / 4).
    pub regs: Vec<u32>,
}

impl ClkProf {
    pub fn new() -> ClkProf { ClkProf { regs: vec![0; WINDOW / 4] } }

    pub fn read(&self, off: u32) -> u32 {
        let i = (off as usize & (WINDOW - 1)) >> 2;
        let v = self.regs[i];
        if i == 1 { (v & !5) | (self.regs[8] & 4) } else { v }
    }
    pub fn write(&mut self, off: u32, value: u32) { self.regs[(off as usize & (WINDOW - 1)) >> 2] = value; }

    pub const VERSION: u32 = 1;
    /// The registers that are not zero as (word number, value).
    pub fn save(&self, w: &mut Wr) { save_regs(&self.regs, w); }
    pub fn load(&mut self, r: &mut Rd) -> Option<()> { load_regs(&mut self.regs, r) }
}

fn save_regs(regs: &[u32], w: &mut Wr) {
    w.u32(regs.iter().filter(|&&x| x != 0).count() as u32);
    for (i, &x) in regs.iter().enumerate() { if x != 0 { w.u32(i as u32); w.u32(x); } }
}
fn load_regs(regs: &mut [u32], r: &mut Rd) -> Option<()> {
    regs.fill(0);
    for _ in 0..r.u32()? { let i = r.u32()? as usize; let x = r.u32()?; if i >= regs.len() { return None; } regs[i] = x; }
    Some(())
}

#[cfg(test)]
mod tests {
    use crate::dev::{F_READS, F_WRITES, K_CLKPROF, K_SYSCTL};
    use crate::ffi::*;
    use core::ffi::c_void;

    const CODE: u32 = 0x8000;
    const WIN: u32 = 0x1000_0000;

    unsafe extern "C" fn rd(user: *mut c_void, dev: u32, off: u32, size: u32) -> u32 { (*(user as *mut Vec<(u32, u32, u32, u32)>)).push((dev, off, size, u32::MAX)); 0x5a }
    unsafe extern "C" fn wr(user: *mut c_void, dev: u32, off: u32, size: u32, value: u32) { (*(user as *mut Vec<(u32, u32, u32, u32)>)).push((dev, off, size, value)); }

    /// RAM with ARM code at CODE, an external window of two pages (device 9) at WIN: system control, then the clock profile.
    unsafe fn machine(code: &[u32], log: &mut Vec<(u32, u32, u32, u32)>) -> *mut Core {
        let c = dbc_new();
        assert_eq!(dbc_map_ram(c, 0, 0x10_0000), 0);
        for (i, w) in code.iter().enumerate() { dbc_mem_write(c, CODE + 4 * i as u32, w.to_le_bytes().as_ptr(), 4); }
        assert_eq!(dbc_map_ext(c, WIN, 0x2000, 9), 0);
        dbc_set_ext(c, Some(rd), Some(wr), log as *mut _ as *mut c_void);
        assert_eq!(dbc_map_dev(c, WIN, 0x1000, K_SYSCTL), 0);
        assert_eq!(dbc_map_dev(c, WIN + 0x1000, 0x1000, K_CLKPROF), 0);
        dbc_set_reg(c, 16, 0xd3); dbc_set_reg(c, 15, CODE); dbc_set_reg(c, 1, WIN);
        c
    }
    unsafe fn read(c: *mut Core, kind: u32, off: u32, size: u32) -> u32 { let mut v = 0u32; assert_eq!(dbc_dev_read(c, kind, off, size, &mut v), 1); v }

    #[test]
    fn system_control_stores_by_byte_offset_and_has_its_two_rules() { unsafe {
        let mut log = Vec::new();
        // ldrh r0,[r1,#0x28] ; orr r0,r0,#0x40 ; strh r0,[r1,#0x28] ; ldrb r2,[r1,#0x29] ; ldr r3,[r1,#4] ; ldrh r4,[r1,#0x28]
        let c = machine(&[0xe1d1_02b8, 0xe380_0040, 0xe1c1_02b8, 0xe5d1_2029, 0xe591_3004, 0xe1d1_42b8], &mut log);
        dbc_dev_set(c, K_SYSCTL, 0x1000 + 0x400, 0xE8);
        dbc_dev_set(c, K_SYSCTL, 0x1000 + 0x28, 0x1_0228);
        assert_eq!(dbc_run(c, 6), 6);
        assert_eq!((dbc_reg(c, 0), dbc_reg(c, 2), dbc_reg(c, 3), dbc_reg(c, 4)), (0x268, 0, 2, 0x268), "a read is cut to its size; +0x29 is a register of its own; PLL locked");
        assert!(log.is_empty(), "no call to the host");
        assert_eq!((dbc_dev_get(c, K_SYSCTL, F_READS), dbc_dev_get(c, K_SYSCTL, F_WRITES)), (4, 1));
        assert_eq!(read(c, K_SYSCTL, 0x400, 4), 0xE8);
        assert_eq!(dbc_dev_write(c, K_SYSCTL, 0, 4, 0x14), 1);
        assert_eq!(read(c, K_SYSCTL, 4, 4), 0, "clock select 4: PLL off");
        assert_eq!(dbc_dev_write(c, K_SYSCTL, 0, 4, 0x13), 1);
        assert_eq!((read(c, K_SYSCTL, 4, 4), read(c, K_SYSCTL, 5, 1), read(c, K_SYSCTL, 0, 4)), (2, 0, 0x13));
        assert_eq!(dbc_dev_write(c, K_SYSCTL, 0x4d0, 4, 0x4), 1);
        assert_eq!((read(c, K_SYSCTL, 0x4d0, 4), read(c, K_SYSCTL, 0x4d3, 1), read(c, K_SYSCTL, 0x4d4, 4), read(c, K_SYSCTL, 0x4cf, 1)), (0xc, 8, 0, 0));
        // writes handed to the host
        dbc_dev_set(c, K_SYSCTL, 0, 1);
        assert_eq!(dbc_dev_get(c, K_SYSCTL, 0), 1);
        dbc_set_reg(c, 15, CODE);
        assert_eq!(dbc_run(c, 3), 3);
        assert_eq!(log, vec![(9, 0x28, 2, 0x268)], "the write goes out, the read before it does not");
        assert_eq!(dbc_dev_write(c, K_SYSCTL, 0x30, 4, 1), 0);
        assert_eq!(read(c, K_SYSCTL, 0x30, 4), 0, "a declined write changes nothing");
        dbc_dev_set(c, K_SYSCTL, 0x1000 + 0x30, 7);
        assert_eq!(read(c, K_SYSCTL, 0x30, 4), 7, "the host's model stores through dev_set");
        dbc_free(c);
    } }

    #[test]
    fn the_clock_profile_stores_by_word_and_acknowledges_the_request() { unsafe {
        let mut log = Vec::new();
        // add r1,r1,#0x1000 ; mov r0,#4 ; str r0,[r1,#0x20] ; ldr r2,[r1,#4] ; strb r0,[r1,#0x27] ; ldr r3,[r1,#0x24]
        let c = machine(&[0xe281_1a01, 0xe3a0_0004, 0xe581_0020, 0xe591_2004, 0xe5c1_0027, 0xe591_3024], &mut log);
        dbc_dev_set(c, K_CLKPROF, 0x1000 + 4, 0xf5);
        assert_eq!(read(c, K_CLKPROF, 4, 4), 0xf0, "bits 0 and 2 cleared, no request yet");
        assert_eq!(dbc_run(c, 6), 6);
        assert_eq!((dbc_reg(c, 2), dbc_reg(c, 3)), (0xf4, 4), "bit 2 follows the request; a byte written at +0x27 is the word at +0x24");
        assert!(log.is_empty());
        assert_eq!((read(c, K_CLKPROF, 6, 2), read(c, K_CLKPROF, 0x21, 1), dbc_dev_get(c, K_CLKPROF, 0x1000 + 0x26)), (0xf4, 4, 4));
        assert_eq!((dbc_dev_get(c, K_CLKPROF, F_READS), dbc_dev_get(c, K_CLKPROF, F_WRITES)), (5, 2));
        dbc_free(c);
    } }

    #[test]
    fn both_blocks_go_into_a_fresh_core() { unsafe {
        let mut log = Vec::new();
        let c = machine(&[0xe1d1_02b8], &mut log);
        dbc_dev_set(c, K_SYSCTL, 0x1000 + 0x400, 0xE8); dbc_dev_set(c, K_SYSCTL, 0x1000 + 0xfff, 0xabcd_ef01); dbc_dev_set(c, K_SYSCTL, 0, 1);
        dbc_dev_set(c, K_CLKPROF, 0x1000 + 0x20, 4); dbc_dev_set(c, K_CLKPROF, 0x1000 + 0xffc, 9);
        let n = dbc_state_size(c);
        let mut blob = vec![0u8; n as usize];
        assert_eq!(dbc_state_save(c, blob.as_mut_ptr(), n), n);
        let d = dbc_new();
        assert_eq!(dbc_state_load(d, blob.as_ptr(), n), 0);
        for (kind, f) in [(K_SYSCTL, 0), (K_SYSCTL, 0x1400), (K_SYSCTL, 0x1fff), (K_SYSCTL, 0x1028), (K_CLKPROF, 0x1020), (K_CLKPROF, 0x1ffc), (K_CLKPROF, 0x1004)] {
            assert_eq!(dbc_dev_get(d, kind, f), dbc_dev_get(c, kind, f), "kind {} field {:#x}", kind, f);
        }
        assert_eq!((dbc_dev_get(d, K_SYSCTL, 0), dbc_dev_get(d, K_SYSCTL, 0x1fff), read(d, K_CLKPROF, 4, 4)), (1, 0xabcd_ef01, 4));
        let mut blob2 = vec![0u8; n as usize];
        assert_eq!(dbc_state_save(d, blob2.as_mut_ptr(), n), n);
        assert!(blob == blob2, "the container of the second core is the first one's");
        dbc_free(c); dbc_free(d);
    } }
}
